"""批次仓储协议 + 内存实现（阶段 1 占位）。"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from ..domain.models import Batch

# 批次生命周期（V1.1 第 8 章）。阶段 1 只用到 draft / collecting，
# 其余状态先占位，保证状态机命名从现在起就是统一的。
STATUS_DRAFT = "draft"
STATUS_COLLECTING = "collecting"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_VERIFIED = "verified"
STATUS_EXPORTED = "exported"
STATUS_LOCKED = "locked"
STATUS_ARCHIVED = "archived"
STATUS_VOID = "void"

BATCH_STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_COLLECTING,
    STATUS_PENDING_REVIEW,
    STATUS_VERIFIED,
    STATUS_EXPORTED,
    STATUS_LOCKED,
    STATUS_ARCHIVED,
    STATUS_VOID,
)

READONLY_STATUSES: frozenset[str] = frozenset(
    {STATUS_LOCKED, STATUS_ARCHIVED, STATUS_VOID}
)
"""这些状态下禁止任何业务数据修改（V1.1 8.5）。"""


@dataclass(slots=True)
class BatchRecord:
    """批次记录：领域数据 + 生命周期元数据。"""

    id: str
    status: str
    created_at: str
    updated_at: str
    batch: Batch
    # 二期 SyncMeta 占位，现在就把字段名固定下来
    revision: int = 1
    hlc: str = ""
    updated_by: str = "local-user"
    device_id: str = "windows-main"
    deleted: bool = False
    extra: dict[str, object] = field(default_factory=dict)


class BatchRepository(Protocol):
    def list(self) -> list[BatchRecord]: ...

    def get(self, batch_id: str) -> BatchRecord | None: ...

    def find_by_batch_no(self, batch_no: str) -> BatchRecord | None: ...

    def create(self, batch: Batch, status: str) -> BatchRecord: ...

    def update(self, batch_id: str, batch: Batch) -> BatchRecord | None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryBatchRepository:
    """进程内实现。仅用于阶段 1 打通接口，重启即丢。"""

    def __init__(self) -> None:
        self._records: dict[str, BatchRecord] = {}
        self._lock = threading.Lock()

    def list(self) -> list[BatchRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda record: record.created_at, reverse=True)

    def get(self, batch_id: str) -> BatchRecord | None:
        with self._lock:
            return self._records.get(batch_id)

    def find_by_batch_no(self, batch_no: str) -> BatchRecord | None:
        with self._lock:
            for record in self._records.values():
                if record.batch.batch_no == batch_no and not record.deleted:
                    return record
        return None

    def create(self, batch: Batch, status: str = STATUS_DRAFT) -> BatchRecord:
        record = BatchRecord(
            id=str(uuid.uuid4()),
            status=status,
            created_at=_now(),
            updated_at=_now(),
            batch=batch,
        )
        with self._lock:
            self._records[record.id] = record
        return record

    def update(self, batch_id: str, batch: Batch) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None:
                return None
            record.batch = batch
            record.revision += 1
            record.updated_at = _now()
            return record


__all__ = [
    "BATCH_STATUSES",
    "READONLY_STATUSES",
    "STATUS_ARCHIVED",
    "STATUS_COLLECTING",
    "STATUS_DRAFT",
    "STATUS_EXPORTED",
    "STATUS_LOCKED",
    "STATUS_PENDING_REVIEW",
    "STATUS_VERIFIED",
    "STATUS_VOID",
    "BatchRecord",
    "BatchRepository",
    "InMemoryBatchRepository",
]
