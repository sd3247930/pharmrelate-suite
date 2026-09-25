"""条码识别管线：单帧多码 + 抗反光 + 同区域冲突检测。

设计依据来自真实照片（private/微信图片_20260920122532_2236_7.jpg）的实测结论：

1. **中文路径必须走字节解码。** OpenCV 在 Windows 上走 ANSI 文件 API，
   `cv2.imread('微信图片….jpg')` 直接返回 None。统一用 numpy.fromfile + imdecode。

2. **同一帧里会出现"同一物理条码、两个不同解码值"。** 实测中
   `82062339000000001006`（正确）与 `82062339000000001007`（幻影）被解出，
   两者包围盒几乎完全重合。幻影码同样是 8206233 开头的 20 位数字，
   **能通过前缀与长度校验** —— 单靠格式校验防不住它。
   因此本模块对"同区域多值"一律判为冲突并拒绝自动采信，
   交由操作员重扫或确认，绝不静默绑定一个可能是错的码。

3. **退化包围盒要丢弃。** 实测中同一个码被解出两次，其一的框高度只有 3 像素。

4. **分阶段解码。** 原图通常一次就能解出全部码；只有失败时才升级到
   抗反光预处理与第二引擎，避免每帧都付出十几倍的算力。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.constants import classify_code, layer_label, looks_like_code

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BBox:
    """轴对齐包围盒。"""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.right) / 2, (self.top + self.bottom) / 2

    def iou(self, other: BBox) -> float:
        """交并比，用来判断两个结果是不是落在同一块物理区域。"""

        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def contains(self, other: BBox) -> bool:
        """other 是否基本落在 self 之内（用于识别"嵌套的幻影框"）。"""

        if other.area <= 0:
            return False
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return False
        return (right - left) * (bottom - top) / other.area >= 0.7


@dataclass(slots=True)
class DecodedCode:
    """一次解码命中的原始记录。"""

    text: str
    engine: str
    variant: str
    box: BBox


@dataclass(slots=True)
class Candidate:
    """按条码值聚合后的候选。"""

    text: str
    boxes: list[BBox] = field(default_factory=list)
    engines: set[str] = field(default_factory=set)
    variants: set[str] = field(default_factory=set)

    @property
    def votes(self) -> int:
        """投票数 = 命中的（引擎，预处理版本）组合数。"""

        return len(self.engines) * len(self.variants)

    @property
    def box(self) -> BBox:
        """取面积最大的框，避免被退化的细条框带偏。"""

        return max(self.boxes, key=lambda item: item.area)


@dataclass(slots=True)
class Conflict:
    """同一物理区域解出多个不同值 —— 必须拒绝自动采信。"""

    region: BBox
    candidates: list[str]
    reason: str
    support: dict[str, int] = field(default_factory=dict)
    """每个候选在（引擎 × 预处理版本）上的命中次数。

    只作为界面上的提示信息，**绝不用于自动挑选**：本项目的原则是
    宁要求重扫，也不静默绑定一个可能是错的码。
    """

    def to_dict(self) -> dict[str, object]:
        return {
            "region": {
                "left": round(self.region.left, 1),
                "top": round(self.region.top, 1),
                "right": round(self.region.right, 1),
                "bottom": round(self.region.bottom, 1),
            },
            "candidates": self.candidates,
            "support": self.support,
            "reason": self.reason,
        }


@dataclass(slots=True)
class RecognitionResult:
    accepted: list[Candidate] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    """(条码文本, 拒绝原因)。"""

    variants_used: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def codes(self) -> list[str]:
        return [item.text for item in self.accepted]

    def by_layer(self) -> dict[int, list[str]]:
        grouped: dict[int, list[str]] = {}
        for item in self.accepted:
            layer = classify_code(item.text)
            if layer is not None:
                grouped.setdefault(layer, []).append(item.text)
        return grouped

    def to_dict(self, *, include_codes: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "accepted": [
                {
                    "text": item.text,
                    "layer": classify_code(item.text),
                    "layerLabel": layer_label(classify_code(item.text)),
                    "engines": sorted(item.engines),
                    "variants": sorted(item.variants),
                    "votes": item.votes,
                }
                for item in self.accepted
            ],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "rejected": [{"text": text, "reason": reason} for text, reason in self.rejected],
            "variantsUsed": self.variants_used,
            "elapsedMs": round(self.elapsed_ms, 1),
        }
        if include_codes:
            payload["codes"] = self.codes
        return payload


# ---------------------------------------------------------------------------
# 几何辅助
# ---------------------------------------------------------------------------

MIN_BOX_EDGE_PX = 8
"""任一方向小于该像素数的框视为退化（实测出现过高度 3px 的幻影框）。"""

DEFAULT_MAX_WIDTH = 1920
"""默认工作分辨率上限，取值依据见 `decode_frame` 的实测表。"""

OVERLAP_IOU = 0.35
"""交并比超过该阈值即认定落在同一物理区域。"""


def is_degenerate(box: BBox) -> bool:
    return box.width < MIN_BOX_EDGE_PX or box.height < MIN_BOX_EDGE_PX


def same_region(a: BBox, b: BBox) -> bool:
    """两个框是否指向同一块物理区域。

    一维码的框在不同预处理下高度会有波动，纯 IoU 阈值容易漏判，
    因此同时接受"互相包含"这一条。
    """

    return a.iou(b) >= OVERLAP_IOU or a.contains(b) or b.contains(a)


# ---------------------------------------------------------------------------
# 图像预处理（抗反光）
# ---------------------------------------------------------------------------

VARIANT_ORIGINAL = "原图"
VARIANT_FLATTENED = "光照拉平"
VARIANT_SHARPENED = "光照拉平+锐化"
VARIANT_CLAHE = "CLAHE"
VARIANT_OTSU = "拉平+Otsu"


def load_image(path: Path):
    """按字节读图，避开 cv2.imread 在中文路径上的失败。"""

    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise FileNotFoundError(f"图片不存在或为空：{path}")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"图片无法解码：{path}")
    return image


def flatten_illumination(gray):
    """大核形态学闭运算估计背景光照，再相除。

    标签纸反光时局部亮到发白、对比度塌陷，全局阈值救不回来；
    先估出光照面再除掉，条空对比就恢复了。
    """

    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    return cv2.divide(gray, background, scale=255)


def make_variant(image, name: str):
    """按名称产出预处理版本。未知名称返回原图。"""

    import cv2

    if name == VARIANT_ORIGINAL:
        return image

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if name == VARIANT_FLATTENED:
        return flatten_illumination(gray)
    if name == VARIANT_CLAHE:
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        return clahe.apply(gray)
    if name == VARIANT_SHARPENED:
        flattened = flatten_illumination(gray)
        blur = cv2.GaussianBlur(flattened, (0, 0), 3)
        return cv2.addWeighted(flattened, 1.6, blur, -0.6, 0)
    if name == VARIANT_OTSU:
        flattened = flatten_illumination(gray)
        return cv2.threshold(flattened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return image


# ---------------------------------------------------------------------------
# 解码引擎
# ---------------------------------------------------------------------------

ENGINE_ZXING = "zxingcpp"
ENGINE_PYZBAR = "pyzbar"


def _decode_with_zxing(image) -> tuple[list[DecodedCode], str | None]:
    """ZXing-C++ 主引擎：快、对一维码稳，是首选。"""

    import zxingcpp

    codes: list[DecodedCode] = []
    try:
        results = zxingcpp.read_barcodes(image)
    except Exception as exc:  # noqa: BLE001 - 引擎异常不能让整帧失败
        return codes, str(exc)

    for item in results:
        text = (item.text or "").strip()
        if not text:
            continue
        position = item.position
        xs = [
            position.top_left.x,
            position.top_right.x,
            position.bottom_right.x,
            position.bottom_left.x,
        ]
        ys = [
            position.top_left.y,
            position.top_right.y,
            position.bottom_right.y,
            position.bottom_left.y,
        ]
        codes.append(
            DecodedCode(
                text=text,
                engine=ENGINE_ZXING,
                variant="",
                box=BBox(min(xs), min(ys), max(xs), max(ys)),
            )
        )
    return codes, None


def _decode_with_pyzbar(image) -> tuple[list[DecodedCode], str | None]:
    """pyzbar 作为第二引擎，只在主引擎结果不足时启用。

    实测 pyzbar 明显更慢，且在极端二值图上会触发 zbar 内部断言，
    因此不放在默认路径上。
    """

    codes: list[DecodedCode] = []
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode

        results = pyzbar_decode(image)
    except Exception as exc:  # noqa: BLE001
        return codes, str(exc)

    for item in results:
        text = item.data.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        rect = item.rect
        codes.append(
            DecodedCode(
                text=text,
                engine=ENGINE_PYZBAR,
                variant="",
                box=BBox(rect.left, rect.top, rect.left + rect.width, rect.top + rect.height),
            )
        )
    return codes, None


ENGINES = {ENGINE_ZXING: _decode_with_zxing, ENGINE_PYZBAR: _decode_with_pyzbar}


def decode_once(image, variant_name: str, engines: tuple[str, ...]) -> list[DecodedCode]:
    found: list[DecodedCode] = []
    for engine_name in engines:
        decoder = ENGINES[engine_name]
        codes, _error = decoder(image)
        for code in codes:
            code.variant = variant_name
        found.extend(codes)
    return found


# ---------------------------------------------------------------------------
# 聚合与冲突判定
# ---------------------------------------------------------------------------


def _aggregate(raw: list[DecodedCode]) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """按条码值聚合，顺便丢掉落不到任何过滤器里的脏结果。"""

    candidates: dict[str, Candidate] = {}
    rejected: list[tuple[str, str]] = []

    for item in raw:
        if not looks_like_code(item.text):
            rejected.append((item.text, "条码长度或字符不符合 20 位数字规则"))
            continue
        if classify_code(item.text) is None:
            rejected.append((item.text, "条码前缀不在箱/罐/粒子白名单内"))
            continue
        if is_degenerate(item.box):
            rejected.append(
                (item.text, f"包围盒退化（{round(item.box.width)}x{round(item.box.height)} 像素）")
            )
            continue

        candidate = candidates.setdefault(item.text, Candidate(text=item.text))
        candidate.boxes.append(item.box)
        candidate.engines.add(item.engine)
        candidate.variants.add(item.variant)

    return list(candidates.values()), rejected


def _resolve_conflicts(
    candidates: list[Candidate],
) -> tuple[list[Candidate], list[Conflict]]:
    """同一物理区域出现多个不同条码值 → 判为冲突，双方都不自动采信。

    这是本模块最重要的一条防线。真实照片里出现过同一位置解出
    `…110307353`（正确）与 `…123307313`（幻影）的情况，且幻影码
    同样满足 20 位与前缀白名单，格式校验完全拦不住。
    宁可要求操作员重扫，也绝不静默写入一个可能是错的码。
    """

    accepted: list[Candidate] = []
    conflicts: list[Conflict] = []
    used: set[int] = set()

    ordered = sorted(candidates, key=lambda item: item.box.area, reverse=True)

    for index, candidate in enumerate(ordered):
        if index in used:
            continue
        group = [candidate]
        for other_index in range(index + 1, len(ordered)):
            if other_index in used:
                continue
            if same_region(candidate.box, ordered[other_index].box):
                group.append(ordered[other_index])
                used.add(other_index)
        used.add(index)

        if len(group) == 1:
            accepted.append(candidate)
            continue

        conflicts.append(
            Conflict(
                region=group[0].box,
                candidates=[item.text for item in group],
                support={item.text: item.votes for item in group},
                reason="同一位置解出多个不同条码值，可能是条码污损或反光导致误读，请重扫",
            )
        )

    return accepted, conflicts


def decode_frame(
    image,
    *,
    expected_min: int = 1,
    max_width: int = DEFAULT_MAX_WIDTH,
    engines: tuple[str, ...] = (ENGINE_ZXING,),
    escalation_engines: tuple[str, ...] = (ENGINE_ZXING, ENGINE_PYZBAR),
    variants: tuple[str, ...] = (
        VARIANT_ORIGINAL,
        VARIANT_FLATTENED,
        VARIANT_SHARPENED,
        VARIANT_CLAHE,
        VARIANT_OTSU,
    ),
    max_variants: int = 5,
) -> RecognitionResult:
    """识别一帧图像中的全部条码。

    分阶段策略：先用主引擎跑原图；结果数量达标就收工，
    否则逐级升级（更多预处理版本 + 第二引擎）。
    车间连续扫码时，绝大多数帧都走最短路径。

    `max_width` 大于 0 时先把图缩到该宽度。默认 1920 由真实照片实测得出：

        分辨率上限   耗时      结果
        不缩        607 ms    6 枚全解，但多出一个幻影码（判为冲突）
        2400        324 ms    6 枚全解，无冲突
        1920        246 ms    6 枚全解，无冲突
        1280        142 ms    6 枚全解，无冲突

    幻影码是超高分辨率下的解码伪影——降采样把码元宽度归一化之后就消失了，
    顺带把耗时压进 300ms 指标。但**冲突检测依然保留**：分辨率归一化只是常态
    手段，不能假定它对每一帧都有效。
    """

    import time

    started = time.perf_counter()
    result = RecognitionResult()
    collected: list[DecodedCode] = []
    used_variants: list[str] = []

    if max_width > 0 and image.shape[1] > max_width:
        import cv2

        scale = max_width / image.shape[1]
        image = cv2.resize(
            image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )

    for attempt, variant_name in enumerate(variants[:max_variants]):
        try:
            frame = make_variant(image, variant_name)
        except Exception:  # noqa: BLE001 - 某个预处理失败不应中断扫描
            continue

        active_engines = engines if attempt == 0 else escalation_engines
        collected.extend(decode_once(frame, variant_name, active_engines))
        used_variants.append(variant_name)

        candidates, _rejected = _aggregate(collected)
        # 提前结束的依据是"找到了足够多的不同条码值"，而不是"冲突已解决"：
        # 冲突往往无法靠换预处理解决，若等它消除就会一路升级到全部变体
        # （实测从 0.3 秒涨到 7 秒），车间连续扫码完全不能接受。
        if len(candidates) >= expected_min:
            break

    candidates, rejected = _aggregate(collected)
    accepted, conflicts = _resolve_conflicts(candidates)

    result.accepted = sorted(accepted, key=lambda item: (item.box.top, item.box.left))
    result.conflicts = conflicts
    result.rejected = rejected
    result.variants_used = used_variants
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


def decode_file(path: Path, **kwargs) -> RecognitionResult:
    return decode_frame(load_image(path), **kwargs)
