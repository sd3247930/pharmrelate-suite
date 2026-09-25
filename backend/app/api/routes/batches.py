"""批次 CRUD、生命周期流转与「提前结束」。

设计原则：
    - 状态流转的唯一权威在后端；前端只读状态、只发流转请求
    - 非法流转一律 409 并说明允许的目标状态，不静默通过
    - 只读状态下任何写入都被拒绝（前端置灰只是体验，不是权限）
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from ...domain import batch_state as state
from ...domain.models import Batch, EarlyEnd
from ...domain.validation import has_blocking_issue, validate_batch
from ...repositories.batch_repository import BatchRecord, BatchRepository
from ...schemas.batch import (
    BatchCreatePayload,
    BatchPayload,
    BatchStatusPayload,
    EarlyEndPayload,
    serialize_batch_data,
)
from ..deps import get_batch_repository
from ..errors import ConflictError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/batches", tags=["batches"])


def _not_found(batch_id: str) -> NotFoundError:
    return NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})


def _serialize(record: BatchRecord, *, include_data: bool = False) -> dict[str, object]:
    descriptor = state.describe(record.status)
    payload: dict[str, object] = {
        "id": record.id,
        "status": record.status,
        "statusLabel": descriptor.label,
        "editable": descriptor.editable,
        "terminal": descriptor.terminal,
        "allowedTransitions": list(descriptor.allowed),
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "revision": record.revision,
        "batchNo": record.batch.batch_no,
        "madeDate": record.batch.made_date,
        "validateDate": record.batch.validate_date,
        "canCount": record.batch.can_count,
        "actualParticleTotal": record.batch.actual_particle_total,
        "plannedParticleTotal": record.batch.planned_particle_total,
        "earlyEnd": _serialize_early_end(record.batch.early_end),
    }
    if include_data:
        payload["data"] = serialize_batch_data(record.batch)
    return payload


def _serialize_early_end(early_end: EarlyEnd | None) -> dict[str, object] | None:
    if early_end is None:
        return None
    return {
        "reason": early_end.reason,
        "operator": early_end.operator,
        "note": early_end.note,
        "at": early_end.at,
        "actualCanCount": early_end.actual_can_count,
        "actualParticleCount": early_end.actual_particle_count,
    }


def _assert_editable(record: BatchRecord) -> None:
    if not state.is_editable(record.status):
        raise ConflictError(
            f"批次当前状态为「{state.label_of(record.status)}」，业务数据只读。"
            "如需修改，请先由管理员解锁。",
            detail={
                "batchId": record.id,
                "status": record.status,
                "statusLabel": state.label_of(record.status),
                "hint": "exported 之后默认只读；解锁需管理员并填写原因。",
            },
        )


def _validate_or_raise(batch: Batch) -> None:
    issues = validate_batch(batch)
    if has_blocking_issue(issues):
        raise ValidationFailedError(
            "批次数据校验未通过。",
            detail={"issues": [issue.to_dict() for issue in issues]},
        )


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------


@router.get("/statuses", summary="生命周期状态与流转规则")
def list_statuses() -> dict[str, object]:
    return {
        "items": [
            {
                "status": descriptor.status,
                "label": descriptor.label,
                "editable": descriptor.editable,
                "terminal": descriptor.terminal,
                "allowed": list(descriptor.allowed),
                "allowedLabels": [
                    state.label_of(item) for item in state.allowed_transitions(status)
                ],
            }
            for status in state.BATCH_STATUSES
            for descriptor in (state.describe(status),)
        ]
    }


# ---------------------------------------------------------------------------
# 列表与详情
# ---------------------------------------------------------------------------


@router.get("", summary="批次列表")
def list_batches(
    status: str | None = Query(default=None, description="按状态筛选"),
    search: str | None = Query(default=None, description="按批号模糊搜索"),
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    records = repository.list(status=status, search=search)
    return {
        "items": [_serialize(record) for record in records],
        "total": len(records),
        "statuses": list(state.BATCH_STATUSES),
    }


@router.get("/{batch_id}", summary="批次详情")
def get_batch(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)
    return _serialize(record, include_data=True)


@router.get("/{batch_id}/transitions", summary="该批次当前允许的流转")
def get_transitions(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)

    descriptor = state.describe(record.status)
    return {
        "status": record.status,
        "statusLabel": descriptor.label,
        "editable": descriptor.editable,
        "terminal": descriptor.terminal,
        "options": [
            {
                "target": target,
                "label": state.label_of(target),
                "requiresAdmin": state.requires_admin(record.status, target),
                "requiresReason": (
                    state.requires_admin(record.status, target) or target == state.STATUS_VOID
                ),
            }
            for target in descriptor.allowed
        ],
    }


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------


@router.post("", status_code=201, summary="创建批次")
def create_batch(
    payload: BatchCreatePayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    batch = payload.to_domain()
    _validate_or_raise(batch)

    existing = repository.find_by_batch_no(batch.batch_no)
    if existing is not None and not payload.force_new_version:
        # V1.1 8.4：batchNo 唯一。不直接报错挡死用户，而是给出三选一。
        suggested = repository.next_version_no(batch.batch_no)
        raise ConflictError(
            f"批号 {batch.batch_no} 已存在。",
            detail={
                "reason": "BATCH_NO_EXISTS",
                "existing": {
                    "id": existing.id,
                    "batchNo": existing.batch.batch_no,
                    "status": existing.status,
                    "statusLabel": state.label_of(existing.status),
                    "updatedAt": existing.updated_at,
                    "canCount": existing.batch.can_count,
                    "actualParticleTotal": existing.batch.actual_particle_total,
                },
                "suggestedBatchNo": suggested,
                "options": [
                    {"action": "open_existing", "label": "打开已有批次"},
                    {"action": "create_new_version", "label": f"创建新版本 {suggested}"},
                    {"action": "cancel", "label": "取消并返回修改"},
                ],
            },
        )

    if payload.force_new_version and existing is not None:
        # 用户已明确选择「创建新版本」，此时才允许改写批号
        batch.batch_no = repository.next_version_no(batch.batch_no)
        if repository.find_by_batch_no(batch.batch_no) is not None:  # pragma: no cover
            raise ConflictError(
                f"新版本批号 {batch.batch_no} 已被占用，请重试。",
                detail={"reason": "BATCH_NO_EXISTS"},
            )

    record = repository.create(batch, status=state.STATUS_DRAFT)
    return _serialize(record, include_data=True)


# ---------------------------------------------------------------------------
# 更新
# ---------------------------------------------------------------------------


@router.put("/{batch_id}", summary="更新批次业务数据")
def update_batch(
    batch_id: str,
    payload: BatchPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)

    _assert_editable(record)

    batch = payload.to_domain()

    # 改批号也要守住唯一性，但行为与创建不同：这里是明确的编辑操作，直接拒绝。
    duplicate = repository.find_by_batch_no(batch.batch_no)
    if duplicate is not None and duplicate.id != batch_id:
        raise ConflictError(
            f"批号 {batch.batch_no} 已被批次 {duplicate.id[:8]} 使用。",
            detail={"reason": "BATCH_NO_EXISTS", "existingId": duplicate.id},
        )

    _validate_or_raise(batch)
    batch.early_end = record.batch.early_end  # 提前结束记录只能由专用接口修改

    updated = repository.update(batch_id, batch)
    if updated is None:  # pragma: no cover - 上面已确认存在
        raise _not_found(batch_id)
    return _serialize(updated, include_data=True)


# ---------------------------------------------------------------------------
# 生命周期流转
# ---------------------------------------------------------------------------


@router.post("/{batch_id}/status", summary="流转批次状态")
def change_status(
    batch_id: str,
    payload: BatchStatusPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)

    try:
        state.assert_transition(record.status, payload.target)
    except state.IllegalTransitionError as exc:
        raise ConflictError(
            str(exc),
            detail={
                "reason": "ILLEGAL_TRANSITION",
                "current": exc.current,
                "currentLabel": state.label_of(exc.current),
                "target": exc.target,
                "targetLabel": state.label_of(exc.target),
                "allowed": sorted(exc.allowed, key=lambda item: state.STATUS_ORDER[item]),
                "allowedLabels": [
                    state.label_of(item)
                    for item in sorted(exc.allowed, key=lambda item: state.STATUS_ORDER[item])
                ],
            },
        ) from exc

    if state.requires_admin(record.status, payload.target) and not (payload.reason or "").strip():
        raise ValidationFailedError(
            "该流转需要管理员权限并填写原因。",
            detail={
                "reason": "REASON_REQUIRED",
                "target": payload.target,
                "targetLabel": state.label_of(payload.target),
            },
        )

    updated = repository.set_status(batch_id, payload.target)
    if updated is None:  # pragma: no cover
        raise _not_found(batch_id)

    return {
        "batch": _serialize(updated, include_data=True),
        "transition": {
            "from": record.status,
            "fromLabel": state.label_of(record.status),
            "to": updated.status,
            "toLabel": state.label_of(updated.status),
            "reason": payload.reason or "",
            "operator": payload.operator or "",
        },
    }


# ---------------------------------------------------------------------------
# 提前结束
# ---------------------------------------------------------------------------


@router.post("/{batch_id}/early-end", summary="登记提前结束（含签名）")
def register_early_end(
    batch_id: str,
    payload: EarlyEndPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)

    _assert_editable(record)

    if not payload.reason.strip():
        raise ValidationFailedError(
            "提前结束必须填写原因。", detail={"field": "reason"}
        )
    if not payload.operator.strip():
        raise ValidationFailedError(
            "提前结束必须选择操作人。", detail={"field": "operator"}
        )

    early_end = EarlyEnd(
        reason=payload.reason.strip(),
        operator=payload.operator.strip(),
        note=payload.note.strip(),
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        # 实际数量由服务端按当前库内数据填写，不接受前端传入，避免被改数
        actual_can_count=record.batch.can_count,
        actual_particle_count=record.batch.actual_particle_total,
    )

    updated = repository.set_early_end(batch_id, early_end)
    if updated is None:  # pragma: no cover
        raise _not_found(batch_id)

    return {
        "batch": _serialize(updated, include_data=True),
        "earlyEnd": _serialize_early_end(early_end),
        "missingParticles": max(
            0, updated.batch.planned_particle_total - updated.batch.actual_particle_total
        ),
    }


@router.delete("/{batch_id}/early-end", summary="撤销提前结束登记")
def clear_early_end(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise _not_found(batch_id)
    _assert_editable(record)

    updated = repository.set_early_end(batch_id, None)
    if updated is None:  # pragma: no cover
        raise _not_found(batch_id)
    return {"batch": _serialize(updated, include_data=True), "earlyEnd": None}
