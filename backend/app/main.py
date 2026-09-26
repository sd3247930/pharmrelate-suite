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
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import api_router
from .api.errors import register_exception_handlers
from .db import Database
from .logging_config import configure_logging
from .repositories.sqlite_repository import SqliteBatchRepository
from .repositories.audit_repository import AuditRepository
from .services.scan_service import ScanService
from .services.camera import CameraManager
from .services.scan_history import ScanHistoryService
from .services.review_service import ReviewService
from .services.export_service import ExportService

logger = logging.getLogger("pharmrelate.api")

DEFAULT_PORT = 17800

# 打包态由桌面壳通过该变量把前端产物目录交给服务端，由服务端托管。
# 这样 Electron 可以直接 loadURL(http://127.0.0.1:<port>/)，与 /api 同源：
# 既没有 file:// 下绝对路径 404（白屏），也没有跨源拦截（CORS）。
# 开发态不设该变量，前端仍由 Vite dev server 提供。
FRONTEND_DIR_ENV = "PHARMRELATE_FRONTEND_DIR"

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


def _frontend_dir() -> str | None:
    """前端产物目录；未配置或不可用时返回 None（退回不托管）。"""

    raw = os.environ.get(FRONTEND_DIR_ENV, "").strip()
    if not raw:
        return None
    if not os.path.isdir(raw):
        logger.warning("前端目录不存在，跳过静态托管：%s", raw)
        return None
    if not os.path.isfile(os.path.join(raw, "index.html")):
        logger.warning("前端目录缺少 index.html，跳过静态托管：%s", raw)
        return None
    return raw


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("PharmRelate 本地服务已启动，版本 %s", __version__)
    yield
    logger.info("PharmRelate 本地服务已停止")


def create_app(database: Database | None = None) -> FastAPI:
    configure_logging(os.environ.get("PHARMRELATE_LOG_LEVEL", "INFO"))

    app = FastAPI(
        title="籽关通 (PharmRelate Multi) 本地服务",
        description="三级包装（箱 → 罐 → 粒子）关联采集与导出。一期：Windows 单机闭环。",
        version=__version__,
        lifespan=_lifespan,
    )

    # 数据库文件默认放在用户数据目录，不放安装目录
    # （安装目录通常无写权限，且卸载/升级容易把它清掉）。
    app.state.database = database or Database()
    app.state.batch_repository = SqliteBatchRepository(app.state.database)
    app.state.audit_repository = AuditRepository(app.state.database)
    app.state.scan_service = ScanService(
        app.state.batch_repository, app.state.audit_repository
    )
    app.state.camera_manager = CameraManager()
    app.state.camera_manager.attach_scan_service(app.state.scan_service)
    app.state.scan_history = ScanHistoryService(
        app.state.database,
        app.state.batch_repository,
        app.state.audit_repository,
    )
    app.state.review_service = ReviewService(app.state.scan_service)
    app.state.export_service = ExportService(
        app.state.database,
        app.state.batch_repository,
        app.state.audit_repository,
        app.state.review_service,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    # 静态托管必须挂在 API 路由之后：Starlette 按注册顺序匹配，
    # 挂在 "/" 上的 Mount 会吞掉一切路径，放在前面就会把 /api/* 一起吃掉。
    frontend_dir = _frontend_dir()
    if frontend_dir is not None:
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
        logger.info("前端静态托管已启用：%s", frontend_dir)

    logger.info("本地库：%s", app.state.database.path)

    return app


app = create_app()
