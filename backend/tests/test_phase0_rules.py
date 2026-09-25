"""阶段 0 附加规则测试：固定参数、层级前缀校验、顺序保留。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.domain.constants import (  # noqa: E402
    CODE_LENGTH,
    LAYER_BOX,
    LAYER_CAN,
    LAYER_PARTICLE,
    MAX_PARTICLES_PER_BATCH,
    MAX_PARTICLES_PER_CAN,
    classify_code,
    looks_like_code,
    split_trace_code,
)
from app.services.xml_builder import render  # noqa: E402
from app.services.xml_parser import parse_file  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


class PrefixRuleTests(unittest.TestCase):
    """条码层级前缀校验（本项目补充规则，文档中原本没有）。"""

    def test_classify_known_prefixes(self) -> None:
        self.assertEqual(classify_code("80217619000000001003"), LAYER_BOX)
        self.assertEqual(classify_code("80217629000000001005"), LAYER_CAN)
        self.assertEqual(classify_code("82062339000000001004"), LAYER_PARTICLE)

    def test_rejects_wrong_shape(self) -> None:
        self.assertIsNone(classify_code("8021761000001412585"))  # 19 位
        self.assertIsNone(classify_code("802176190000000010030"))  # 21 位
        self.assertIsNone(classify_code("8021761000001412585a"))
        self.assertIsNone(classify_code("12345678901234567890"))  # 未知前缀

    def test_rejects_non_ascii_digits(self) -> None:
        """全角数字 isdigit() 为真，必须被 isascii() 拦住。"""

        fullwidth = "８０２１７６１０００００１４１２５８５６"
        self.assertEqual(len(fullwidth), CODE_LENGTH)
        self.assertTrue(fullwidth.isdigit())
        self.assertFalse(looks_like_code(fullwidth))
        self.assertIsNone(classify_code(fullwidth))

    def test_every_golden_code_matches_declared_layer(self) -> None:
        """基准文件里每个条码，其前缀必须与 packLayer 自洽。"""

        for name in ("1箱3罐.xml", "一箱一罐.xml"):
            with self.subTest(golden=name):
                batch = parse_file(GOLDEN_DIR / name)
                for code, layer, _parent in batch.iter_export_nodes():
                    self.assertTrue(looks_like_code(code), f"{code} 不是合法条码")
                    self.assertEqual(
                        classify_code(code),
                        layer,
                        f"{code} 的前缀与 packLayer={layer} 不符",
                    )

    def test_photo_trace_codes_are_valid_particle_codes(self) -> None:
        """照片实测：药品标识码(7 位) + 序列号(13 位) = 20 位粒子码。"""

        serials = (
            "0000110295569",
            "0000110307353",
            "0000110313029",
            "0000110265841",
            "0000110271913",
            "0000110280860",
        )
        for serial in serials:
            with self.subTest(serial=serial):
                code = "8206233" + serial
                self.assertEqual(len(code), CODE_LENGTH)
                self.assertEqual(classify_code(code), LAYER_PARTICLE)
                self.assertEqual(split_trace_code(code), ("8206233", serial))
        self.assertEqual(len(set(serials)), len(serials), "照片上的 6 个序列号应互不相同")


class FixedParamTests(unittest.TestCase):
    def test_cascade_is_literal_not_derived(self) -> None:
        """1 罐 400 粒的批次，cascade 仍必须是 1:5:2500。"""

        batch = parse_file(GOLDEN_DIR / "一箱一罐.xml")
        self.assertEqual(batch.can_count, 1)
        self.assertEqual(batch.actual_particle_total, 400)
        self.assertIn('cascade="1:5:2500"', render(batch))

    def test_fixed_literals_present_in_output(self) -> None:
        text = render(parse_file(GOLDEN_DIR / "1箱3罐.xml"))
        for fragment in (
            'License="1001123"',
            'xsi:noNamespaceSchemaLocation="关联关系XML Schema-3.0.xsd"',
            '<Events Version="3.0">',
            '<Event Name="RelationCreate">',
            'productCode="9999999"',
            'subTypeNo="9500000001"',
            'packageSpec="粒1粒"',
            'comment="0"',
            'workshop="一号车间"',
            'lineName="一号生产线"',
            'lineManager="操作员甲"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


class OrderPreservationTests(unittest.TestCase):
    def test_particle_order_is_not_sorted(self) -> None:
        """基准中粒子顺序是采集原序，导出禁止排序。"""

        batch = parse_file(GOLDEN_DIR / "一箱一罐.xml")
        particles = batch.box.cans[0].particles
        self.assertNotEqual(particles, sorted(particles))
        self.assertEqual(particles[0], "82062339000000001137")
        self.assertEqual(particles[-1], "82062339000000001010")

    def test_1box3can_particle_order_within_can(self) -> None:
        batch = parse_file(GOLDEN_DIR / "1箱3罐.xml")
        self.assertEqual(
            batch.box.cans[2].particles,
            ["82062339000000001003", "82062339000000001002"],
        )


class ScaleBoundaryTests(unittest.TestCase):
    def test_boundaries_match_v11(self) -> None:
        self.assertEqual(MAX_PARTICLES_PER_CAN, 2500)
        self.assertEqual(MAX_PARTICLES_PER_BATCH, 12500)


if __name__ == "__main__":
    unittest.main()
