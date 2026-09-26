"""手机拍照上传：一张照片 → 识别结果 → 会话状态机。

与 PC 侧摄像头的差别只有"帧从哪来"：那边是本地设备连续取流，这边是手机传上来的一张图。
识别、同区域冲突判定、写状态机全部复用同一条管线 —— 不能出现第二条识别路径，
否则"为什么手机识别不出、电脑识别得出"这种问题将无从解释。

图片规格（拍板 D6）：长边 ≤1920（由识别管线的 `max_width` 归一化）、JPEG、≤5MB。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..repositories.batch_repository import BatchRepository
from .recognition import DEFAULT_MAX_WIDTH, decode_bytes, decode_frame
from .scan_service import ScanService

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
"""单张照片上限（D6）。超过就拒收，而不是压缩后再猜。"""

MIN_EDGE_PIXELS = 200
"""小于这个边长基本是误拍（拍糊、拍到桌面），直接提示重拍比识别失败更好懂。"""


@dataclass(slots=True)
class CaptureResult:
    codes: list[str] = field(default_factory=list)
    conflicts: list[dict[str, object]] = field(default_factory=list)
    variants_used: list[str] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    width: int = 0
    height: int = 0
    snapshot: dict[str, object] | None = None
    """绑定了批次时，状态机处理这一帧之后的会话快照。"""

    def to_dict(self) -> dict[str, object]:
        return {
            "codes": list(self.codes),
            "conflicts": list(self.conflicts),
            "variantsUsed": list(self.variants_used),
            "rejected": list(self.rejected),
            "elapsedMs": round(self.elapsed_ms, 1),
            "width": self.width,
            "height": self.height,
            "snapshot": self.snapshot,
        }


class CaptureRejected(Exception):
    """照片本身不合规：太大、解不开、太小。带上可操作的建议。"""

    def __init__(self, message: str, *, reason: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.hint = hint


def recognize_upload(
    data: bytes,
    *,
    filename: str = "",
    repository: BatchRepository,
    scan_service: ScanService,
    batch_id: str = "",
    max_width: int = DEFAULT_MAX_WIDTH,
) -> CaptureResult:
    """识别一张上传的照片；给了批次号就直接进状态机。"""

    source = filename or "<上传的照片>"
    if len(data) > MAX_UPLOAD_BYTES:
        raise CaptureRejected(
            f"照片 {len(data) / 1024 / 1024:.1f} MB，超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限。",
            reason="PHOTO_TOO_LARGE",
            hint="请在拍照界面选择压缩画质后重拍，或在系统设置里降低相机分辨率。",
        )

    try:
        image = decode_bytes(data, source=source)
    except ValueError as exc:
        raise CaptureRejected(
            "这张文件解不出图像，可能不是照片或已损坏。",
            reason="PHOTO_INVALID",
            hint=str(exc),
        ) from exc

    height, width = image.shape[:2]
    if min(width, height) < MIN_EDGE_PIXELS:
        raise CaptureRejected(
            f"照片只有 {width}×{height}，太小了，条码占的像素不够。",
            reason="PHOTO_TOO_SMALL",
            hint="请靠近标签重拍，让条码占画面的大部分。",
        )

    result = decode_frame(image, expected_min=1, max_width=max_width)
    capture = CaptureResult(
        codes=list(result.codes),
        conflicts=[item.to_dict() for item in result.conflicts],
        variants_used=list(result.variants_used),
        rejected=[{"text": text, "reason": why} for text, why in result.rejected],
        elapsed_ms=result.elapsed_ms,
        width=width,
        height=height,
    )

    if not batch_id:
        return capture

    record = repository.get(batch_id)
    if record is None:
        raise CaptureRejected(
            f"批次 {batch_id} 不存在。",
            reason="BATCH_NOT_FOUND",
            hint="请先在电脑端创建批次，或在手机上重新选择批次。",
        )

    snapshot = scan_service.apply_frame(
        record,
        codes=capture.codes,
        conflicts=capture.conflicts,
        engine_version="zxingcpp+pyzbar",
        variants=capture.variants_used,
    )
    capture.snapshot = snapshot.to_dict()
    return capture
