"""阶段 2 补强：draft 状态允许空结构。

这是真实浏览器 E2E 测试抓出来的缺陷：
「保存草稿」原本会跑完整的结构校验，导致还没填包装结构时根本存不下来草稿。
而 V1.1 对 draft 的定义恰恰是「界面 1 已保存，尚未生成包装结构」。

正确的边界：
    基础信息  —— 任何时候都必须合法
    包装结构  —— 空壳允许保存；一旦动笔就必须自洽；生成扫码网格前必须完整
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase, golden_batch_payload
except ImportError:
    from support import TempDatabaseTestCase, golden_batch_payload

from fastapi.testclient import TestClient


def empty_structure_payload(batch_no: str = "DRAFT-0001") -> dict[str, object]:
    """只有界面 1 的信息，包装结构还是空白。"""

    return {
        "batchNo": batch_no,
        "madeDate": "2026-09-23",
        "validateDate": "2026-10-23",
        "plannedParticleCounts": [],
        "box": {"code": "", "cans": [{"index": 1, "code": "", "plannedParticleCount": 0, "particles": []}]},
    }


class DraftValidationTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())

    def test_empty_structure_draft_can_be_saved(self) -> None:
        response = self.client.post("/api/batches", json=empty_structure_payload())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "draft")
        # 空结构草稿在库里就是"还没有包装结构"，因此罐数为 0
        self.assertEqual(body["canCount"], 0)
        self.assertEqual(body["actualParticleTotal"], 0)

    def test_empty_structure_draft_can_be_updated(self) -> None:
        created = self.client.post("/api/batches", json=empty_structure_payload()).json()
        payload = empty_structure_payload()
        payload["madeDate"] = "2026-09-24"
        updated = self.client.put(f"/api/batches/{created['id']}", json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["madeDate"], "2026-09-24")

    def test_base_info_is_still_validated(self) -> None:
        payload = empty_structure_payload()
        payload["madeDate"] = "2026-11-01"
        payload["validateDate"] = "2026-10-01"
        response = self.client.post("/api/batches", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("DATE_ORDER", codes)

    def test_empty_batch_no_is_rejected(self) -> None:
        payload = empty_structure_payload()
        payload["batchNo"] = "   "
        response = self.client.post("/api/batches", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("BATCH_NO_REQUIRED", codes)

    def test_box_code_alone_is_allowed_in_draft(self) -> None:
        """箱号在基础信息页就能填，它单独存在不代表包装结构已开始配置。"""

        payload = empty_structure_payload()
        payload["box"]["code"] = "80217619000000001003"
        response = self.client.post("/api/batches", json=payload)
        self.assertEqual(response.status_code, 201, response.text)

    def test_bad_box_code_is_still_rejected_in_draft(self) -> None:
        """填了就检查：箱号格式不对或层级不对，必须当场拦下。"""

        for wrong in ("80217629000000001005", "12345678901234567890", "8021761"):
            with self.subTest(code=wrong):
                payload = empty_structure_payload()
                payload["box"]["code"] = wrong
                response = self.client.post("/api/batches", json=payload)
                self.assertEqual(response.status_code, 422, response.text)

    def test_plan_with_zero_particles_is_rejected(self) -> None:
        """计划一动笔就必须自洽：某罐计划 0 粒直接拦下。"""

        payload = empty_structure_payload()
        payload["plannedParticleCounts"] = [500, 0]
        response = self.client.post("/api/batches", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("PARTICLE_PLAN_RANGE", codes)

    def test_plan_over_batch_limit_is_rejected(self) -> None:
        payload = empty_structure_payload()
        payload["plannedParticleCounts"] = [2500, 2500, 2500, 2500, 2500, 2500]
        response = self.client.post("/api/batches", json=payload)
        self.assertEqual(response.status_code, 422)
        codes = {issue["code"] for issue in response.json()["error"]["detail"]["issues"]}
        self.assertIn("CAN_COUNT_RANGE", codes)
        self.assertIn("PARTICLE_TOTAL_RANGE", codes)

    def test_generating_scan_grid_requires_complete_structure(self) -> None:
        created = self.client.post("/api/batches", json=empty_structure_payload()).json()

        response = self.client.post(
            f"/api/batches/{created['id']}/status", json={"target": "collecting"}
        )
        self.assertEqual(response.status_code, 422)
        detail = response.json()["error"]["detail"]
        self.assertEqual(detail["reason"], "STRUCTURE_INCOMPLETE")
        codes = {issue["code"] for issue in detail["issues"]}
        self.assertIn("PLAN_REQUIRED", codes)

    def test_generating_scan_grid_succeeds_after_structure_filled(self) -> None:
        created = self.client.post("/api/batches", json=empty_structure_payload()).json()

        payload = golden_batch_payload("DRAFT-0001")
        updated = self.client.put(f"/api/batches/{created['id']}", json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)

        response = self.client.post(
            f"/api/batches/{created['id']}/status", json={"target": "collecting"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["batch"]["status"], "collecting")


if __name__ == "__main__":
    unittest.main()
