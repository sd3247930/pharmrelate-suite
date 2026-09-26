"""XML 导入（阶段 2）：解析、结构校验、批号三选一、字节级往返。

核心判据只有一条：**导入 → 再导出 → 与原文件 SHA-256 完全相同**。
这条一过，就说明"读回来的东西没有走形"，其余都是它的保护条件。
"""

from __future__ import annotations

import hashlib
import unittest

from fastapi.testclient import TestClient

try:  # 标准用法：python -m unittest discover -s tests -t .
    from tests.support import TempDatabaseTestCase
except ImportError:  # 直接以 tests 为顶层目录运行时
    from support import TempDatabaseTestCase

from app.services import golden


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class XmlImportRoundTripTests(TempDatabaseTestCase):
    """两个真实基准文件都必须能原样读回、再原样写出。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def import_golden(self, name: str) -> dict[str, object]:
        raw = golden.read_bytes(name)
        response = self.client.post(
            "/api/import/xml",
            json={"xml": raw.decode("utf-8"), "sourceName": name},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def walk_to_verified(self, batch_id: str) -> None:
        for target in ("collecting", "pending_review", "verified"):
            response = self.client.post(
                f"/api/batches/{batch_id}/status", json={"target": target}
            )
            self.assertEqual(response.status_code, 200, response.text)

    def export_bytes(self, batch_id: str) -> bytes:
        response = self.client.post(
            f"/api/batches/{batch_id}/export", json={"kinds": ["xml"], "operator": "导入测试"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        download = self.client.get(f"/api/exports/{items[0]['id']}/download")
        self.assertEqual(download.status_code, 200)
        return download.content

    def test_each_golden_round_trips_byte_for_byte(self) -> None:
        for name in golden.GOLDEN_NAMES:
            with self.subTest(name=name):
                original = golden.read_bytes(name)
                payload = self.import_golden(name)
                batch_id = payload["batchId"]
                summary = payload["summary"]
                self.assertTrue(batch_id)
                self.assertTrue(summary["boxCode"])
                self.assertGreaterEqual(summary["canCount"], 1)
                self.assertGreaterEqual(summary["particleTotal"], 1)
                self.assertEqual(
                    summary["plannedParticleCounts"], [1, 1, 2] if name == "1箱3罐.xml" else [400]
                )

                self.walk_to_verified(batch_id)
                exported = self.export_bytes(batch_id)
                self.assertEqual(
                    sha256(exported),
                    sha256(original),
                    f"{name} 导入后导出未能回到原字节",
                )

    def test_imported_batch_shows_plan_equals_actual(self) -> None:
        """计划由文件推断，因此导入后"计划 vs 实际"天然一致、可直接核对。"""

        batch_id = self.import_golden("1箱3罐.xml")["batchId"]
        review = self.client.get(f"/api/batches/{batch_id}/review").json()
        self.assertEqual(review["plan"]["particleTotal"], review["actual"]["particleTotal"])
        self.assertEqual(review["missingParticles"], 0)
        self.assertTrue(all(item["passed"] for item in review["checks"]))

    def test_imported_batch_starts_as_draft(self) -> None:
        payload = self.import_golden("1箱3罐.xml")
        self.assertEqual(payload["summary"]["status"], "draft")
        detail = self.client.get(f"/api/batches/{payload['batchId']}").json()
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(detail["canCount"], 3)
        self.assertEqual(detail["actualParticleTotal"], 4)


class XmlImportRejectionTests(TempDatabaseTestCase):
    """严格校验：坏文件必须给出可读中文原因，而不是 500 或静默接受。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.original = golden.read_bytes("1箱3罐.xml").decode("utf-8")

    def post(self, xml: str) -> tuple[int, dict[str, object]]:
        response = self.client.post("/api/import/xml", json={"xml": xml, "sourceName": "坏文件.xml"})
        return response.status_code, response.json()

    def test_missing_parent_code_is_rejected(self) -> None:
        broken = self.original.replace(
            '<Code curCode="82062339000000001004" packLayer="1" parentCode="80217629000000001005" flag="2"/>',
            '<Code curCode="82062339000000001004" packLayer="1" flag="2"/>',
        )
        status, body = self.post(broken)
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["detail"]["reason"], "XML_INVALID")
        self.assertIn("parentCode", body["error"]["detail"]["issues"][0]["message"])

    def test_changed_fixed_param_is_rejected(self) -> None:
        broken = self.original.replace('cascade="1:5:2500"', 'cascade="1:3:900"')
        status, body = self.post(broken)
        self.assertEqual(status, 422)
        message = body["error"]["detail"]["issues"][0]["message"]
        self.assertIn("cascade", message)

    def test_particle_under_box_is_rejected(self) -> None:
        broken = self.original.replace(
            '<Code curCode="82062339000000001004" packLayer="1" parentCode="80217629000000001005" flag="2"/>',
            '<Code curCode="82062339000000001004" packLayer="1" parentCode="80217619000000001003" flag="2"/>',
        )
        status, body = self.post(broken)
        self.assertEqual(status, 422)
        self.assertIn("未匹配到任何已出现的罐节点", body["error"]["detail"]["issues"][0]["message"])

    def test_second_box_is_rejected(self) -> None:
        broken = self.original.replace(
            '<Code curCode="80217629000000001005" packLayer="2" parentCode="80217619000000001003" flag="2"/>',
            '<Code curCode="80217619000000001004" packLayer="3" flag="2"/>',
            1,
        )
        status, body = self.post(broken)
        self.assertEqual(status, 422)
        self.assertIn("第 2 个箱节点", body["error"]["detail"]["issues"][0]["message"])

    def test_garbage_is_rejected(self) -> None:
        status, body = self.post("这不是 XML")
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["detail"]["reason"], "XML_INVALID")

    def test_empty_xml_is_rejected_by_schema(self) -> None:
        response = self.client.post("/api/import/xml", json={"xml": ""})
        self.assertEqual(response.status_code, 422)


class XmlImportConflictTests(TempDatabaseTestCase):
    """批号冲突走与创建草稿完全相同的"三选一"。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.xml = golden.read_bytes("1箱3罐.xml").decode("utf-8")

    def import_once(self, *, force_new_version: bool = False):
        return self.client.post(
            "/api/import/xml",
            json={"xml": self.xml, "sourceName": "1箱3罐.xml", "forceNewVersion": force_new_version},
        )

    def test_duplicate_batch_no_returns_three_options(self) -> None:
        first = self.import_once()
        self.assertEqual(first.status_code, 200, first.text)

        second = self.import_once()
        self.assertEqual(second.status_code, 409)
        detail = second.json()["error"]["detail"]
        self.assertEqual(detail["reason"], "BATCH_NO_EXISTS")
        self.assertEqual(
            [option["action"] for option in detail["options"]],
            ["open_existing", "create_new_version", "cancel"],
        )
        self.assertTrue(detail["suggestedBatchNo"])
        self.assertEqual(detail["existing"]["id"], first.json()["batchId"])

    def test_force_new_version_creates_versioned_batch(self) -> None:
        self.import_once()
        second = self.import_once(force_new_version=True)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(second.json()["summary"]["batchNo"], "20260901")
        self.assertTrue(second.json()["summary"]["batchNo"].startswith("20260901-V"))


if __name__ == "__main__":
    unittest.main()
