from __future__ import annotations

from pydantic import Field

from .base import CamelModel


class CameraStartPayload(CamelModel):
    kind: str = "opencv"
    """opencv（真实摄像头）或 test_image（测试图片）。"""

    device_index: int = Field(default=0, ge=0, le=9)
    images: list[str] = Field(default_factory=list)
    """测试源使用的图片路径。"""

    batch_id: str = ""
    """绑定批次后，识别结果直接进入该批次的扫码状态机。"""

    max_width: int = Field(default=0, ge=0, le=8192)
    """0 表示使用识别管线默认值（1920）。"""

    recognize_interval_ms: int = Field(default=300, ge=50, le=5000)
