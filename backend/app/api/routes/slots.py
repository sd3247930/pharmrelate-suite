"""槽位编辑与撤销/重做（阶段 3.4）。

所有编辑都要求批次处于可编辑状态：只读状态（已导出及之后）一律拒绝，
前端的置灰只是体验，真正的门在这里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...domain import batch_state as state
from ...repositories.batch_repository import BatchRepository
from ...schemas.slot import (
    DeleteParticlePayload,
    ReplaceParticlePayload,
    RescanBoxPayload,
    RescanCanPayload,
)
from ...services.scan_history import ScanHistoryService, SlotEditError
from ...schemas.batch import serialize_batch_data
from ..deps import get_batch_repository, get_scan_history
from ..errors import ConflictError, NotFoundError

router = APIRouter(prefix="/batches", tags=["slots"])


def _load(batch_id: str, repository: BatchRepository):
    record = repository.get(batch_id)
    if record is None:
        raise NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})
    return record


def _assert_editable(record) -> None:
    if not state.is_editable(record.status):
        raise ConflictError(
            f"批次当前状态为「{state.label_of(record.status)}」，业务数据只读。",
            detail={
                "reason": "READONLY",
                "status": record.status,
                "statusLabel": state.label_of(record.status),
            },
        )


def _guard(action):
    """把编辑拒绝与"没有可撤销的操作"转成 409，并带上原因。"""

    def wrapper(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except SlotEditError as exc:
            raise ConflictError(str(exc), detail={"reason": "SLOT_EDIT_REJECTED", **exc.detail}) from exc

    return wrapper


def _payload(batch_id: str, repository: BatchRepository, history: ScanHistoryService) -> dict:
    record = repository.get(batch_id)
    assert record is not None
    return {
        "data": serialize_batch_data(record.batch),
        "history": history.history(batch_id).to_dict(),
        "canCount": record.batch.can_count,
        "actualParticleTotal": record.batch.actual_particle_total,
    }


@router.post("/{batch_id}/slots/replace", summary="替换粒子槽位条码")
def replace(
    batch_id: str,
    body: ReplaceParticlePayload,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.replace_particle)(batch_id, body.code, body.new_code)
    return _payload(batch_id, repository, history)


@router.post("/{batch_id}/slots/delete", summary="删除粒子槽位条码")
def delete(
    batch_id: str,
    body: DeleteParticlePayload,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.delete_particle)(batch_id, body.code)
    return _payload(batch_id, repository, history)


@router.post("/{batch_id}/cans/{can_index}/clear", summary="清空当前罐的粒子")
def clear_can(
    batch_id: str,
    can_index: int,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.clear_can)(batch_id, can_index)
    return _payload(batch_id, repository, history)


@router.post("/{batch_id}/cans/{can_index}/rescan", summary="重拍罐号（清除该罐粒子）")
def rescan_can(
    batch_id: str,
    can_index: int,
    body: RescanCanPayload,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.rescan_can)(batch_id, can_index, body.new_can_code)
    return _payload(batch_id, repository, history)


@router.post("/{batch_id}/box/rescan", summary="重拍箱号（清空全部罐与粒子）")
def rescan_box(
    batch_id: str,
    body: RescanBoxPayload,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.rescan_box)(batch_id, body.new_box_code)
    return _payload(batch_id, repository, history)


@router.get("/{batch_id}/history", summary="撤销/重做栈状态")
def history_state(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _load(batch_id, repository)
    return history.history(batch_id).to_dict()


@router.post("/{batch_id}/undo", summary="撤销")
def undo(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.undo)(batch_id)
    return _payload(batch_id, repository, history)


@router.post("/{batch_id}/redo", summary="重做")
def redo(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    history: ScanHistoryService = Depends(get_scan_history),
) -> dict[str, object]:
    _assert_editable(_load(batch_id, repository))
    _guard(history.redo)(batch_id)
    return _payload(batch_id, repository, history)
