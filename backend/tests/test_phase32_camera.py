"""阶段 3.2 第二批：可插拔帧源与摄像头管理器。

没有真实摄像头，所以验证靠 `TestImageFrameSource` 喂**真实照片**：
这条链路里没有一处是模拟数据——喂的是现场实拍，走的是同一套识别与状态机。
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR, TempDatabaseTestCase, resolve_photo
except ImportError:
    from support import BACKEND_DIR, TempDatabaseTestCase, resolve_photo

from fastapi.testclient import TestClient

from app.services.frame_source import (
    SOURCE_OPENCV,
    SOURCE_TEST_IMAGE,
    FrameSourceError,
    OpenCVFrameSource,
    TestImageFrameSource,
    create_frame_source,
)
from app.services.recognition import DEFAULT_MAX_WIDTH

PHOTO = resolve_photo()

BOX = "80217619000000001003"
CAN1 = "80217629000000001005"


class FrameSourceFactoryTests(unittest.TestCase):
    def test_unknown_kind_is_rejected_with_hint(self) -> None:
        with self.assertRaises(FrameSourceError) as ctx:
            create_frame_source("并不存在的源")
        self.assertIn("可用类型", ctx.exception.hint)

    def test_factory_builds_both_sources(self) -> None:
        opencv = create_frame_source(SOURCE_OPENCV, device_index=1)
        self.assertIsInstance(opencv, OpenCVFrameSource)
        self.assertEqual(opencv.metadata()["deviceIndex"], 1)

        test_source = create_frame_source(
            SOURCE_TEST_IMAGE, images=[Path("x.jpg")], max_width=1024
        )
        self.assertIsInstance(test_source, TestImageFrameSource)
        self.assertEqual(test_source.metadata()["maxWidth"], 1024)

    def test_default_max_width_is_shared_with_recognition(self) -> None:
        """帧源与识别必须用同一个分辨率上限，否则阈值就白标了。"""

        self.assertEqual(DEFAULT_MAX_WIDTH, 1920)
        self.assertEqual(
            create_frame_source(SOURCE_OPENCV).metadata()["maxWidth"], 1920
        )

    def test_opencv_source_reports_actionable_error_when_no_camera(self) -> None:
        """没有摄像头时不能只抛一句失败，要告诉操作员怎么处理。"""

        source = OpenCVFrameSource(device_index=9)
        try:
            source.open()
        except FrameSourceError as exc:
            self.assertIn("摄像头", str(exc))
            self.assertTrue(exc.hint, "应给出可操作的排查建议")
        else:
            # 环境里恰好有第 10 个设备：直接释放，不判失败
            self.assertTrue(source.is_open())
            source.close()


@unittest.skipUnless(PHOTO.is_file(), f"缺少真实照片：{PHOTO}")
class TestImageSourceTests(unittest.TestCase):
    def test_reads_frames_in_a_loop(self) -> None:
        source = TestImageFrameSource([PHOTO])
        source.open()
        try:
            first = source.read()
            second = source.read()
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first and second
            self.assertEqual(first.image.shape, second.image.shape)
            self.assertEqual(second.index, first.index + 1, "帧序号应递增")
            self.assertEqual(first.source, SOURCE_TEST_IMAGE)
        finally:
            source.close()

    def test_width_is_normalised_to_max_width(self) -> None:
        source = TestImageFrameSource([PHOTO], max_width=1280)
        source.open()
        try:
            frame = source.read()
            assert frame is not None
            self.assertEqual(frame.image.shape[1], 1280)
            self.assertEqual(source.metadata()["width"], 1280)
        finally:
            source.close()

    def test_missing_image_is_reported(self) -> None:
        source = TestImageFrameSource([Path("并不存在.jpg")])
        with self.assertRaises(FrameSourceError):
            source.open()

    def test_empty_source_cannot_be_built(self) -> None:
        with self.assertRaises(FrameSourceError):
            TestImageFrameSource([])


@unittest.skipUnless(PHOTO.is_file(), f"缺少真实照片：{PHOTO}")
class CameraManagerTests(TempDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.camera = self.app.state.camera_manager

    def tearDown(self) -> None:
        self.camera.stop()
        super().tearDown()

    def _wait_for(self, predicate, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.1)
        return False

    def test_status_before_start(self) -> None:
        body = self.client.get("/api/camera/status").json()
        self.assertFalse(body["running"])
        self.assertEqual(body["source"], "none")

    def test_start_with_test_source_produces_frames_and_detections(self) -> None:
        response = self.client.post(
            "/api/camera/start",
            json={
                "kind": SOURCE_TEST_IMAGE,
                "images": [str(PHOTO)],
                "maxWidth": 1280,
                "recognizeIntervalMs": 100,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["running"])

        self.assertTrue(
            self._wait_for(lambda: self.client.get("/api/camera/frame.jpg").status_code == 200),
            "应能取到 JP/EG 帧",
        )
        self.assertTrue(
            self._wait_for(
                lambda: (self.client.get("/api/camera/detections").json()["detection"] or {}).get(
                    "accepted"
                )
            ),
            "应产生识别结果",
        )

        detection = self.client.get("/api/camera/detections").json()["detection"]
        codes = set(detection["codes"])
        self.assertEqual(len(codes), 6, f"真实照片应解出 6 枚标签，实际 {sorted(codes)}")

        status = self.client.get("/api/camera/status").json()
        self.assertGreater(status["framesRead"], 0)
        self.assertGreater(status["recognitions"], 0)
        self.assertEqual(status["metadata"]["width"], 1280)

    def test_detection_applies_to_bound_batch(self) -> None:
        """绑定批次后，识别结果直接进状态机 —— 前端不必再中转一次。"""

        created = self.client.post(
            "/api/batches",
            json={
                "batchNo": "CAM-0001",
                "madeDate": "2026-09-23",
                "validateDate": "2026-10-23",
                "plannedParticleCounts": [2],
                "box": {"code": "", "cans": []},
            },
        ).json()
        batch_id = created["id"]
        self.client.post(f"/api/batches/{batch_id}/status", json={"target": "collecting"})

        self.client.post(
            "/api/camera/start",
            json={
                "kind": SOURCE_TEST_IMAGE,
                "images": [str(PHOTO)],
                "batchId": batch_id,
                "maxWidth": 1280,
                "recognizeIntervalMs": 100,
            },
        )

        # 照片上有 6 个码，而拍箱号要求画面里只有 1 个 → 先命中的是"多码报警"
        # （严格单码优先于层级校验，这是正确行为）
        self.assertTrue(
            self._wait_for(
                lambda: (self.client.get(f"/api/scan/{batch_id}/session").json().get("lastEvent") or {}).get(
                    "code"
                )
                == "MULTI_CODE"
            ),
            "6 个码在等箱号阶段应触发多码报警",
        )

        snapshot = self.client.get(f"/api/scan/{batch_id}/session").json()
        self.assertEqual(snapshot["status"], "box_scanning", "拦截后状态不变")
        self.assertEqual(snapshot["actualParticleTotal"], 0, "拦截时不写入任何数据")
        self.assertGreaterEqual(snapshot["alarmCount"], 1, "多码报警应计数")

        detail = self.client.get(f"/api/batches/{batch_id}").json()
        self.assertEqual(detail["data"]["box"]["code"], "")

    def test_start_with_bad_source_reports_error_not_crash(self) -> None:
        response = self.client.post(
            "/api/camera/start", json={"kind": "并不存在的源"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["running"])
        self.assertTrue(body["error"])
        self.assertTrue(body["hint"])

    def test_stop_is_idempotent(self) -> None:
        self.client.post(
            "/api/camera/start",
            json={"kind": SOURCE_TEST_IMAGE, "images": [str(PHOTO)], "maxWidth": 640},
        )
        first = self.client.post("/api/camera/stop").json()
        second = self.client.post("/api/camera/stop").json()
        self.assertFalse(first["running"])
        self.assertFalse(second["running"])

    def test_frame_endpoint_returns_204_before_first_frame(self) -> None:
        response = self.client.get("/api/camera/frame.jpg")
        self.assertEqual(response.status_code, 204)


class CameraApiSurfaceTests(TempDatabaseTestCase):
    def test_start_rejects_unknown_field(self) -> None:
        client = TestClient(self.make_app())
        response = client.post("/api/camera/start", json={"kind": "opencv", "typo": 1})
        self.assertEqual(response.status_code, 422)

    def test_start_rejects_out_of_range_interval(self) -> None:
        client = TestClient(self.make_app())
        response = client.post(
            "/api/camera/start", json={"kind": "opencv", "recognizeIntervalMs": 1}
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
