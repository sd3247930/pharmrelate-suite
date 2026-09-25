"""HLC（混合逻辑时钟）测试。

重点验三件事：
    1. **字符串比较 == 语义比较** —— 落库后靠字符串排序，这个不变量破了排序就会错；
    2. 严格递增 —— 同一毫秒内连续操作也不能产生相同时间戳；
    3. 时钟回拨与并发观察下的行为正确。
"""

from __future__ import annotations

import unittest

try:
    from tests.support import BACKEND_DIR  # noqa: F401
except ImportError:
    from support import BACKEND_DIR  # noqa: F401

from app.sync.hlc import (
    Clock,
    HlcError,
    Timestamp,
    compare,
    is_newer,
    merge_winner,
    parse,
)

DEVICE_A = "android-01"
DEVICE_B = "android-02"


class TimestampTests(unittest.TestCase):
    def test_format_is_fixed_width(self) -> None:
        stamp = Timestamp(1700000000000, 7, DEVICE_A)
        text = str(stamp)
        physical, counter, device = text.split("-", 2)
        self.assertEqual(len(physical), 15, "物理时间必须定宽补零，否则字符串比较会错")
        self.assertEqual(len(counter), 6)
        self.assertEqual(device, DEVICE_A)

    def test_round_trip(self) -> None:
        original = Timestamp(1700000000000, 12, DEVICE_A)
        self.assertEqual(parse(str(original)), original)

    def test_rejects_malformed(self) -> None:
        for value in ("", "只有两段-000001", "abc-000001-dev", "17000-xyz-dev"):
            with self.subTest(value=value):
                with self.assertRaises(HlcError):
                    parse(value)

    def test_string_compare_equals_semantic_compare(self) -> None:
        """核心不变量：字符串序必须等于语义序。"""

        samples = [
            Timestamp(1000, 0, DEVICE_A),
            Timestamp(1000, 1, DEVICE_A),
            Timestamp(1000, 999999, DEVICE_A),
            Timestamp(1001, 0, DEVICE_A),
            Timestamp(1001, 0, DEVICE_B),
            Timestamp(9_999_999_999_999, 0, DEVICE_A),
        ]
        for left in samples:
            for right in samples:
                with self.subTest(left=str(left), right=str(right)):
                    expected = (left > right) - (left < right)
                    self.assertEqual(compare(str(left), str(right)), expected)

    def test_device_id_breaks_ties_deterministically(self) -> None:
        """物理时间与计数都相同时靠设备 ID 定序 —— 两端必须得出同一结果。"""

        first = Timestamp(1000, 0, DEVICE_A)
        second = Timestamp(1000, 0, DEVICE_B)
        self.assertNotEqual(first, second)
        self.assertEqual(compare(str(first), str(second)), -1)
        # 换顺序比较，结论必须一致（否则两端会各选各的）
        self.assertEqual(compare(str(second), str(first)), 1)


class ClockTests(unittest.TestCase):
    def make_clock(self, start_ms: int = 1700000000000) -> tuple[Clock, list[int]]:
        """注入可控时钟：返回值与"当前毫秒"的可变容器，改动它即可模拟时间前进/回拨。"""

        now = [start_ms]
        return Clock(DEVICE_A, clock_fn=lambda: now[0]), now

    def test_now_is_strictly_increasing_within_same_millisecond(self) -> None:
        """同一毫秒内连续 100 次操作也不能产生相同时间戳。"""

        clock, _ = self.make_clock()
        stamps = [clock.now() for _ in range(100)]
        self.assertEqual(len(set(stamps)), 100)
        self.assertEqual(stamps, sorted(stamps))

    def test_now_follows_wall_clock_when_it_advances(self) -> None:
        clock, now = self.make_clock()
        clock.now()  # 同一毫秒内先占一次计数
        now[0] += 1000  # 系统时间前进 1 秒
        text = clock.now()
        self.assertEqual(parse(text).counter, 0)
        self.assertEqual(parse(text).physical, 1700000001000)

    def test_clock_rollback_does_not_go_backwards(self) -> None:
        """系统时钟被回拨时，HLC 不能倒退 —— 否则新数据会被判成旧数据。"""

        clock, now = self.make_clock(1700000005000)
        before = clock.now()
        now[0] -= 5000  # 回拨 5 秒
        after = clock.now()
        self.assertGreater(compare(after, before), 0)

    def test_observe_advances_past_remote(self) -> None:
        clock, _ = self.make_clock()
        remote = str(Timestamp(1700000009000, 3, DEVICE_B))
        local = clock.observe(remote)
        self.assertGreater(compare(local, remote), 0, "本地时钟必须推进到远端之后")

    def test_observe_handles_same_physical_and_counter(self) -> None:
        clock, _ = self.make_clock()
        remote = clock.now()
        after = clock.observe(remote)
        self.assertGreater(compare(after, remote), 0)

    def test_observe_from_slower_device_keeps_local_ahead(self) -> None:
        clock, _ = self.make_clock(1700000009000)
        remote = str(Timestamp(1700000001000, 5, DEVICE_B))  # 远端慢 8 秒
        local = clock.observe(remote)
        self.assertGreater(compare(local, remote), 0)
        self.assertGreaterEqual(parse(local).physical, 1700000009000)

    def test_counter_overflow_promotes_physical(self) -> None:
        """计数溢出时推进物理时间，保证仍严格递增。"""

        clock, _ = self.make_clock()
        # 手动把计数推到上限，模拟同一毫秒内操作过多
        clock._last = Timestamp(1700000000000, 10**6 - 1, DEVICE_A)
        text = clock.now()
        stamp = parse(text)
        self.assertEqual(stamp.physical, 1700000000001)
        self.assertEqual(stamp.counter, 0)

    def test_peek_does_not_advance(self) -> None:
        clock, _ = self.make_clock()
        first = clock.peek()
        self.assertEqual(clock.peek(), first)
        self.assertGreater(compare(clock.now(), first), 0)

    def test_requires_device_id(self) -> None:
        with self.assertRaises(HlcError):
            Clock("")


class ConcurrencyTests(unittest.TestCase):
    def test_two_devices_converge_on_same_order(self) -> None:
        """两端各自产生的事件，无论从哪边排序，结论必须一致。"""

        stamp_ms = [1700000000000]
        clock_a = Clock(DEVICE_A, clock_fn=lambda: stamp_ms[0])
        clock_b = Clock(DEVICE_B, clock_fn=lambda: stamp_ms[0])
        stamps = [clock_a.now(), clock_b.now(), clock_a.now(), clock_b.now()]

        self.assertEqual(sorted(stamps), sorted(stamps, key=lambda item: item))
        # 再排一次，顺序稳定（没有依赖输入顺序的隐式状态）
        self.assertEqual(list(reversed(sorted(stamps))), sorted(stamps, reverse=True))

    def test_merge_winner_picks_larger_hlc(self) -> None:
        older = "1700000000000-000000-android-01"
        newer = "1700000000001-000000-android-02"
        self.assertEqual(merge_winner(older, newer), newer)
        self.assertEqual(merge_winner(newer, older), newer)

    def test_is_newer_rejects_stale_write(self) -> None:
        current = "1700000000005-000000-android-01"
        stale = "1700000000000-000000-android-02"
        fresh = "1700000000006-000000-android-02"
        self.assertFalse(is_newer(stale, current), "旧数据不得覆盖新数据")
        self.assertTrue(is_newer(fresh, current))
        self.assertFalse(is_newer(current, current), "相同时间戳不算更新")


if __name__ == "__main__":
    unittest.main()
