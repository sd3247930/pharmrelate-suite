"""依赖注入。

仓储挂在 `app.state` 上，而不是模块级单例 —— 否则同一进程内的多个
应用实例（尤其是测试）会共享数据，造成互相污染。
"""

from __future__ import annotations

from fastapi import Request

from ..db import Database
from ..repositories.audit_repository import AuditRepository
from ..repositories.batch_repository import BatchRepository
from ..services.scan_service import ScanService
from ..services.camera import CameraManager
from ..services.scan_history import ScanHistoryService
from ..services.review_service import ReviewService


def get_batch_repository(request: Request) -> BatchRepository:
    return request.app.state.batch_repository


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_audit_repository(request: Request) -> AuditRepository:
    return request.app.state.audit_repository


def get_scan_service(request: Request) -> ScanService:
    return request.app.state.scan_service


def get_camera_manager(request: Request) -> CameraManager:
    return request.app.state.camera_manager


def get_scan_history(request: Request) -> ScanHistoryService:
    return request.app.state.scan_history


def get_review_service(request: Request) -> ReviewService:
    return request.app.state.review_service
