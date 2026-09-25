"""FastAPI 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from .routes import batches, golden, health, system, xml_export

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(golden.router)
api_router.include_router(xml_export.router)
api_router.include_router(batches.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
