"""阶段 2：批次状态机测试。

重点：合法流转必须通过，非法流转必须被拒绝且报出允许的目标状态。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase, golden_batch_payload
except ImportError:
    from support import TempDatabaseTestCase, golden_batch_payload

from fastapi.testclient import TestClient

from app.domain import batch_state as state


class TransitionRulesTests(unittest.TestCase):
    """纯规则层测试，不经过 HTTP。"""

    def test_expected_forward_path_is_allowed(self) -> None:
        path = [
            state.STATUS_DRAFT,
            state.STATUS_COLLECTING,
            state.STATUS_PENDING_REVIEW,
            state.STATUS_VERIFIED,
            state.STATUS_EXPORTED,
            state.STATUS_LOCKED,
            state.STATUS_ARCHIVED,
        ]
        for current, target in zip(path, path[1:]):
            with self.subTest(current=current, target=target):
                self.assertTrue(state.can_transition(current, target))
                state.assert_transition(current, target)  # 不应抛错

    def test_skipping_states_is_rejected(self) -> None:
        illegal = [
            (state.STATUS_DRAFT, state.STATUS_VERIFIED),
            (state.STATUS_DRAFT, state.STATUS_EXPORTED),
            (state.STATUS_COLLECTING, state.STATUS_EXPORTED),
            (state.STATUS_PENDING_REVIEW, state.STATUS_EXPORTED),
            (state.STATUS_VERIFIED, state.STATUS_LOCKED),
            (state.STATUS_EXPORTED, state.STATUS_ARCHIVED),
        ]
        for current, target in illegal:
            with self.subTest(current=current, target=target):
                self.assertFalse(state.can_transition(current, target))
                with self.assertRaises(state.IllegalTransitionError) as ctx:
                    state.assert_transition(current, target)
                self.assertEqual(ctx.exception.current, current)
                self.assertEqual(ctx.exception.target, target)
                self.assertTrue(ctx.exception.allowed)

    def test_void_is_terminal(self) -> None:
        self.assertEqual(state.allowed_transitions(state.STATUS_VOID), frozenset())
        for target in state.BATCH_STATUSES:
            with self.subTest(target=target):
                self.assertFalse(state.can_transition(state.STATUS_VOID, target))

    def test_archived_cannot_be_voided(self) -> None:
        """V1.1 8.3：作废只适用于 archived/void 之外的状态。"""

        self.assertFalse(state.can_transition(state.STATUS_ARCHIVED, state.STATUS_VOID))

    def test_every_status_except_archived_and_void_can_be_voided(self) -> None:
        for status in state.BATCH_STATUSES:
            if status in (state.STATUS_ARCHIVED, state.STATUS_VOID):
                continue
            with self.subTest(status=status):
                self.assertTrue(state.can_transition(status, state.STATUS_VOID))

    def test_readonly_statuses(self) -> None:
        for status in (
            state.STATUS_EXPORTED,
            state.STATUS_LOCKED,
            state.STATUS_ARCHIVED,
            state.STATUS_VOID,
        ):
            with self.subTest(status=status):
                self.assertTrue(state.is_readonly(status))
                self.assertFalse(state.is_editable(status))

    def test_editable_statuses(self) -> None:
        for status in (
            state.STATUS_DRAFT,
            state.STATUS_COLLECTING,
            state.STATUS_PENDING_REVIEW,
            state.STATUS_VERIFIED,
        ):
            with self.subTest(status=status):
                self.assertTrue(state.is_editable(status))

    def test_admin_only_transitions(self) -> None:
        self.assertTrue(state.requires_admin(state.STATUS_EXPORTED, state.STATUS_VERIFIED))
        self.assertTrue(state.requires_admin(state.STATUS_LOCKED, state.STATUS_EXPORTED))
        self.assertFalse(state.requires_admin(state.STATUS_DRAFT, state.STATUS_COLLECTING))
        self.assertFalse(state.requires_admin(state.STATUS_VERIFIED, state.STATUS_EXPORTED))

    def test_unknown_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            state.assert_transition("不存在的状态", state.STATUS_DRAFT)
        with self.assertRaises(ValueError):
            state.assert_transition(state.STATUS_DRAFT, "不存在的状态")


class TransitionApiTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        created = self.client.post("/api/batches", json=golden_batch_payload("20260901"))
        self.batch_id = created.json()["id"]

    def _status(self) -> str:
        return self.client.get(f"/api/batches/{self.batch_id}").json()["status"]

    def _go(self, target: str, **extra) -> object:
        return self.client.post(
            f"/api/batches/{self.batch_id}/status",
            json={"target": target, **extra},
        )

    def test_full_lifecycle_through_api(self) -> None:
        self.assertEqual(self._status(), "draft")

        for target in ("collecting", "pending_review", "verified", "exported", "locked", "archived"):
            with self.subTest(target=target):
                response = self._go(target)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["batch"]["status"], target)

        self.assertEqual(self._status(), "archived")

    def test_illegal_transition_returns_409_with_allowed_targets(self) -> None:
        response = self._go("verified")  # draft → verified 跳级
        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertEqual(error["code"], "CONFLICT")
        self.assertEqual(error["detail"]["reason"], "ILLEGAL_TRANSITION")
        self.assertEqual(error["detail"]["current"], "draft")
        self.assertEqual(error["detail"]["target"], "verified")
        self.assertIn("collecting", error["detail"]["allowed"])
        self.assertEqual(error["detail"]["currentLabel"], "草稿")
        self.assertEqual(error["detail"]["targetLabel"], "已核对")

    def test_transitions_endpoint_lists_options(self) -> None:
        body = self.client.get(f"/api/batches/{self.batch_id}/transitions").json()
        self.assertEqual(body["status"], "draft")
        self.assertTrue(body["editable"])
        targets = {option["target"] for option in body["options"]}
        self.assertEqual(targets, {"collecting", "void"})
        void_option = next(item for item in body["options"] if item["target"] == "void")
        self.assertTrue(void_option["requiresAdmin"])
        self.assertTrue(void_option["requiresReason"])

    def test_void_requires_reason(self) -> None:
        response = self._go("void")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_FAILED")
        self.assertEqual(response.json()["error"]["detail"]["reason"], "REASON_REQUIRED")

        ok = self._go("void", reason="批次录入错误，整批作废", operator="操作员甲")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["batch"]["status"], "void")
        self.assertEqual(ok.json()["transition"]["reason"], "批次录入错误，整批作废")

    def test_unlock_requires_reason_and_is_admin_only(self) -> None:
        for target in ("collecting", "pending_review", "verified", "exported"):
            self._go(target)

        # exported → verified 是解锁，必须填原因
        rejected = self._go("verified")
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["detail"]["reason"], "REASON_REQUIRED")

        unlocked = self._go("verified", reason="发现条码录入错误，需解锁修正", operator="操作员甲")
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(unlocked.json()["batch"]["status"], "verified")

    def test_void_cannot_be_undone(self) -> None:
        self._go("void", reason="测试作废")
        for target in state.BATCH_STATUSES:
            with self.subTest(target=target):
                self.assertNotEqual(self._go(target).status_code, 200)

    def test_readonly_status_rejects_business_update(self) -> None:
        for target in ("collecting", "pending_review", "verified", "exported"):
            self._go(target)

        response = self.client.put(
            f"/api/batches/{self.batch_id}",
            json=golden_batch_payload("20260901"),
        )
        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertIn("只读", error["message"])
        self.assertEqual(error["detail"]["status"], "exported")


if __name__ == "__main__":
    unittest.main()
