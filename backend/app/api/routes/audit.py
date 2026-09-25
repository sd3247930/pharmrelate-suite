from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...repositories.audit_repository import AuditRepository
from ..deps import get_audit_repository

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", summary="审计日志（不可删除，仅追加）")
def list_audit(
    batch_id: str | None = Query(default=None, description="按批次过滤"),
    action: str | None = Query(default=None, description="按动作过滤"),
    limit: int = Query(default=100, ge=1, le=1000),
    repository: AuditRepository = Depends(get_audit_repository),
) -> dict[str, object]:
    entries = repository.list(entity_id=batch_id, action=action, limit=limit)
    return {
        "items": [entry.to_dict() for entry in entries],
        "total": len(entries),
        "availableActions": ["scan", "scan_box", "scan_can", "scan_conflict", "scan_alarm", "rescan", "next_can", "early_end_requested"],
    }
