"""扫码采集 API。

前端只做两件事：把"识别到了什么"交给 `POST /frame`，把"操作员点了什么"
交给 `confirm` / `rescan` / `next-can`。状态一律由服务端返回，前端不自行推进。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...domain import scan_state as st
from ...repositories.batch_repository import BatchRepository
from ...schemas.scan import FramePayload, NextCanPayload
from ...services.scan_service import ScanService
from ..deps import get_batch_repository, get_scan_service
from ..errors import ConflictError, NotFoundError

router = APIRouter(prefix="/scan", tags=["scan"])


def _load(batch_id: str, repository: BatchRepository):
    record = repository.get(batch_id)
    if record is None:
        raise NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})
    return record


def _guarded(action):
    """把状态机的拒绝转成 409，并带上当前状态，便于前端给出恢复路径。"""

    def wrapper(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except st.ScanError as exc:
            raise ConflictError(
                str(exc),
                detail={
                    "reason": st.EVENT_WRONG_STATE,
                    "status": exc.status,
                    "statusLabel": st.label_of(exc.status),
                    "action": exc.action,
                },
            ) from exc

    return wrapper


@router.get("/{batch_id}/session", summary="扫码会话快照")
def session(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    return service.snapshot(record).to_dict()


@router.post("/{batch_id}/reset", summary="重置会话（不透支库内数据）")
def reset(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    service.reset_session(batch_id)
    return service.snapshot(record).to_dict()


@router.post("/{batch_id}/frame", summary="提交一帧识别结果")
def frame(
    batch_id: str,
    payload: FramePayload,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    snapshot = service.apply_frame(
        record,
        codes=payload.codes,
        conflicts=payload.conflicts,
        engine_version=payload.engine_version,
        variants=payload.variants,
    )
    return snapshot.to_dict()


@router.post("/{batch_id}/confirm", summary="确认待确认的箱号 / 罐号 / 本罐满额")
def confirm(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    return _guarded(service.confirm)(record).to_dict()


@router.post("/{batch_id}/rescan", summary="重拍")
def rescan(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    return _guarded(service.rescan)(record).to_dict()


@router.post("/{batch_id}/next-can", summary="下一罐询问的答复")
def next_can(
    batch_id: str,
    payload: NextCanPayload,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    record = _load(batch_id, repository)
    return _guarded(service.next_can)(record, proceed=payload.proceed).to_dict()
