"""识别管线探针：在真实照片上试各种预处理策略，看哪种能稳定解出多码。

这是开发期的实验工具，不进生产路径。写它的原因很直接：
抗反光方案必须用真实照片选，不能凭直觉拍脑袋定。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\probe_recognition.py
    .venv\\Scripts\\python.exe tools\\probe_recognition.py --image path\\to.jpg
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_IMAGE = BACKEND_DIR.parent / "private" / "微信图片_20260920122532_2236_7.jpg"


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def variants(image):
    """产出候选图像版本，从最简单到最激进。"""

    import cv2
    import numpy as np

    yield "原图", image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    yield "灰度", gray

    # CLAHE：压掉局部过曝造成的对比度塌陷
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    yield "CLAHE", clahe.apply(gray)

    # 大核形态学闭运算估计背景光照，再相除 —— 这就是"去反光"的核心
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    flattened = cv2.divide(gray, background, scale=255)
    yield "光照拉平", flattened

    yield "光照拉平+CLAHE", clahe.apply(flattened)

    # 去反光后做自适应二值化，应对不均匀光照
    adaptive = cv2.adaptiveThreshold(
        flattened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 12
    )
    yield "自适应二值", adaptive

    # 锐化：一维码的条空边缘更利落
    blur = cv2.GaussianBlur(flattened, (0, 0), 3)
    unsharp = cv2.addWeighted(flattened, 1.6, blur, -0.6, 0)
    yield "拉平+锐化", unsharp

    # 上采样：小标签在大图里可能不足最小条宽
    yield "拉平x2", cv2.resize(flattened, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    yield "灰度x2", cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # 极强的对比拉伸
    yield "拉平+Otsu", cv2.threshold(flattened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def decode_all(image) -> list[tuple[str, str]]:
    """返回 (引擎, 条码文本) 列表。"""

    import zxingcpp

    found: list[tuple[str, str]] = []

    try:
        results = zxingcpp.read_barcodes(image)
        for item in results:
            if item.text:
                found.append(("zxingcpp", item.text))
    except Exception as exc:  # noqa: BLE001
        found.append(("zxingcpp-ERROR", str(exc)))

    try:
        from pyzbar.pyzbar import decode as pyzbar_decode

        for item in pyzbar_decode(image):
            text = item.data.decode("utf-8", errors="replace")
            if text:
                found.append(("pyzbar", text))
    except Exception as exc:  # noqa: BLE001
        found.append(("pyzbar-ERROR", str(exc)))

    return found


def read_image(path: Path):
    """读图必须绕开 cv2.imread。

    OpenCV 在 Windows 上走 ANSI 文件 API，遇到中文文件名（本项目全是中文名）
    会直接返回 None。用 numpy.fromfile + imdecode，按字节解码就没事。
    """

    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="识别管线探针")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    args = parser.parse_args()

    if not args.image.is_file():
        print(f"[FAIL] 找不到图片：{args.image}")
        return 2

    image = read_image(args.image)
    if image is None:
        print(f"[FAIL] 图片无法解码：{args.image}")
        return 2
    print(f"图片 : {args.image.name}")
    print(f"尺寸 : {image.shape[1]} x {image.shape[0]}\n")

    best: tuple[str, set[str]] | None = None
    for label, candidate in variants(image):
        started = time.perf_counter()
        try:
            hits = decode_all(candidate)
        except Exception as exc:  # noqa: BLE001
            print(f"{label:<16} 异常：{exc}")
            continue
        elapsed = (time.perf_counter() - started) * 1000

        codes = {text for _engine, text in hits if "ERROR" not in _engine}
        engines = sorted({engine for engine, _ in hits if "ERROR" not in engine})
        errors = [text for engine, text in hits if "ERROR" in engine]

        print(f"{label:<16} 唯一码 {len(codes):>2}  {elapsed:>7.1f} ms  引擎 {engines or '—'}")
        for code in sorted(codes):
            print(f"                    {code}")
        for error in errors:
            print(f"                    错误：{error[:100]}")

        if best is None or len(codes) > len(best[1]):
            best = (label, codes)

    print()
    if best:
        print(f"最佳策略：{best[0]}，唯一码 {len(best[1])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
