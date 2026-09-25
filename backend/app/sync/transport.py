"""`SyncTransport` 契约。

与 docs/43 的定义一一对应。核心约定：

1. **业务拒绝与通道故障必须分开。**
   重复条码、HLC 落后等属于业务拒绝 —— 通过 `SendResult.rejected` 返回，
   触发人工介入或自动仲裁；
   断线、超时属于通道故障 —— 抛 `TransportError`，调用方按指数退避重试。
   混在一起会让重试逻辑吃掉业务错误，这是同步实现里最常见的坑。

2. **至少投递一次。** 去重靠 `(deviceId, seq)`，不靠通道。

3. **`receive` 超时不算错误。** 车间网络会长时间静默，空返回是常态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .envelope import Envelope


class TransportError(RuntimeError):
    """通道故障：断线、超时、服务不可达。**可重试**。"""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class RejectedOp:
    """被服务端拒绝的操作。**不可重试**，需要人工处理或自动仲裁。"""

    seq: int
    reason: str
    detail: dict[str, object] = field(default_factory=dict)
    retryable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "reason": self.reason,
            "detail": self.detail,
            "retryable": self.retryable,
        }


@dataclass(slots=True)
class SendResult:
    accepted: list[int] = field(default_factory=list)
    rejected: list[RejectedOp] = field(default_factory=list)
    duplicate: list[int] = field(default_factory=list)
    """服务端已收过、本次忽略的 seq（幂等保证）。"""

    gap_detected: bool = False
    """服务端发现序号缺口，要求客户端从 `expected_seq` 补发。"""

    expected_seq: int = 0

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.gap_detected


@dataclass(slots=True)
class TransportStatus:
    open: bool = False
    rtt_ms: float = 0.0
    pending: int = 0
    last_pong_at: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "open": self.open,
            "rttMs": round(self.rtt_ms, 1),
            "pending": self.pending,
            "lastPongAt": self.last_pong_at,
            "lastError": self.last_error,
        }


@dataclass(frozen=True, slots=True)
class TransportCapabilities:
    """通道能力声明。不同通道能力确实不同，所以显式声明而不是假设。"""

    push: bool
    max_batch: int
    encrypted: bool
    stable_rtt: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "push": self.push,
            "maxBatch": self.max_batch,
            "encrypted": self.encrypted,
            "stableRtt": self.stable_rtt,
        }


class SyncTransport(Protocol):
    name: str

    def open(self, *, batch_id: str, device_id: str) -> None: ...

    def close(self) -> None: ...

    def is_open(self) -> bool: ...

    def send(self, envelopes: list[Envelope]) -> SendResult: ...

    def receive(self, *, timeout: float) -> list[Envelope]: ...

    def status(self) -> TransportStatus: ...

    def capabilities(self) -> TransportCapabilities: ...
