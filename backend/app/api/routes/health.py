from __future__ import annotations

import platform
import sys

from fastapi import APIRouter

from ... import __version__
from ...schemas.batch import GoldenInfoPayload
from ...services import golden

router = APIRouter(tags=["health"])


@router.get("/health", summary="服务健康检查")
def health() -> dict[str, object]:
    """报告服务状态，并顺带验证黄金基准是否仍然字节级一致。

    基准一旦被改坏，健康检查会直接暴露（goldenOk=False），
    而不是等到导出阶段才发现。
    """

    infos = golden.inspect_all()
    return {
        "status": "ok",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "goldenDir": str(golden.GOLDEN_DIR),
        "goldenOk": all(info.roundtrip_ok for info in infos),
        "golden": [
            GoldenInfoPayload(**info.to_dict()).model_dump(by_alias=True) for info in infos
        ],
    }
