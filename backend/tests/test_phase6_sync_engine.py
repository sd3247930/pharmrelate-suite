"""批次 1：oplog 增量同步（5.1）+ 摘要校验（5.3）。

两者互为验证是这组测试的核心思路：
    - 增量推送保证每条 oplog 都送到；
    - 摘要校验保证送到之后两端确实长成一样。
所以既要用假实现对照，也要验"数量对但内容不对"这种情况能被摘要抓住。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import TempDatabaseTestCase
except ImportError:
    from support import TempDatabaseTestCase

from app.domain.models import Batch, BoxCode, CanCode
from app.sync import (
    ACTION_CREATE,
    InMemoryHub,
    InMemorySyncTransport,
    OplogEntry,
    OplogError,
    OplogStore,
    SyncDigest,
    SyncEngine,
    digest_of_batch,
)
from app.sync.digest import code_set_hash

BATCH_KEY = "SYNC-0001"
DEVICE = "android-01"
BOX = "80217619000000001003"
CAN = "80217629000000001005"
PARTICLES = ["82062339000000001004", "82062339000000001001"]


def entry(code: str, layer: int, hlc: str, *, op_id: str = "") -> OplogEntry:
    return OplogEntry(
        op_id=op_id or f"{BATCH_KEY}:{layer}:{code}",
        batch_id=BATCH_KEY,
        entity={3: "box", 2: "can", 1: "particle"}[layer],
        entity_id=code,
        action=ACTION_CREATE,
        hlc=hlc,
        device_id=DEVICE,
        user_id="操作员甲",
        timestamp="2026-09-26T10:00:00+00:00",
        new_value={"code": code, "packLayer": layer},
    )


def sample_batch() -> Batch:
    return Batch(
        batch_no="20260901",
        made_date="2026-09-23",
        validate_date="2026-10-23",
        box=BoxCode(
            code=BOX,
            cans=[
                CanCode(index=1, code=CAN, planned_particle_count=2, particles=list(PARTICLES))
            ],
        ),
    )


class OplogSerialisationTests(unittest.TestCase):
    def test_round_trip_keeps_all_fields(self) -> None:
        original = entry(PARTICLES[0], 1, "1700000000000-000000-android-01")
        restored = OplogEntry.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_field_names_match_phase_one_table(self) -> None:
        """字段名必须与一期 oplog 表一一对应，不新增字段。"""

        payload = entry(PARTICLES[0], 1, "1700000000000-000000-android-01").to_dict()
        self.assertEqual(
            set(payload),
            {
                "opId", "batchId", "entity", "entityId", "action", "field",
                "oldValue", "newValue", "hlc", "deviceId", "userId", "timestamp",
            },
        )

    def test_rejects_unknown_entity_and_action(self) -> None:
        bad = entry(PARTICLES[0], 1, "1700000000000-000000-android-01")
        bad.entity = "unknown"
        with self.assertRaises(OplogError):
            bad.validate()

        bad_action = entry(PARTICLES[0], 1, "1700000000000-000000-android-01")
        bad_action.action = "frobnicate"
        with self.assertRaises(OplogError):
            bad_action.validate()

    def test_rejects_missing_hlc(self) -> None:
        """没有 HLC 就无法定序，宁可拒绝也不要产生一条无法合并的记录。"""

        bad = entry(PARTICLES[0], 1, "")
        with self.assertRaises(OplogError):
            bad.validate()

    def test_from_scan_op_maps_layer_to_entity(self) -> None:
        for layer, expected in ((3, "box"), (2, "can"), (1, "particle")):
            with self.subTest(layer=layer):
                converted = OplogEntry.from_scan_op(
                    {"code": BOX, "packLayer": layer, "batchId": BATCH_KEY, "hlc": "x"}
                )
                self.assertEqual(converted.entity, expected)
                self.assertEqual(converted.action, ACTION_CREATE)

    def test_from_scan_op_rejects_unknown_layer(self) -> None:
        with self.assertRaises(OplogError):
            OplogEntry.from_scan_op({"code": BOX, "packLayer": 7, "batchId": BATCH_KEY})


class OplogStoreTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = OplogStore(self.database)

    def test_append_then_pending(self) -> None:
        self.store.append(entry(PARTICLES[0], 1, "1700000000001-000000-android-01"))
        pending = self.store.pending(BATCH_KEY)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].entity_id, PARTICLES[0])
        self.assertEqual(self.store.count(BATCH_KEY, synced=False), 1)

    def test_duplicate_op_id_is_ignored(self) -> None:
        item = entry(PARTICLES[0], 1, "1700000000001-000000-android-01")
        self.store.append(item)
        self.store.append(item)
        self.assertEqual(self.store.count(BATCH_KEY), 1)

    def test_pending_is_ordered_by_hlc_not_insert_order(self) -> None:
        """必须按 HLC 升序取数：离线补录的 rowid 顺序可能与真实发生顺序不同。"""

        self.store.append(entry(PARTICLES[1], 1, "1700000000002-000000-android-01"))
        self.store.append(entry(BOX, 3, "1700000000001-000000-android-01"))
        self.store.append(entry(CAN, 2, "1700000000003-000000-android-01"))

        order = [item.entity_id for item in self.store.pending(BATCH_KEY)]
        self.assertEqual(order, [BOX, PARTICLES[1], CAN])

    def test_mark_synced_removes_from_pending(self) -> None:
        self.store.append(entry(PARTICLES[0], 1, "1700000000001-000000-android-01"))
        marked = self.store.mark_synced([f"{BATCH_KEY}:1:{PARTICLES[0]}"])
        self.assertEqual(marked, 1)
        self.assertEqual(self.store.pending(BATCH_KEY), [])

    def test_json_values_survive_round_trip(self) -> None:
        self.store.append(entry(PARTICLES[0], 1, "1700000000001-000000-android-01"))
        restored = self.store.pending(BATCH_KEY)[0]
        self.assertEqual(restored.new_value, {"code": PARTICLES[0], "packLayer": 1})


class EnginePushTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = OplogStore(self.database)
        self.hub = InMemoryHub()
        self.transport = InMemorySyncTransport(self.hub, DEVICE)
        self.transport.open(batch_id=BATCH_KEY, device_id=DEVICE)
        self.engine = SyncEngine(self.store)

    def tearDown(self) -> None:
        self.transport.close()
        super().tearDown()

    def seed(self) -> None:
        self.store.append(entry(BOX, 3, "1700000000001-000000-android-01"))
        self.store.append(entry(CAN, 2, "1700000000002-000000-android-01"))
        self.store.append(entry(PARTICLES[0], 1, "1700000000003-000000-android-01"))

    def test_push_marks_records_synced(self) -> None:
        self.seed()
        outcome = self.engine.push_pending(self.transport, BATCH_KEY)

        self.assertTrue(outcome.ok, outcome.to_dict())
        self.assertEqual(outcome.sent, 3)
        self.assertEqual(self.store.pending(BATCH_KEY), [], "推送后队列应清空")
        self.assertEqual(self.hub.state(BATCH_KEY).particle_count, 1)
        self.assertEqual(self.hub.state(BATCH_KEY).can_count, 1)

    def test_second_push_is_noop(self) -> None:
        self.seed()
        self.engine.push_pending(self.transport, BATCH_KEY)
        again = self.engine.push_pending(self.transport, BATCH_KEY)
        self.assertEqual(again.sent, 0)
        self.assertEqual(again.rounds, 0)

    def test_business_rejection_is_marked_synced_so_queue_drains(self) -> None:
        """被业务拒绝的记录必须移出队列。

        否则每次推送都重发同一批必被拒绝的记录，队列永远清不空。
        """

        self.store.append(entry(PARTICLES[0], 1, "1700000000001-000000-android-01"))
        self.engine.push_pending(self.transport, BATCH_KEY)

        # 换一台设备提交同一个粒子码 → 必被拒绝
        other = InMemorySyncTransport(self.hub, "android-02")
        other.open(batch_id=BATCH_KEY, device_id="android-02")
        try:
            self.store.append(
                entry(PARTICLES[0], 1, "1700000000002-000000-android-02", op_id="dup-op")
            )
            outcome = self.engine.push_pending(other, BATCH_KEY)
            self.assertEqual(len(outcome.rejected), 1)
            self.assertEqual(outcome.rejected[0]["reason"], "DUPLICATE_CODE")
            self.assertEqual(
                self.store.pending(BATCH_KEY), [], "被拒绝的记录也应移出队列，避免死循环"
            )
        finally:
            other.close()

    def test_channel_error_keeps_records_pending(self) -> None:
        """通道故障与业务拒绝必须区别对待：故障时记录必须留在队列里。"""

        self.seed()
        self.hub.disconnect(DEVICE)
        outcome = self.engine.push_pending(self.transport, BATCH_KEY)

        self.assertEqual(outcome.channel_errors, 1)
        self.assertFalse(outcome.ok)
        self.assertEqual(
            self.store.count(BATCH_KEY, synced=False), 3, "断线时不得标记为已同步"
        )

    def test_pending_limit_batches_large_queues(self) -> None:
        for index in range(10):
            self.store.append(
                entry(f"8206233{index:013d}", 1, f"17000000000{index:02d}-000000-android-01")
            )
        engine = SyncEngine(self.store, batch_size=4)
        outcome = engine.push_pending(self.transport, BATCH_KEY)
        self.assertTrue(outcome.ok, outcome.to_dict())
        self.assertEqual(outcome.sent, 10, "分多轮推送应把队列推空")
        self.assertGreaterEqual(outcome.rounds, 3)


class DigestTests(unittest.TestCase):
    def test_digest_counts_and_hash(self) -> None:
        digest = digest_of_batch(sample_batch())
        self.assertEqual(digest.box_count, 1)
        self.assertEqual(digest.can_count, 1)
        self.assertEqual(digest.particle_count, 2)
        self.assertEqual(digest.code_hash, code_set_hash(PARTICLES))

    def test_hash_is_order_independent(self) -> None:
        self.assertEqual(code_set_hash(["a", "b"]), code_set_hash(["b", "a"]))

    def test_hash_changes_when_content_changes(self) -> None:
        self.assertNotEqual(code_set_hash(["a", "b"]), code_set_hash(["a", "c"]))

    def test_digest_matches_mock_hub_for_same_codes(self) -> None:
        """互为验证：本地摘要与假实现服务端算出的摘要必须一致。

        这条如果失败，说明两端的哈希算法出现了分歧 ——
        那会导致同步永远"看起来不一致"，是最难查的一类问题。
        """

        hub = InMemoryHub()
        transport = InMemorySyncTransport(hub, DEVICE)
        transport.open(batch_id=BATCH_KEY, device_id=DEVICE)
        try:
            transport.send(
                [
                    transport.next_envelope(
                        [{"code": BOX, "packLayer": 3, "batchId": BATCH_KEY}]
                    )
                ]
            )
            transport.send(
                [
                    transport.next_envelope(
                        [{"code": CAN, "packLayer": 2, "batchId": BATCH_KEY}]
                    )
                ]
            )
            for code in PARTICLES:
                transport.send(
                    [
                        transport.next_envelope(
                            [{"code": code, "packLayer": 1, "batchId": BATCH_KEY}]
                        )
                    ]
                )
            remote = hub.state(BATCH_KEY)
        finally:
            transport.close()

        self.assertEqual(digest_of_batch(sample_batch()), remote)

    def test_differences_pinpoint_the_field(self) -> None:
        """差异要指到具体字段，而不是只回一句"不一致"。

        数量对但哈希不对 → 条码内容问题；数量不对 → 丢操作。排查方向完全不同。
        """

        local = SyncDigest(1, 1, 2, code_set_hash(PARTICLES))
        same_count_other_codes = SyncDigest(1, 1, 2, code_set_hash(["x", "y"]))
        fewer = SyncDigest(1, 1, 1, code_set_hash(PARTICLES[:1]))

        _, content_diff = local.differences(same_count_other_codes), None
        differences = local.differences(same_count_other_codes)
        self.assertEqual(len(differences), 1)
        self.assertIn("codeHash", differences[0])

        count_differences = local.differences(fewer)
        self.assertTrue(any("particleCount" in item for item in count_differences))
        self.assertTrue(any("codeHash" in item for item in count_differences))

    def test_verify_pair_flags_full_pull_on_mismatch(self) -> None:
        engine = SyncEngine(OplogStore.__new__(OplogStore))  # 只用纯比对，不碰库
        local = SyncDigest(1, 1, 2, code_set_hash(PARTICLES))
        outcome = engine.verify_pair(local, SyncDigest(1, 1, 3, code_set_hash(PARTICLES)))

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.needs_full_pull, "不一致时必须要求全量拉取，不猜原因")
        self.assertTrue(outcome.differences)

    def test_verify_pair_reports_match(self) -> None:
        engine = SyncEngine(OplogStore.__new__(OplogStore))
        local = SyncDigest(1, 1, 2, code_set_hash(PARTICLES))
        outcome = engine.verify_pair(local, local)
        self.assertTrue(outcome.matched)
        self.assertFalse(outcome.needs_full_pull)
        self.assertEqual(outcome.differences, [])


class DigestOverChannelTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = OplogStore(self.database)
        self.hub = InMemoryHub()
        self.transport = InMemorySyncTransport(self.hub, DEVICE)
        self.transport.open(batch_id=BATCH_KEY, device_id=DEVICE)
        self.engine = SyncEngine(self.store)

    def tearDown(self) -> None:
        self.transport.close()
        super().tearDown()

    def push_all(self) -> None:
        self.store.append(entry(BOX, 3, "1700000000001-000000-android-01"))
        self.store.append(entry(CAN, 2, "1700000000002-000000-android-01"))
        for offset, code in enumerate(PARTICLES):
            self.store.append(entry(code, 1, f"17000000000{offset + 3}-000000-android-01"))
        self.engine.push_pending(self.transport, BATCH_KEY)

    def test_digest_over_channel_matches_after_push(self) -> None:
        self.push_all()
        outcome = self.engine.verify_digest(
            self.transport, sample_batch(), batch_key=BATCH_KEY
        )
        self.assertTrue(outcome.matched, outcome.differences)
        self.assertFalse(outcome.needs_full_pull)

    def test_digest_over_channel_detects_missing_data(self) -> None:
        """少推一条 → 摘要必须报不一致并要求全量拉取。"""

        self.store.append(entry(BOX, 3, "1700000000001-000000-android-01"))
        self.engine.push_pending(self.transport, BATCH_KEY)

        outcome = self.engine.verify_digest(
            self.transport, sample_batch(), batch_key=BATCH_KEY
        )
        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.needs_full_pull)
        self.assertTrue(any("particleCount" in item for item in outcome.differences))


if __name__ == "__main__":
    unittest.main()
