"""阶段 3.2 第一批：扫码状态机 + 即时拦截 + 冲突审计。

全部用"模拟扫描事件"驱动，不依赖任何硬件 —— 这正是把逻辑核心与 I/O 层
分批的原因。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase
except ImportError:
    from support import TempDatabaseTestCase

from fastapi.testclient import TestClient

from app.domain import scan_state as st

BOX = "80217619000000001003"
CAN1 = "80217629000000001005"
CAN2 = "80217629000000001004"
PARTICLES_1 = ["82062339000000001004", "82062339000000001001"]
PARTICLES_2 = ["82062339000000001003", "82062339000000001002"]


class ScanFlowTestCase(TempDatabaseTestCase):
    """建一个 2 罐 × 2 粒的批次并推进到 collecting。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        created = self.client.post(
            "/api/batches",
            json={
                "batchNo": "SCAN-0001",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [2, 2],
                "box": {"code": "", "cans": []},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.batch_id = created.json()["id"]

        moved = self.client.post(
            f"/api/batches/{self.batch_id}/status", json={"target": "collecting"}
        )
        self.assertEqual(moved.status_code, 200, moved.text)

    def session(self) -> dict:
        response = self.client.get(f"/api/scan/{self.batch_id}/session")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def frame(self, codes: list[str], conflicts: list[dict] | None = None) -> dict:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/frame",
            json={"codes": codes, "conflicts": conflicts or []},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self) -> dict:
        response = self.client.post(f"/api/scan/{self.batch_id}/confirm")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rescan(self) -> dict:
        response = self.client.post(f"/api/scan/{self.batch_id}/rescan")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def next_can(self, proceed: bool) -> dict:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/next-can", json={"proceed": proceed}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def scan_box(self, code: str = BOX) -> dict:
        self.frame([code])
        return self.confirm()

    def scan_can(self, code: str) -> dict:
        self.frame([code])
        return self.confirm()


class StateMachineTests(ScanFlowTestCase):
    def test_initial_status_is_box_scanning(self) -> None:
        snapshot = self.session()
        self.assertEqual(snapshot["status"], st.STATUS_BOX_SCANNING)
        self.assertEqual(snapshot["statusLabel"], "拍箱号")
        self.assertEqual(snapshot["plannedCanCount"], 2)
        self.assertEqual(snapshot["plannedParticleTotal"], 4)
        self.assertEqual(snapshot["actualParticleTotal"], 0)
        self.assertEqual(snapshot["missingParticles"], 4)

    def test_full_happy_path_two_cans(self) -> None:
        snapshot = self.frame([BOX])
        self.assertEqual(snapshot["status"], st.STATUS_BOX_CONFIRM)
        self.assertEqual(snapshot["pendingCode"], BOX)
        snapshot = self.confirm()
        self.assertEqual(snapshot["status"], st.STATUS_CAN_SCANNING)
        self.assertEqual(snapshot["currentCanIndex"], 1)

        snapshot = self.frame([CAN1])
        self.assertEqual(snapshot["status"], st.STATUS_CAN_CONFIRM)
        snapshot = self.confirm()
        self.assertEqual(snapshot["status"], st.STATUS_PARTICLE_SCANNING)

        snapshot = self.frame(PARTICLES_1)
        self.assertEqual(snapshot["status"], st.STATUS_CAN_REVIEW)
        self.assertTrue(snapshot["canComplete"])
        self.assertEqual(snapshot["currentCanScanned"], 2)

        snapshot = self.confirm()
        self.assertEqual(snapshot["status"], st.STATUS_NEXT_CAN_PROMPT)

        snapshot = self.next_can(True)
        self.assertEqual(snapshot["status"], st.STATUS_CAN_SCANNING)
        self.assertEqual(snapshot["currentCanIndex"], 2)

        self.frame([CAN2])
        snapshot = self.confirm()
        self.assertEqual(snapshot["status"], st.STATUS_PARTICLE_SCANNING)

        snapshot = self.frame(PARTICLES_2)
        self.assertEqual(snapshot["status"], st.STATUS_CAN_REVIEW)
        snapshot = self.confirm()
        self.assertEqual(snapshot["status"], st.STATUS_OVERALL_REVIEW)
        self.assertEqual(snapshot["actualParticleTotal"], 4)
        self.assertEqual(snapshot["missingParticles"], 0)

    def test_particle_order_is_scan_order_not_sorted(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)

        detail = self.client.get(f"/api/batches/{self.batch_id}").json()
        stored = detail["data"]["box"]["cans"][0]["particles"]
        self.assertEqual(stored, PARTICLES_1)
        self.assertNotEqual(stored, sorted(stored))

    def test_next_can_declined_enters_early_end(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)
        self.confirm()
        snapshot = self.next_can(False)
        self.assertEqual(snapshot["status"], st.STATUS_EARLY_END)

    def test_confirm_in_wrong_state_is_rejected(self) -> None:
        response = self.client.post(f"/api/scan/{self.batch_id}/confirm")
        self.assertEqual(response.status_code, 409)
        detail = response.json()["error"]["detail"]
        self.assertEqual(detail["reason"], st.EVENT_WRONG_STATE)
        self.assertEqual(detail["status"], st.STATUS_BOX_SCANNING)

    def test_next_can_before_prompt_is_rejected(self) -> None:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/next-can", json={"proceed": True}
        )
        self.assertEqual(response.status_code, 409)

    def test_session_survives_restart_by_deriving_from_data(self) -> None:
        """会话是瞬态的：换一个 app 实例后状态应由库内数据重新推导出来。"""

        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1[:1])

        other = TestClient(self.make_app())
        snapshot = other.get(f"/api/scan/{self.batch_id}/session").json()
        self.assertEqual(snapshot["status"], st.STATUS_PARTICLE_SCANNING)
        self.assertEqual(snapshot["currentCanIndex"], 1)
        self.assertEqual(snapshot["currentCanScanned"], 1)


