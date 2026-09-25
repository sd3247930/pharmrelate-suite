"""SQLite 批次仓储（生产实现）。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from ..db import Database
from ..domain.batch_state import STATUS_DRAFT
from ..domain.constants import FIXED_PARAMS
from ..domain.models import Batch, BoxCode, CanCode, EarlyEnd
from .batch_repository import BatchRecord

BATCH_COLUMNS = """
    id, batch_no, made_date, validate_date, status,
    product_code, sub_type_no, cascade, package_spec, comment, flag,
    workshop, line_name, line_manager, license,
    early_end_reason, early_end_operator, early_end_note, early_end_at,
    early_end_can_count, early_end_particle_count,
    revision, hlc, updated_by, device_id, deleted, created_at, updated_at
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteBatchRepository:
    """落库到 SQLite 的批次仓储。

    写入一律走事务：批次行与其全部条码行必须同时成功或同时失败，
    否则会出现"批次存在但条码缺失"的残缺数据。
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.initialise()

    # ------------------------------------------------------------------ 读

    def _load_batch(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Batch:
        codes = connection.execute(
            """
            SELECT cur_code, pack_layer, parent_code, planned_particle_count
            FROM code
            WHERE batch_id = ? AND deleted = 0
            ORDER BY seq ASC
            """,
            (row["id"],),
        ).fetchall()

        box: BoxCode | None = None
        cans_by_code: dict[str, CanCode] = {}

        for code_row in codes:
            cur_code = code_row["cur_code"]
            pack_layer = code_row["pack_layer"]

            if pack_layer == 3:
                box = BoxCode(code=cur_code)
            elif pack_layer == 2:
                can = CanCode(
                    index=len(box.cans) + 1 if box else 1,
                    code=cur_code,
                    planned_particle_count=code_row["planned_particle_count"] or 0,
                )
                if box is not None:
                    box.cans.append(can)
                cans_by_code[cur_code] = can
            elif pack_layer == 1:
                can = cans_by_code.get(code_row["parent_code"] or "")
                if can is not None:
                    can.particles.append(cur_code)

        if box is None:
            box = BoxCode(code="")

        early_end = None
        if row["early_end_reason"] is not None:
            early_end = EarlyEnd(
                reason=row["early_end_reason"],
                operator=row["early_end_operator"] or "",
                note=row["early_end_note"] or "",
                at=row["early_end_at"] or "",
                actual_can_count=row["early_end_can_count"] or 0,
                actual_particle_count=row["early_end_particle_count"] or 0,
            )

        plan_rows = connection.execute(
            "SELECT planned_particle_count FROM can_plan WHERE batch_id = ? ORDER BY can_index ASC",
            (row["id"],),
        ).fetchall()

        return Batch(
            batch_no=row["batch_no"],
            made_date=row["made_date"],
            validate_date=row["validate_date"],
            box=box,
            early_end=early_end,
            planned_particle_counts=[item["planned_particle_count"] for item in plan_rows],
        )

    def _record(self, connection: sqlite3.Connection, row: sqlite3.Row) -> BatchRecord:
        return BatchRecord(
            id=row["id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            batch=self._load_batch(connection, row),
            revision=row["revision"],
            hlc=row["hlc"],
            updated_by=row["updated_by"],
            device_id=row["device_id"],
            deleted=bool(row["deleted"]),
        )

    def list(self, *, status: str | None = None, search: str | None = None) -> list[BatchRecord]:
        sql = f"SELECT {BATCH_COLUMNS} FROM batch WHERE deleted = 0"
        params: list[object] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if search:
            sql += " AND batch_no LIKE ?"
            params.append(f"%{search}%")
        sql += " ORDER BY updated_at DESC, created_at DESC"

        with self._db.read() as connection:
            rows = connection.execute(sql, params).fetchall()
            return [self._record(connection, row) for row in rows]

    def get(self, batch_id: str) -> BatchRecord | None:
        with self._db.read() as connection:
            row = connection.execute(
                f"SELECT {BATCH_COLUMNS} FROM batch WHERE id = ? AND deleted = 0",
                (batch_id,),
            ).fetchone()
            return self._record(connection, row) if row else None

    def find_by_batch_no(self, batch_no: str) -> BatchRecord | None:
        with self._db.read() as connection:
            row = connection.execute(
                f"SELECT {BATCH_COLUMNS} FROM batch WHERE batch_no = ? AND deleted = 0",
                (batch_no,),
            ).fetchone()
            return self._record(connection, row) if row else None

    def count(self) -> int:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM batch WHERE deleted = 0"
            ).fetchone()
        return int(row["total"]) if row else 0

    def next_version_no(self, base_batch_no: str) -> str:
        """为「创建新版本」生成 batchNo-V2 / -V3 …，返回第一个未被占用的编号。"""

        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT batch_no FROM batch WHERE batch_no LIKE ? AND deleted = 0",
                (f"{base_batch_no}-V%",),
            ).fetchall()

        used: set[int] = set()
        prefix = f"{base_batch_no}-V"
        for row in rows:
            suffix = str(row["batch_no"])[len(prefix) :]
            if suffix.isdigit():
                used.add(int(suffix))

        version = 2
        while version in used:
            version += 1
        return f"{base_batch_no}-V{version}"

    # ------------------------------------------------------------------ 写

    def _insert_codes(
        self, connection: sqlite3.Connection, batch_id: str, batch: Batch, timestamp: str
    ) -> None:
        """写入条码行。

        空结构草稿（界面 1 已保存、尚未生成包装结构）不应该产生任何条码行 ——
        数据库里的 cur_code 不允许为空，而且"还没有结构"本来就不该伪装成
        一条空条码。此时只留 batch 行。
        """

        rows: list[tuple[object, ...]] = []
        emitted: set[str] = set()
        for seq, (cur_code, pack_layer, parent_code) in enumerate(batch.iter_export_nodes()):
            if not cur_code.strip():
                continue
            # 父没有落库，子就不能落库：否则会插入悬空条码，触发器也会拒绝。
            # 这条同时覆盖"空箱号 → 其下全部跳过"和"空罐号 → 其下粒子跳过"。
            if parent_code is not None and parent_code not in emitted:
                continue
            planned: int | None = None
            if pack_layer == 2:
                can = next((item for item in batch.box.cans if item.code == cur_code), None)
                planned = can.planned_particle_count if can else 0
            rows.append(
                (
                    str(uuid.uuid4()),
                    batch_id,
                    cur_code,
                    pack_layer,
                    parent_code,
                    seq,
                    planned,
                    timestamp,
                    timestamp,
                )
            )
            emitted.add(cur_code)

        connection.executemany(
            """
            INSERT INTO code
                (id, batch_id, cur_code, pack_layer, parent_code, seq,
                 planned_particle_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _replace_can_plan(
        self, connection: sqlite3.Connection, batch_id: str, batch: Batch
    ) -> None:
        connection.execute("DELETE FROM can_plan WHERE batch_id = ?", (batch_id,))
        if not batch.planned_particle_counts:
            return
        connection.executemany(
            """
            INSERT INTO can_plan (batch_id, can_index, planned_particle_count)
            VALUES (?, ?, ?)
            """,
            [
                (batch_id, index, planned)
                for index, planned in enumerate(batch.planned_particle_counts, start=1)
            ],
        )

    def create(self, batch: Batch, status: str = STATUS_DRAFT) -> BatchRecord:
        batch_id = str(uuid.uuid4())
        timestamp = _now()
        early = batch.early_end

        with self._db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO batch (
                    id, batch_no, made_date, validate_date, status,
                    product_code, sub_type_no, cascade, package_spec, comment, flag,
                    workshop, line_name, line_manager, license,
                    early_end_reason, early_end_operator, early_end_note, early_end_at,
                    early_end_can_count, early_end_particle_count,
                    revision, hlc, updated_by, device_id, deleted, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?,
                          1, '', 'local-user', 'windows-main', 0, ?, ?)
                """,
                (
                    batch_id,
                    batch.batch_no,
                    batch.made_date,
                    batch.validate_date,
                    status,
                    FIXED_PARAMS.product_code,
                    FIXED_PARAMS.sub_type_no,
                    FIXED_PARAMS.cascade,
                    FIXED_PARAMS.package_spec,
                    FIXED_PARAMS.comment,
                    FIXED_PARAMS.flag,
                    FIXED_PARAMS.workshop,
                    FIXED_PARAMS.line_name,
                    FIXED_PARAMS.line_manager,
                    FIXED_PARAMS.license,
                    early.reason if early else None,
                    early.operator if early else None,
                    early.note if early else None,
                    early.at if early else None,
                    early.actual_can_count if early else None,
                    early.actual_particle_count if early else None,
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_codes(connection, batch_id, batch, timestamp)
            self._replace_can_plan(connection, batch_id, batch)

        record = self.get(batch_id)
        assert record is not None
        return record

    def update(self, batch_id: str, batch: Batch) -> BatchRecord | None:
        """整批替换业务数据。

        条码行做物理删除重建，而不是逐行 diff：粒子数量动辄上千，
        diff 的复杂度与出错面都远大于重建；整个过程在一个事务里完成，
        中途失败会整体回滚，不会留下半套数据。
        """

        timestamp = _now()
        early = batch.early_end

        with self._db.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM batch WHERE id = ? AND deleted = 0", (batch_id,)
            ).fetchone()
            if row is None:
                return None

            connection.execute(
                """
                UPDATE batch SET
                    batch_no = ?, made_date = ?, validate_date = ?,
                    early_end_reason = ?, early_end_operator = ?, early_end_note = ?,
                    early_end_at = ?, early_end_can_count = ?, early_end_particle_count = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    batch.batch_no,
                    batch.made_date,
                    batch.validate_date,
                    early.reason if early else None,
                    early.operator if early else None,
                    early.note if early else None,
                    early.at if early else None,
                    early.actual_can_count if early else None,
                    early.actual_particle_count if early else None,
                    timestamp,
                    batch_id,
                ),
            )

            connection.execute("DELETE FROM code WHERE batch_id = ?", (batch_id,))
            self._insert_codes(connection, batch_id, batch, timestamp)
            self._replace_can_plan(connection, batch_id, batch)

        return self.get(batch_id)

    def set_status(self, batch_id: str, status: str) -> BatchRecord | None:
        timestamp = _now()
        with self._db.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE batch SET status = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND deleted = 0
                """,
                (status, timestamp, batch_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(batch_id)

    # ------------------------------------------------------------------
    # 扫码增量写入
    #
    # 扫码是逐条发生的（一罐最多 2500 粒），绝不能每扫一条就把整批条码
    # 删掉重建 —— 那是 O(n²)。这里只做单行 INSERT/UPDATE。
    #
    # seq 取当前批次最大值 +1：导出顺序 = 采集顺序，父先于子，
    # 于是 D-010 的触发器约束天然成立。
    # ------------------------------------------------------------------

    def _next_seq(self, connection: sqlite3.Connection, batch_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM code WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return int(row["next_seq"])

    def set_box_code(self, batch_id: str, code: str) -> BatchRecord | None:
        timestamp = _now()
        with self._db.transaction() as connection:
            exists = connection.execute(
                "SELECT id FROM batch WHERE id = ? AND deleted = 0", (batch_id,)
            ).fetchone()
            if exists is None:
                return None
            connection.execute(
                "DELETE FROM code WHERE batch_id = ? AND pack_layer = 3", (batch_id,)
            )
            connection.execute(
                """
                INSERT INTO code
                    (id, batch_id, cur_code, pack_layer, parent_code, seq,
                     planned_particle_count, created_at, updated_at)
                VALUES (?, ?, ?, 3, NULL, 0, NULL, ?, ?)
                """,
                (str(uuid.uuid4()), batch_id, code, timestamp, timestamp),
            )
            connection.execute(
                "UPDATE batch SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (timestamp, batch_id),
            )
        return self.get(batch_id)

    def add_can(self, batch_id: str, code: str, planned_particle_count: int) -> BatchRecord | None:
        timestamp = _now()
        with self._db.transaction() as connection:
            box = connection.execute(
                "SELECT cur_code FROM code WHERE batch_id = ? AND pack_layer = 3 AND deleted = 0",
                (batch_id,),
            ).fetchone()
            if box is None:
                raise ValueError("批次还没有箱号，无法添加罐")
            seq = self._next_seq(connection, batch_id)
            connection.execute(
                """
                INSERT INTO code
                    (id, batch_id, cur_code, pack_layer, parent_code, seq,
                     planned_particle_count, created_at, updated_at)
                VALUES (?, ?, ?, 2, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    batch_id,
                    code,
                    box["cur_code"],
                    seq,
                    planned_particle_count,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE batch SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (timestamp, batch_id),
            )
        return self.get(batch_id)

    def append_particles(
        self, batch_id: str, can_code: str, codes: list[str]
    ) -> BatchRecord | None:
        if not codes:
            return self.get(batch_id)

        timestamp = _now()
        with self._db.transaction() as connection:
            can = connection.execute(
                "SELECT cur_code FROM code WHERE batch_id = ? AND cur_code = ? AND pack_layer = 2 AND deleted = 0",
                (batch_id, can_code),
            ).fetchone()
            if can is None:
                raise ValueError(f"批次内找不到罐 {can_code}")

            start = self._next_seq(connection, batch_id)
            connection.executemany(
                """
                INSERT INTO code
                    (id, batch_id, cur_code, pack_layer, parent_code, seq,
                     planned_particle_count, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, NULL, ?, ?)
                """,
                [
                    (str(uuid.uuid4()), batch_id, code, can_code, start + offset, timestamp, timestamp)
                    for offset, code in enumerate(codes)
                ],
            )
            connection.execute(
                "UPDATE batch SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (timestamp, batch_id),
            )
        return self.get(batch_id)

    # ------------------------------------------------------------------
    # 槽位状态读写（阶段 3.4）
    #
    # 所有编辑（删除 / 替换 / 清空 / 重拍罐号）都归结为"恢复某一罐的状态"：
    # 给出该罐的罐号与粒子列表（有序），一次性把这一罐写回目标状态。
    # 这样编辑、撤销、重做共用同一个原语，不必各写一套。
    #
    # 关键约束：导出顺序必须始终是 箱 → 罐1 → 罐1粒子 → 罐2 → …。
    # 删除再插入会让新行拿到更大的 seq，从而打乱罐之间的相对顺序，
    # 因此结构性改动之后统一重排 seq（renumber）。
    # ------------------------------------------------------------------

    def _can_rows(self, connection: sqlite3.Connection, batch_id: str) -> list[sqlite3.Row]:
        """按导出顺序返回罐行。罐序号 = 这里的下标 + 1。

        用序号而不是罐号来定位：重拍罐号会改掉罐号，
        靠罐号定位会让撤销时找不到目标。
        """

        return connection.execute(
            "SELECT id, cur_code FROM code WHERE batch_id = ? AND pack_layer = 2 "
            "AND deleted = 0 ORDER BY seq ASC",
            (batch_id,),
        ).fetchall()

    def can_state(self, batch_id: str, can_index: int) -> dict[str, object] | None:
        with self._db.read() as connection:
            cans = self._can_rows(connection, batch_id)
            if not 1 <= can_index <= len(cans):
                return None
            can_code = cans[can_index - 1]["cur_code"]
            rows = connection.execute(
                "SELECT cur_code FROM code WHERE batch_id = ? AND parent_code = ? "
                "AND pack_layer = 1 AND deleted = 0 ORDER BY seq ASC",
                (batch_id, can_code),
            ).fetchall()
        return {
            "canIndex": can_index,
            "canCode": can_code,
            "particles": [row["cur_code"] for row in rows],
        }

    def box_state(self, batch_id: str) -> dict[str, object] | None:
        with self._db.read() as connection:
            box = connection.execute(
                "SELECT cur_code FROM code WHERE batch_id = ? AND pack_layer = 3 AND deleted = 0",
                (batch_id,),
            ).fetchone()
            if box is None:
                return None
            cans = connection.execute(
                "SELECT cur_code FROM code WHERE batch_id = ? AND pack_layer = 2 AND deleted = 0 "
                "ORDER BY seq ASC",
                (batch_id,),
            ).fetchall()
            states = []
            for can in cans:
                rows = connection.execute(
                    "SELECT cur_code FROM code WHERE batch_id = ? AND parent_code = ? "
                    "AND pack_layer = 1 AND deleted = 0 ORDER BY seq ASC",
                    (batch_id, can["cur_code"]),
                ).fetchall()
                states.append(
                    {"canCode": can["cur_code"], "particles": [row["cur_code"] for row in rows]}
                )
        return {"boxCode": box["cur_code"], "cans": states}

    def _renumber(self, connection: sqlite3.Connection, batch_id: str) -> None:
        """按规范顺序重排 seq：箱 → 各罐（保持现有罐间顺序）→ 该罐粒子（保持现有顺序）。

        按规范顺序逐行更新，因此每一步父的 seq 都已经更新完毕，
        D-010 的 `parent.seq < child.seq` 触发器不会误报。
        """

        box = connection.execute(
            "SELECT id, seq FROM code WHERE batch_id = ? AND pack_layer = 3 AND deleted = 0",
            (batch_id,),
        ).fetchone()
        if box is None:
            return

        cans = connection.execute(
            "SELECT id, cur_code, seq FROM code WHERE batch_id = ? AND pack_layer = 2 "
            "AND deleted = 0 ORDER BY seq ASC",
            (batch_id,),
        ).fetchall()

        updates: list[tuple[int, str]] = []
        next_seq = 0

        if (box["seq"] or 0) != next_seq:
            updates.append((next_seq, box["id"]))
        next_seq += 1

        for can in cans:
            if (can["seq"] or 0) != next_seq:
                updates.append((next_seq, can["id"]))
            next_seq += 1
            particles = connection.execute(
                "SELECT id, seq FROM code WHERE batch_id = ? AND parent_code = ? "
                "AND pack_layer = 1 AND deleted = 0 ORDER BY seq ASC",
                (batch_id, can["cur_code"]),
            ).fetchall()
            for particle in particles:
                if (particle["seq"] or 0) != next_seq:
                    updates.append((next_seq, particle["id"]))
                next_seq += 1

        if updates:
            connection.executemany("UPDATE code SET seq = ? WHERE id = ?", updates)

    def apply_can_state(
        self,
        batch_id: str,
        can_index: int,
        *,
        new_can_code: str,
        particles: list[str] | None = None,
    ) -> BatchRecord | None:
        """把某一罐写回目标状态（罐号可改，粒子列表整列表替换）。"""

        timestamp = _now()

        with self._db.transaction() as connection:
            cans = self._can_rows(connection, batch_id)
            if not 1 <= can_index <= len(cans):
                return None
            can = cans[can_index - 1]
            can_code = can["cur_code"]

            if new_can_code != can_code:
                connection.execute(
                    "UPDATE code SET cur_code = ?, updated_at = ? WHERE id = ?",
                    (new_can_code, timestamp, can["id"]),
                )
                connection.execute(
                    "UPDATE code SET parent_code = ?, updated_at = ? "
                    "WHERE batch_id = ? AND parent_code = ? AND pack_layer = 1",
                    (new_can_code, timestamp, batch_id, can_code),
                )
                can_code = new_can_code

            if particles is not None:
                connection.execute(
                    "DELETE FROM code WHERE batch_id = ? AND parent_code = ? AND pack_layer = 1",
                    (batch_id, can_code),
                )
                if particles:
                    max_seq = connection.execute(
                        "SELECT COALESCE(MAX(seq), -1) AS value FROM code WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()["value"]
                    connection.executemany(
                        """
                        INSERT INTO code
                            (id, batch_id, cur_code, pack_layer, parent_code, seq,
                             planned_particle_count, created_at, updated_at)
                        VALUES (?, ?, ?, 1, ?, ?, NULL, ?, ?)
                        """,
                        [
                            (
                                str(uuid.uuid4()),
                                batch_id,
                                code,
                                can_code,
                                max_seq + 1 + offset,
                                timestamp,
                                timestamp,
                            )
                            for offset, code in enumerate(particles)
                        ],
                    )

            self._renumber(connection, batch_id)
            connection.execute(
                "UPDATE batch SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (timestamp, batch_id),
            )
        return self.get(batch_id)

    def apply_box_state(
        self, batch_id: str, box_code: str, cans: list[dict[str, object]]
    ) -> BatchRecord | None:
        """整箱写回（重拍箱号 / 撤销箱级操作）。"""

        timestamp = _now()
        with self._db.transaction() as connection:
            exists = connection.execute(
                "SELECT id FROM batch WHERE id = ? AND deleted = 0", (batch_id,)
            ).fetchone()
            if exists is None:
                return None

            connection.execute("DELETE FROM code WHERE batch_id = ?", (batch_id,))

            if box_code:
                connection.execute(
                    """
                    INSERT INTO code
                        (id, batch_id, cur_code, pack_layer, parent_code, seq,
                         planned_particle_count, created_at, updated_at)
                    VALUES (?, ?, ?, 3, NULL, 0, NULL, ?, ?)
                    """,
                    (str(uuid.uuid4()), batch_id, box_code, timestamp, timestamp),
                )
                seq = 1
                for can in cans:
                    can_code = str(can.get("canCode") or "")
                    if not can_code:
                        continue
                    connection.execute(
                        """
                        INSERT INTO code
                            (id, batch_id, cur_code, pack_layer, parent_code, seq,
                             planned_particle_count, created_at, updated_at)
                        VALUES (?, ?, ?, 2, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            batch_id,
                            can_code,
                            box_code,
                            seq,
                            int(can.get("plannedParticleCount") or 0),
                            timestamp,
                            timestamp,
                        ),
                    )
                    seq += 1
                    for particle in list(can.get("particles") or []):
                        connection.execute(
                            """
                            INSERT INTO code
                                (id, batch_id, cur_code, pack_layer, parent_code, seq,
                                 planned_particle_count, created_at, updated_at)
                            VALUES (?, ?, ?, 1, ?, ?, NULL, ?, ?)
                            """,
                            (
                                str(uuid.uuid4()),
                                batch_id,
                                str(particle),
                                can_code,
                                seq,
                                timestamp,
                                timestamp,
                            ),
                        )
                        seq += 1

            connection.execute(
                "UPDATE batch SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (timestamp, batch_id),
            )
        return self.get(batch_id)

    def set_early_end(self, batch_id: str, early_end: EarlyEnd | None) -> BatchRecord | None:
        timestamp = _now()
        with self._db.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE batch SET
                    early_end_reason = ?, early_end_operator = ?, early_end_note = ?,
                    early_end_at = ?, early_end_can_count = ?, early_end_particle_count = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND deleted = 0
                """,
                (
                    early_end.reason if early_end else None,
                    early_end.operator if early_end else None,
                    early_end.note if early_end else None,
                    early_end.at if early_end else None,
                    early_end.actual_can_count if early_end else None,
                    early_end.actual_particle_count if early_end else None,
                    timestamp,
                    batch_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(batch_id)
