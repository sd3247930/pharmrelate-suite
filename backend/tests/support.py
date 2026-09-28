"""测试公共设施。

关键点：每个测试用例使用**独立的临时 SQLite 文件**，绝不能碰用户真实数据目录，
否则测试之间会互相污染，也会污染开发机上正在使用的库。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 app.main 之前设置：该模块在导入时就会构建一个默认 app 并打印日志，
# 测试里每个用例都会构建新 app，不降级会把输出淹没。
os.environ.setdefault("PHARMRELATE_LOG_LEVEL", "WARNING")

from app.db import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import golden  # noqa: E402
from app.services.xml_parser import parse_bytes  # noqa: E402

PRIVATE_DIR = BACKEND_DIR.parent / "private"

PHOTO_CANDIDATES: tuple[str, ...] = (
    "条形码.jpg",
    "微信图片_20260920122532_2236_7.jpg",
)
"""现场实拍的标签照片（**本地夹具，不在公开仓库里**）。

这张照片含真实药品追溯码，已于 2026-09-28 随 `private/` 一起移出公开仓库，
所以新克隆的机器上根本没有它。允许改名，因此按候选名依次找。

处理策略（2026-09-29 调整）：
  找不到时**不再在收集阶段抛异常** —— 那会让整个后端测试套件一项都跑不起来。
  改成返回 None + 打印醒目提示，由各测试模块自己 skip 掉依赖照片的用例。
  跳过依旧是**响亮的**：stderr 有横幅、pytest 汇总里有 skipped 计数，
  不会出现「19 项识别测试悄悄消失却没人发现」。
"""


def resolve_photo() -> Path | None:
    """现场照片路径；本地没有就返回 None（调用方负责 skip）。"""
    override = os.environ.get("PHARMRELATE_PHOTO", "").strip()
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
    for name in PHOTO_CANDIDATES:
        candidate = PRIVATE_DIR / name
        if candidate.is_file():
            return candidate
    return None


def require_photo() -> Path:
    """严格版：拿不到照片直接抛错。给「必须跑真图」的工具脚本用。"""
    photo = resolve_photo()
    if photo is None:
        raise FileNotFoundError(
            "找不到实拍标签照片。已尝试："
            + "、".join(PHOTO_CANDIDATES)
            + f"。照片含真实追溯码，已从公开仓库移出；本地复现请把它放回 {PRIVATE_DIR}，"
            "或用环境变量 PHARMRELATE_PHOTO 指向图片文件。"
        )
    return photo


if resolve_photo() is None:
    print(
        "\n"
        + "=" * 74
        + "\n[提示] 找不到现场实拍照片（private/条形码.jpg）。"
        "\n       该照片含真实药品追溯码，已随 private/ 移出公开仓库，新克隆的机器上不会有。"
        "\n       依赖它的识别 / 摄像头用例会被 **skip 并计入 skipped**，不是静默通过。"
        "\n       本地要跑真图用例：把照片放回 private\\，或设 PHARMRELATE_PHOTO=<图片路径>。"
        "\n" + "=" * 74 + "\n",
        file=sys.stderr,
    )


class TempDatabaseTestCase(unittest.TestCase):
    """为每个用例准备一个临时 SQLite 库，并在结束后清理。"""

    _tempdir: tempfile.TemporaryDirectory[str]
    database: Database

    def setUp(self) -> None:
        super().setUp()
        self._tempdir = tempfile.TemporaryDirectory(prefix="pharmrelate-test-")
        self.database = Database(Path(self._tempdir.name) / "test.db")

    def tearDown(self) -> None:
        self._tempdir.cleanup()
        super().tearDown()

    def make_app(self):
        return create_app(database=self.database)


def golden_batch_payload(batch_no: str = "20260901") -> dict[str, object]:
    """用 1箱3罐 基准的结构构造一份合法请求体。

    同时带上包装结构计划（每罐计划粒子数），因为 draft → collecting
    要求计划完整；实际条码则来自基准文件。
    """

    batch = parse_bytes(golden.read_bytes("1箱3罐.xml"))
    return {
        "batchNo": batch_no,
        "madeDate": batch.made_date,
        "validateDate": batch.validate_date,
        "plannedParticleCounts": [len(can.particles) for can in batch.box.cans],
        "box": {
            "code": batch.box.code,
            "cans": [
                {
                    "index": can.index,
                    "code": can.code,
                    "plannedParticleCount": len(can.particles),
                    "particles": list(can.particles),
                }
                for can in batch.box.cans
            ],
        },
    }
