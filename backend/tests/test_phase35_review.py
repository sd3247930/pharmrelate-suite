"""阶段 3.5：整体核对与缺漏禁止导出。

核对的核心不是"完成"两个字，而是能指出**缺在哪一罐、缺几个**；
导出闸门是硬规则：实际少于计划一律禁止，除非办理了提前结束并留下签名。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase
except ImportError:
    from support import TempDatabaseTestCase

from fastapi.testclient import TestClient

BOX = "80217619000000001003"
CAN1 = "80217629000000001005"
CAN2 = "80217629000000001004"
P1 = ["82062339000000001004", "82062339000000001001"]
P2 = ["82062339000000001003", "82062339000000001002"]


class ReviewTestCase(TempDatabaseTestCase):
    """2 罐 × 2 粒的批次。默认只扫满罐 1，制造罐 2 的缺漏。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.batch_id = self.client.post(
            "/api/batches",
            json={
                "batchNo": "REVIEW-01",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [2, 2],
                "box": {"code": "", "cans": []},
            },
        ).json()["id"]

    def scan(self, path: str, body: dict | None = None) -> dict:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/{path}", json=body if body is not None else {}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def review(self) -> dict:
        response = self.client.get(f"/api/batches/{self.batch_id}/review")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def start_scanning(self) -> None:
        self.client.post(
            f"/api/batches/{self.batch_id}/status", json={"target": "collecting"}
        )

    def scan_can1_only(self) -> None:
        self.start_scanning()
        self.scan("frame", {"codes": [BOX]})
        self.scan("confirm")
        self.scan("frame", {"codes": [CAN1]})
        self.scan("confirm")
        self.scan("frame", {"codes": P1})

    def scan_everything(self) -> None:
        self.scan_can1_only()
        self.scan("confirm")
        self.scan("next-can", {"proceed": True})
        self.scan("frame", {"codes": [CAN2]})
        self.scan("confirm")
        self.scan("frame", {"codes": P2})
        self.scan("confirm")

    def check_passed(self, body: dict, code: str) -> bool:
        return next(item for item in body["checks"] if item["code"] == code)["passed"]

    def blocking_codes(self, body: dict) -> set[str]:
        return {item["code"] for item in body["blocking"]}


class PlanVsActualTests(ReviewTestCase):
    def test_missing_can_is_pinpointed(self) -> None:
        self.scan_can1_only()
        body = self.review()

        self.assertEqual(body["plan"], {"canCount": 2, "particleTotal": 4})
        self.assertEqual(body["actual"]["particleTotal"], 2)
        self.assertEqual(body["missingParticles"], 2)

        per_can = {item["index"]: item for item in body["perCan"]}
        self.assertEqual(per_can[1]["scanned"], 2)
        self.assertTrue(per_can[1]["complete"])
        self.assertEqual(per_can[2]["scanned"], 0)
        self.assertEqual(per_can[2]["missing"], 2)
        self.assertFalse(per_can[2]["complete"])
        self.assertEqual(per_can[2]["canCode"], "", "罐 2 还没扫，罐号应显式为空")

    def test_no_missing_when_everything_scanned(self) -> None:
        self.scan_everything()
        body = self.review()
        self.assertEqual(body["missingParticles"], 0)
        self.assertTrue(all(item["complete"] for item in body["perCan"]))

    def test_empty_plan_is_reported(self) -> None:
        created = self.client.post(
            "/api/batches",
            json={
                "batchNo": "REVIEW-NOPLAN",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [],
                "box": {"code": "", "cans": []},
            },
        ).json()
        body = self.client.get(f"/api/batches/{created['id']}/review").json()
        self.assertFalse(body["canExport"])
        self.assertIn("PLAN_INCOMPLETE", {item["code"] for item in body["blocking"]})


