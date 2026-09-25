"""阶段 2 补强：parentCode 完整性与导出顺序约束（D-008 追加要求）。

单表方案下 parent_code 只是文本，必须由数据库自己保证三件事：
    1. 父码存在于同一批次；
    2. 父的层级正好高一级（罐的父是箱，粒子的父是罐）；
    3. 父排在子之前 —— 这正是 XML 基准要求的 "箱 → 罐 → 该罐的粒子" 顺序。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR
except ImportError:
    from support import BACKEND_DIR

from app.db import Database
from app.domain.models import Batch, BoxCode, CanCode
from app.repositories.sqlite_repository import SqliteBatchRepository
from app.services.xml_parser import parse_file

GOLDEN_DIR = BACKEND_DIR / "tests" / "golden"

BOX = "80217619000000001003"


def _insert_code(
    database: Database,
    *,
    batch_id: str,
    cur_code: str,
    pack_layer: int,
    parent_code: str | None,
    seq: int,
    planned: int | None = None,
) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO code
                (id, batch_id, cur_code, pack_layer, parent_code, seq,
                 planned_particle_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', '')
            """,
            (f"id-{cur_code}", batch_id, cur_code, pack_layer, parent_code, seq, planned),
        )


def _flake_batch() -> Batch:
    """构造一个只有箱、没有罐的批次，方便往里面手动插条码做边界测试。"""

    return Batch(
        batch_no="PARENT-TEST",
        made_date="2026-09-23",
        validate_date="2026-10-23",
        box=BoxCode(code=BOX, cans=[]),
    )


class ParentIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.database = Database(Path(self._tempdir.name) / "test.db")
        self.repository = SqliteBatchRepository(self.database)
        self.batch_id = self.repository.create(_flake_batch()).id

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    # ------------------------------------------------------------ 正常路径

    def test_valid_hierarchy_is_accepted(self) -> None:
        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=2,
        )
        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="82062339000000001004",
            pack_layer=1, parent_code="80217629000000001005", seq=2,
        )
        with self.database.read() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS n FROM code WHERE batch_id = ?", (self.batch_id,)
            ).fetchone()["n"]
        self.assertEqual(total, 3)

    # ------------------------------------------------------------ 拒绝路径

    def test_parent_must_exist_in_same_batch(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
                pack_layer=2, parent_code="80217610000000000000", seq=1, planned=1,
            )
        self.assertIn("parentCode", str(ctx.exception))

    def test_parent_must_be_exactly_one_layer_up(self) -> None:
        """粒子的父必须是罐（2），不能直接挂到箱（3）上。"""

        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="82062339000000001004",
                pack_layer=1, parent_code=BOX, seq=2,
            )

    def test_parent_must_come_before_child(self) -> None:
        """先插子、后插父：顺序反了必须拒绝（XML 要求父在前）。"""

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
                pack_layer=2, parent_code=BOX, seq=0, planned=1,
            )
        # 箱的 seq 是 0，罐不能用小于等于 0 的序号
        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="82062339000000001004",
                pack_layer=1, parent_code="80217629000000001005", seq=1,
            )

    def test_code_cannot_be_its_own_parent(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
                pack_layer=2, parent_code="80217629000000001005", seq=1, planned=1,
            )

    def test_parent_from_other_batch_is_rejected(self) -> None:
        other_id = self.repository.create(
            Batch(
                batch_no="PARENT-OTHER",
                made_date="2026-09-23",
                validate_date="2026-10-23",
                box=BoxCode(code=BOX, cans=[]),
            )
        ).id
        # 另一个批次里的罐码，不能当本批次的父
        _insert_code(
            self.database, batch_id=other_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="82062339000000001004",
                pack_layer=1, parent_code="80217629000000001005", seq=2,
            )

    def test_soft_deleted_parent_no_longer_counts(self) -> None:
        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=1,
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE code SET deleted = 1 WHERE cur_code = ?", ("80217629000000001005",)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_code(
                self.database, batch_id=self.batch_id, cur_code="82062339000000001004",
                pack_layer=1, parent_code="80217629000000001005", seq=2,
            )

    def test_update_cannot_break_parent_link(self) -> None:
        _insert_code(
            self.database, batch_id=self.batch_id, cur_code="80217629000000001005",
            pack_layer=2, parent_code=BOX, seq=1, planned=1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE code SET parent_code = ? WHERE cur_code = ?",
                    ("80217610000000000000", "80217629000000001005"),
                )


class GoldenDataSatisfiesConstraintsTests(unittest.TestCase):
    """基准数据必须天然满足新增约束，否则说明约束设计错了。"""

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.repository = SqliteBatchRepository(
            Database(Path(self._tempdir.name) / "test.db")
        )

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_both_golden_files_insert_cleanly(self) -> None:
        for name in ("1箱3罐.xml", "一箱一罐.xml"):
            with self.subTest(golden=name):
                batch = parse_file(GOLDEN_DIR / name)
                record = self.repository.create(batch)
                reloaded = self.repository.get(record.id)
                assert reloaded is not None
                self.assertEqual(
                    reloaded.batch.actual_particle_total, batch.actual_particle_total
                )

    def test_repository_still_round_trips_to_golden_bytes(self) -> None:
        from app.services.xml_builder import render_bytes

        for name in ("1箱3罐.xml", "一箱一罐.xml"):
            with self.subTest(golden=name):
                record = self.repository.create(parse_file(GOLDEN_DIR / name))
                reloaded = self.repository.get(record.id)
                assert reloaded is not None
                self.assertEqual(
                    render_bytes(reloaded.batch), (GOLDEN_DIR / name).read_bytes()
                )


if __name__ == "__main__":
    unittest.main()
