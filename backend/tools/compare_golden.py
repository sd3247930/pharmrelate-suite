"""基准比对 CLI：重新生成 XML 并与 golden 文件逐字节比较。

用法：
    python backend/tools/compare_golden.py
    python backend/tools/compare_golden.py --details

退出码 0 表示两个基准文件完全一致；非 0 表示存在差异。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.domain.constants import LAYER_BOX, LAYER_CAN, LAYER_PARTICLE, classify_code  # noqa: E402
from app.services.xml_builder import render_bytes  # noqa: E402
from app.services.xml_parser import parse_file  # noqa: E402

GOLDEN_DIR = BACKEND_DIR / "tests" / "golden"
GOLDEN_FILES = ("1箱3罐.xml", "一箱一罐.xml")


def _use_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，中文路径/批号会变乱码。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # pragma: no cover - 重定向到非文本流时
                pass


def first_difference(expected: bytes, actual: bytes) -> tuple[int, str]:
    limit = min(len(expected), len(actual))
    for offset in range(limit):
        if expected[offset] != actual[offset]:
            return offset, f"偏移 {offset}：期望 {expected[offset]:#04x}，实际 {actual[offset]:#04x}"
    if len(expected) != len(actual):
        return limit, f"长度不同：期望 {len(expected)}，实际 {len(actual)}"
    return -1, "无差异"


def main() -> int:
    _use_utf8_stdout()

    parser = argparse.ArgumentParser(description="PharmRelate 阶段 0 基准比对")
    parser.add_argument("--details", action="store_true", help="输出结构摘要")
    args = parser.parse_args()

    if not GOLDEN_DIR.is_dir():
        print(f"[FAIL] 未找到基准目录：{GOLDEN_DIR}", file=sys.stderr)
        return 2

    failed = 0
    for name in GOLDEN_FILES:
        path = GOLDEN_DIR / name
        if not path.is_file():
            print(f"[FAIL] {name:<14} 基准文件缺失")
            failed += 1
            continue

        expected = path.read_bytes()
        try:
            batch = parse_file(path)
            actual = render_bytes(batch)
        except Exception as exc:  # noqa: BLE001 - CLI 需要汇总任何错误
            print(f"[FAIL] {name:<14} 生成失败：{exc}")
            failed += 1
            continue

        if expected != actual:
            offset, message = first_difference(expected, actual)
            print(f"[FAIL] {name:<14} {message}")
            if offset >= 0:
                start = max(0, offset - 40)
                print(f"       期望: {expected[start:offset + 40]!r}")
                print(f"       实际: {actual[start:offset + 40]!r}")
            failed += 1
            continue

        print(f"[ OK ] {name:<14} 字节级一致  {len(expected):>7} 字节")
        if args.details:
            layers: dict[int, int] = {}
            for _code, layer, _parent in batch.iter_export_nodes():
                layers[layer] = layers.get(layer, 0) + 1
            print(
                f"       批号 {batch.batch_no}  生产日期 {batch.made_date}  "
                f"有效期 {batch.validate_date}"
            )
            print(
                f"       箱 {layers.get(LAYER_BOX, 0)}  "
                f"罐 {layers.get(LAYER_CAN, 0)}  "
                f"粒子 {layers.get(LAYER_PARTICLE, 0)}"
            )
            for can in batch.box.cans:
                state = "通过" if classify_code(can.code) == LAYER_CAN else "失败"
                print(
                    f"       罐{can.index} {can.code}  粒子 {len(can.particles):>4}  "
                    f"前缀校验 {state}"
                )
            duplicates = batch.find_duplicate_codes()
            print(f"       重复条码 {len(duplicates)} 个")

    print()
    if failed:
        print(f"阶段 0 验收：未通过（{failed} 个文件不一致）")
        return 1
    print("阶段 0 验收：通过 —— 两个基准文件均实现字节级一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
