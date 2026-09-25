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
