"""手机端一步导出（阶段 4）：`GET /api/export/xml` 必须与电脑端导出同源同物。

判据：同一批次经这条接口拿到的文件，与电脑端导出记录里的
文件名、SHA-256、字节内容三者全部一致。
"""

from __future__ import annotations

import hashlib
import re
import unittest

from fastapi.testclient import TestClient

try:  # 标准用法：python -m unittest discover -s tests -t .
    from tests.support import TempDatabaseTestCase
except ImportError:  # 直接以 tests 为顶层目录运行时
    from support import TempDatabaseTestCase

from app.services import golden


class ExportXmlDirectTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.original = golden.read_bytes("1箱3罐.xml")

    def imported_verified_batch(self) -> str:
        response = self.client.post(
            "/api/import/xml",
            json={"xml": self.original.decode("utf-8"), "sourceName": "1箱3罐.xml"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        batch_id = response.json()["batchId"]
        for target in ("collecting", "pending_review", "verified"):
            moved = self.client.post(f"/api/batches/{batch_id}/status", json={"target": target})
            self.assertEqual(moved.status_code, 200, moved.text)
        return batch_id

    def test_direct_export_matches_pc_export(self) -> None:
        batch_id = self.imported_verified_batch()

        response = self.client.get(
            f"/api/export/xml?batchId={batch_id}&operator=honorANDROID_DEVICE"
        )
        self.assertEqual(response.status_code, 200, response.text)

        disposition = response.headers["content-disposition"]
        match = re.search(r'filename="([^"]+)"', disposition)
        self.assertIsNotNone(match, disposition)
        filename = match.group(1)
        self.assertRegex(filename, r"^Relation_20260901_\d{14}\.xml$")

        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        self.assertEqual(digest, hashlib.sha256(self.original).hexdigest(), "内容必须与原文件一致")
        self.assertEqual(response.headers["x-content-sha256"], digest)

        # 服务端的导出记录：文件名、哈希、操作人与文件本体一一对应
        history = self.client.get(f"/api/batches/{batch_id}/exports").json()
        self.assertEqual(len(history["items"]), 1)
        record = history["items"][0]
        self.assertEqual(record["filename"], filename)
        self.assertEqual(record["sha256"], digest)
        self.assertEqual(record["operator"], "honorANDROID_DEVICE")

        # 导出后状态推进（与电脑端导出同一条路径）
        detail = self.client.get(f"/api/batches/{batch_id}").json()
        self.assertEqual(detail["status"], "exported")

    def test_download_record_matches_direct_export(self) -> None:
        """导出记录里的下载地址与直连接口取到的是同一份字节。"""

        batch_id = self.imported_verified_batch()
        direct = self.client.get(f"/api/export/xml?batchId={batch_id}")
        record = self.client.get(f"/api/batches/{batch_id}/exports").json()["items"][0]
        via_record = self.client.get(f"/api/exports/{record['id']}/download")
        self.assertEqual(direct.content, via_record.content)

    def test_export_before_review_is_blocked(self) -> None:
        response = self.client.post(
            "/api/batches", json={
                "batchNo": "DIRECT01",
                "madeDate": "2026-09-26",
                "validateDate": "2026-10-26",
                "plannedParticleCounts": [3],
                "box": {"code": "", "cans": []},
            },
        )
        batch_id = response.json()["id"]
        self.client.post(f"/api/batches/{batch_id}/status", json={"target": "collecting"})

        blocked = self.client.get(f"/api/export/xml?batchId={batch_id}")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["detail"]["reason"], "STATUS_NOT_VERIFIED")

    def test_missing_batch_id_is_rejected(self) -> None:
        response = self.client.get("/api/export/xml")
        self.assertEqual(response.status_code, 422)

    def test_unknown_batch_is_rejected_like_pc_export(self) -> None:
        """未知批次与电脑端导出的行为一致（同为 409 + batchId），不另造一套语义。"""

        response = self.client.get("/api/export/xml?batchId=不存在的批次")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["detail"]["batchId"], "不存在的批次")

        pc = self.client.post(
            "/api/batches/不存在的批次/export", json={"kinds": ["xml"]}
        )
        self.assertEqual(pc.status_code, 409)


if __name__ == "__main__":
    unittest.main()
