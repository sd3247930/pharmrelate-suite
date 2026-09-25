"""阶段 3.4：槽位替换/删除/重拍/清空 + 撤销重做 ≥50 步。

重点验证三件事：
    1. 编辑后导出顺序仍然是 箱 → 罐1 → 罐1粒子 → 罐2 → …（这是最容易被打乱的地方）；
    2. 撤销/重做严格 LIFO，且游标语义正确（前缀已应用）；
    3. 只读状态与去重规则在编辑路径上同样生效。
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
SPARE_A = "82062339000000001005"
SPARE_B = "82062339000000001006"


class SlotTestCase(TempDatabaseTestCase):
    """建一个 2 罐 × 2 粒、已扫完罐 1 的批次。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.batch_id = self.client.post(
            "/api/batches",
            json={
                "batchNo": "SLOT-0001",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [2, 2],
                "box": {"code": "", "cans": []},
            },
        ).json()["id"]

    def move_to(self, target: str) -> dict:
        response = self.client.post(
            f"/api/batches/{self.batch_id}/status", json={"target": target}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def scan(self, path: str, body: dict | None = None) -> dict:
        response = self.client.post(
            f"/api/scan/{self.batch_id}/{path}", json=body if body is not None else {}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def scan_full_can1(self) -> None:
        self.move_to("collecting")
        self.scan("frame", {"codes": [BOX]})
        self.scan("confirm")
        self.scan("frame", {"codes": [CAN1]})
        self.scan("confirm")
        self.scan("frame", {"codes": P1})

    def scan_both_cans(self) -> None:
        self.scan_full_can1()
        self.scan("confirm")  # can_review → next_can_prompt
        self.scan("next-can", {"proceed": True})
        self.scan("frame", {"codes": [CAN2]})
        self.scan("confirm")
        self.scan("frame", {"codes": P2})

    def data(self) -> dict:
        return self.client.get(f"/api/batches/{self.batch_id}").json()["data"]

    def cans(self) -> list[dict]:
        return self.data()["box"]["cans"]

    def can_particles(self, index: int = 1) -> list[str]:
        return self.cans()[index - 1]["particles"]

    def history(self) -> dict:
        return self.client.get(f"/api/batches/{self.batch_id}/history").json()

    def post(self, path: str, body: dict | None = None) -> object:
        return self.client.post(
            f"/api/batches/{self.batch_id}/{path}", json=body if body is not None else {}
        )

    def export_order(self) -> list[tuple[str, int]]:
        """按导出顺序摊平库内数据，用于断言编辑没有打乱 箱→罐→粒子 的顺序。

        直接读仓储而不是走 HTTP，避免把接口层的字段顺序当成数据顺序来断言。
        """

        repository = self.make_app().state.batch_repository
        record = repository.get(self.batch_id)
        assert record is not None
        return [
            (code, layer) for code, layer, _parent in record.batch.iter_export_nodes()
        ]


class DeleteTests(SlotTestCase):
    def test_delete_removes_only_that_slot(self) -> None:
        self.scan_full_can1()
        response = self.post("slots/delete", {"code": P1[0]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), [P1[1]])
        self.assertEqual(response.json()["actualParticleTotal"], 1)

    def test_delete_unknown_code_is_rejected(self) -> None:
        self.scan_full_can1()
        response = self.post("slots/delete", {"code": SPARE_A})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["detail"]["reason"], "SLOT_EDIT_REJECTED")
        self.assertIn("不在当前批次", response.json()["error"]["message"])

    def test_delete_is_audited(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        entries = self.client.get(
            f"/api/audit?batchId={self.batch_id}&action=delete_particle"
        ).json()["items"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["result"], "success")
        self.assertEqual(entries[0]["oldValue"]["particles"], P1)
        self.assertEqual(entries[0]["newValue"]["particles"], [P1[1]])


class ReplaceTests(SlotTestCase):
    def test_replace_swaps_in_place_and_keeps_position(self) -> None:
        self.scan_full_can1()
        response = self.post(
            "slots/replace", {"code": P1[0], "newCode": SPARE_A}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), [SPARE_A, P1[1]], "新码应落在原位置")

    def test_replace_rejects_code_used_elsewhere(self) -> None:
        self.scan_full_can1()
        response = self.post("slots/replace", {"code": P1[0], "newCode": P1[1]})
        self.assertEqual(response.status_code, 409)
        message = response.json()["error"]["message"]
        self.assertIn("已被", message)
        self.assertIn("罐 1 / 粒子槽位 2", message, "应指出新码已绑在哪里")
        self.assertEqual(self.can_particles(), P1, "拒绝时不得改动数据")

    def test_replace_rejects_wrong_layer(self) -> None:
        self.scan_full_can1()
        response = self.post("slots/replace", {"code": P1[0], "newCode": BOX})
        self.assertEqual(response.status_code, 409)
        self.assertIn("只接受粒子码", response.json()["error"]["message"])

    def test_replace_with_same_code_is_rejected(self) -> None:
        self.scan_full_can1()
        response = self.post("slots/replace", {"code": P1[0], "newCode": P1[0]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("相同", response.json()["error"]["message"])

    def test_replace_frees_the_old_code(self) -> None:
        """旧码释放后可以被用到别的槽位。"""

        self.scan_full_can1()
        self.post("slots/replace", {"code": P1[0], "newCode": SPARE_A})
        response = self.post("slots/replace", {"code": SPARE_A, "newCode": P1[0]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), P1)


class UndoRedoTests(SlotTestCase):
    def test_delete_then_undo_restores_exact_order(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        self.assertEqual(self.can_particles(), [P1[1]])

        response = self.post("undo")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), P1, "撤销必须还原原始顺序，而不只是还原集合")
        self.assertEqual(response.json()["history"]["canUndo"], 0)
        self.assertEqual(response.json()["history"]["canRedo"], 1)

    def test_redo_reapplies(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        self.post("undo")
        response = self.post("redo")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), [P1[1]])

    def test_undo_redo_is_lifo(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        self.post("slots/delete", {"code": P1[1]})
        self.assertEqual(self.can_particles(), [])

        self.post("undo")
        self.assertEqual(self.can_particles(), [P1[1]], "先撤销最后一步")
        self.post("undo")
        self.assertEqual(self.can_particles(), P1)

        self.post("redo")
        self.assertEqual(self.can_particles(), [P1[1]])
        self.post("redo")
        self.assertEqual(self.can_particles(), [])

    def test_new_edit_truncates_redo_branch(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        self.post("undo")
        self.assertEqual(self.history()["canRedo"], 1)

        self.post("slots/delete", {"code": P1[1]})
        self.assertEqual(self.history()["canRedo"], 0, "新操作应丢弃重做分支")
        self.assertEqual(self.can_particles(), [P1[0]])

    def test_undo_with_empty_stack_is_rejected(self) -> None:
        self.scan_full_can1()
        response = self.post("undo")
        self.assertEqual(response.status_code, 409)
        self.assertIn("没有可撤销", response.json()["error"]["message"])

    def test_redo_with_empty_stack_is_rejected(self) -> None:
        self.scan_full_can1()
        response = self.post("redo")
        self.assertEqual(response.status_code, 409)
        self.assertIn("没有可重做", response.json()["error"]["message"])

    def test_supports_at_least_50_steps(self) -> None:
        """V1.1 10.3 要求撤销栈 ≥50 步。"""

        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})

        # 用替换/换回来反复产生 60 步操作
        codes = [SPARE_A, SPARE_B]
        current = P1[1]
        for step in range(60):
            target = codes[step % 2]
            response = self.post("slots/replace", {"code": current, "newCode": target})
            self.assertEqual(response.status_code, 200, response.text)
            current = target

        history = self.history()
        self.assertEqual(history["maxSteps"], 50)
        self.assertEqual(history["canUndo"], 50, "栈深应被裁剪到 50")

        # 连续撤销 50 次都必须成功
        for _ in range(50):
            response = self.post("undo")
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.history()["canUndo"], 0)
        self.assertEqual(self.post("undo").status_code, 409, "第 51 次撤销应被拒绝")

    def test_history_survives_restart(self) -> None:
        """操作栈持久化：换一个 app 实例仍能撤销。"""

        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})

        other = TestClient(self.make_app())
        self.assertEqual(other.get(f"/api/batches/{self.batch_id}/history").json()["canUndo"], 1)
        response = other.post(f"/api/batches/{self.batch_id}/undo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["box"]["cans"][0]["particles"], P1
        )

    def test_undo_and_redo_are_audited(self) -> None:
        self.scan_full_can1()
        self.post("slots/delete", {"code": P1[0]})
        self.post("undo")
        self.post("redo")
        actions = {
            entry["action"]
            for entry in self.client.get(f"/api/audit?batchId={self.batch_id}").json()["items"]
        }
        self.assertIn("undo", actions)
        self.assertIn("redo", actions)


