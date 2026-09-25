"""导出 API（阶段 4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from ...services.export_service import ExportBlockedError, ExportService
from ...schemas.export import ExportPayload
from ..deps import get_export_service
from ..errors import ConflictError, NotFoundError

router = APIRouter(tags=["export"])


def _guard(action):
    def wrapper(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except ExportBlockedError as exc:
            # 内层更具体的原因优先（如 STATUS_NOT_VERIFIED / REVIEW_BLOCKED），
            # 没有具体原因时才退回通用码
            detail = {"reason": "EXPORT_BLOCKED", **exc.detail}
            raise ConflictError(str(exc), detail=detail) from exc

    return wrapper


@router.post("/batches/{batch_id}/export", summary="导出 XML / HTML")
def export(
    batch_id: str,
    payload: ExportPayload,
    service: ExportService = Depends(get_export_service),
) -> dict[str, object]:
    # 不在这里补默认值：字段缺失时 schema 已给 ["xml"]，
    # 显式传空列表说明调用方搞错了，应当拒绝而不是悄悄改成 XML
    artifacts = _guard(service.export)(batch_id, payload.kinds, operator=payload.operator)
    return {
        "items": [item.to_dict() for item in artifacts],
        "exportKind": artifacts[0].export_kind if artifacts else "normal",
    }


@router.get("/batches/{batch_id}/exports", summary="导出记录")
def history(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    service: ExportService = Depends(get_export_service),
) -> dict[str, object]:
    items = service.history(batch_id, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/exports/{record_id}/download", summary="下载导出文件")
def download(
    record_id: str,
    service: ExportService = Depends(get_export_service),
) -> Response:
    artifact = service.artifact(record_id)
    if artifact is None:
        # 记录存在但内容已不可得（进程重启），与"记录不存在"要分开告诉用户
        if service.record_exists(record_id):
            raise NotFoundError(
                "该导出记录的内容已不可用（应用重启后未持久化文件本体）。"
                "请重新导出。",
                detail={"recordId": record_id, "reason": "CONTENT_UNAVAILABLE"},
            )
        raise NotFoundError(
            f"导出记录 {record_id} 不存在。", detail={"recordId": record_id}
        )

    media = "application/xml" if artifact.kind == "xml" else "text/html"
    return Response(
        content=artifact.content,
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-SHA256": artifact.sha256,
        },
    )
