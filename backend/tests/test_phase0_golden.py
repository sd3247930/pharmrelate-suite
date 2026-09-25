"""阶段 0 验收测试：两个真实 XML 必须字节级往返一致。

运行：
    cd backend
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.domain.models import Batch, BoxCode, CanCode  # noqa: E402
from app.services.xml_builder import render_bytes  # noqa: E402
from app.services.xml_parser import parse_bytes, parse_file  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

GOLDEN_FILES = ("1箱3罐.xml", "一箱一罐.xml")


def first_difference(expected: bytes, actual: bytes) -> str:
    """定位首个不同字节，便于失败时快速排查。"""

    limit = min(len(expected), len(actual))
    for offset in range(limit):
        if expected[offset] != actual[offset]:
            start = max(0, offset - 40)
            return (
                f"首个差异在偏移 {offset}（期望 {expected[offset]:#04x}，"
                f"实际 {actual[offset]:#04x}）\n"
                f"  期望上下文: {expected[start:offset + 40]!r}\n"
                f"  实际上下文: {actual[start:offset + 40]!r}"
            )
    if len(expected) != len(actual):
        return f"长度不同：期望 {len(expected)} 字节，实际 {len(actual)} 字节"
    return "未发现差异"


class GoldenRoundTripTests(unittest.TestCase):
    """基准文件 → 模型 → 文本，必须逐字节还原。"""

    def test_round_trip_is_byte_identical(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                golden_bytes = (GOLDEN_DIR / name).read_bytes()
                rebuilt = render_bytes(parse_bytes(golden_bytes, source=name))
                self.assertEqual(
                    rebuilt,
                    golden_bytes,
                    f"{name} 往返结果与基准不一致：{first_difference(golden_bytes, rebuilt)}",
                )

    def test_render_is_idempotent(self) -> None:
        """二次往返必须稳定，不产生漂移。"""

        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                once = render_bytes(parse_file(GOLDEN_DIR / name))
                twice = render_bytes(parse_bytes(once, source=f"{name}(rebuilt)"))
                self.assertEqual(once, twice)


class GoldenByteFormatTests(unittest.TestCase):
    """基准文件的字节级格式事实，必须被测试锁死。"""

    def test_no_bom_and_starts_with_declaration(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                data = (GOLDEN_DIR / name).read_bytes()
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"), f"{name} 不应带 BOM")
                self.assertTrue(data.startswith(b"<?xml"), f"{name} 应以 XML 声明开头")

    def test_lf_only_and_single_trailing_newline(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                data = (GOLDEN_DIR / name).read_bytes()
                self.assertNotIn(b"\r", data, f"{name} 不应含 CR")
                self.assertTrue(data.endswith(b"\n"), f"{name} 应以换行结尾")
                self.assertFalse(data.endswith(b"\n\n"), f"{name} 结尾只应有一个换行")

    def test_declaration_and_document_share_first_line(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                first_line = (GOLDEN_DIR / name).read_text(encoding="utf-8").split("\n")[0]
                self.assertIn('<?xml version="1.0" encoding="utf-8"?><Document ', first_line)

    def test_no_indentation(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                text = (GOLDEN_DIR / name).read_text(encoding="utf-8")
                for line in text.split("\n"):
                    self.assertFalse(line.startswith(" "), f"{name} 不应有缩进：{line!r}")

    def test_document_attribute_order(self) -> None:
        """xmlns:xsi → xsi:noNamespaceSchemaLocation → License。"""

        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                first_line = (GOLDEN_DIR / name).read_text(encoding="utf-8").split("\n")[0]
                self.assertLess(
                    first_line.index("xmlns:xsi"),
                    first_line.index("xsi:noNamespaceSchemaLocation"),
                )
                self.assertLess(
                    first_line.index("xsi:noNamespaceSchemaLocation"),
                    first_line.index("License"),
                )

    def test_code_attribute_order(self) -> None:
        """curCode → packLayer → parentCode → flag。"""

        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                text = (GOLDEN_DIR / name).read_text(encoding="utf-8")
                code_lines = [line for line in text.split("\n") if line.startswith("<Code ")]
                self.assertTrue(code_lines, f"{name} 未找到 Code 行")
                for line in code_lines:
                    positions = [
                        line.index('curCode="'),
                        line.index('packLayer="'),
                        line.index('flag="'),
                    ]
                    if 'parentCode="' in line:
                        positions.insert(2, line.index('parentCode="'))
                    self.assertEqual(positions, sorted(positions), f"属性顺序错误：{line}")


class LiteralFixtureTests(unittest.TestCase):
    """手写锚点：绕开解析器，独立验证生成器。"""

    def test_literal_model_reproduces_golden(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "1箱3罐.model.json").read_text(encoding="utf-8"))
        batch = Batch(
            batch_no=fixture["batch_no"],
            made_date=fixture["made_date"],
            validate_date=fixture["validate_date"],
            box=BoxCode(
                code=fixture["box"]["code"],
                cans=[
                    CanCode(
                        index=can["index"],
                        code=can["code"],
                        planned_particle_count=len(can["particles"]),
                        particles=list(can["particles"]),
                    )
                    for can in fixture["box"]["cans"]
                ],
            ),
        )
        golden_bytes = (GOLDEN_DIR / "1箱3罐.xml").read_bytes()
        rebuilt = render_bytes(batch)
        self.assertEqual(
            rebuilt,
            golden_bytes,
            f"手写锚点生成结果与基准不一致：{first_difference(golden_bytes, rebuilt)}",
        )


class GoldenContentFactsTests(unittest.TestCase):
    """把基准文件承载的业务事实写进测试，防止后续被"优化"掉。"""

    def test_1box3can_structure(self) -> None:
        batch = parse_file(GOLDEN_DIR / "1箱3罐.xml")
        self.assertEqual(batch.batch_no, "20260901")
        self.assertEqual(batch.can_count, 3)
        self.assertEqual([len(can.particles) for can in batch.box.cans], [1, 1, 2])
        self.assertEqual(batch.actual_particle_total, 4)

    def test_1box1can_structure(self) -> None:
        batch = parse_file(GOLDEN_DIR / "一箱一罐.xml")
        self.assertEqual(batch.batch_no, "20251001")
        self.assertEqual(batch.made_date, "2025-10-20")
        self.assertEqual(batch.validate_date, "2026-01-08")
        self.assertEqual(batch.can_count, 1)
        self.assertEqual(batch.actual_particle_total, 400)
        self.assertEqual(batch.box.cans[0].code, "80217629000000001001")

    def test_no_duplicate_codes(self) -> None:
        for name in GOLDEN_FILES:
            with self.subTest(golden=name):
                self.assertEqual(parse_file(GOLDEN_DIR / name).find_duplicate_codes(), [])


if __name__ == "__main__":
    unittest.main()