class ClearAndRescanTests(SlotTestCase):
    def test_clear_can_keeps_can_code(self) -> None:
        self.scan_full_can1()
        response = self.post("cans/1/clear")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.can_particles(), [])
        self.assertEqual(self.cans()[0]["code"], CAN1, "清空粒子不应影响罐号")

    def test_clear_empty_can_is_rejected(self) -> None:
        self.move_to("collecting")
        self.scan("frame", {"codes": [BOX]})
        self.scan("confirm")
        self.scan("frame", {"codes": [CAN1]})
        self.scan("confirm")
        response = self.post("cans/1/clear")
        self.assertEqual(response.status_code, 409)
        self.assertIn("本来就是空", response.json()["error"]["message"])

    def test_rescan_can_changes_code_and_clears_particles(self) -> None:
        self.scan_full_can1()
        response = self.post("cans/1/rescan", {"newCanCode": CAN2})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.cans()[0]["code"], CAN2)
        self.assertEqual(self.can_particles(), [])

    def test_rescan_can_rejects_duplicate_code(self) -> None:
        self.scan_both_cans()
        response = self.post("cans/1/rescan", {"newCanCode": CAN2})
        self.assertEqual(response.status_code, 409)
        self.assertIn("已被罐 2 使用", response.json()["error"]["message"])

    def test_rescan_can_rejects_particle_code(self) -> None:
        self.scan_full_can1()
        response = self.post("cans/1/rescan", {"newCanCode": SPARE_A})
        self.assertEqual(response.status_code, 409)
        self.assertIn("必须使用罐码", response.json()["error"]["message"])

    def test_rescan_box_clears_everything_and_undo_restores(self) -> None:
        self.scan_both_cans()
        self.assertEqual(self.data()["box"]["code"], BOX)

        response = self.post("box/rescan", {"newBoxCode": ""})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["box"]["code"], "")
        self.assertEqual(response.json()["canCount"], 0)

        restored = self.post("undo")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["data"]["box"]["code"], BOX)
        self.assertEqual(self.can_particles(1), P1)
        self.assertEqual(self.can_particles(2), P2)

    def test_clear_can_then_rescan_works_as_before(self) -> None:
        """让「本罐核对还没好」真正可用：删掉一粒后就能继续补扫。"""

        self.scan_full_can1()
        self.assertEqual(self.scan("confirm")["status"], "next_can_prompt")
        self.scan("next-can", {"proceed": True})
        self.scan("frame", {"codes": [CAN2]})
        self.scan("confirm")

        # 罐 2 已有一条记录，删掉后应能重新补扫
        self.post("slots/delete", {"code": P2[0]})
        snapshot = self.scan("frame", {"codes": [SPARE_A]})
        self.assertEqual(snapshot["lastEvent"]["code"], "OK")
        self.assertEqual(self.can_particles(2), [SPARE_A])


