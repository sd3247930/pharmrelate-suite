"""混合逻辑时钟（Hybrid Logical Clock）。

为什么需要它：多端并发写入时，"谁后发生"不能用墙上时钟判断 ——
手机与 PC 的系统时间会差几十毫秒甚至更多，车间里还可能有人手动改过时间。
HLC 把"物理时间"与"逻辑计数"结合起来：

    hlc = <物理毫秒>-<逻辑计数>-<设备ID>

    1. 本地事件：物理时间取 max(上一次, 现在)；若物理时间没前进，逻辑计数 +1；
       若物理时间前进了，逻辑计数归零。
    2. 收到远端事件：物理时间取 max(本地, 远端)；按规则推进逻辑计数。

这样得到的全序与"真实发生顺序"一致，且不受时钟偏差影响。
它是 V1.1 9.3 要求 `hlc` 字段的直接落点。

排序规则（**必须与字符串比较一致**，否则落库后排序会错）：
    物理时间升序 → 逻辑计数升序 → 设备 ID 字典序升序
因此时间戳按固定宽度补零，保证 `字符串比较 == 语义比较`。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

PHYSICAL_DIGITS = 15
COUNTER_DIGITS = 6
MAX_COUNTER = 10**COUNTER_DIGITS - 1


class HlcError(ValueError):
    """时间戳格式非法。"""


@dataclass(frozen=True, slots=True, order=True)
class Timestamp:
    """可直接比较的 HLC 时间戳。字段顺序即比较顺序。"""

    physical: int
    counter: int
    device: str = ""

    def __str__(self) -> str:
        return (
            f"{self.physical:0{PHYSICAL_DIGITS}d}"
            f"-{self.counter:0{COUNTER_DIGITS}d}"
            f"-{self.device}"
        )

    @classmethod
    def parse(cls, value: str) -> Timestamp:
        parts = value.split("-", 2)
        if len(parts) != 3:
            raise HlcError(f"HLC 时间戳格式应为 <物理>-<计数>-<设备>，实际 {value!r}")
        physical, counter, device = parts
        if not physical.isdigit() or not counter.isdigit():
            raise HlcError(f"HLC 时间戳的物理时间与计数必须为数字：{value!r}")
        return cls(int(physical), int(counter), device)


def parse(value: str) -> Timestamp:
    return Timestamp.parse(value)


def compare(left: str, right: str) -> int:
    """比较两个时间戳字符串。**直接用字符串比较**，因为格式保证了两者一致。"""

    return (left > right) - (left < right)


def sort_key(value: str) -> str:
    """排序键。格式设计保证了它等于语义序，因此直接返回原值。"""

    return value


class Clock:
    """一个设备上的 HLC 实例。

    线程安全：车间里取流线程与提交线程会并发调用。
    """

    def __init__(
        self,
        device_id: str,
        *,
        now_ms: int | None = None,
        clock_fn: Callable[[], int] | None = None,
    ) -> None:
        """`clock_fn` 用于注入可控时钟。

        没有它，测试只能去 monkeypatch 模块私有函数 —— 那是坏味道：
        生产代码为了可测而留下"可被替换的私有符号"，比显式注入更容易出意外。
        """

        if not device_id:
            raise HlcError("HLC 必须绑定设备 ID —— 没有它无法在多端间定序。")
        self._device = device_id
        self._clock_fn = clock_fn or _wall_clock_ms
        self._lock = threading.Lock()
        self._last = Timestamp(
            now_ms if now_ms is not None else self._clock_fn(), 0, device_id
        )

    @property
    def device_id(self) -> str:
        return self._device

    def now(self) -> str:
        """本地事件：产生一个新的时间戳并推进时钟。"""

        with self._lock:
            physical = self._clock_fn()
            if physical > self._last.physical:
                self._last = Timestamp(physical, 0, self._device)
            else:
                # 物理时间没前进（同一毫秒内多次操作，或系统时钟回拨）
                counter = self._last.counter + 1
                if counter > MAX_COUNTER:
                    # 计数溢出：把物理时间推进 1ms 再归零，保证仍严格递增
                    self._last = Timestamp(self._last.physical + 1, 0, self._device)
                else:
                    self._last = Timestamp(self._last.physical, counter, self._device)
            return str(self._last)

    def observe(self, remote: str) -> str:
        """收到远端事件：把本地时钟推进到"已知发生过的之后"。"""

        incoming = Timestamp.parse(remote)
        with self._lock:
            physical = max(self._clock_fn(), self._last.physical, incoming.physical)

            if physical == self._last.physical == incoming.physical:
                counter = max(self._last.counter, incoming.counter) + 1
            elif physical == self._last.physical:
                counter = self._last.counter + 1
            elif physical == incoming.physical:
                counter = incoming.counter + 1
            else:
                counter = 0

            if counter > MAX_COUNTER:
                physical += 1
                counter = 0

            self._last = Timestamp(physical, counter, self._device)
            return str(self._last)

    def peek(self) -> str:
        """只读当前时间戳，不推进时钟。"""

        with self._lock:
            return str(self._last)


def _wall_clock_ms() -> int:
    return int(time.time() * 1000)


def merge_winner(left: str, right: str) -> str:
    """LWW 仲裁：取 HLC 较大者。

    V1.1 9.4 规定"罐号/箱号被并发修改"用 Last-Write-Wins，以 HLC 大者为准。
    """

    return left if compare(left, right) >= 0 else right


def is_newer(candidate: str, current: str) -> bool:
    """候选值是否严格新于当前值。用于"旧数据不覆盖新数据"的判断（V1.1 9.4）。"""

    return compare(candidate, current) > 0
