"""手机拍照上传（阶段 3）：照片 → 识别 → 会话状态机。

用的就是现场实拍的那张标签照片（`private/条形码.jpg`），
所以这条测试同时证明了"上传路径"与"识别管线"在真实图上都成立。
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

try:  # 标准用法：python -m unittest discover -s tests -t .
    from tests.support import TempDatabaseTestCase, resolve_photo
except ImportError:  # 直接以 tests 为顶层目录运行时
    from support import TempDatabaseTestCase, resolve_photo

PHOTO = resolve_photo()
BOX = "80217619000000001003"
CAN = "80217629000000001005"

# 照片已随 private/ 移出公开仓库：拿不到就 skip，而不是让整个套件收集失败。
needs_photo = unittest.skipIf(PHOTO is None, "缺少现场实拍照片（已从公开仓库移出）")


def jpeg_bytes(width: int, height: int) -> bytes:
    import cv2
    import numpy as np

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    assert ok
    return encoded.tobytes()


class CaptureUploadTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        self.photo = PHOTO.read_bytes() if PHOTO is not None else b""

    def upload(self, data: bytes, *, filename: str = "photo.jpg", batch_id: str = ""):
        return self.client.post(
            "/api/capture/upload",
            files={"photo": (filename, data, "image/jpeg")},
            data={"batchId": batch_id},
        )

    def make_scanning_batch(self, *, plan: list[int], box: str, can: str, can_count: int = 1) -> str:
        payload = {
            "batchNo": "CAP001",
            "madeDate": "2026-09-26",
            "validateDate": "2026-10-26",
            "plannedParticleCounts": plan,
            "box": {
                "code": box,
                "cans": [
                    {"index": index + 1, "code": can if index == 0 else "", "plannedParticleCount": plan[index], "particles": []}
                    for index in range(can_count)
                ],
            },
        }
        created = self.client.post("/api/batches", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        moved = self.client.post(f"/api/batches/{batch_id}/status", json={"target": "collecting"})
        self.assertEqual(moved.status_code, 200, moved.text)
        return batch_id

    # ---------------------------------------------------------------- 识别
    @needs_photo
    def test_photo_recognises_particle_codes(self) -> None:
        response = self.upload(self.photo, filename=PHOTO.name)
        self.assertEqual(response.status_code, 200, response.text)
        capture = response.json()["capture"]
        codes = capture["codes"]
        self.assertEqual(len(codes), 6, capture)
        self.assertTrue(all(code.startswith("8206233") for code in codes), codes)
        self.assertEqual(capture["conflicts"], [])
        # 现场照片是竖幅 3072×4096
        self.assertEqual((capture["width"], capture["height"]), (3072, 4096))
        self.assertEqual(capture["variantsUsed"], ["原图"])

    @needs_photo
    def test_upload_without_batch_does_not_touch_state(self) -> None:
        """不带批次号时只识别，不写入任何批次 —— 手机在设置页试拍就是这条路径。"""

        response = self.upload(self.photo, filename=PHOTO.name)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["capture"]["snapshot"])

    # ------------------------------------------------------------ 状态机
    @needs_photo
    def test_upload_fills_six_particles_in_one_frame(self) -> None:
        batch_id = self.make_scanning_batch(plan=[6], box=BOX, can=CAN)
        before = self.client.get(f"/api/scan/{batch_id}/session").json()
        self.assertEqual(before["status"], "particle_scanning")

        response = self.upload(self.photo, filename=PHOTO.name, batch_id=batch_id)
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()["capture"]["snapshot"]
        self.assertEqual(snapshot["actualParticleTotal"], 6)
        self.assertEqual(snapshot["status"], "can_review")
        self.assertEqual(snapshot["remainingInCan"], 0)
        self.assertEqual(snapshot["canParticles"][0], response.json()["capture"]["codes"])

    @needs_photo
    def test_many_codes_at_box_step_are_rejected(self) -> None:
        """拍箱号时一张纸多枚 → 多码报警，整帧不写入（与电脑端同一规则）。"""

        batch_id = self.make_scanning_batch(plan=[6], box="", can="", can_count=1)
        response = self.upload(self.photo, filename=PHOTO.name, batch_id=batch_id)
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()["capture"]["snapshot"]
        self.assertEqual(snapshot["status"], "box_scanning")
        self.assertEqual(snapshot["lastEvent"]["code"], "MULTI_CODE")
        self.assertEqual(snapshot["pendingCode"], "")

    # -------------------------------------------------------------- 拒收
    def test_not_an_image_is_rejected(self) -> None:
        response = self.upload("这不是图片".encode("utf-8").ljust(4096, b"x"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["reason"], "PHOTO_INVALID")

    def test_oversized_photo_is_rejected(self) -> None:
        response = self.upload(b"\xff\xd8" + b"0" * (5 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 422)
        detail = response.json()["error"]["detail"]
        self.assertEqual(detail["reason"], "PHOTO_TOO_LARGE")
        self.assertTrue(detail["hint"])

    def test_tiny_photo_is_rejected(self) -> None:
        response = self.upload(jpeg_bytes(120, 120))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["reason"], "PHOTO_TOO_SMALL")

    @needs_photo
    def test_unknown_batch_is_rejected(self) -> None:
        response = self.upload(self.photo, batch_id="不存在的批次")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["reason"], "BATCH_NOT_FOUND")

    def test_empty_file_is_rejected(self) -> None:
        response = self.upload(b"")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["detail"]["reason"], "PHOTO_INVALID")


if __name__ == "__main__":
    unittest.main()
