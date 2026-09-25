"""FastAPI 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from .routes import audit, batches, camera, golden, health, scan, system, xml_export

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(golden.router)
api_router.include_router(xml_export.router)
api_router.include_router(batches.router)
api_router.include_router(scan.router)
api_router.include_router(camera.router)
api_router.include_router(audit.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
