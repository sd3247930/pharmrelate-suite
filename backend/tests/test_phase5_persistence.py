"""阶段 5：导出文件落盘。

落盘要解决的是"记录还在、内容没了"这个问题，所以测试重点是：
进程重启（缓存清空）之后，文件仍能按哈希校验后取回。
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR
except ImportError:
    from support import BACKEND_DIR

from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.services import golden
from app.services.xml_parser import parse_bytes

GOLDEN_DIR = BACKEND_DIR / "tests" / "golden"


def golden_payload() -> dict[str, object]:
    batch = parse_bytes(golden.read_bytes("1箱3罐.xml"))
    return {
        "batchNo": "20260901",
        "madeDate": batch.made_date,
        "validateDate": batch.validate_date,
        "plannedParticleCounts": [len(can.particles) for can in batch.box.cans],
        "box": {
            "code": batch.box.code,
            "cans": [
                {
                    "index": can.index,
                    "code": can.code,
                    "plannedParticleCount": len(can.particles),
                    "particles": list(can.particles),
                }
                for can in batch.box.cans
            ],
        },
    }


class ExportPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.data_dir = Path(self._tempdir.name)
        self.database = Database(self.data_dir / "pharmrelate.db")
        self.client = TestClient(create_app(database=self.database))
        self.batch_id = self.client.post("/api/batches", json=golden_payload()).json()["id"]
        for target in ("collecting", "pending_review", "verified"):
            self.client.post(
                f"/api/batches/{self.batch_id}/status", json={"target": target}
            )

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def export(self, kinds: list[str]) -> dict:
        response = self.client.post(
            f"/api/batches/{self.batch_id}/export", json={"kinds": kinds}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def restart(self) -> TestClient:
        """换一个 app 实例（缓存清空），复用同一个数据目录。"""

        return TestClient(create_app(database=Database(self.data_dir / "pharmrelate.db")))

    def test_files_are_written_under_exports_batch_no(self) -> None:
        items = self.export(["xml", "html"])["items"]
        directory = self.data_dir / "exports" / "20260901"
        self.assertTrue(directory.is_dir(), f"导出目录应存在于 {directory}")

        for item in items:
            path = directory / item["filename"]
            self.assertTrue(path.is_file(), f"缺少文件：{path}")

    def test_written_content_matches_record_hash(self) -> None:
        item = self.export(["xml"])["items"][0]
        path = self.data_dir / "exports" / "20260901" / item["filename"]
        content = path.read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"])
        self.assertEqual(content, (GOLDEN_DIR / "1箱3罐.xml").read_bytes())

    def test_download_works_after_process_restart(self) -> None:
        """核心用例：重启后缓存没了，仍要能从磁盘取回文件。"""

        item = self.export(["xml"])["items"][0]

        fresh = self.restart()
        response = fresh.get(f"/api{item['downloadUrl']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, (GOLDEN_DIR / "1箱3罐.xml").read_bytes())
        self.assertEqual(response.headers["X-Content-SHA256"], item["sha256"])

    def test_history_survives_restart_and_reports_storage_path(self) -> None:
        item = self.export(["html"])["items"][0]
        fresh = self.restart()
        body = fresh.get(f"/api/batches/{self.batch_id}/exports").json()
        self.assertEqual(body["total"], 1)
        record = body["items"][0]
        self.assertEqual(record["filename"], item["filename"])
        self.assertTrue(Path(record["storedAt"]).is_file())
        self.assertIn("exports", record["storedAt"])

    def test_tampered_file_is_reported_unavailable(self) -> None:
        """文件被外部改动 → 哈希对不上 → 宁可报不可用，也不给错文件。"""

        item = self.export(["xml"])["items"][0]
        path = self.data_dir / "exports" / "20260901" / item["filename"]
        path.write_bytes(b"<Document/>")

        fresh = self.restart()
        response = fresh.get(f"/api{item['downloadUrl']}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["detail"]["reason"], "CONTENT_UNAVAILABLE"
        )

    def test_record_without_file_is_reported_unavailable(self) -> None:
        item = self.export(["xml"])["items"][0]
        path = self.data_dir / "exports" / "20260901" / item["filename"]
        path.unlink()

        fresh = self.restart()
        response = fresh.get(f"/api{item['downloadUrl']}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["detail"]["reason"], "CONTENT_UNAVAILABLE"
        )

    def test_repeated_export_creates_separate_files(self) -> None:
        first = self.export(["xml"])["items"][0]
        second = self.export(["xml"])["items"][0]
        directory = self.data_dir / "exports" / "20260901"
        files = {item.name for item in directory.iterdir()}

        # 文件名精确到秒，同一秒内重名时：内容相同复用同一文件，
        # 内容不同才加序号。绝不覆盖已有文件。
        for item in (first, second):
            self.assertIn(item["filename"], files, f"记录里的名字必须真的存在于磁盘：{item}")
        self.assertEqual(first["sha256"], second["sha256"], "同样数据应得到同样内容")

    def test_export_dir_is_beside_the_database(self) -> None:
        """导出目录必须与库同在用户数据目录，不能落在安装目录。"""

        self.export(["xml"])
        self.assertTrue((self.data_dir / "pharmrelate.db").is_file())
        self.assertTrue((self.data_dir / "exports").is_dir())


if __name__ == "__main__":
    unittest.main()
