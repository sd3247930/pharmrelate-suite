"""批次仓储协议与记录结构。

仓储挂在 `app.state` 上而不是模块级单例，否则同一进程内的多个应用实例
（尤其是测试）会共享数据、互相污染。

实现：
    sqlite_repository.SqliteBatchRepository  生产实现（默认）
    memory_repository.InMemoryBatchRepository 仅用于不关心持久化的测试
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..domain.models import Batch
from ..domain.batch_state import (
    BATCH_STATUSES,
    READONLY_STATUSES,
    STATUS_ARCHIVED,
    STATUS_COLLECTING,
    STATUS_DRAFT,
    STATUS_EXPORTED,
    STATUS_LOCKED,
    STATUS_PENDING_REVIEW,
    STATUS_VERIFIED,
    STATUS_VOID,
)


@dataclass(slots=True)
class BatchRecord:
    """批次记录：领域数据 + 生命周期元数据。"""

    id: str
    status: str
    created_at: str
    updated_at: str
    batch: Batch
    revision: int = 1
    hlc: str = ""
    updated_by: str = "local-user"
    device_id: str = "windows-main"
    deleted: bool = False
    extra: dict[str, object] = field(default_factory=dict)


class BatchRepository(Protocol):
    def list(self, *, status: str | None = None, search: str | None = None) -> list[BatchRecord]: ...

    def get(self, batch_id: str) -> BatchRecord | None: ...

    def find_by_batch_no(self, batch_no: str) -> BatchRecord | None: ...

    def create(self, batch: Batch, status: str = STATUS_DRAFT) -> BatchRecord: ...

    def update(self, batch_id: str, batch: Batch) -> BatchRecord | None: ...

    def set_status(self, batch_id: str, status: str) -> BatchRecord | None: ...

    def count(self) -> int: ...


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
]
