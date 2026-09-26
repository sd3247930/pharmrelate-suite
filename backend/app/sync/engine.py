"""同步引擎：增量推送 + 摘要校验（批次 1 的 5.1 + 5.3）。

两者互为验证：
    - 增量推送保证**每条 oplog 都送到了**；
    - 摘要校验保证**送到之后两端确实长成一样**。
只有前者，丢了操作也不知道；只有后者，知道不一致却不知道差在哪。

设计约束：
    1. 通道只面对 `SyncTransport`，因此假实现、WebSocket、将来的云端通道通用；
    2. 业务拒绝（`retryable=False`）与通道故障（抛 `TransportError`）分开处理；
    3. 摘要不一致时**不猜测原因**，直接要求全量拉取。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .digest import SyncDigest, compare, digest_of_batch
from .oplog import OplogEntry, OplogStore
from .transport import SendResult, SyncTransport, TransportError

DEFAULT_BATCH_SIZE = 200


@dataclass(slots=True)
class PushOutcome:
    sent: int = 0
    accepted: int = 0
    duplicate: int = 0
    rejected: list[dict[str, object]] = field(default_factory=list)
    gap_detected: bool = False
    expected_seq: int = 0
    channel_errors: int = 0
    rounds: int = 0

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.gap_detected and self.channel_errors == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "sent": self.sent,
            "accepted": self.accepted,
            "duplicate": self.duplicate,
            "rejected": list(self.rejected),
            "gapDetected": self.gap_detected,
            "expectedSeq": self.expected_seq,
            "channelErrors": self.channel_errors,
            "rounds": self.rounds,
        }


@dataclass(slots=True)
class VerifyOutcome:
    matched: bool
    local: SyncDigest
    remote: SyncDigest
    differences: list[str] = field(default_factory=list)
    needs_full_pull: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "local": self.local.to_dict(),
            "remote": self.remote.to_dict(),
            "differences": list(self.differences),
            "needsFullPull": self.needs_full_pull,
        }


class SyncEngine:
    def __init__(
        self,
        store: OplogStore,
        *,
        max_rounds: int = 20,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._store = store
        self._max_rounds = max_rounds
        self._batch_size = batch_size
        self.last_outcome: PushOutcome | None = None

    # ------------------------------------------------------------------ 5.1

    def push_pending(self, transport: SyncTransport, batch_id: str) -> PushOutcome:
        """把未同步的 oplog 全部推上去。

        循环直到没有待发记录或达到轮次上限：
        缺口被补齐后需要重新取数，因为服务端要求的 `expected_seq`
        可能对应一条更早的记录。
        """

        outcome = PushOutcome()

        for round_index in range(self._max_rounds):
            entries = self._store.pending(batch_id, limit=self._batch_size)
            if not entries:
                break

            outcome.rounds = round_index + 1
            envelopes = [transport.next_envelope([_payload(entry) for entry in entries])]
            envelope = envelopes[0]

            try:
                result = transport.send(envelopes)
            except TransportError:
                # 通道故障：不进"已同步"，保留在队列里等下次重连
                outcome.channel_errors += 1
                break

            self._absorb(outcome, result, entries)

            if result.rejected:
                # 业务拒绝不可重试。**整批标记为已同步**：
                # 同一条信封里的操作要么已被应用、要么已被审计拒绝，两者都不需要再发。
                # 只标记被拒的那几条会让已成功的那些每轮重发一次、并在下一轮被判重复，
                # 队列永远清不空（这个坑踩过）。
                self._store.mark_synced([item.op_id for item in entries])
                continue

            if result.gap_detected:
                outcome.gap_detected = True
                outcome.expected_seq = result.expected_seq
                # 服务端要求从缺口补发：不标记任何记录，下一轮按 HLC 顺序重取
                continue

            # 注意：`accepted` / `duplicate` 里装的是**通道序号**，不是操作 id。
            # 要标记的是本次发出去的那些 oplog 记录。
            if envelope.seq in set(result.accepted) | set(result.duplicate):
                self._store.mark_synced([item.op_id for item in entries])

            if envelope.seq not in set(result.accepted) | set(result.duplicate):
                # 服务端既没接受也没拒绝，说明有无进展的异常情况，避免死循环
                break

        self.last_outcome = outcome
        return outcome

    def _absorb(
        self, outcome: PushOutcome, result: SendResult, entries: list[OplogEntry]
    ) -> None:
        outcome.sent += len(entries)
        outcome.accepted += len(result.accepted)
        outcome.duplicate += len(result.duplicate)
        for item in result.rejected:
            outcome.rejected.append(item.to_dict())

    # ------------------------------------------------------------------ 5.3

    def verify_digest(
        self, transport: SyncTransport, batch, *, batch_key: str = ""
    ) -> VerifyOutcome:
        """把本地摘要发给服务端比对。

        服务端在 `hello_ack` 里已经带回摘要，但这里采用**主动请求**的方式：
        摘要校验可能发生在同步之后的任意时刻（例如定时巡检），
        不能只依赖连接建立那一刻的数据。
        """

        local = digest_of_batch(batch)

        try:
            result = transport.send(
                [
                    transport.next_envelope(
                        [
                            {
                                "code": "__digest__",
                                "packLayer": 0,
                                "batchId": batch_key or batch.batch_no,
                                "digest": local.to_dict(),
                            }
                        ]
                    )
                ]
            )
        except TransportError:
            return VerifyOutcome(
                matched=False,
                local=local,
                remote=SyncDigest(),
                differences=["通道不可用，无法校验"],
                needs_full_pull=False,
            )

        remote = _extract_digest(result) or SyncDigest()
        matched, differences = compare(local, remote)
        return VerifyOutcome(
            matched=matched,
            local=local,
            remote=remote,
            differences=differences,
            # 不一致时不猜测原因，直接要求全量拉取 —— 猜错会掩盖真实的数据问题
            needs_full_pull=not matched,
        )

    def verify_pair(self, local: SyncDigest, remote: SyncDigest) -> VerifyOutcome:
        """纯摘要比对，不经过通道。用于服务端自身的一致性检查与测试。"""

        matched, differences = compare(local, remote)
        return VerifyOutcome(
            matched=matched,
            local=local,
            remote=remote,
            differences=differences,
            needs_full_pull=not matched,
        )


def _payload(entry: OplogEntry) -> dict[str, object]:
    """把 oplog 记录转成走线上的 `op`。

    线上格式比 oplog 记录薄：服务端的仲裁只需要条码与层级，
    完整 oplog 字段留给二期做操作回放与审计关联。
    """

    layer = {"box": 3, "can": 2, "particle": 1}.get(entry.entity, 0)
    code = entry.entity_id
    if isinstance(entry.new_value, dict) and entry.new_value.get("code"):
        code = str(entry.new_value["code"])
    return {
        "code": code,
        "packLayer": layer,
        "batchId": entry.batch_id,
        "opId": entry.op_id,
        "hlc": entry.hlc,
        "deviceId": entry.device_id,
        "userId": entry.user_id,
        "timestamp": entry.timestamp,
        "entity": entry.entity,
        "action": entry.action,
    }


def _extract_digest(result: SendResult) -> SyncDigest | None:
    """从服务端返回里取摘要。当前假实现把它放在 `accepted` 之外的字段上。"""

    payload = getattr(result, "digest", None)
    if isinstance(payload, dict):
        return SyncDigest.from_dict(payload)
    return None
