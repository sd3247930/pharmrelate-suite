"""查看识别结果的几何位置：判断多出来的码是真实的第 7 枚标签，还是误读。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\probe_positions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools.probe_recognition import DEFAULT_IMAGE, read_image, use_utf8_stdout  # noqa: E402


def main() -> int:
    use_utf8_stdout()
    import zxingcpp

    image = read_image(DEFAULT_IMAGE)
    height, width = image.shape[:2]
    print(f"图片尺寸：{width} x {height}\n")

    results = zxingcpp.read_barcodes(image)
    print(f"zxingcpp 解出 {len(results)} 个：\n")

    for index, item in enumerate(results, start=1):
        text = item.text or ""
        pos = item.position
        xs = [pos.top_left.x, pos.top_right.x, pos.bottom_right.x, pos.bottom_left.x]
        ys = [pos.top_left.y, pos.top_right.y, pos.bottom_right.y, pos.bottom_left.y]
        box_w = max(xs) - min(xs)
        box_h = max(ys) - min(ys)
        marker = "  <-- 不在照片识读的 6 枚之内" if text.startswith("820623300001233") else ""
        print(
            f"{index:>2}. {text}\n"
            f"    位置 x:[{min(xs):>5},{max(xs):>5}] y:[{min(ys):>5},{max(ys):>5}] "
            f"尺寸 {box_w}x{box_h} 格式 {item.format}{marker}"
        )

    print("\n—— 按纵向位置排序（判断是否有边缘标签）——")
    rows = []
    for item in results:
        pos = item.position
        cx = (pos.top_left.x + pos.bottom_right.x) / 2
        cy = (pos.top_left.y + pos.bottom_right.y) / 2
        rows.append((cy, cx, item.text or ""))
    for cy, cx, text in sorted(rows):
        print(f"    y={cy:>7.0f}  x={cx:>7.0f}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
