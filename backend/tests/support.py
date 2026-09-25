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