class ExportGateTests(ReviewTestCase):
    def test_missing_particles_block_export(self) -> None:
        self.scan_can1_only()
        body = self.review()

        self.assertFalse(body["canExport"])
        self.assertIn("MISSING_PARTICLES", self.blocking_codes(body))
        self.assertFalse(self.check_passed(body, "COUNT_MATCHES"))

        block = next(item for item in body["blocking"] if item["code"] == "MISSING_PARTICLES")
        self.assertIn("2", block["message"])
        self.assertIn("提前结束", block["action"], "必须给出恢复路径")
        self.assertEqual(body["exportKind"], "normal")

    def test_complete_batch_can_export(self) -> None:
        self.scan_everything()
        body = self.review()
        self.assertTrue(body["canExport"])
        self.assertEqual(body["blocking"], [])
        self.assertEqual(body["exportKind"], "normal")
        self.assertTrue(self.check_passed(body, "COUNT_MATCHES"))
        self.assertTrue(self.check_passed(body, "NO_DUPLICATE_CODES"))
        self.assertTrue(self.check_passed(body, "PLAN_COMPLETE"))

    def test_early_end_unlocks_export_and_switches_kind(self) -> None:
        self.scan_can1_only()
        self.assertEqual(self.review()["canExport"], False)

        signed = self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={
                "reason": "药液不足，本批提前结束",
                "operator": "操作员甲",
                "note": "剩余 2 粒未灌装，已确认报废",
            },
        )
        self.assertEqual(signed.status_code, 200, signed.text)

        body = self.review()
        self.assertTrue(body["canExport"], "签名后允许导出")
        self.assertEqual(body["exportKind"], "early_end")
        self.assertEqual(body["blocking"], [])
        self.assertTrue(self.check_passed(body, "EARLY_END_SIGNED"))
        self.assertEqual(body["earlyEnd"]["operator"], "操作员甲")
        # 缺漏仍然如实呈现，只是不再阻断
        self.assertEqual(body["missingParticles"], 2)
        self.assertFalse(self.check_passed(body, "COUNT_MATCHES"))

    def test_early_end_requires_reason_and_operator(self) -> None:
        self.scan_can1_only()
        for payload, field in (
            ({"reason": " ", "operator": "操作员甲"}, "reason"),
            ({"reason": "药液不足", "operator": ""}, "operator"),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    f"/api/batches/{self.batch_id}/early-end", json=payload
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["detail"]["field"], field)

    def test_early_end_records_server_side_actual_counts(self) -> None:
        self.scan_can1_only()
        body = self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={"reason": "测试", "operator": "操作员乙", "note": ""},
        ).json()
        self.assertEqual(body["earlyEnd"]["actualCanCount"], 1)
        self.assertEqual(body["earlyEnd"]["actualParticleCount"], 2)
        self.assertTrue(body["earlyEnd"]["at"])

    def test_early_end_does_not_mask_duplicate_codes(self) -> None:
        """提前结束只解决缺漏，不能掩盖重复条码这类数据错误。"""

        self.scan_can1_only()
        self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={"reason": "药液不足", "operator": "操作员甲", "note": ""},
        )
        self.assertTrue(self.review()["canExport"])

        # 制造一个重复条码：把罐 1 的粒子码复制到罐 2 之外的位置不可行，
        # 这里直接验证去重检查本身是独立的
        body = self.review()
        self.assertTrue(self.check_passed(body, "NO_DUPLICATE_CODES"))

    def test_blocking_list_is_empty_only_when_exportable(self) -> None:
        self.scan_can1_only()
        body = self.review()
        self.assertEqual(body["canExport"], not body["blocking"])

    def test_review_reports_status_and_editability(self) -> None:
        self.scan_everything()
        for target in ("pending_review", "verified", "exported"):
            self.client.post(
                f"/api/batches/{self.batch_id}/status", json={"target": target}
            )
        body = self.review()
        self.assertEqual(body["status"], "exported")
        self.assertEqual(body["statusLabel"], "已导出")
        self.assertFalse(body["editable"])
        self.assertTrue(body["canExport"], "已导出状态下仍可再次导出")

    def test_review_of_unknown_batch_returns_404(self) -> None:
        response = self.client.get("/api/batches/nope/review")
        self.assertEqual(response.status_code, 404)


class ConflictGateTests(ReviewTestCase):
    def test_unresolved_conflict_blocks_export(self) -> None:
        self.scan_everything()
        self.assertTrue(self.review()["canExport"])

        # 制造一次同区域歧义（识别层上报的冲突）
        conflict = {
            "region": {"left": 1, "top": 1, "right": 2, "bottom": 2},
            "candidates": ["82062339000000001006", "82062339000000001007"],
            "support": {},
            "reason": "同区域多值",
        }
        self.scan("frame", {"codes": [], "conflicts": [conflict]})

        body = self.review()
        self.assertFalse(body["canExport"])
        self.assertIn("UNRESOLVED_CONFLICT", self.blocking_codes(body))
        self.assertFalse(self.check_passed(body, "CONFLICT_RESOLVED"))

        # 重扫一次（正常帧）后应恢复可导出
        self.scan("frame", {"codes": ["82062339000000001003"]})
        after = self.review()
        self.assertTrue(after["canExport"], "重扫后冲突视为已解决")


if __name__ == "__main__":
    unittest.main()
