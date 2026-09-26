"""内存假实现：把"通道无关"从设计意图变成可验证的事实。

它模拟三件事：
    1. 服务端按 `(deviceId, seq)` 去重 —— 至少投递一次语义下的幂等保证；
    2. 序号缺口检测 —— 客户端补发而不是服务端静默接受；
    3. 业务拒绝与通道故障的区别 —— 前者进 `SendResult.rejected`，后者抛 `TransportError`。

它**不模拟**：加密、真实延迟、网络抖动。那些是真实通道要解决的事。
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .envelope import (
    KIND_BROADCAST,
    KIND_OPLOG,
    KIND_OPLOG_ACK,
    Envelope,
)
from .digest import SyncDigest, code_set_hash
from .transport import (
    RejectedOp,
    SendResult,
    TransportCapabilities,
    TransportError,
    TransportStatus,
)

REASON_DUPLICATE_CODE = "DUPLICATE_CODE"
REASON_BATCH_MISMATCH = "BATCH_MISMATCH"
REASON_WRONG_LAYER = "WRONG_LAYER"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class _ServerBatch:
    """服务端某一批次的状态。只存摘要所需的最小信息。"""

    codes: set[str] = field(default_factory=set)
    """已占用的粒子码。"""

    can_codes: set[str] = field(default_factory=set)
    """已占用的罐号。**

    必须在服务端拦住重复罐号：多台移动端抢同一个罐时，
    若只靠客户端自觉，会出现两个罐共用同一个罐号的数据。
    真实实现里这条由数据库唯一索引保证；假实现必须同样对待，
    否则压测跑出来的"通过"没有意义。
    """

    box_count: int = 0
    can_count: int = 0

    def digest(self) -> SyncDigest:
        # 摘要算法只有一份（digest.code_set_hash），假实现与真实通道共用，
        # 否则两端各写一个哈希会永远比对不上。
        return SyncDigest(
            box_count=self.box_count,
            can_count=self.can_count,
            particle_count=len(self.codes),
            code_hash=code_set_hash(self.codes),
        )


class InMemoryHub:
    """内存版服务端。多个客户端连同一个 hub 就能模拟多端并发。"""

    def __init__(self, *, encrypted: bool = False, max_batch: int = 500) -> None:
        self._lock = threading.RLock()
        self._batches: dict[str, _ServerBatch] = {}
        self._seen: dict[str, set[int]] = {}
        """deviceId → 已收 seq 集合，用于去重与缺口检测。"""
        self._online: set[str] = set()
        self._outbox: dict[str, list[Envelope]] = {}
        """deviceId → 待投递给它的广播。"""
        self._encrypted = encrypted
        self._max_batch = max_batch
        self.audit: list[dict[str, object]] = []
        """服务端的接收 / 拒绝记录，等价于一期的审计日志。"""

    # ------------------------------------------------------------------ 连接

    def connect(self, device_id: str) -> None:
        with self._lock:
            self._online.add(device_id)
            self._outbox.setdefault(device_id, [])
            self._seen.setdefault(device_id, set())

    def disconnect(self, device_id: str) -> None:
        """模拟断网。之后的 send 会抛 TransportError（通道故障，可重试）。"""

        with self._lock:
            self._online.discard(device_id)

    def is_online(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._online

    def online_devices(self) -> list[str]:
        with self._lock:
            return sorted(self._online)

    # ------------------------------------------------------------------ 接收

    def deliver(self, envelope: Envelope) -> SendResult:
        """服务端收到一条消息。断线时抛 TransportError。"""

        if envelope.version != 1:
            raise TransportError(
                f"协议版本不兼容：对端 {envelope.version}，本端 1", retryable=False
            )

        with self._lock:
            if envelope.device_id not in self._online:
                raise TransportError(f"设备 {envelope.device_id} 不在线")

            if envelope.kind != KIND_OPLOG:
                # 非 oplog 消息不参与去重与缺口检测
                return SendResult(accepted=[envelope.seq])

            seen = self._seen.setdefault(envelope.device_id, set())
            if envelope.seq in seen:
                # 幂等：重复投递不重复应用，也不报错
                return SendResult(duplicate=[envelope.seq])

            expected = (max(seen) + 1) if seen else 1
            if envelope.seq > expected:
                # 缺口：要求客户端从 expected 补发，不静默接受
                self.audit.append(
                    {
                        "action": "sync_gap",
                        "deviceId": envelope.device_id,
                        "expected": expected,
                        "received": envelope.seq,
                        "at": _now(),
                    }
                )
                return SendResult(gap_detected=True, expected_seq=expected)

            result = SendResult()
            ops = list(envelope.payload.get("ops") or [])  # type: ignore[arg-type]
            batch = self._batches.setdefault(envelope.batch_id, _ServerBatch())

            # 摘要探测：只回摘要，不改数据、不推进去重状态
            if len(ops) == 1 and int(ops[0].get("packLayer") or 0) == 0:
                return SendResult(accepted=[envelope.seq], digest=batch.digest().to_dict())

            applied_any = False
            for op in ops:
                code = str(op.get("code") or "")
                layer = int(op.get("packLayer") or 0)  # type: ignore[arg-type]
                op_batch = str(op.get("batchId") or envelope.batch_id)

                if op_batch != envelope.batch_id:
                    result.rejected.append(
                        RejectedOp(
                            seq=envelope.seq,
                            reason=REASON_BATCH_MISMATCH,
                            detail={"opBatchId": op_batch, "envelopeBatchId": envelope.batch_id},
                        )
                    )
                    continue

                if layer == 1 and code in batch.codes:
                    # 业务拒绝：条码已被占用。不可重试 —— 重试一百次也一样。
                    result.rejected.append(
                        RejectedOp(
                            seq=envelope.seq,
                            reason=REASON_DUPLICATE_CODE,
                            detail={"code": code, "opId": str(op.get("opId") or "")},
                        )
                    )
                    continue

                if layer == 3:
                    batch.box_count = 1
                elif layer == 2:
                    if code in batch.can_codes:
                        result.rejected.append(
                            RejectedOp(
                                seq=envelope.seq,
                                reason=REASON_DUPLICATE_CODE,
                                detail={
                                    "code": code,
                                    "entity": "can",
                                    "opId": str(op.get("opId") or ""),
                                },
                            )
                        )
                        continue
                    batch.can_codes.add(code)
                    batch.can_count += 1
                elif layer == 1:
                    batch.codes.add(code)
                else:
                    result.rejected.append(
                        RejectedOp(
                            seq=envelope.seq,
                            reason=REASON_WRONG_LAYER,
                            detail={
                                "code": code,
                                "packLayer": layer,
                                "opId": str(op.get("opId") or ""),
                            },
                        )
                    )
                    continue
                applied_any = True

            if result.rejected:
                # 整条消息被拒时**不推进 seq**，让客户端能修正后重发同一个序号；
                # 但已应用的部分保留，避免重复应用。
                self.audit.append(
                    {
                        "action": "sync_rejected",
                        "deviceId": envelope.device_id,
                        "seq": envelope.seq,
                        "reasons": [item.reason for item in result.rejected],
                        "at": _now(),
                    }
                )
                return result

            seen.add(envelope.seq)
            result.accepted.append(envelope.seq)

            if applied_any:
                self._fanout(envelope)
            return result

    def _fanout(self, envelope: Envelope) -> None:
        """把变更广播给同批次的其他在线设备。"""

        for device_id in sorted(self._online):
            if device_id == envelope.device_id:
                continue
            self._outbox.setdefault(device_id, []).append(
                Envelope(
                    kind=KIND_BROADCAST,
                    device_id="server",
                    batch_id=envelope.batch_id,
                    seq=envelope.seq,
                    hlc=envelope.hlc,
                    sent_at=_now(),
                    payload={
                        "from": envelope.device_id,
                        "ops": list(envelope.payload.get("ops") or []),  # type: ignore[arg-type]
                    },
                )
            )

    # ------------------------------------------------------------------ 拉取

    def poll(self, device_id: str) -> list[Envelope]:
        with self._lock:
            if device_id not in self._online:
                raise TransportError(f"设备 {device_id} 不在线")
            pending = self._outbox.get(device_id, [])
            self._outbox[device_id] = []
            return pending

    def state(self, batch_id: str) -> SyncDigest:
        with self._lock:
            return self._batches.setdefault(batch_id, _ServerBatch()).digest()


class InMemorySyncTransport:
    """把 `InMemoryHub` 包装成 `SyncTransport`。"""

    name = "memory"

    def __init__(self, hub: InMemoryHub, device_id: str) -> None:
        self._hub = hub
        self._device_id = device_id
        self._batch_id = ""
        self._seq = 0
        self._status = TransportStatus()

    # ------------------------------------------------------------------ 连接

    def open(self, *, batch_id: str, device_id: str) -> None:
        if self.is_open() and batch_id == self._batch_id and device_id == self._device_id:
            return  # 幂等
        self._batch_id = batch_id
        self._device_id = device_id
        self._seq = 0
        self._hub.connect(device_id)
        self._status = TransportStatus(open=True)

    def close(self) -> None:
        self._hub.disconnect(self._device_id)
        self._status = TransportStatus(open=False)

    def is_open(self) -> bool:
        return self._status.open and self._hub.is_online(self._device_id)

    # ------------------------------------------------------------------ 收发

    def next_envelope(self, ops: list[dict[str, object]], *, hlc: str = "") -> Envelope:
        """构造下一条 oplog 信封。序号由通道自己维护。"""

        self._seq += 1
        return Envelope(
            kind=KIND_OPLOG,
            device_id=self._device_id,
            batch_id=self._batch_id,
            seq=self._seq,
            hlc=hlc,
            sent_at=_now(),
            payload={"ops": ops},
        )

    def send(self, envelopes: list[Envelope]) -> SendResult:
        if not self.is_open():
            raise TransportError("通道未打开")

        capabilities = self.capabilities()
        combined = SendResult()
        # 通道自己按 max_batch 切分 —— 调用方不需要知道这个限制
        for start in range(0, len(envelopes), capabilities.max_batch):
            chunk = envelopes[start : start + capabilities.max_batch]
            for envelope in chunk:
                part = self._hub.deliver(envelope)
                combined.accepted.extend(part.accepted)
                combined.rejected.extend(part.rejected)
                combined.duplicate.extend(part.duplicate)
                if part.digest is not None:
                    # 摘要探测的应答必须透传，否则调用方永远看不到远端摘要
                    combined.digest = part.digest
                if part.gap_detected:
                    combined.gap_detected = True
                    combined.expected_seq = part.expected_seq
        self._status.pending = 0
        return combined

    def receive(self, *, timeout: float) -> list[Envelope]:
        if not self.is_open():
            raise TransportError("通道未打开")
        messages = self._hub.poll(self._device_id)
        self._status.pending = 0
        return messages

    def ack(self, envelope: Envelope, result: SendResult) -> Envelope:
        """构造 oplog_ack（供测试与将来的真实通道使用）。"""

        return Envelope(
            kind=KIND_OPLOG_ACK,
            device_id="server",
            batch_id=envelope.batch_id,
            seq=envelope.seq,
            sent_at=_now(),
            payload={
                "accepted": result.accepted,
                "rejected": [item.to_dict() for item in result.rejected],
                "duplicate": result.duplicate,
                "gapDetected": result.gap_detected,
                "expectedSeq": result.expected_seq,
            },
        )

    # ------------------------------------------------------------------ 状态

    def status(self) -> TransportStatus:
        return TransportStatus(
            open=self.is_open(),
            rtt_ms=0.0,
            pending=self._status.pending,
            last_pong_at=self._status.last_pong_at,
            last_error=self._status.last_error,
        )

    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities(
            push=True,
            max_batch=self._hub._max_batch,  # noqa: SLF001 - 同包内的假实现，读配置
            encrypted=self._hub._encrypted,  # noqa: SLF001
            stable_rtt=True,
        )
