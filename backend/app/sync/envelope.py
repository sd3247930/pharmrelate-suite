"""同步消息信封（定义见 docs/43-SyncTransport接口定义.md）。

所有通道传的都是同一个信封，不因通道而异 —— 这是"通道无关"的落点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROTOCOL_VERSION = 1

KIND_HELLO = "hello"
KIND_HELLO_ACK = "hello_ack"
KIND_OPLOG = "oplog"
KIND_OPLOG_ACK = "oplog_ack"
KIND_BROADCAST = "broadcast"
KIND_DIGEST = "digest"
KIND_PING = "ping"
KIND_PONG = "pong"
KIND_ERROR = "error"


@dataclass(slots=True)
class Envelope:
    """一条同步消息。

    `seq` 是**通道级**单调序号（从 1 开始），用于重连补发与缺口检测；
    业务排序一律用 `hlc` —— 这两个不要混用。
    """

    kind: str
    device_id: str
    batch_id: str
    seq: int
    hlc: str = ""
    sent_at: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "kind": self.kind,
            "deviceId": self.device_id,
            "batchId": self.batch_id,
            "seq": self.seq,
            "hlc": self.hlc,
            "sentAt": self.sent_at,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Envelope:
        return cls(
            kind=str(data["kind"]),
            device_id=str(data["deviceId"]),
            batch_id=str(data["batchId"]),
            seq=int(data["seq"]),  # type: ignore[arg-type]
            hlc=str(data.get("hlc") or ""),
            sent_at=str(data.get("sentAt") or ""),
            payload=dict(data.get("payload") or {}),  # type: ignore[arg-type]
            version=int(data.get("version") or PROTOCOL_VERSION),  # type: ignore[arg-type]
        )
