"""可插拔帧源（V1.1 14 章 / 阶段 3.2.1）。

分两件事：
    - `FrameSource`：只负责"给我一帧"，不关心识别、不关心业务；
    - `CameraManager`（camera.py）：取流与识别异步跑，对外只暴露最新状态。

这样当前环境没有真实摄像头时，用 `TestImageFrameSource` 喂真实照片就能把整条
链路走通；硬件到位后换成 `OpenCVFrameSource`，架构不动，只需重新标定阈值。

与 D-013 一致：图像一律走字节解码，不用 `cv2.imread`（中文文件名会返回 None）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .recognition import DEFAULT_MAX_WIDTH, load_image

SOURCE_OPENCV = "opencv"
SOURCE_TEST_IMAGE = "test_image"
SOURCE_NONE = "none"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class Frame:
    image: Any
    """numpy 数组（BGR）。"""

    index: int
    captured_at: str
    source: str


class FrameSourceError(RuntimeError):
    """打不开或读不到帧。带上可操作的建议，而不是只抛一句失败。"""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class FrameSource(Protocol):
    """帧源接口。实现只需保证四件事：打开、关闭、读一帧、报元数据。"""

    name: str

    def open(self) -> None: ...

    def close(self) -> None: ...

    def read(self) -> Frame | None: ...

    def is_open(self) -> bool: ...

    def metadata(self) -> dict[str, object]: ...


# ---------------------------------------------------------------------------
# 真实源：OpenCV VideoCapture
# ---------------------------------------------------------------------------


class OpenCVFrameSource:
    """本机 USB 摄像头（或其他 OpenCV 可打开的采集设备）。"""

    name = SOURCE_OPENCV

    def __init__(self, device_index: int = 0, max_width: int = DEFAULT_MAX_WIDTH) -> None:
        self.device_index = device_index
        self.max_width = max_width
        self._capture: Any = None
        self._index = 0
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._lock = threading.Lock()

    def open(self) -> None:
        import cv2

        # Windows 上 CAP_DSHOW 通常比默认后端更快打开、也更少出现首帧黑屏，
        # 但不是所有设备都支持，因此失败后退回默认后端。
        attempts: list[tuple[str, int]] = []
        if hasattr(cv2, "CAP_DSHOW"):
            attempts.append(("DirectShow", cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)))
        attempts.append(("默认后端", cv2.VideoCapture(self.device_index)))

        last_error = ""
        for label, capture in attempts:
            if capture.isOpened():
                ok, _frame = capture.read()
                if ok:
                    self._capture = capture
                    self._width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                    self._height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                    self._fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                    return
                capture.release()
                last_error = f"{label}：能打开但读不到画面"
            else:
                capture.release()
                last_error = f"{label}：无法打开设备"

        raise FrameSourceError(
            f"摄像头 {self.device_index} 打开失败（{last_error}）。",
            hint="请确认设备未被其它程序占用（会议软件、相机应用），并检查系统隐私设置里的摄像头权限。",
        )

    def close(self) -> None:
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    def is_open(self) -> bool:
        return self._capture is not None and bool(self._capture.isOpened())

    def read(self) -> Frame | None:
        import cv2

        capture = self._capture
        if capture is None:
            return None

        with self._lock:
            ok, image = capture.read()
        if not ok or image is None:
            return None

        # 帧尺寸归一化：识别阈值是按 1920 上限标的，超出的先缩下来
        if self.max_width > 0 and image.shape[1] > self.max_width:
            scale = self.max_width / image.shape[1]
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        self._index += 1
        return Frame(
            image=image, index=self._index, captured_at=_now(), source=self.name
        )

    def metadata(self) -> dict[str, object]:
        return {
            "source": self.name,
            "deviceIndex": self.device_index,
            "width": self._width,
            "height": self._height,
            "fps": round(self._fps, 1),
            "maxWidth": self.max_width,
        }


# ---------------------------------------------------------------------------
# 测试源：喂真实照片（无硬件也能走通全链路）
# ---------------------------------------------------------------------------


class TestImageFrameSource:
    """把一张或多张真实照片当作摄像头帧循环吐出。

    用途是把"识别 → 状态机 → 入库"整条链路在没有摄像头的情况下验证到底。
    它不是模拟数据：喂的就是现场实拍的那张标签照片。
    """

    name = SOURCE_TEST_IMAGE

    def __init__(self, paths: list[Path], max_width: int = DEFAULT_MAX_WIDTH) -> None:
        if not paths:
            raise FrameSourceError("测试帧源至少需要一张图片。")
        self.paths = [Path(item) for item in paths]
        self.max_width = max_width
        self._images: list[Any] = []
        self._index = 0
        self._lock = threading.Lock()

    def open(self) -> None:
        import cv2

        self._images = []
        for path in self.paths:
            if not path.is_file():
                raise FrameSourceError(f"测试图片不存在：{path}")
            image = load_image(path)
            if self.max_width > 0 and image.shape[1] > self.max_width:
                scale = self.max_width / image.shape[1]
                image = cv2.resize(
                    image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                )
            self._images.append(image)
        self._index = 0

    def close(self) -> None:
        self._images = []

    def is_open(self) -> bool:
        return bool(self._images)

    def read(self) -> Frame | None:
        with self._lock:
            if not self._images:
                return None
            image = self._images[self._index % len(self._images)]
            self._index += 1
        return Frame(
            image=image, index=self._index, captured_at=_now(), source=self.name
        )

    def metadata(self) -> dict[str, object]:
        height, width = (self._images[0].shape[:2] if self._images else (0, 0))
        return {
            "source": self.name,
            "images": [item.name for item in self.paths],
            "width": width,
            "height": height,
            "fps": 0.0,
            "maxWidth": self.max_width,
        }


def create_frame_source(
    kind: str,
    *,
    device_index: int = 0,
    images: list[Path] | None = None,
    max_width: int = DEFAULT_MAX_WIDTH,
) -> FrameSource:
    """工厂：按名称建帧源。未知名称直接报错，不静默退化成空源。"""

    if kind == SOURCE_OPENCV:
        return OpenCVFrameSource(device_index=device_index, max_width=max_width)
    if kind == SOURCE_TEST_IMAGE:
        return TestImageFrameSource(images or [], max_width=max_width)
    raise FrameSourceError(
        f"未知的帧源类型 {kind!r}。",
        hint=f"可用类型：{SOURCE_OPENCV}（真实摄像头）、{SOURCE_TEST_IMAGE}（测试图片）。",
    )
