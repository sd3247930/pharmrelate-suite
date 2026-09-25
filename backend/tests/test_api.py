"""阶段 1 API 契约测试（阶段 2 起改用临时 SQLite 库）。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

try:  # 标准用法：python -m unittest discover -s tests -t .
    from tests.support import TempDatabaseTestCase, golden_batch_payload
except ImportError:  # 直接以 tests 为顶层目录运行时
    from support import TempDatabaseTestCase, golden_batch_payload

from app.services import golden


class HealthTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def test_health_ok(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("python", body)

    def test_health_reports_golden_roundtrip(self) -> None:
        body = self.client.get("/api/health").json()
        self.assertTrue(body["goldenOk"], "黄金基准应保持字节级一致")
        self.assertEqual(len(body["golden"]), 2)
        for item in body["golden"]:
            self.assertTrue(item["roundtripOk"], f"{item['name']} 往返校验失败")
            self.assertEqual(len(item["sha256"]), 64)


class GoldenTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def test_list_golden(self) -> None:
        body = self.client.get("/api/golden").json()
        self.assertTrue(body["allOk"])
        names = {item["name"] for item in body["items"]}
        self.assertEqual(names, {"1箱3罐.xml", "一箱一罐.xml"})

    def test_read_golden_xml_is_byte_exact(self) -> None:
        for name in ("1箱3罐.xml", "一箱一罐.xml"):
            with self.subTest(name=name):
                response = self.client.get(f"/api/golden/{name}/xml")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.text.encode("utf-8"),
                    golden.read_bytes(name),
                    f"{name} 经 HTTP 返回后字节发生变化",
                )

    def test_unknown_golden_returns_unified_error(self) -> None:
        response = self.client.get("/api/golden/不存在.xml/xml")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertIn("available", body["error"]["detail"])

    def test_path_traversal_is_rejected(self) -> None:
        for attempt in (
            "/api/golden/..%2F..%2Fpyproject.toml/xml",
            "/api/golden/%2E%2E%2F%2E%2E%2Fpyproject.toml/xml",
            "/api/golden/..%5C..%5Cpyproject.toml/xml",
        ):
            with self.subTest(attempt=attempt):
                response = self.client.get(attempt)
                self.assertEqual(response.status_code, 404, attempt)
                self.assertNotIn("pharmrelate-multi-backend", response.text)

    def test_whitelist_rejects_non_golden_name(self) -> None:
        response = self.client.get("/api/golden/pyproject.toml/xml")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertIn("available", response.json()["error"]["detail"])


class XmlPreviewTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def test_preview_returns_stage0_xml(self) -> None:
        response = self.client.post("/api/xml/preview", json=golden_batch_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        expected = golden.read_text("1箱3罐.xml")
        self.assertEqual(body["xml"], expected, "预览结果与阶段 0 基准不一致")
        self.assertEqual(body["byteLength"], len(expected.encode("utf-8")))
        self.assertEqual(body["stats"]["canCount"], 3)
        self.assertEqual(body["stats"]["actualParticleTotal"], 4)

    def test_preview_rejects_wrong_layer_code(self) -> None:
        payload = golden_batch_payload()
        payload["box"]["cans"][0]["code"] = "82062339000000001004"  # type: ignore[index]
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_FAILED")
        codes = {issue["code"] for issue in error["detail"]["issues"]}
        self.assertIn("CODE_LAYER_MISMATCH", codes)

    def test_preview_rejects_duplicate_particle(self) -> None:
        payload = golden_batch_payload()
        cans = payload["box"]["cans"]  # type: ignore[index]
        cans[0]["particles"] = ["82062339000000001004"]
        cans[1]["particles"] = ["82062339000000001004"]
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("DUPLICATE_CODE", codes)

    def test_validate_endpoint_separates_ok_from_issues(self) -> None:
        ok = self.client.post("/api/xml/validate", json=golden_batch_payload()).json()
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["issues"], [])

    def test_unknown_field_is_rejected(self) -> None:
        payload = golden_batch_payload()
        payload["batchNom"] = "typo"
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "REQUEST_INVALID")


class BatchCrudTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def test_create_then_get_then_update(self) -> None:
        created = self.client.post("/api/batches", json=golden_batch_payload("20260911"))
        self.assertEqual(created.status_code, 201)
        record = created.json()
        self.assertEqual(record["status"], "draft")
        self.assertEqual(record["statusLabel"], "草稿")
        self.assertTrue(record["editable"])
        self.assertEqual(record["canCount"], 3)

        fetched = self.client.get(f"/api/batches/{record['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["batchNo"], "20260911")

        payload = golden_batch_payload("20260911")
        payload["madeDate"] = "2026-09-24"
        updated = self.client.put(f"/api/batches/{record['id']}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["revision"], 2)

    def test_list_includes_lifecycle_statuses(self) -> None:
        self.client.post("/api/batches", json=golden_batch_payload("20260913"))
        body = self.client.get("/api/batches").json()
        self.assertEqual(body["total"], 1)
        self.assertIn("exported", body["statuses"])
        self.assertIn("void", body["statuses"])

    def test_missing_batch_returns_unified_error(self) -> None:
        response = self.client.get("/api/batches/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_storage_reports_database_path(self) -> None:
        body = self.client.get("/api/system/storage").json()
        self.assertTrue(body["exists"])
        self.assertEqual(body["schemaVersion"], "4")
        # 必须落在临时目录，不能是用户真实数据目录
        self.assertIn("pharmrelate-test-", body["databasePath"])


class OpenApiTests(TempDatabaseTestCase):
    def test_openapi_is_generated(self) -> None:
        client = TestClient(self.make_app())
        schema = client.get("/openapi.json").json()
        self.assertEqual(schema["info"]["title"], "籽关通 (PharmRelate Multi) 本地服务")
        for path in ("/api/health", "/api/xml/preview", "/api/batches"):
            self.assertIn(path, schema["paths"])


if __name__ == "__main__":
    unittest.main()
