"""SyncTransport 假实现的一致性测试。

对应 docs/43 的一致性测试清单前五条 + 第六条"两条通道等价"。
这些测试**不需要网络也不需要硬件** —— 这正是先把假实现做出来的意义：
契约可以在真机到位之前就被验证。
"""

from __future__ import annotations

import unittest

from app.sync import (
    KIND_BROADCAST,
    PROTOCOL_VERSION,
    Envelope,
    InMemoryHub,
    InMemorySyncTransport,
    TransportError,
    TransportStatus,
)
from app.sync.memory import REASON_BATCH_MISMATCH, REASON_DUPLICATE_CODE

BATCH = "20260901"
DEVICE_A = "android-01"
DEVICE_B = "android-02"


def op(code: str, layer: int = 1, batch_id: str = BATCH) -> dict[str, object]:
    return {"code": code, "packLayer": layer, "batchId": batch_id}


class TransportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = InMemoryHub()
        self.a = InMemorySyncTransport(self.hub, DEVICE_A)
        self.a.open(batch_id=BATCH, device_id=DEVICE_A)

    def tearDown(self) -> None:
        if self.a.is_open():
            self.a.close()


class RoundTripTests(TransportTestCase):
    """清单第 1 条：往返顺序与内容一致。"""

    def test_send_and_ack_round_trip(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004"), op("82062339000000001001")])
        result = self.a.send([envelope])

        self.assertTrue(result.ok, result.rejected)
        self.assertEqual(result.accepted, [1])
        self.assertEqual(self.hub.state(BATCH).particle_count, 2)

    def test_ack_envelope_carries_result(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")])
        result = self.a.send([envelope])
        ack = self.a.ack(envelope, result)
        self.assertEqual(ack.kind, "oplog_ack")
        self.assertEqual(ack.payload["accepted"], [1])

    def test_envelope_serialisation_round_trip(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")], hlc="0001-0001-a")
        restored = Envelope.from_dict(envelope.to_dict())
        self.assertEqual(restored.kind, envelope.kind)
        self.assertEqual(restored.device_id, DEVICE_A)
        self.assertEqual(restored.batch_id, BATCH)
        self.assertEqual(restored.seq, envelope.seq)
        self.assertEqual(restored.hlc, "0001-0001-a")
        self.assertEqual(restored.version, PROTOCOL_VERSION)
        self.assertEqual(restored.payload, envelope.payload)

    def test_sequence_numbers_increase_monotonically(self) -> None:
        first = self.a.next_envelope([op("82062339000000001004")])
        second = self.a.next_envelope([op("82062339000000001001")])
        self.assertEqual(second.seq, first.seq + 1)


class IdempotencyTests(TransportTestCase):
    """清单第 2 条：同一 (deviceId, seq) 投两次，业务只应用一次。"""

    def test_duplicate_delivery_applies_once(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")])
        first = self.a.send([envelope])
        second = self.hub.deliver(envelope)

        self.assertEqual(first.accepted, [1])
        self.assertEqual(second.duplicate, [1])
        self.assertEqual(second.accepted, [])
        self.assertEqual(self.hub.state(BATCH).particle_count, 1, "重复投递不得重复应用")


class GapDetectionTests(TransportTestCase):
    """清单第 3 条：序号跳跃要求补发，而不是静默接受。"""

    def test_gap_is_detected_and_reports_expected_seq(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")])
        envelope.seq = 5
        result = self.a.send([envelope])

        self.assertTrue(result.gap_detected)
        self.assertEqual(result.expected_seq, 1)
        self.assertEqual(self.hub.state(BATCH).particle_count, 0, "缺口时不得应用")

    def test_resend_from_expected_seq_succeeds(self) -> None:
        self.a.send([self.a.next_envelope([op("82062339000000001004")])])
        jumped = self.a.next_envelope([op("82062339000000001001")])
        jumped.seq = 9
        gap = self.a.send([jumped])
        self.assertTrue(gap.gap_detected)

        jumped.seq = gap.expected_seq
        ok = self.a.send([jumped])
        self.assertTrue(ok.ok)
        self.assertEqual(self.hub.state(BATCH).particle_count, 2)

    def test_gap_is_audited(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")])
        envelope.seq = 3
        self.a.send([envelope])
        actions = {entry["action"] for entry in self.hub.audit}
        self.assertIn("sync_gap", actions)


class FailureSemanticsTests(TransportTestCase):
    """清单第 4 条：业务拒绝不重试，通道故障才重试。"""

    def test_channel_failure_is_retryable(self) -> None:
        self.hub.disconnect(DEVICE_A)
        with self.assertRaises(TransportError) as ctx:
            self.a.send([self.a.next_envelope([op("82062339000000001004")])])
        self.assertTrue(ctx.exception.retryable, "断线属于通道故障，应当可重试")

    def test_protocol_version_mismatch_is_not_retryable(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004")])
        envelope.version = 99
        with self.assertRaises(TransportError) as ctx:
            self.hub.deliver(envelope)
        self.assertFalse(ctx.exception.retryable, "版本不兼容重试也没用")

    def test_duplicate_code_is_business_rejection_not_failure(self) -> None:
        """第二个设备提交同一码 → 业务拒绝（不可重试），而不是抛异常。"""

        self.a.send([self.a.next_envelope([op("82062339000000001004")])])

        b = InMemorySyncTransport(self.hub, DEVICE_B)
        b.open(batch_id=BATCH, device_id=DEVICE_B)
        try:
            result = b.send([b.next_envelope([op("82062339000000001004")])])
        finally:
            b.close()

        self.assertFalse(result.ok)
        self.assertEqual(len(result.rejected), 1)
        rejection = result.rejected[0]
        self.assertEqual(rejection.reason, REASON_DUPLICATE_CODE)
        self.assertFalse(rejection.retryable, "重复条码重试一百次也一样")

    def test_batch_mismatch_is_rejected(self) -> None:
        envelope = self.a.next_envelope([op("82062339000000001004", batch_id="别的批次")])
        result = self.a.send([envelope])
        self.assertEqual(result.rejected[0].reason, REASON_BATCH_MISMATCH)

    def test_rejection_is_audited(self) -> None:
        self.a.send([self.a.next_envelope([op("82062339000000001004")])])
        self.a.send([self.a.next_envelope([op("82062339000000001004")])])
        actions = {entry["action"] for entry in self.hub.audit}
        self.assertIn("sync_rejected", actions)

    def test_unknown_layer_is_rejected(self) -> None:
        result = self.a.send([self.a.next_envelope([op("99000000000000000000", layer=7)])])
        self.assertEqual(result.rejected[0].reason, "WRONG_LAYER")


class CapabilityTests(TransportTestCase):
    """清单第 5 条：能力声明，尤其是 encrypted。"""

    def test_duplicate_can_code_is_rejected(self) -> None:
        """罐号也必须由服务端去重。

        这是压测骨架发现的一个保真度缺口：多台移动端抢同一个罐时，
        服务端若不去重，会出现两个罐共用一个罐号的数据。
        真实实现里这条由数据库唯一索引保证，假实现必须同样对待 ——
        否则压测跑出来的"通过"没有意义。
        """

        self.a.send([self.a.next_envelope([op("80217629000000001005", layer=2)])])
        result = self.a.send([self.a.next_envelope([op("80217629000000001005", layer=2)])])

        self.assertFalse(result.ok)
        self.assertEqual(result.rejected[0].reason, REASON_DUPLICATE_CODE)
        self.assertEqual(result.rejected[0].detail.get("entity"), "can")
        self.assertEqual(self.hub.state(BATCH).can_count, 1, "重复罐号不得计入")

    def test_different_can_codes_are_fine(self) -> None:
        self.a.send([self.a.next_envelope([op("80217629000000001005", layer=2)])])
        result = self.a.send([self.a.next_envelope([op("80217629000000001004", layer=2)])])
        self.assertTrue(result.ok)
        self.assertEqual(self.hub.state(BATCH).can_count, 2)

    def test_default_mock_is_not_encrypted(self) -> None:
        """选项 B 下通道就是明文的，能力声明必须如实反映，界面才能提示风险。"""

        self.assertFalse(self.a.capabilities().encrypted)

    def test_encrypted_hub_reports_encrypted(self) -> None:
        hub = InMemoryHub(encrypted=True)
        transport = InMemorySyncTransport(hub, DEVICE_A)
        transport.open(batch_id=BATCH, device_id=DEVICE_A)
        try:
            self.assertTrue(transport.capabilities().encrypted)
        finally:
            transport.close()

    def test_capabilities_shape(self) -> None:
        payload = self.a.capabilities().to_dict()
        self.assertEqual(set(payload), {"push", "maxBatch", "encrypted", "stableRtt"})
        self.assertGreater(payload["maxBatch"], 0)

    def test_status_reports_open_state(self) -> None:
        self.assertTrue(self.a.status().open)
        self.assertIsInstance(self.a.status(), TransportStatus)
        self.a.close()
        self.assertFalse(self.a.status().open)


class MultiDeviceTests(TransportTestCase):
    def test_broadcast_reaches_other_devices_only(self) -> None:
        b = InMemorySyncTransport(self.hub, DEVICE_B)
        b.open(batch_id=BATCH, device_id=DEVICE_B)
        try:
            self.a.send([self.a.next_envelope([op("82062339000000001004")])])
            received = b.receive(timeout=0)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].kind, KIND_BROADCAST)
            self.assertEqual(received[0].payload["from"], DEVICE_A)

            self.assertEqual(self.a.receive(timeout=0), [], "自己不该收到自己的广播")
        finally:
            b.close()

    def test_receive_when_offline_raises_channel_error(self) -> None:
        self.hub.disconnect(DEVICE_A)
        with self.assertRaises(TransportError):
            self.a.receive(timeout=0)

    def test_open_is_idempotent(self) -> None:
        self.a.open(batch_id=BATCH, device_id=DEVICE_A)
        self.a.open(batch_id=BATCH, device_id=DEVICE_A)
        self.assertEqual(self.hub.online_devices(), [DEVICE_A])


class EquivalenceTests(unittest.TestCase):
    """清单第 6 条：两条通道等价。

    同一条 oplog 分别走"小批量通道"（max_batch=1）与"大批量通道"（max_batch=500），
    最终的服务端数据与摘要必须完全一致。
    这是把"通道无关"从设计意图变成可验证事实的关键一条。
    """

    OPS = [
        op("80217619000000001003", layer=3),
        op("80217629000000001005", layer=2),
        op("82062339000000001004"),
        op("82062339000000001001"),
    ]

    def run_through(self, max_batch: int):
        hub = InMemoryHub(max_batch=max_batch)
        transport = InMemorySyncTransport(hub, DEVICE_A)
        transport.open(batch_id=BATCH, device_id=DEVICE_A)
        try:
            for item in self.OPS:
                transport.send([transport.next_envelope([item])])
            return hub.state(BATCH)
        finally:
            transport.close()

    def test_two_channel_configurations_produce_identical_digest(self) -> None:
        small = self.run_through(1)
        large = self.run_through(500)
        self.assertEqual(small.to_dict(), large.to_dict())
        self.assertEqual(small.particle_count, 2)
        self.assertEqual(small.can_count, 1)
        self.assertEqual(small.box_count, 1)

    def test_digest_changes_when_codes_change(self) -> None:
        hub = InMemoryHub()
        transport = InMemorySyncTransport(hub, DEVICE_A)
        transport.open(batch_id=BATCH, device_id=DEVICE_A)
        try:
            transport.send([transport.next_envelope([op("82062339000000001004")])])
            first = hub.state(BATCH).code_hash
            transport.send([transport.next_envelope([op("82062339000000001001")])])
            second = hub.state(BATCH).code_hash
        finally:
            transport.close()
        self.assertNotEqual(first, second, "集合内容变了摘要就该变")


if __name__ == "__main__":
    unittest.main()