class InterceptionTests(ScanFlowTestCase):
    """即时拦截：严格单码、层级白名单、去重、溢出。"""

    def test_box_rejects_no_code(self) -> None:
        snapshot = self.frame([])
        self.assertEqual(snapshot["lastEvent"]["code"], st.EVENT_NO_CODE)
        self.assertEqual(snapshot["status"], st.STATUS_BOX_SCANNING)
        self.assertEqual(snapshot["actualParticleTotal"], 0)

    def test_box_rejects_multiple_codes_and_raises_alarm(self) -> None:
        snapshot = self.frame([BOX, "80217619000000001004"])
        event = snapshot["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_MULTI_CODE)
        self.assertTrue(event["blocking"])
        self.assertTrue(event["needsAlarm"])
        self.assertEqual(snapshot["alarmCount"], 1)
        self.assertEqual(snapshot["status"], st.STATUS_BOX_SCANNING)

    def test_box_rejects_wrong_layer(self) -> None:
        snapshot = self.frame([CAN1])
        event = snapshot["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_WRONG_LAYER)
        self.assertEqual(event["detail"]["actualLayer"], 2)
        self.assertEqual(event["detail"]["expectedLayer"], 3)

    def test_can_rejects_multiple_codes(self) -> None:
        self.scan_box()
        snapshot = self.frame([CAN1, CAN2])
        self.assertEqual(snapshot["lastEvent"]["code"], st.EVENT_MULTI_CODE)
        self.assertEqual(snapshot["status"], st.STATUS_CAN_SCANNING)

    def test_can_rejects_particle_code(self) -> None:
        self.scan_box()
        snapshot = self.frame([PARTICLES_1[0]])
        self.assertEqual(snapshot["lastEvent"]["code"], st.EVENT_WRONG_LAYER)
        self.assertEqual(snapshot["lastEvent"]["detail"]["expectedLayer"], 2)

    def test_duplicate_can_code_tells_where_it_is_used(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)
        self.confirm()
        self.next_can(True)

        snapshot = self.frame([CAN1])
        event = snapshot["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_DUPLICATE_CODE)
        self.assertIn("罐 1", event["detail"]["usedAt"])
        self.assertEqual(event["detail"]["canIndex"], 1)
        self.assertEqual(snapshot["status"], st.STATUS_CAN_SCANNING)

    def test_duplicate_particle_within_one_frame(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        snapshot = self.frame([PARTICLES_1[0], PARTICLES_1[0]])
        self.assertEqual(snapshot["lastEvent"]["code"], st.EVENT_DUPLICATE_CODE)
        self.assertEqual(snapshot["currentCanScanned"], 0, "整帧拒绝，不部分写入")

    def test_duplicate_particle_across_cans(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)
        self.confirm()
        self.next_can(True)
        self.scan_can(CAN2)

        snapshot = self.frame([PARTICLES_1[0]])
        event = snapshot["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_DUPLICATE_CODE)
        self.assertIn("罐 1", event["detail"]["usedAt"])

    def test_overflow_is_rejected_and_nothing_written(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame([PARTICLES_1[0]])  # 1/2

        fresh = self.frame(["82062339000000001003", "82062339000000001002"])
        event = fresh["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_OVERFLOW)
        self.assertTrue(event["needsAlarm"])
        self.assertEqual(event["detail"]["remaining"], 1)
        self.assertEqual(event["detail"]["incoming"], 2)
        self.assertEqual(fresh["currentCanScanned"], 1, "溢出时不得部分写入")

    def test_overflow_boundary_exactly_fills(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame([PARTICLES_1[0]])
        snapshot = self.frame([PARTICLES_1[1]])
        self.assertEqual(snapshot["status"], st.STATUS_CAN_REVIEW)
        self.assertEqual(snapshot["currentCanScanned"], 2)

    def test_empty_plan_cannot_be_scanned(self) -> None:
        created = self.client.post(
            "/api/batches",
            json={
                "batchNo": "SCAN-EMPTY",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [],
                "box": {"code": "", "cans": []},
            },
        )
        batch_id = created.json()["id"]
        snapshot = self.client.get(f"/api/scan/{batch_id}/session").json()
        self.assertEqual(snapshot["status"], st.STATUS_IDLE)


class RescanTests(ScanFlowTestCase):
    def test_rescan_clears_pending_box_code(self) -> None:
        self.frame([BOX])
        snapshot = self.rescan()
        self.assertEqual(snapshot["status"], st.STATUS_BOX_SCANNING)
        self.assertEqual(snapshot["pendingCode"], "")
        detail = self.client.get(f"/api/batches/{self.batch_id}").json()
        self.assertEqual(detail["data"]["box"]["code"], "")

    def test_rescan_can_review_returns_to_particle_scanning(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)
        snapshot = self.rescan()
        self.assertEqual(snapshot["status"], st.STATUS_PARTICLE_SCANNING)
        self.assertEqual(snapshot["currentCanScanned"], 2)


class ConflictAuditTests(ScanFlowTestCase):
    """3.2.5 冲突审计。"""

    CONFLICT = {
        "region": {"left": 1138, "top": 1512, "right": 1768, "bottom": 1665},
        "candidates": ["82062339000000001006", "82062339000000001007"],
        "support": {"82062339000000001006": 1, "82062339000000001007": 1},
        "reason": "同一位置解出多个不同条码值",
    }

    def test_conflict_blocks_frame_and_is_audited(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)

        snapshot = self.frame(["82062339000000001006"], [self.CONFLICT])

        event = snapshot["lastEvent"]
        self.assertEqual(event["code"], st.EVENT_CONFLICT)
        self.assertTrue(event["needsAlarm"])
        self.assertEqual(snapshot["conflictCount"], 1)
        self.assertEqual(snapshot["currentCanScanned"], 0, "冲突时整帧拒绝")

        entries = self.client.get(
            f"/api/audit?batchId={self.batch_id}&action=scan_conflict"
        ).json()["items"]
        self.assertEqual(len(entries), 1)

        payload = entries[0]["newValue"]
        self.assertEqual(
            payload["conflicts"][0]["candidates"],
            ["82062339000000001006", "82062339000000001007"],
        )
        self.assertIn("support", payload["conflicts"][0])
        self.assertIn("engineVersion", payload)
        self.assertIn("variants", payload)
        self.assertEqual(entries[0]["result"], "blocked")

    def test_conflict_count_accumulates(self) -> None:
        conflict = {"region": {}, "candidates": ["a", "b"], "support": {}, "reason": "x"}
        self.frame([], [conflict])
        self.frame([], [conflict])
        self.assertEqual(self.session()["conflictCount"], 2)

    def test_audit_is_append_only_and_filterable(self) -> None:
        self.scan_box()
        actions = {
            entry["action"]
            for entry in self.client.get(f"/api/audit?batchId={self.batch_id}").json()["items"]
        }
        self.assertIn("scan_box", actions)

        filtered = self.client.get(
            f"/api/audit?batchId={self.batch_id}&action=scan_box"
        ).json()["items"]
        self.assertEqual(len(filtered), 1)

    def test_alarm_events_are_audited(self) -> None:
        self.frame([BOX, "80217619000000001004"])
        alarms = self.client.get(
            f"/api/audit?batchId={self.batch_id}&action=scan_alarm"
        ).json()["items"]
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]["reason"], st.EVENT_MULTI_CODE)

    def test_duplicate_code_is_audited(self) -> None:
        self.scan_box()
        self.scan_can(CAN1)
        self.frame(PARTICLES_1)
        self.confirm()
        self.next_can(True)
        self.frame([CAN1])

        reasons = {
            entry["reason"]
            for entry in self.client.get(f"/api/audit?batchId={self.batch_id}").json()["items"]
        }
        self.assertIn(st.EVENT_DUPLICATE_CODE, reasons)

    def test_audit_has_no_delete_endpoint(self) -> None:
        schema = self.client.get("/openapi.json").json()
        audit_paths = [path for path in schema["paths"] if path.startswith("/api/audit")]
        self.assertEqual(audit_paths, ["/api/audit"])
        self.assertNotIn("delete", schema["paths"]["/api/audit"])


class ScanApiSurfaceTests(ScanFlowTestCase):
    def test_missing_batch_returns_404(self) -> None:
        response = self.client.get("/api/scan/does-not-exist/session")
        self.assertEqual(response.status_code, 404)

    def test_frame_rejects_unknown_field(self) -> None:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/frame", json={"codes": [], "typo": 1}
        )
        self.assertEqual(response.status_code, 422)

    def test_reset_clears_transient_state_only(self) -> None:
        self.frame([BOX])
        self.client.post(f"/api/scan/{self.batch_id}/reset")
        snapshot = self.session()
        self.assertEqual(snapshot["status"], st.STATUS_BOX_SCANNING)
        self.assertEqual(snapshot["pendingCode"], "")


if __name__ == "__main__":
    unittest.main()
