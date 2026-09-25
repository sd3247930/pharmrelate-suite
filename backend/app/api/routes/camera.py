"""摄像头 API。

取流在服务端进行（Windows 主控机接摄像头），前端只做两件事：
看最新画面、拿最新识别结果。识别结果在绑定了批次时会直接进入扫码状态机。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from ...schemas.camera import CameraStartPayload
from ...services.camera import CameraManager
from ..deps import get_camera_manager

router = APIRouter(prefix="/camera", tags=["camera"])


@router.get("/status", summary="取流状态")
def status(manager: CameraManager = Depends(get_camera_manager)) -> dict[str, object]:
    return manager.status().to_dict()


@router.post("/start", summary="开始取流")
def start(
    payload: CameraStartPayload,
    manager: CameraManager = Depends(get_camera_manager),
) -> dict[str, object]:
    from pathlib import Path

    status = manager.start(
        kind=payload.kind,
        device_index=payload.device_index,
        images=[Path(item) for item in payload.images],
        batch_id=payload.batch_id,
        max_width=payload.max_width,
        recognize_interval_ms=payload.recognize_interval_ms,
    )
    return status.to_dict()


@router.post("/stop", summary="停止取流")
def stop(manager: CameraManager = Depends(get_camera_manager)) -> dict[str, object]:
    return manager.stop().to_dict()


@router.get("/frame.jpg", summary="最新一帧（JPEG）")
def frame(manager: CameraManager = Depends(get_camera_manager)) -> Response:
    jpeg = manager.latest_jpeg()
    if jpeg is None:
        return Response(status_code=204)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/detections", summary="最新识别结果")
def detections(manager: CameraManager = Depends(get_camera_manager)) -> dict[str, object]:
    payload = manager.latest_detection()
    return {"detection": payload}


@router.get("/devices", summary="探测可用摄像头")
def devices(
    limit: int = Query(default=5, ge=1, le=10),
    manager: CameraManager = Depends(get_camera_manager),
) -> dict[str, object]:
    return {"items": manager.list_devices(limit=limit)}
