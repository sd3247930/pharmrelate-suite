"""同步层（二期预备）。

本目录**只包含通道无关的契约与假实现**，不接入一期任何业务逻辑：
一期的扫码、槽位编辑、导出全部照旧走本地库。
二期一批接入局域网通道时，只需新增一个 `SyncTransport` 实现。
"""

from .envelope import (
    KIND_BROADCAST,
    KIND_DIGEST,
    KIND_ERROR,
    KIND_HELLO,
    KIND_HELLO_ACK,
    KIND_OPLOG,
    KIND_OPLOG_ACK,
    KIND_PING,
    KIND_PONG,
    PROTOCOL_VERSION,
    Envelope,
)
from .memory import InMemoryHub, InMemorySyncTransport, SyncDigest
from .transport import (
    RejectedOp,
    SendResult,
    SyncTransport,
    TransportCapabilities,
    TransportError,
    TransportStatus,
)

__all__ = [
    "KIND_BROADCAST",
    "KIND_DIGEST",
    "KIND_ERROR",
    "KIND_HELLO",
    "KIND_HELLO_ACK",
    "KIND_OPLOG",
    "KIND_OPLOG_ACK",
    "KIND_PING",
    "KIND_PONG",
    "PROTOCOL_VERSION",
    "Envelope",
    "InMemoryHub",
    "InMemorySyncTransport",
    "RejectedOp",
    "SendResult",
    "SyncDigest",
    "SyncTransport",
    "TransportCapabilities",
    "TransportError",
    "TransportStatus",
]
