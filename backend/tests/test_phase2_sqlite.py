"""阶段 2：SQLite 持久化、唯一约束与事务性测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR, golden_batch_payload
except ImportError:
    from support import BACKEND_DIR, golden_batch_payload

from app.db import Database
from app.domain.constants import FIXED_PARAMS
from app.domain.models import Batch, BoxCode, CanCode
from app.repositories.sqlite_repository import SqliteBatchRepository
from app.services import golden
from app.services.xml_builder import render_bytes
from app.services.xml_parser import parse_file

GOLDEN_DIR = BACKEND_DIR / "tests" / "golden"


def golden_batch() -> Batch:
    return parse_file(GOLDEN_DIR / "1箱3罐.xml")


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.db_path = Path(self._tempdir.name) / "test.db"

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_schema_version_is_recorded(self) -> None:
        database = Database(self.db_path)
        database.initialise()
        self.assertEqual(database.schema_version(), "3")

    def test_data_survives_reopen(self) -> None:
        """模拟"重启进程"：换一个 Database 实例打开同一个文件。"""

        first = SqliteBatchRepository(Database(self.db_path))
        created = first.create(golden_batch())

        second = SqliteBatchRepository(Database(self.db_path))
        reloaded = second.get(created.id)

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.batch.batch_no, "20260901")
        self.assertEqual(reloaded.batch.can_count, 3)
        self.assertEqual([len(can.particles) for can in reloaded.batch.box.cans], [1, 1, 2])

    def test_round_trip_to_xml_is_still_byte_exact(self) -> None:
        """数据经 SQLite 走一圈后，导出结果仍必须与基准字节级一致。"""

        repository = SqliteBatchRepository(Database(self.db_path))
        created = repository.create(golden_batch())
        reloaded = repository.get(created.id)
        assert reloaded is not None

        expected = (GOLDEN_DIR / "1箱3罐.xml").read_bytes()
        self.assertEqual(render_bytes(reloaded.batch), expected)

    def test_particle_order_is_preserved(self) -> None:
        """400 粒的批次经持久化后顺序不得改变。"""

        repository = SqliteBatchRepository(Database(self.db_path))
        big = parse_file(GOLDEN_DIR / "一箱一罐.xml")
        created = repository.create(big)
        reloaded = repository.get(created.id)
        assert reloaded is not None

        original = big.box.cans[0].particles
        restored = reloaded.batch.box.cans[0].particles
        self.assertEqual(restored, original)
        self.assertNotEqual(restored, sorted(restored), "顺序应保持采集原序，而不是被排序")
        self.assertEqual((GOLDEN_DIR / "一箱一罐.xml").read_bytes(), render_bytes(reloaded.batch))

    def test_fixed_params_are_persisted_not_recomputed(self) -> None:
        repository = SqliteBatchRepository(Database(self.db_path))
        created = repository.create(parse_file(GOLDEN_DIR / "一箱一罐.xml"))

        with Database(self.db_path).read() as connection:
            row = connection.execute(
                "SELECT cascade, license, flag, workshop FROM batch WHERE id = ?",
                (created.id,),
            ).fetchone()

        self.assertEqual(row["cascade"], "1:5:2500")
        self.assertEqual(row["cascade"], FIXED_PARAMS.cascade)
        self.assertEqual(row["license"], FIXED_PARAMS.license)
        self.assertEqual(row["flag"], FIXED_PARAMS.flag)
        self.assertEqual(row["workshop"], FIXED_PARAMS.workshop)


class ConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.database = Database(Path(self._tempdir.name) / "test.db")
        self.repository = SqliteBatchRepository(self.database)

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_batch_no_is_unique(self) -> None:
        self.repository.create(golden_batch())
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.create(golden_batch())

    def test_same_code_twice_in_one_batch_is_rejected(self) -> None:
        """同批次内条码全局唯一：跨层级的重复也要被拦。"""

        batch = golden_batch()
        # 让罐 2 复用罐 1 的粒子码 → 同批次内 code 重复
        batch.box.cans[1].particles = list(batch.box.cans[0].particles)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.create(batch)

    def test_layer_check_rejects_box_with_parent(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO code
                        (id, batch_id, cur_code, pack_layer, parent_code, seq, created_at, updated_at)
                    VALUES ('x', 'missing-batch', '80217619000000001003', 3, '有父不该允许', 0, '', '')
                    """
                )

    def test_layer_check_rejects_can_without_plan(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO code
                        (id, batch_id, cur_code, pack_layer, parent_code, seq, created_at, updated_at)
                    VALUES ('y', 'missing-batch', '80217629000000001005', 2, '80217619000000001003', 1, '', '')
                    """
                )

    def test_unknown_pack_layer_is_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO code
                        (id, batch_id, cur_code, pack_layer, parent_code, seq, created_at, updated_at)
                    VALUES ('z', 'missing-batch', '99000000000000000000', 9, NULL, 0, '', '')
                    """
                )

    def test_foreign_key_rejects_orphan_code(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO code
                        (id, batch_id, cur_code, pack_layer, parent_code, seq, created_at, updated_at)
                    VALUES ('w', '不存在的批次', '80217619000000001003', 3, NULL, 0, '', '')
                    """
                )

    def test_schema_has_expected_tables_and_views(self) -> None:
        with self.database.read() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            views = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'view'"
                )
            }

        for table in ("batch", "code", "oplog", "audit_log", "meta"):
            self.assertIn(table, tables)
        for view in ("v_box", "v_can", "v_particle"):
            self.assertIn(view, views)

    def test_sync_meta_columns_are_reserved(self) -> None:
        """一期不实现同步，但字段必须先落库，二期才不用改表。"""

        with self.database.read() as connection:
            batch_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(batch)")
            }
            code_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(code)")
            }

        for column in ("revision", "hlc", "updated_by", "device_id", "deleted"):
            self.assertIn(column, batch_columns)
            self.assertIn(column, code_columns)

    def test_early_end_columns_exist(self) -> None:
        with self.database.read() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(batch)")}
        for column in (
            "early_end_reason",
            "early_end_operator",
            "early_end_note",
            "early_end_at",
            "early_end_can_count",
            "early_end_particle_count",
        ):
            self.assertIn(column, columns)


class TransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.database = Database(Path(self._tempdir.name) / "test.db")
        self.repository = SqliteBatchRepository(self.database)

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_failed_insert_rolls_back_whole_batch(self) -> None:
        """条码写入失败时，批次行不能留下，否则会出现残缺批次。"""

        batch = golden_batch()
        batch.box.cans[1].particles = list(batch.box.cans[0].particles)  # 触发唯一约束

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.create(batch)

        self.assertEqual(self.repository.count(), 0)
        with self.database.read() as connection:
            codes = connection.execute("SELECT COUNT(*) AS n FROM code").fetchone()
        self.assertEqual(codes["n"], 0)

    def test_update_replaces_codes_atomically(self) -> None:
        created = self.repository.create(golden_batch())

        modified = golden_batch()
        modified.box.cans[2].particles = ["82062339000000001003"]  # 从 2 粒减为 1 粒
        updated = self.repository.update(created.id, modified)
        assert updated is not None

        self.assertEqual(updated.batch.actual_particle_total, 3)
        self.assertEqual(updated.revision, 2)
        with self.database.read() as connection:
            codes = connection.execute(
                "SELECT COUNT(*) AS n FROM code WHERE batch_id = ?", (created.id,)
            ).fetchone()
        self.assertEqual(codes["n"], 7)  # 1 箱 + 3 罐 + 3 粒

    def test_failed_update_keeps_original_data(self) -> None:
        created = self.repository.create(golden_batch())

        broken = golden_batch()
        broken.box.cans[1].particles = ["82062339000000001003"]  # 与罐 3 冲突
        broken.box.cans[2].particles = ["82062339000000001003"]

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.update(created.id, broken)

        reloaded = self.repository.get(created.id)
        assert reloaded is not None
        self.assertEqual(reloaded.batch.actual_particle_total, 4)
        self.assertEqual(reloaded.revision, 1, "失败的回滚不应推进 revision")


class VersionNumberingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.repository = SqliteBatchRepository(
            Database(Path(self._tempdir.name) / "test.db")
        )

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_next_version_skips_used_numbers(self) -> None:
        batch = golden_batch()
        batch.batch_no = "20260901-V2"
        self.repository.create(batch)
        batch.batch_no = "20260901-V4"
        self.repository.create(batch)

        self.assertEqual(self.repository.next_version_no("20260901"), "20260901-V3")


if __name__ == "__main__":
    unittest.main()
