"""导入 API：外部的关联关系 XML → 本系统批次。

与导出侧共用同一个解析器与固定参数常量，保证"导入 → 导出"能回到原字节。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...repositories.batch_repository import BatchRepository
from ...schemas.import_xml import XmlImportPayload
from ...services.xml_import import XmlImportConflict, XmlImportRejected, import_batch
from ..deps import get_batch_repository
from ..errors import ConflictError, ValidationFailedError

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/xml", summary="导入一期格式的关联关系 XML（新建批次）")
def import_xml(
    payload: XmlImportPayload,
    repository: BatchRepository = Depends(get_batch_repository),
) -> dict[str, object]:
    try:
        record, summary = import_batch(
            payload.xml.encode("utf-8"),
            source_name=payload.source_name,
            repository=repository,
            force_new_version=payload.force_new_version,
        )
    except XmlImportRejected as exc:
        # 解析与结构校验都属于"请求内容不合法"，用 422 并带问题清单，
        # 前端能直接渲染出"哪一行、哪个字段、为什么"
        raise ValidationFailedError(
            exc.message, detail={"reason": exc.reason, "issues": exc.issues}
        ) from exc
    except XmlImportConflict as exc:
        raise ConflictError(exc.message, detail=exc.detail) from exc

    # 只回 batchId + 摘要：批次详情由前端走 GET /api/batches/{id} 取，
    # 避免把序列化契约复制成两份
    return {"batchId": record.id, "summary": summary.to_dict()}