class OrderIntegrityTests(SlotTestCase):
    def test_export_order_holds_after_edits(self) -> None:
        """编辑后导出顺序仍必须是 箱 → 罐1 → 罐1粒子 → 罐2 → 罐2粒子。"""

        self.scan_both_cans()
        self.post("slots/delete", {"code": P1[0]})
        self.post("slots/delete", {"code": P2[1]})

        self.assertEqual(
            self.export_order(),
            [
                (BOX, 3),
                (CAN1, 2),
                (P1[1], 1),
                (CAN2, 2),
                (P2[0], 1),
            ],
        )

    def test_export_order_holds_after_undo(self) -> None:
        self.scan_both_cans()
        self.post("slots/delete", {"code": P1[0]})
        self.post("undo")

        self.assertEqual(
            self.export_order(),
            [
                (BOX, 3),
                (CAN1, 2),
                (P1[0], 1),
                (P1[1], 1),
                (CAN2, 2),
                (P2[0], 1),
                (P2[1], 1),
            ],
        )


class ReadonlyGuardTests(SlotTestCase):
    def test_edits_are_rejected_when_exported(self) -> None:
        self.scan_full_can1()
        for target in ("pending_review", "verified", "exported"):
            self.move_to(target)

        for path, body in (
            ("slots/delete", {"code": P1[0]}),
            ("slots/replace", {"code": P1[0], "newCode": SPARE_A}),
            ("cans/1/clear", None),
            ("cans/1/rescan", {"newCanCode": CAN2}),
            ("box/rescan", {"newBoxCode": ""}),
            ("undo", None),
            ("redo", None),
        ):
            with self.subTest(path=path):
                response = self.post(path, body)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["detail"]["reason"], "READONLY")

        self.assertEqual(self.can_particles(), P1, "只读状态下数据一个字节都不该变")


if __name__ == "__main__":
    unittest.main()
