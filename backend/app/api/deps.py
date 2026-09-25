"""依赖注入。

仓储挂在 `app.state` 上，而不是模块级单例 —— 否则同一进程内的多个
应用实例（尤其是测试）会共享数据，造成互相污染。
"""

from __future__ import annotations

from fastapi import Request

from ..repositories.batch_repository import BatchRepository


def get_batch_repository(request: Request) -> BatchRepository:
    return request.app.state.batch_repository
