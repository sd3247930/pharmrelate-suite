"""阶段 3：识别管线测试（用真实照片做基准）。

照片 `private/微信图片_20260920122532_2236_7.jpg` 是现场实拍：
一张标签纸 2 行 × 3 列共 6 枚药品追溯码，纸面反光、背景是木纹桌面。
这里把它当作识别率的验收依据，而不是靠合成图自说自话。

照片不存在时整组跳过 —— 它是外部输入，不该让缺失导致整条流水线红掉。
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR
except ImportError:
    from support import BACKEND_DIR

from app.services.recognition import (
    DEFAULT_MAX_WIDTH,
    BBox,
    decode_file,
    decode_frame,
    is_degenerate,
    load_image,
    make_variant,
    same_region,
)

PHOTO = (
    BACKEND_DIR.parent
    / "private"
    / "微信图片_20260920122532_2236_7.jpg"
)

# 照片上 6 枚标签的药品标识码(8206233) + 序列号
EXPECTED_SERIALS = (
    "0000110265841",
    "0000110271913",
    "0000110280860",
    "0000110295569",
    "0000110307353",
    "0000110313029",
)
EXPECTED_CODES = {f"8206233{serial}" for serial in EXPECTED_SERIALS}

# 全分辨率下会出现的解码伪影：同一位置被解出的第二个值
PHANTOM_CODE = "82062339000000001007"
TRUE_CODE_OF_THAT_REGION = "82062339000000001006"


class GeometryTests(unittest.TestCase):
    """几何辅助函数：冲突判定全靠它们，先单独验。"""

    def test_iou_of_identical_boxes_is_one(self) -> None:
        box = BBox(0, 0, 100, 50)
        self.assertAlmostEqual(box.iou(box), 1.0)

    def test_iou_of_disjoint_boxes_is_zero(self) -> None:
        self.assertEqual(BBox(0, 0, 10, 10).iou(BBox(100, 100, 110, 110)), 0.0)

    def test_partial_overlap_between_zero_and_one(self) -> None:
        value = BBox(0, 0, 100, 100).iou(BBox(50, 0, 150, 100))
        self.assertGreater(value, 0.0)
        self.assertLess(value, 1.0)

    def test_contains_detects_nested_box(self) -> None:
        outer = BBox(0, 0, 100, 100)
        self.assertTrue(outer.contains(BBox(10, 10, 90, 90)))
        self.assertFalse(outer.contains(BBox(10, 10, 200, 200)))

    def test_degenerate_box_is_rejected(self) -> None:
        # 实测出现过高度只有 3 像素的框
        self.assertTrue(is_degenerate(BBox(0, 0, 651, 3)))
        self.assertTrue(is_degenerate(BBox(0, 0, 4, 66)))
        self.assertFalse(is_degenerate(BBox(0, 0, 600, 150)))

    def test_same_region_for_overlapping_and_nested(self) -> None:
        """实测中幻影框与真码框几乎重合、且一个基本被另一个包住。"""

        true_box = BBox(1138, 1512, 1768, 1665)
        phantom_box = BBox(1140, 1536, 1770, 1629)
        self.assertTrue(same_region(true_box, phantom_box))
        self.assertFalse(same_region(true_box, BBox(0, 0, 600, 150)))


class PreprocessTests(unittest.TestCase):
    def test_unknown_variant_falls_back_to_original(self) -> None:
        import numpy as np

        image = np.zeros((32, 32, 3), dtype=np.uint8)
        result = make_variant(image, "并不存在的预处理")
        self.assertEqual(result.shape, image.shape)

    def test_flattening_is_available(self) -> None:
        import numpy as np

        from app.services.recognition import VARIANT_FLATTENED

        image = np.full((64, 64, 3), 128, dtype=np.uint8)
        flattened = make_variant(image, VARIANT_FLATTENED)
        self.assertEqual(flattened.shape[:2], (64, 64))


@unittest.skipUnless(PHOTO.is_file(), f"缺少真实照片：{PHOTO}")
class RealPhotoTests(unittest.TestCase):
    """真实照片验收。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image = load_image(PHOTO)

    def test_image_loads_despite_chinese_filename(self) -> None:
        """中文文件名必须能读：cv2.imread 在这里会返回 None。"""

        self.assertEqual(self.image.shape[2], 3)
        self.assertGreater(self.image.shape[1], 1000)

    def test_default_settings_decode_all_six_labels(self) -> None:
        result = decode_file(PHOTO, expected_min=6)

        self.assertEqual(
            set(result.codes),
            EXPECTED_CODES,
            f"应解出照片上的 6 枚标签，实际得到 {sorted(result.codes)}",
        )
        self.assertEqual(result.conflicts, [], "默认分辨率下不应有冲突")
        self.assertEqual(result.variants_used, ["原图"], "首轮即达标，不应升级到其它预处理")

    def test_all_decoded_codes_are_layer1_particles(self) -> None:
        result = decode_file(PHOTO, expected_min=6)
        self.assertEqual(list(result.by_layer().keys()), [1])
        self.assertEqual(len(result.by_layer()[1]), 6)

    def test_meets_recognition_latency_target(self) -> None:
        """V1.1 13.3：条码识别延迟 ≤ 300ms。这里用单帧全流程耗时衡量。"""

        result = decode_file(PHOTO, expected_min=6)
        self.assertLess(result.elapsed_ms, 300.0, f"实际 {result.elapsed_ms:.1f} ms")

    def test_default_max_width_is_applied(self) -> None:
        self.assertEqual(DEFAULT_MAX_WIDTH, 1920)

    def test_full_resolution_exposes_the_phantom_but_never_accepts_it(self) -> None:
        """全分辨率会解出幻影码，这是真实的解码伪影。

        它同样是 8206233 开头的 20 位数字，能通过格式与前缀校验，
        所以必须由"同区域冲突"把它拦住 —— 而且**两个值都不能被自动采信**，
        宁可要求重扫，也不静默绑定一个可能是错的码。
        """

        result = decode_frame(self.image, expected_min=6, max_width=0)

        conflicted = {text for conflict in result.conflicts for text in conflict.candidates}
        self.assertIn(PHANTOM_CODE, conflicted, "幻影码应被识别为冲突")
        self.assertIn(TRUE_CODE_OF_THAT_REGION, conflicted, "同区域真码也不能被自动采信")
        self.assertNotIn(PHANTOM_CODE, result.codes, "幻影码绝不能出现在接受结果里")
        self.assertNotIn(TRUE_CODE_OF_THAT_REGION, result.codes)

        self.assertEqual(len(result.conflicts), 1)
        conflict = result.conflicts[0]
        self.assertIn("support", conflict.to_dict())
        self.assertGreater(conflict.region.area, 0)

    def test_result_is_deterministic(self) -> None:
        first = decode_file(PHOTO, expected_min=6)
        second = decode_file(PHOTO, expected_min=6)
        self.assertEqual(first.codes, second.codes)
        self.assertEqual(len(first.conflicts), len(second.conflicts))

    def test_degenerate_duplicate_is_rejected_not_accepted_twice(self) -> None:
        """实测中同一个码会被解出两次，其一的框高度只有 3 像素。"""

        result = decode_frame(self.image, expected_min=6, max_width=0)
        self.assertEqual(len(result.codes), len(set(result.codes)), "接受结果不能有重复")
        for text, reason in result.rejected:
            self.assertIn("退化", reason, f"{text} 的拒绝原因应为包围盒退化")

    def test_serialisation_shape_for_api(self) -> None:
        payload = decode_file(PHOTO, expected_min=6).to_dict()
        self.assertIn("accepted", payload)
        self.assertIn("conflicts", payload)
        self.assertIn("elapsedMs", payload)
        for item in payload["accepted"]:
            self.assertEqual(item["layer"], 1)
            self.assertEqual(item["layerLabel"], "粒子")


if __name__ == "__main__":
    unittest.main()
