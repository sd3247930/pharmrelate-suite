"""批次 CRUD（阶段 1 骨架）。

持久化目前是进程内内存实现，重启即丢；SQLite 在阶段 2 接入。
接口契约、状态命名、重复批号的三选一语义现在就按 V1.1 固定下来。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...domain.validation import has_blocking_issue, validate_batch
from ...repositories.batch_repository import (
    BATCH_STATUSES,
    READONLY_STATUSES,
    STATUS_DRAFT,
    BatchRecord,
    BatchRepository,
)
from ...schemas.batch import BatchPayload
from ..deps import get_batch_repository
from ..errors import ConflictError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/batches", tags=["batches"])


def _serialize(record: BatchRecord, *, include_data: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": record.id,
        "status": record.status,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "revision": record.revision,
        "batchNo": record.batch.batch_no,
        "madeDate": record.batch.made_date,
        "validateDate": record.batch.validate_date,
        "canCount": record.batch.can_count,
        "actualParticleTotal": record.batch.actual_particle_total,
        "plannedParticleTotal": record.batch.planned_particle_total,
    }
    if include_data:
        payload["data"] = {
            "batchNo": record.batch.batch_no,
            "madeDate": record.batch.made_date,
            "validateDate": record.batch.validate_date,
            "box": {
                "code": record.batch.box.code,
                "cans": [
                    {
                        "index": can.index,
                        "code": can.code,
                        "plannedParticleCount": can.planned_particle_count,
                        "particles": list(can.particles),
                    }
                    for can in record.batch.box.cans
                ],
            },
        }
    return payload


@router.get("", summary="批次列表")
def list_batches(repository: BatchRepository = Depends(get_batch_repository)) -> dict[str, object]:
    records = repository.list()
    return {
        "items": [_serialize(record) for record in records],
        "total": len(records),
        "statuses": list(BATCH_STATUSES),
    }


@router.get("/{batch_id}", summary="批次详情")
def get_batch(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})
    return _serialize(record, include_data=True)


@router.post("", status_code=201, summary="创建批次")
def create_batch(
    payload: BatchPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    batch = payload.to_domain()

    # V1.1 8.4：batchNo 唯一。此处不直接报错挡死用户，而是给出三选一。
    existing = repository.find_by_batch_no(batch.batch_no)
    if existing is not None:
        raise ConflictError(
            f"批号 {batch.batch_no} 已存在。",
            detail={
                "reason": "BATCH_NO_EXISTS",
                "existing": {
                    "id": existing.id,
                    "batchNo": existing.batch.batch_no,
                    "status": existing.status,
                    "updatedAt": existing.updated_at,
                },
                "options": [
                    {"action": "open_existing", "label": "打开已有批次"},
                    {"action": "create_new_version", "label": f"创建新版本 {batch.batch_no}-V2"},
                    {"action": "cancel", "label": "取消并返回修改"},
                ],
            },
        )

    issues = validate_batch(batch)
    if has_blocking_issue(issues):
        raise ValidationFailedError(
            "批次数据校验未通过。",
            detail={"issues": [issue.to_dict() for issue in issues]},
        )

    record = repository.create(batch, status=STATUS_DRAFT)
    return _serialize(record, include_data=True)


@router.put("/{batch_id}", summary="更新批次")
def update_batch(
    batch_id: str,
    payload: BatchPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})

    # 阶段 2 再按状态机细化；此处先拦住已锁定/已作废。
    if record.status in READONLY_STATUSES:
        raise ConflictError(
            f"批次当前状态为 {record.status}，不允许修改。",
            detail={"batchId": batch_id, "status": record.status},
        )

    batch = payload.to_domain()
    issues = validate_batch(batch)
    if has_blocking_issue(issues):
        raise ValidationFailedError(
            "批次数据校验未通过。",
            detail={"issues": [issue.to_dict() for issue in issues]},
        )

    updated = repository.update(batch_id, batch)
    assert updated is not None  # 上一行已确认存在
    return _serialize(updated, include_data=True)
