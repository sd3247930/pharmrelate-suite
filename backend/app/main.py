"""FastAPI 应用入口。

启动：
    cd backend
    python -m uvicorn app.main:app --port 17800 --reload

OpenAPI 文档： http://127.0.0.1:17800/docs
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import api_router
from .api.errors import register_exception_handlers
from .logging_config import configure_logging
from .repositories.batch_repository import InMemoryBatchRepository

logger = logging.getLogger("pharmrelate.api")

DEFAULT_PORT = 17800

# Tauri 使用 tauri://localhost（Windows 上为 http://tauri.localhost），
# Electron 与 Vite 开发服务器用 http 本地源。二期移动端接入时再追加。
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://tauri.localhost",
    "tauri://localhost",
    "https://tauri.localhost",
)


def _allowed_origins() -> list[str]:
    raw = os.environ.get("PHARMRELATE_ALLOWED_ORIGINS", "")
    extra = [item.strip() for item in raw.split(",") if item.strip()]
    return [*DEFAULT_ALLOWED_ORIGINS, *extra]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("PharmRelate 本地服务已启动，版本 %s", __version__)
    yield
    logger.info("PharmRelate 本地服务已停止")


def create_app() -> FastAPI:
    configure_logging(os.environ.get("PHARMRELATE_LOG_LEVEL", "INFO"))

    app = FastAPI(
        title="籽关通 (PharmRelate Multi) 本地服务",
        description="三级包装（箱 → 罐 → 粒子）关联采集与导出。一期：Windows 单机闭环。",
        version=__version__,
        lifespan=_lifespan,
    )

    # 阶段 2 换成 SQLite 实现即可，路由层通过依赖注入获取，无需改动。
    app.state.batch_repository = InMemoryBatchRepository()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
