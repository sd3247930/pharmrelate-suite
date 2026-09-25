"""内存批次仓储。

保留它是因为有一批测试只关心状态机与路由行为，不需要真的落库；
生产默认使用 `SqliteBatchRepository`。
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from ..domain.batch_state import STATUS_DRAFT
from ..domain.models import Batch, CanCode, EarlyEnd
from .batch_repository import BatchRecord


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryBatchRepository:
    """进程内实现。仅用于测试，重启即丢。"""

    def __init__(self) -> None:
        self._records: dict[str, BatchRecord] = {}
        self._lock = threading.Lock()

    def list(self, *, status: str | None = None, search: str | None = None) -> list[BatchRecord]:
        with self._lock:
            records = [record for record in self._records.values() if not record.deleted]
        if status:
            records = [record for record in records if record.status == status]
        if search:
            records = [record for record in records if search in record.batch.batch_no]
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def get(self, batch_id: str) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
        if record is None or record.deleted:
            return None
        return record

    def find_by_batch_no(self, batch_no: str) -> BatchRecord | None:
        with self._lock:
            for record in self._records.values():
                if record.batch.batch_no == batch_no and not record.deleted:
                    return record
        return None

    def count(self) -> int:
        with self._lock:
            return sum(1 for record in self._records.values() if not record.deleted)

    def next_version_no(self, base_batch_no: str) -> str:
        with self._lock:
            existing = {
                record.batch.batch_no
                for record in self._records.values()
                if not record.deleted
            }
        version = 2
        while f"{base_batch_no}-V{version}" in existing:
            version += 1
        return f"{base_batch_no}-V{version}"

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
            if record is None or record.deleted:
                return None
            record.batch = batch
            record.revision += 1
            record.updated_at = _now()
            return record

    def set_status(self, batch_id: str, status: str) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None or record.deleted:
                return None
            record.status = status
            record.revision += 1
            record.updated_at = _now()
            return record

    def set_early_end(self, batch_id: str, early_end: EarlyEnd | None) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None or record.deleted:
                return None
            record.batch.early_end = early_end
            record.revision += 1
            record.updated_at = _now()
            return record

    # ------------------------------------------------------- 扫码增量写入
    # 与 SQLite 实现保持同一协议，便于测试里替换而不改调用方。

    def _touch(self, record: BatchRecord) -> BatchRecord:
        record.revision += 1
        record.updated_at = _now()
        return record

    def set_box_code(self, batch_id: str, code: str) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None or record.deleted:
                return None
            record.batch.box.code = code
            return self._touch(record)

    def add_can(self, batch_id: str, code: str, planned_particle_count: int) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None or record.deleted:
                return None
            record.batch.box.cans.append(
                CanCode(
                    index=len(record.batch.box.cans) + 1,
                    code=code,
                    planned_particle_count=planned_particle_count,
                )
            )
            return self._touch(record)

    def append_particles(
        self, batch_id: str, can_code: str, codes: list[str]
    ) -> BatchRecord | None:
        with self._lock:
            record = self._records.get(batch_id)
            if record is None or record.deleted:
                return None
            can = next(
                (item for item in record.batch.box.cans if item.code == can_code), None
            )
            if can is None:
                raise ValueError(f"批次内找不到罐 {can_code}")
            can.particles.extend(codes)
            return self._touch(record)
