"""阶段 1 API 契约测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.services import golden  # noqa: E402
from app.services.xml_parser import parse_bytes  # noqa: E402


def valid_payload(batch_no: str = "20260901") -> dict[str, object]:
    """用 1箱3罐 基准的结构构造一份合法请求体。"""

    batch = parse_bytes(golden.read_bytes("1箱3罐.xml"))
    return {
        "batchNo": batch_no,
        "madeDate": batch.made_date,
        "validateDate": batch.validate_date,
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


class HealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

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


class GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

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
                # HTTP 层不应改动字节：响应体转回 UTF-8 后须与基准一致
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
        """名称必须走白名单，不能穿越目录读取到任意文件。"""

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
        """路由匹配到但不在白名单内的名称，返回统一错误而非文件内容。"""

        response = self.client.get("/api/golden/pyproject.toml/xml")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertIn("available", response.json()["error"]["detail"])


class XmlPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_preview_returns_stage0_xml(self) -> None:
        response = self.client.post("/api/xml/preview", json=valid_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        expected = golden.read_text("1箱3罐.xml")
        self.assertEqual(body["xml"], expected, "预览结果与阶段 0 基准不一致")
        self.assertEqual(body["byteLength"], len(expected.encode("utf-8")))
        self.assertEqual(body["stats"]["canCount"], 3)
        self.assertEqual(body["stats"]["actualParticleTotal"], 4)

    def test_preview_rejects_wrong_layer_code(self) -> None:
        """把粒子码当罐号提交，必须被层级前缀校验拦住。"""

        payload = valid_payload()
        payload["box"]["cans"][0]["code"] = "82062339000000001004"  # type: ignore[index]
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_FAILED")
        codes = {issue["code"] for issue in error["detail"]["issues"]}
        self.assertIn("CODE_LAYER_MISMATCH", codes)

    def test_preview_rejects_duplicate_particle(self) -> None:
        payload = valid_payload()
        cans = payload["box"]["cans"]  # type: ignore[index]
        cans[0]["particles"] = ["82062339000000001004"]
        cans[1]["particles"] = ["82062339000000001004"]
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("DUPLICATE_CODE", codes)

    def test_validate_endpoint_separates_ok_from_issues(self) -> None:
        ok = self.client.post("/api/xml/validate", json=valid_payload()).json()
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["issues"], [])

    def test_unknown_field_is_rejected(self) -> None:
        payload = valid_payload()
        payload["batchNom"] = "typo"
        response = self.client.post("/api/xml/preview", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "REQUEST_INVALID")


class BatchCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        # 仓储挂在 app.state 上，因此每个 app 实例数据独立，用例互不干扰
        self.client = TestClient(create_app())

    def test_create_then_get_then_update(self) -> None:
        created = self.client.post("/api/batches", json=valid_payload("20260911"))
        self.assertEqual(created.status_code, 201)
        record = created.json()
        self.assertEqual(record["status"], "draft")
        self.assertEqual(record["canCount"], 3)

        fetched = self.client.get(f"/api/batches/{record['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["batchNo"], "20260911")

        payload = valid_payload("20260911")
        payload["madeDate"] = "2026-09-24"  # type: ignore[index]
        updated = self.client.put(f"/api/batches/{record['id']}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["revision"], 2)

    def test_duplicate_batch_no_returns_three_options(self) -> None:
        self.client.post("/api/batches", json=valid_payload("20260912"))
        duplicate = self.client.post("/api/batches", json=valid_payload("20260912"))
        self.assertEqual(duplicate.status_code, 409)
        error = duplicate.json()["error"]
        self.assertEqual(error["code"], "CONFLICT")
        self.assertEqual(error["detail"]["reason"], "BATCH_NO_EXISTS")
        actions = [option["action"] for option in error["detail"]["options"]]
        self.assertEqual(actions, ["open_existing", "create_new_version", "cancel"])

    def test_list_includes_lifecycle_statuses(self) -> None:
        self.client.post("/api/batches", json=valid_payload("20260913"))
        body = self.client.get("/api/batches").json()
        self.assertEqual(body["total"], 1)
        self.assertIn("exported", body["statuses"])
        self.assertIn("void", body["statuses"])

    def test_missing_batch_returns_unified_error(self) -> None:
        response = self.client.get("/api/batches/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")


class OpenApiTests(unittest.TestCase):
    def test_openapi_is_generated(self) -> None:
        client = TestClient(create_app())
        schema = client.get("/openapi.json").json()
        self.assertEqual(schema["info"]["title"], "籽关通 (PharmRelate Multi) 本地服务")
        for path in ("/api/health", "/api/xml/preview", "/api/batches"):
            self.assertIn(path, schema["paths"])


if __name__ == "__main__":
    unittest.main()
