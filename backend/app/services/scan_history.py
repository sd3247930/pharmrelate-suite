"""槽位编辑与撤销/重做（阶段 3.4）。

模型：每一步编辑记录**受影响范围的完整前后状态**。
撤销 = 恢复前状态，重做 = 恢复后状态。

为什么不做增量日志：条码编辑带有顺序语义（导出必须保持采集原序），
增量要正确重建顺序，复杂度和出错面都远高于直接存前后状态。
一罐最多 2500 粒 ≈ 52KB，50 步 ≈ 2.6MB，SQLite 完全承受得起。

栈用游标表示：cursor 之前（含）的操作是"已应用"，之后是"已撤销"。
撤销/重做严格 LIFO，所以已应用的必然是前缀——这个不变量让实现干净且不会错。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Database
from ..domain.constants import classify_code, layer_label
from ..domain.models import Batch, BoxCode, CanCode
from ..repositories.audit_repository import AuditRepository
from ..repositories.batch_repository import BatchRecord, BatchRepository

MAX_STEPS = 50
"""撤销栈深度下限（V1.1 10.3 要求 ≥50）。"""

SCOPE_CAN = "can"
SCOPE_BOX = "box"


class SlotEditError(ValueError):
    """编辑被拒绝。message 直接面向操作员。"""

    def __init__(self, message: str, *, detail: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


@dataclass(slots=True)
class HistoryState:
    can_undo: int
    can_redo: int
    undo_label: str
    redo_label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "canUndo": self.can_undo,
            "canRedo": self.can_redo,
            "undoLabel": self.undo_label,
            "redoLabel": self.redo_label,
            "maxSteps": MAX_STEPS,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ScanHistoryService:
    def __init__(
        self,
        database: Database,
        repository: BatchRepository,
        audit: AuditRepository,
    ) -> None:
        self._db = database
        self._db.initialise()
        self._repository = repository
        self._audit = audit
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ 位置

    def _locate(self, batch: Batch, code: str) -> tuple[int, int, str]:
        """返回 (罐序号, 槽位序号, 位置描述)。找不到抛错。"""

        for can in batch.box.cans:
            for slot, particle in enumerate(can.particles, start=1):
                if particle == code:
                    return can.index, slot, f"罐 {can.index} / 粒子槽位 {slot}"
        raise SlotEditError(
            f"条码 {code} 不在当前批次的任何槽位中。", detail={"code": code}
        )

    # ------------------------------------------------------------------ 编辑

    def _can_state(self, batch: Batch, can_index: int) -> dict[str, object]:
        if not 1 <= can_index <= batch.can_count:
            raise SlotEditError(
                f"批次中没有罐 {can_index}。", detail={"canIndex": can_index}
            )
        can = batch.box.cans[can_index - 1]
        return {
            "canIndex": can_index,
            "canCode": can.code,
            "particles": list(can.particles),
        }

    def _commit(
        self,
        batch_id: str,
        *,
        kind: str,
        label: str,
        scope: str,
        before: dict[str, object],
        after: dict[str, object],
        reason: str = "",
    ) -> BatchRecord:
        """应用目标状态并压入操作栈。两件事在同一个锁里完成，避免栈与数据脱节。"""

        self._apply_state(batch_id, scope, after)
        with self._db.transaction() as connection:
            self._push(
                connection,
                batch_id,
                kind=kind,
                scope=scope,
                label=label,
                before=before,
                after=after,
            )
        self._audit.append(
            action=kind,
            entity="scan",
            entity_id=batch_id,
            result="success",
            old_value=before,
            new_value=after,
            reason=reason or label,
        )
        record = self._repository.get(batch_id)
        assert record is not None
        return record

    def replace_particle(self, batch_id: str, code: str, new_code: str) -> BatchRecord:
        """替换槽位条码：旧码释放、新码全局去重。"""

        with self._lock:
            record = self._require(batch_id)
            self._allowed(new_code)
            can_index, slot, where = self._locate(record.batch, code)
            if new_code == code:
                raise SlotEditError("新条码与旧条码相同，无需替换。", detail={"code": code})

            before = self._can_state(record.batch, can_index)
            particles = list(before["particles"])
            particles[slot - 1] = new_code

            # 去重分两步，为的是给出准确的提示：
            #   ① 新码是否已被**其它**槽位占用（与本次替换无关的占用）→ 明确告诉它属于哪里
            #   ② 替换后整批是否仍然唯一（防御性检查）
            for can in record.batch.box.cans:
                if new_code in can.particles and can.particles.index(new_code) != slot - 1:
                    used_at = can.particles.index(new_code) + 1
                    raise SlotEditError(
                        f"条码 {new_code} 已被「罐 {can.index} / 粒子槽位 {used_at}」使用，请重新扫描。",
                        detail={"duplicate": new_code, "canIndex": can.index, "slot": used_at},
                    )

            probe = Batch(
                batch_no=record.batch.batch_no,
                made_date=record.batch.made_date,
                validate_date=record.batch.validate_date,
                box=BoxCode(
                    code=record.batch.box.code,
                    cans=[
                        CanCode(
                            index=can.index,
                            code=can.code,
                            particles=(
                                particles
                                if can.index == can_index
                                else list(can.particles)
                            ),
                        )
                        for can in record.batch.box.cans
                    ],
                ),
            )
            self._assert_unique(probe, [])

            after = {**before, "particles": particles}
            return self._commit(
                batch_id,
                kind="replace_particle",
                label=f"替换槽位条码（{where}）",
                scope=SCOPE_CAN,
                before=before,
                after=after,
            )

    def delete_particle(self, batch_id: str, code: str) -> BatchRecord:
        with self._lock:
            record = self._require(batch_id)
            can_index, _slot, where = self._locate(record.batch, code)

            before = self._can_state(record.batch, can_index)
            particles = [item for item in before["particles"] if item != code]
            after = {**before, "particles": particles}
            return self._commit(
                batch_id,
                kind="delete_particle",
                label=f"删除槽位条码（{where}）",
                scope=SCOPE_CAN,
                before=before,
                after=after,
            )

    def clear_can(self, batch_id: str, can_index: int) -> BatchRecord:
        """清空当前罐的粒子，保留罐号。"""

        with self._lock:
            record = self._require(batch_id)
            before = self._can_state(record.batch, can_index)
            if not before["particles"]:
                raise SlotEditError(
                    f"罐 {can_index} 本来就是空的，无需清空。",
                    detail={"canIndex": can_index},
                )
            after = {**before, "particles": []}
            return self._commit(
                batch_id,
                kind="clear_can",
                label=f"清空罐 {can_index} 的粒子（{len(before['particles'])} 粒）",
                scope=SCOPE_CAN,
                before=before,
                after=after,
            )

    def rescan_can(self, batch_id: str, can_index: int, new_can_code: str) -> BatchRecord:
        """重拍罐号：罐号换新，该罐粒子全部清除。"""

        with self._lock:
            record = self._require(batch_id)
            # 注意这里不能用 _allowed：那个校验针对粒子槽位，
            # 而重拍罐号传入的本来就是罐码（层级 2）。
            if classify_code(new_can_code) != 2:
                raise SlotEditError(
                    "重拍罐号必须使用罐码（8021762 开头）。", detail={"code": new_can_code}
                )

            before = self._can_state(record.batch, can_index)
            if new_can_code == before["canCode"] and not before["particles"]:
                raise SlotEditError("罐号未变化且该罐没有粒子，无需重拍。")

            for other in record.batch.box.cans:
                if other.code == new_can_code:
                    raise SlotEditError(
                        f"罐号 {new_can_code} 已被罐 {other.index} 使用。",
                        detail={"duplicate": new_can_code},
                    )

            after = {
                "canIndex": can_index,
                "canCode": new_can_code,
                "particles": [],
            }
            return self._commit(
                batch_id,
                kind="rescan_can",
                label=f"重拍罐 {can_index} 号（原 {before['canCode']}）",
                scope=SCOPE_CAN,
                before=before,
                after=after,
            )

    def rescan_box(self, batch_id: str, new_box_code: str = "") -> BatchRecord:
        """重拍箱号：清空整箱的罐与粒子。"""

        with self._lock:
            record = self._require(batch_id)
            before = self._repository.box_state(batch_id) or {"boxCode": "", "cans": []}
            after = {"boxCode": new_box_code, "cans": []}
            return self._commit(
                batch_id,
                kind="rescan_box",
                label="重拍箱号（清空全部罐与粒子）",
                scope=SCOPE_BOX,
                before=before,
                after=after,
            )

    def _require(self, batch_id: str) -> BatchRecord:
        record = self._repository.get(batch_id)
        if record is None:
            raise SlotEditError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})
        return record

    def _allowed(self, code: str) -> str:
        layer = classify_code(code)
        if layer is None:
            raise SlotEditError(
                f"条码 {code} 不是合法的 20 位数字条码。", detail={"code": code}
            )
        if layer != 1:
            raise SlotEditError(
                f"条码 {code} 是「{layer_label(layer)}」，粒子槽位只接受粒子码。",
                detail={"code": code, "actualLayer": layer},
            )
        return code

    def _assert_unique(self, batch: Batch, candidates: list[str]) -> None:
        """替换后的整批条码必须仍然全局唯一。"""

        seen: set[str] = set()
        for can in batch.box.cans:
            for particle in can.particles:
                if particle in seen:
                    raise SlotEditError(
                        f"条码 {particle} 在替换后重复出现，操作已取消。",
                        detail={"duplicate": particle},
                    )
                seen.add(particle)
        for code in candidates:
            if code in seen:
                raise SlotEditError(
                    f"条码 {code} 已被其它槽位使用，请重新扫描。", detail={"duplicate": code}
                )

    # ------------------------------------------------------------------ 栈

    def _cursor(self, connection: sqlite3.Connection, batch_id: str) -> int:
        row = connection.execute(
            "SELECT cursor FROM scan_cursor WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        return int(row["cursor"]) if row else 0

    def _set_cursor(self, connection: sqlite3.Connection, batch_id: str, value: int) -> None:
        connection.execute(
            "INSERT INTO scan_cursor (batch_id, cursor) VALUES (?, ?) "
            "ON CONFLICT (batch_id) DO UPDATE SET cursor = excluded.cursor",
            (batch_id, value),
        )

    def _push(
        self,
        connection: sqlite3.Connection,
        batch_id: str,
        *,
        kind: str,
        scope: str,
        label: str,
        before: dict[str, object],
        after: dict[str, object],
    ) -> None:
        """压入新操作：先截断重做分支，再压栈，最后裁剪到 MAX_STEPS。"""

        cursor = self._cursor(connection, batch_id)
        connection.execute(
            "DELETE FROM scan_op WHERE batch_id = ? AND op_seq > ?", (batch_id, cursor)
        )
        connection.execute(
            """
            INSERT INTO scan_op (batch_id, kind, scope, label, before_json, after_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                kind,
                scope,
                label,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                _now(),
            ),
        )
        cursor += 1
        # 裁剪：只保留最近 MAX_STEPS 步
        keep = connection.execute(
            "SELECT op_seq FROM scan_op WHERE batch_id = ? ORDER BY op_seq DESC LIMIT ?",
            (batch_id, MAX_STEPS),
        ).fetchall()
        if keep:
            oldest = min(row["op_seq"] for row in keep)
            connection.execute(
                "DELETE FROM scan_op WHERE batch_id = ? AND op_seq < ?", (batch_id, oldest)
            )

        # 游标是"最后一个已应用操作的 op_seq"，不是操作条数：
        # 裁剪会删掉最旧的操作，用条数当游标会让已应用前缀整体错位。
        newest = connection.execute(
            "SELECT MAX(op_seq) AS value FROM scan_op WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        self._set_cursor(connection, batch_id, int(newest["value"] or 0))

    def history(self, batch_id: str) -> HistoryState:
        with self._db.read() as connection:
            cursor = self._cursor(connection, batch_id)
            rows = connection.execute(
                "SELECT op_seq, label FROM scan_op WHERE batch_id = ? ORDER BY op_seq ASC",
                (batch_id,),
            ).fetchall()

        applied = [row for row in rows if row["op_seq"] <= cursor]
        undone = [row for row in rows if row["op_seq"] > cursor]
        return HistoryState(
            can_undo=len(applied),
            can_redo=len(undone),
            undo_label=applied[-1]["label"] if applied else "",
            redo_label=undone[0]["label"] if undone else "",
        )

    def _apply_state(
        self, batch_id: str, scope: str, state: dict[str, object]
    ) -> None:
        if scope == SCOPE_CAN:
            self._repository.apply_can_state(
                batch_id,
                int(state["canIndex"]),
                new_can_code=str(state["canCode"]),
                particles=[str(item) for item in list(state.get("particles") or [])],
            )
        else:
            self._repository.apply_box_state(
                batch_id,
                str(state.get("boxCode") or ""),
                [dict(item) for item in list(state.get("cans") or [])],
            )

    # ------------------------------------------------------------------ 撤销

    def undo(self, batch_id: str) -> BatchRecord:
        with self._lock:
            with self._db.read() as connection:
                cursor = self._cursor(connection, batch_id)
                row = connection.execute(
                    "SELECT op_seq, scope, label, before_json FROM scan_op "
                    "WHERE batch_id = ? AND op_seq <= ? ORDER BY op_seq DESC LIMIT 1",
                    (batch_id, cursor),
                ).fetchone()
            if row is None:
                raise SlotEditError("没有可撤销的操作。")

            self._apply_state(batch_id, row["scope"], json.loads(row["before_json"]))
            with self._db.transaction() as connection:
                previous = connection.execute(
                    "SELECT MAX(op_seq) AS value FROM scan_op "
                    "WHERE batch_id = ? AND op_seq < ?",
                    (batch_id, row["op_seq"]),
                ).fetchone()
                self._set_cursor(connection, batch_id, int(previous["value"] or 0))

            self._audit.append(
                action="undo",
                entity="scan",
                entity_id=batch_id,
                result="success",
                new_value={"opSeq": row["op_seq"], "label": row["label"]},
            )
            record = self._repository.get(batch_id)
            assert record is not None
            return record

    def redo(self, batch_id: str) -> BatchRecord:
        with self._lock:
            with self._db.read() as connection:
                cursor = self._cursor(connection, batch_id)
                row = connection.execute(
                    "SELECT op_seq, scope, label, after_json FROM scan_op "
                    "WHERE batch_id = ? AND op_seq > ? ORDER BY op_seq ASC LIMIT 1",
                    (batch_id, cursor),
                ).fetchone()
            if row is None:
                raise SlotEditError("没有可重做的操作。")

            self._apply_state(batch_id, row["scope"], json.loads(row["after_json"]))
            with self._db.transaction() as connection:
                self._set_cursor(connection, batch_id, int(row["op_seq"]))

            self._audit.append(
                action="redo",
                entity="scan",
                entity_id=batch_id,
                result="success",
                new_value={"opSeq": row["op_seq"], "label": row["label"]},
            )
            record = self._repository.get(batch_id)
            assert record is not None
            return record
