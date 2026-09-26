"""手机拍照上传 API。

手机端把拍到的照片直接传上来，服务端用与 PC 侧摄像头**同一条**识别管线处理；
带了批次号就把结果交给同一个状态机，所以"手机拍到的码"和"电脑拍到的码"
走完全相同的拦截与入格规则。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ...repositories.batch_repository import BatchRepository
from ...services.capture import CaptureRejected, recognize_upload
from ...services.recognition import DEFAULT_MAX_WIDTH
from ...services.scan_service import ScanService
from ..deps import get_batch_repository, get_scan_service
from ..errors import ValidationFailedError

router = APIRouter(prefix="/capture", tags=["capture"])


@router.post("/upload", summary="上传一张照片并识别（可绑定批次直接入格）")
async def upload(
    photo: UploadFile = File(..., description="手机拍到的照片（JPEG/PNG）"),
    # 表单字段名与其它接口保持同一套 camelCase 命名
    batch_id: str = Form("", alias="batchId", description="绑定批次后识别结果直接进入该批次的扫码状态机"),
    max_width: int = Form(
        DEFAULT_MAX_WIDTH, alias="maxWidth", description="识别前把长边缩到该值（默认 1920）"
    ),
    repository: BatchRepository = Depends(get_batch_repository),
    scan_service: ScanService = Depends(get_scan_service),
) -> dict[str, object]:
    data = await photo.read()
    try:
        result = recognize_upload(
            data,
            filename=photo.filename or "",
            repository=repository,
            scan_service=scan_service,
            batch_id=batch_id.strip(),
            max_width=max_width or DEFAULT_MAX_WIDTH,
        )
    except CaptureRejected as exc:
        raise ValidationFailedError(
            exc.message,
            detail={"reason": exc.reason, "hint": exc.hint, "filename": photo.filename or ""},
        ) from exc

    return {"filename": photo.filename or "", "capture": result.to_dict()}
