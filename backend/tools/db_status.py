"""查看本地库位置与内容概况。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\db_status.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import Database  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    database = Database()
    print(f"本地库路径 : {database.path}")
    print(f"文件存在   : {database.path.is_file()}")
    if not database.path.is_file():
        return 0

    with database.read() as connection:
        for label, sql in (
            ("schema 版本", "SELECT value FROM meta WHERE key = 'schema_version'"),
            ("批次行数", "SELECT COUNT(*) FROM batch WHERE deleted = 0"),
            ("条码行数", "SELECT COUNT(*) FROM code WHERE deleted = 0"),
            ("oplog 行数", "SELECT COUNT(*) FROM oplog"),
            ("审计行数", "SELECT COUNT(*) FROM audit_log"),
        ):
            value = connection.execute(sql).fetchone()[0]
            print(f"{label:<12}: {value}")

        rows = connection.execute(
            "SELECT batch_no, status, updated_at FROM batch WHERE deleted = 0 "
            "ORDER BY updated_at DESC LIMIT 10"
        ).fetchall()

    if rows:
        print("\n最近批次：")
        for row in rows:
            print(f"  {row['batch_no']:<20} {row['status']:<15} {row['updated_at']}")
    else:
        print("\n（暂无批次）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
