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
    from tests.support import BACKEND_DIR, resolve_photo
except ImportError:
    from support import BACKEND_DIR, resolve_photo

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

PHOTO = resolve_photo()

# 照片上那 6 枚标签的**具体条码值不写死在仓库里**：照片本身含真实药品追溯码，
# 且已随 private/ 移出公开仓库。期望值一律从解码结果里取，
# 断言的是「行为与结构」（几枚、什么前缀、是否冲突、是否被采信），
# 而不是「具体是哪两串数字」—— 后者会把真实追溯码又抄回源码里。
PARTICLE_CODE_PATTERN = r"^8206233\d{13}$"


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


@unittest.skipIf(PHOTO is None, "缺少现场实拍照片（已从公开仓库移出）")
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

        codes = sorted(result.codes)
        self.assertEqual(len(codes), 6, f"应解出照片上的 6 枚标签，实际得到 {codes}")
        self.assertEqual(len(set(codes)), 6, "六枚标签的条码必须互不相同")
        for code in codes:
            self.assertRegex(code, PARTICLE_CODE_PATTERN, "照片上都是 20 位粒子码（前缀 8206233）")
        self.assertEqual(result.conflicts, [], "默认分辨率下不应有冲突")
        self.assertEqual(result.variants_used, ["原图"], "首轮即达标，不应升级到其它预处理")

    def test_all_decoded_codes_are_layer1_particles(self) -> None:
        result = decode_file(PHOTO, expected_min=6)
        self.assertEqual(list(result.by_layer().keys()), [1])
        self.assertEqual(len(result.by_layer()[1]), 6)

    def test_meets_recognition_latency_target(self) -> None:
        """识别耗时的回归护栏（宽松阈值）。

        单独跑这条链路时实测约 246ms（见 D-011），但**跑满整个测试套件时**
        会与摄像头线程、其余 190 项测试抢 CPU，中位数涨到 350ms 左右。
        在这种环境下断言 300ms 只会制造偶发红灯，测的是机器负载而不是识别能力。

        因此这里用宽松阈值挡住真正的性能退化；
        严格的 300ms 指标放在 `tools/smoke_test.py` 里单独测量（那里没有并发干扰）。
        """

        decode_file(PHOTO, expected_min=6)  # 预热，排除导入开销
        samples = sorted(decode_file(PHOTO, expected_min=6).elapsed_ms for _ in range(3))
        median = samples[len(samples) // 2]
        self.assertLess(median, 700.0, f"中位数 {median:.1f} ms，三次采样 {samples}")

    def test_default_max_width_is_applied(self) -> None:
        self.assertEqual(DEFAULT_MAX_WIDTH, 1920)

    def test_full_resolution_exposes_the_phantom_but_never_accepts_it(self) -> None:
        """全分辨率会解出幻影码，这是真实的解码伪影。

        它同样是 8206233 开头的 20 位数字，能通过格式与前缀校验，
        所以必须由"同区域冲突"把它拦住 —— 而且**两个值都不能被自动采信**，
        宁可要求重扫，也不静默绑定一个可能是错的码。

        断言不引用任何写死的条码值（理由见文件头），只校验冲突的行为与结构。
        """

        result = decode_frame(self.image, expected_min=6, max_width=0)

        self.assertEqual(len(result.conflicts), 1, "全分辨率下应恰好有一处同区域冲突")
        conflict = result.conflicts[0]

        conflicted = list(dict.fromkeys(conflict.candidates))
        self.assertEqual(len(conflicted), 2, f"冲突区域应有两个互斥候选，实际 {conflicted}")
        for code in conflicted:
            self.assertRegex(code, PARTICLE_CODE_PATTERN, "冲突候选都应是 20 位粒子码")
            self.assertNotIn(code, result.codes, "冲突候选一个都不能被自动采信")

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
