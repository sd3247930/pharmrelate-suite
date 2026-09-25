"""系统信息：本地库位置、schema 版本。

放在这里是为了让"数据库文件到底落在哪"可以被直接查到，
而不是靠翻代码猜。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...db import Database
from ..deps import get_database

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/storage", summary="本地库位置与 schema 版本")
def storage(database: Database = Depends(get_database)) -> dict[str, object]:
    return {
        "databasePath": str(database.path),
        "databaseDir": str(database.path.parent),
        "exists": database.path.is_file(),
        "schemaVersion": database.schema_version(),
    }
