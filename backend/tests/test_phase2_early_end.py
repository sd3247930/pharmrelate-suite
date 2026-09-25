"""阶段 2：「提前结束」签名数据模型测试。

签名形式已定：操作人下拉选择 + 备注文本，另加必填原因。
实际罐数与实际粒子数由服务端按库内数据填写，不接受前端传入（防止改数）。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase, golden_batch_payload
except ImportError:
    from support import TempDatabaseTestCase, golden_batch_payload

from fastapi.testclient import TestClient


class EarlyEndTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        created = self.client.post("/api/batches", json=golden_batch_payload("20260921"))
        self.batch_id = created.json()["id"]

    def _register(self, **payload) -> object:
        return self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={"reason": "", "operator": "", "note": "", **payload},
        )

    def test_batch_starts_without_early_end(self) -> None:
        body = self.client.get(f"/api/batches/{self.batch_id}").json()
        self.assertIsNone(body["earlyEnd"])

    def test_reason_is_required(self) -> None:
        response = self._register(reason="   ", operator="操作员甲")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["field"], "reason")

    def test_operator_is_required(self) -> None:
        response = self._register(reason="药液不足，本批提前结束", operator="")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["field"], "operator")

    def test_register_records_all_four_fields(self) -> None:
        response = self._register(
            reason="药液不足，本批提前结束",
            operator="操作员甲",
            note="剩余 13 粒未灌装，已确认报废",
        )
        self.assertEqual(response.status_code, 200, response.text)

        early = response.json()["earlyEnd"]
        self.assertEqual(early["reason"], "药液不足，本批提前结束")
        self.assertEqual(early["operator"], "操作员甲")
        self.assertEqual(early["note"], "剩余 13 粒未灌装，已确认报废")
        self.assertTrue(early["at"], "应记录办理时间")

        # 实际数量由服务端填写
        self.assertEqual(early["actualCanCount"], 3)
        self.assertEqual(early["actualParticleCount"], 4)

    def test_actual_counts_ignore_client_supplied_values(self) -> None:
        """前端传什么数量都不算数，一律以库内数据为准。"""

        response = self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={
                "reason": "测试",
                "operator": "操作员甲",
                "note": "",
                "actualCanCount": 999,
                "actualParticleCount": 99999,
            },
        )
        self.assertEqual(response.status_code, 422, "多余字段应被拒绝")
        self.assertEqual(response.json()["error"]["code"], "REQUEST_INVALID")

    def test_early_end_persists_and_survives_reload(self) -> None:
        self._register(reason="设备故障", operator="操作员乙", note="已上报")

        # 换一个 app 实例读同一个库，等价于重启进程
        other = TestClient(self.make_app())
        body = other.get(f"/api/batches/{self.batch_id}").json()
        self.assertEqual(body["earlyEnd"]["reason"], "设备故障")
        self.assertEqual(body["earlyEnd"]["operator"], "操作员乙")

    def test_early_end_is_reported_in_data_payload(self) -> None:
        self._register(reason="提前结束", operator="操作员甲")
        body = self.client.get(f"/api/batches/{self.batch_id}").json()
        self.assertEqual(body["data"]["earlyEnd"]["operator"], "操作员甲")

    def test_early_end_can_be_cleared(self) -> None:
        self._register(reason="先登记后撤销", operator="操作员甲")
        cleared = self.client.delete(f"/api/batches/{self.batch_id}/early-end")
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["earlyEnd"])

        body = self.client.get(f"/api/batches/{self.batch_id}").json()
        self.assertIsNone(body["earlyEnd"])

    def test_early_end_rejected_in_readonly_status(self) -> None:
        for target in ("collecting", "pending_review", "verified", "exported"):
            self.client.post(
                f"/api/batches/{self.batch_id}/status", json={"target": target}
            )

        response = self._register(reason="已导出后补登记", operator="操作员甲")
        self.assertEqual(response.status_code, 409)
        self.assertIn("只读", response.json()["error"]["message"])

    def test_update_does_not_wipe_early_end(self) -> None:
        """普通业务更新不能顺手把提前结束记录抹掉。"""

        self._register(reason="药液不足", operator="操作员甲", note="保留我")

        payload = golden_batch_payload("20260921")
        payload["madeDate"] = "2026-09-22"
        updated = self.client.put(f"/api/batches/{self.batch_id}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["earlyEnd"]["note"], "保留我")


if __name__ == "__main__":
    unittest.main()
