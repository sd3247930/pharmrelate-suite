"""SQLite 连接与初始化。

数据库文件放在**用户数据目录**，不放安装目录 —— 安装目录通常无写权限，
且卸载/升级时容易被清掉。

解析顺序：
    1. 环境变量 PHARMRELATE_DATA_DIR
    2. Windows: %LOCALAPPDATA%\\PharmRelate Multi
       其他:    ~/.local/share/pharmrelate-multi
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "repositories" / "schema.sql"
DB_FILENAME = "pharmrelate.db"
SCHEMA_VERSION = "3"


def default_data_dir() -> Path:
    override = os.environ.get("PHARMRELATE_DATA_DIR")
    if override and override.strip():
        return Path(override)

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "PharmRelate Multi"
    return Path.home() / ".local" / "share" / "pharmrelate-multi"


def database_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / DB_FILENAME


class Database:
    """SQLite 数据库句柄。

    每次操作开一条新连接：FastAPI 的同步路由跑在线程池里，共享连接会出现
    跨线程使用问题；本地 SQLite 开连接的开销可以忽略，换来的是没有连接状态泄漏。
    WAL 模式让读写并发不互相阻塞。
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else database_path()
        self._init_lock = threading.Lock()
        self._initialised = False

    # ------------------------------------------------------------------ 连接

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialise(self) -> None:
        with self._init_lock:
            if self._initialised:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    (SCHEMA_VERSION,),
                )
            finally:
                connection.close()
            self._initialised = True

    # -------------------------------------------------------------- 事务封装

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """在一个事务里执行多条写语句；异常时整体回滚。"""

        self.initialise()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        self.initialise()
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------ 工具

    def schema_version(self) -> str | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        return row["value"] if row else None
