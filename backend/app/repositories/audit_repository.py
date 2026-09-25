"""审计日志仓储。

审计日志不可删除、不可修改，只允许追加与查询（V1.1 12.4）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..db import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class AuditEntry:
    log_id: str
    user_id: str
    device_id: str
    timestamp: str
    action: str
    entity: str
    entity_id: str
    result: str
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "logId": self.log_id,
            "userId": self.user_id,
            "deviceId": self.device_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "entity": self.entity,
            "entityId": self.entity_id,
            "result": self.result,
            "oldValue": self.old_value,
            "newValue": self.new_value,
            "reason": self.reason,
        }


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.initialise()

    def append(
        self,
        *,
        action: str,
        entity: str,
        entity_id: str,
        result: str,
        old_value: Any = None,
        new_value: Any = None,
        reason: str | None = None,
        user_id: str = "local-user",
        device_id: str = "windows-main",
    ) -> AuditEntry:
        entry = AuditEntry(
            log_id=str(uuid.uuid4()),
            user_id=user_id,
            device_id=device_id,
            timestamp=_now(),
            action=action,
            entity=entity,
            entity_id=entity_id,
            result=result,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )

        with self._db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log
                    (log_id, user_id, device_id, timestamp, action, entity, entity_id,
                     old_value, new_value, result, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.log_id,
                    entry.user_id,
                    entry.device_id,
                    entry.timestamp,
                    entry.action,
                    entry.entity,
                    entry.entity_id,
                    json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
                    json.dumps(new_value, ensure_ascii=False) if new_value is not None else None,
                    entry.result,
                    entry.reason,
                ),
            )
        return entry

    def list(
        self,
        *,
        entity_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        sql = (
            "SELECT log_id, user_id, device_id, timestamp, action, entity, entity_id, "
            "old_value, new_value, result, reason FROM audit_log WHERE 1 = 1"
        )
        params: list[object] = []
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if action:
            sql += " AND action = ?"
            params.append(action)
        sql += " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))

        with self._db.read() as connection:
            rows = connection.execute(sql, params).fetchall()

        return [
            AuditEntry(
                log_id=row["log_id"],
                user_id=row["user_id"],
                device_id=row["device_id"],
                timestamp=row["timestamp"],
                action=row["action"],
                entity=row["entity"],
                entity_id=row["entity_id"],
                result=row["result"],
                old_value=json.loads(row["old_value"]) if row["old_value"] else None,
                new_value=json.loads(row["new_value"]) if row["new_value"] else None,
                reason=row["reason"],
            )
            for row in rows
        ]

    def count(self, *, entity_id: str | None = None, action: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS total FROM audit_log WHERE 1 = 1"
        params: list[object] = []
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if action:
            sql += " AND action = ?"
            params.append(action)
        with self._db.read() as connection:
            return int(connection.execute(sql, params).fetchone()["total"])
