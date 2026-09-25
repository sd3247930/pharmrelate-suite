from __future__ import annotations

from fastapi import APIRouter, Depends

from ...repositories.batch_repository import BatchRepository
from ...services.review_service import ReviewService
from ..deps import get_batch_repository, get_review_service
from ..errors import NotFoundError

router = APIRouter(prefix="/batches", tags=["review"])


@router.get("/{batch_id}/review", summary="整体核对：计划 vs 实际 + 导出闸门")
def review(
    batch_id: str,
    repository: BatchRepository = Depends(get_batch_repository),
    service: ReviewService = Depends(get_review_service),
) -> dict[str, object]:
    record = repository.get(batch_id)
    if record is None:
        raise NotFoundError(f"批次 {batch_id} 不存在。", detail={"batchId": batch_id})
    return service.review(record).to_dict()
