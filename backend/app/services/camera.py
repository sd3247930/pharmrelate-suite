"""摄像头管理器：取流与识别异步跑。

职责边界很清楚：
    - 取流线程按帧源自身的节奏读帧，只保留"最新一帧"（旧的直接丢，
      车间不需要回放历史帧）；
    - 识别在**同一个线程**里按节流间隔执行，不另开线程：
      识别是纯计算，多开线程只会抢 CPU，反而拖慢取流；
    - 绑定了批次时，识别结果直接交给扫码状态机，前端不必再中转一次。

节流是必要的：整张 12.6MP 照片识别要 0.25 秒，不节流会让 CPU 一直跑满。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .frame_source import (
    SOURCE_NONE,
    FrameSource,
    FrameSourceError,
    create_frame_source,
)
from .recognition import RecognitionResult, decode_frame

DEFAULT_RECOGNIZE_INTERVAL_MS = 300
"""识别节流间隔。0.25 秒级的识别耗时下，300ms 间隔刚好不堆帧。"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class CameraStatus:
    running: bool = False
    source: str = SOURCE_NONE
    batch_id: str = ""
    frames_read: int = 0
    recognitions: int = 0
    error: str = ""
    hint: str = ""
    started_at: str = ""
    last_frame_at: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "source": self.source,
            "batchId": self.batch_id,
            "framesRead": self.frames_read,
            "recognitions": self.recognitions,
            "error": self.error,
            "hint": self.hint,
            "startedAt": self.started_at,
            "lastFrameAt": self.last_frame_at,
            "metadata": self.metadata,
        }


class CameraManager:
    """一个进程内只管理一个摄像头 —— 车间就一台设备接在 Windows 主控机上。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._source: FrameSource | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._status = CameraStatus()
        self._jpeg: bytes | None = None
        self._detection: RecognitionResult | None = None
        self._detection_at = ""
        self._applied_snapshot: dict[str, object] | None = None
        self._scan_service = None
        self._recognize_interval_ms = DEFAULT_RECOGNIZE_INTERVAL_MS

    # ------------------------------------------------------------------ 控制

    def attach_scan_service(self, service: Any) -> None:
        """绑定扫码服务后，识别结果会直接进入状态机。"""

        self._scan_service = service

    def start(
        self,
        *,
        kind: str,
        device_index: int = 0,
        images: list[Path] | None = None,
        batch_id: str = "",
        max_width: int = 0,
        recognize_interval_ms: int = DEFAULT_RECOGNIZE_INTERVAL_MS,
    ) -> CameraStatus:
        self.stop()

        from .recognition import DEFAULT_MAX_WIDTH

        with self._lock:
            self._recognize_interval_ms = max(50, recognize_interval_ms)
            try:
                source = create_frame_source(
                    kind,
                    device_index=device_index,
                    images=images,
                    max_width=max_width or DEFAULT_MAX_WIDTH,
                )
                source.open()
            except FrameSourceError as exc:
                self._status = CameraStatus(
                    running=False,
                    source=kind,
                    batch_id=batch_id,
                    error=str(exc),
                    hint=exc.hint,
                )
                return self._status
            except Exception as exc:  # noqa: BLE001 - 摄像头异常种类很多，统一转成可读状态
                self._status = CameraStatus(
                    running=False, source=kind, batch_id=batch_id, error=str(exc)
                )
                return self._status

            self._source = source
            self._status = CameraStatus(
                running=True,
                source=source.name,
                batch_id=batch_id,
                started_at=_now(),
                metadata=source.metadata(),
            )
            self._jpeg = None
            self._detection = None
            self._applied_snapshot = None
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
            self._thread.start()
            return self._status

    def stop(self) -> CameraStatus:
        thread = self._thread
        self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

        with self._lock:
            if self._source is not None:
                self._source.close()
                self._source = None
            self._status.running = False
            return self._status

    # ------------------------------------------------------------------ 取流

    def _run(self) -> None:
        interval = self._recognize_interval_ms / 1000
        last_recognize = 0.0

        while not self._stop.is_set():
            source = self._source
            if source is None or not source.is_open():
                break

            try:
                frame = source.read()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._status.error = f"读取帧失败：{exc}"
                break

            if frame is None:
                # 断连或读空：不要忙等
                time.sleep(0.05)
                continue

            with self._lock:
                self._status.frames_read += 1
                self._status.last_frame_at = frame.captured_at
            self._update_jpeg(frame.image)

            now = time.monotonic()
            if now - last_recognize < interval:
                continue
            last_recognize = now

            try:
                result = decode_frame(frame.image, expected_min=1)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._status.error = f"识别失败：{exc}"
                continue

            with self._lock:
                self._status.recognitions += 1
                self._detection = result
                self._detection_at = _now()

            self._apply_to_scan(result)

        with self._lock:
            self._status.running = False

    def _apply_to_scan(self, result: RecognitionResult) -> None:
        """把识别结果直接交给状态机（仅在绑定了批次时）。"""

        batch_id = self._status.batch_id
        service = self._scan_service
        if not batch_id or service is None:
            return

        repository = getattr(service, "_repository", None)
        if repository is None:  # pragma: no cover - 只在装配错误时发生
            return

        record = repository.get(batch_id)
        if record is None:
            return

        # 没有识别到任何东西时不打扰状态机：空帧在连续取流里是常态，
        # 每次都报"未识别到条码"会把真正的异常淹没在噪声里。
        if not result.accepted and not result.conflicts:
            return

        snapshot = service.apply_frame(
            record,
            codes=result.codes,
            conflicts=[item.to_dict() for item in result.conflicts],
            engine_version="zxingcpp+pyzbar",
            variants=list(result.variants_used),
        )
        with self._lock:
            self._applied_snapshot = snapshot.to_dict()

    def _update_jpeg(self, image) -> None:
        import cv2

        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if ok:
            with self._lock:
                self._jpeg = encoded.tobytes()

    # ------------------------------------------------------------------ 读取

    def status(self) -> CameraStatus:
        with self._lock:
            # slots 数据类没有 __dict__，用 replace 复制一份再交出去
            return replace(self._status)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def latest_detection(self) -> dict[str, object] | None:
        with self._lock:
            if self._detection is None:
                return None
            payload = self._detection.to_dict()
            payload["detectedAt"] = self._detection_at
            payload["appliedSnapshot"] = self._applied_snapshot
            return payload

    def list_devices(self, limit: int = 5) -> list[dict[str, object]]:
        """探测可用摄像头序号。

        探测本身要打开设备，有一定耗时，因此只在设置页按需调用，不在主流程里轮询。
        """

        import cv2

        found: list[dict[str, object]] = []
        for index in range(limit):
            capture = cv2.VideoCapture(index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(index)
            try:
                if capture.isOpened():
                    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                    found.append({"index": index, "width": width, "height": height})
            finally:
                capture.release()
        return found
