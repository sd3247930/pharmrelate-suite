"""oplog 增量的序列化与读取。

**字段与一期 `oplog` 表一一对应，不新增字段、不改表结构。**
同步层只消费这张表，不改变一期的写入语义。

一期的表结构（schema.sql）：
    op_id / batch_id / entity / entity_id / action / field
    old_value / new_value / hlc / device_id / user_id / timestamp / synced
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..db import Database

ENTITY_BATCH = "batch"
ENTITY_BOX = "box"
ENTITY_CAN = "can"
ENTITY_PARTICLE = "particle"
ENTITIES = (ENTITY_BATCH, ENTITY_BOX, ENTITY_CAN, ENTITY_PARTICLE)

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTION_REPLACE = "replace"
ACTIONS = (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE, ACTION_REPLACE)


class OplogError(ValueError):
    """oplog 记录不符合约定。"""


@dataclass(slots=True)
class OplogEntry:
    """一条操作记录。字段与一期表结构同名同义。"""

    op_id: str
    batch_id: str
    entity: str
    entity_id: str
    action: str
    hlc: str
    device_id: str
    user_id: str
    timestamp: str
    field: str | None = None
    old_value: object = None
    new_value: object = None
    synced: bool = False

    def validate(self) -> None:
        if self.entity not in ENTITIES:
            raise OplogError(f"未知实体类型 {self.entity!r}，应为 {ENTITIES}")
        if self.action not in ACTIONS:
            raise OplogError(f"未知操作 {self.action!r}，应为 {ACTIONS}")
        if not self.op_id or not self.batch_id:
            raise OplogError("op_id 与 batch_id 不能为空")
        if not self.hlc:
            # 没有 HLC 就无法在多端间定序，宁可拒绝也不要产生一条无法合并的记录
            raise OplogError(f"oplog {self.op_id} 缺少 hlc，无法参与冲突仲裁")

    def to_dict(self) -> dict[str, object]:
        """序列化为信封载荷。字段名与表结构一致，便于两端对照。"""

        return {
            "opId": self.op_id,
            "batchId": self.batch_id,
            "entity": self.entity,
            "entityId": self.entity_id,
            "action": self.action,
            "field": self.field,
            "oldValue": self.old_value,
            "newValue": self.new_value,
            "hlc": self.hlc,
            "deviceId": self.device_id,
            "userId": self.user_id,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> OplogEntry:
        return cls(
            op_id=str(data.get("opId") or ""),
            batch_id=str(data.get("batchId") or ""),
            entity=str(data.get("entity") or ""),
            entity_id=str(data.get("entityId") or ""),
            action=str(data.get("action") or ""),
            field=(str(data["field"]) if data.get("field") else None),
            old_value=data.get("oldValue"),
            new_value=data.get("newValue"),
            hlc=str(data.get("hlc") or ""),
            device_id=str(data.get("deviceId") or ""),
            user_id=str(data.get("userId") or ""),
            timestamp=str(data.get("timestamp") or ""),
            synced=bool(data.get("synced", False)),
        )

    @classmethod
    def from_scan_op(cls, op: dict[str, object]) -> OplogEntry:
        """把扫码走线上的简易 `op`（code / packLayer / batchId）转成 oplog 记录。

        一期的扫码提交载荷很薄（只有条码与层级），同步层要把它补成完整 oplog：
        `entity` 由 `packLayer` 推出，`action` 固定为 `create`。
        """

        layer = int(op.get("packLayer") or 0)  # type: ignore[arg-type]
        entity = {3: ENTITY_BOX, 2: ENTITY_CAN, 1: ENTITY_PARTICLE}.get(layer)
        if entity is None:
            raise OplogError(f"无法由 packLayer={layer} 推出实体类型")

        code = str(op.get("code") or "")
        batch_id = str(op.get("batchId") or "")
        entry = cls(
            op_id=str(op.get("opId") or f"{batch_id}:{entity}:{code}"),
            batch_id=batch_id,
            entity=entity,
            entity_id=code,
            action=ACTION_CREATE,
            hlc=str(op.get("hlc") or ""),
            device_id=str(op.get("deviceId") or ""),
            user_id=str(op.get("userId") or ""),
            timestamp=str(op.get("timestamp") or ""),
            new_value={"code": code, "packLayer": layer},
        )
        return entry


class OplogStore:
    """一期 `oplog` 表的读写。

    `pending()` 是增量同步的取数口：只取 `synced = 0` 的记录，按 HLC 升序 ——
    **必须按 HLC 升序而不是插入顺序**，因为离线期间写入的 `rowid` 顺序
    与真实发生顺序可能不同（例如时钟回拨或补录）。
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.initialise()

    def append(self, entry: OplogEntry) -> None:
        entry.validate()
        with self._db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO oplog
                    (op_id, batch_id, entity, entity_id, action, field,
                     old_value, new_value, hlc, device_id, user_id, timestamp, synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (op_id) DO NOTHING
                """,
                (
                    entry.op_id,
                    entry.batch_id,
                    entry.entity,
                    entry.entity_id,
                    entry.action,
                    entry.field,
                    _dump(entry.old_value),
                    _dump(entry.new_value),
                    entry.hlc,
                    entry.device_id,
                    entry.user_id,
                    entry.timestamp,
                    1 if entry.synced else 0,
                ),
            )

    def pending(self, batch_id: str, limit: int = 500) -> list[OplogEntry]:
        with self._db.read() as connection:
            rows = connection.execute(
                """
                SELECT op_id, batch_id, entity, entity_id, action, field,
                       old_value, new_value, hlc, device_id, user_id, timestamp, synced
                FROM oplog
                WHERE batch_id = ? AND synced = 0
                ORDER BY hlc ASC
                LIMIT ?
                """,
                (batch_id, max(1, min(limit, 5000))),
            ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def mark_synced(self, op_ids: list[str]) -> int:
        if not op_ids:
            return 0
        with self._db.transaction() as connection:
            placeholders = ",".join("?" for _ in op_ids)
            cursor = connection.execute(
                f"UPDATE oplog SET synced = 1 WHERE op_id IN ({placeholders})", op_ids
            )
        return int(cursor.rowcount or 0)

    def count(self, batch_id: str, *, synced: bool | None = None) -> int:
        sql = "SELECT COUNT(*) AS total FROM oplog WHERE batch_id = ?"
        params: list[object] = [batch_id]
        if synced is not None:
            sql += " AND synced = ?"
            params.append(1 if synced else 0)
        with self._db.read() as connection:
            return int(connection.execute(sql, params).fetchone()["total"])


def _dump(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(value: object) -> object:
    if value is None or value == "":
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        # 一期写入的旧值可能是裸字符串，按原值返回而不是抛错
        return value


def _row_to_entry(row) -> OplogEntry:
    return OplogEntry(
        op_id=row["op_id"],
        batch_id=row["batch_id"],
        entity=row["entity"],
        entity_id=row["entity_id"],
        action=row["action"],
        field=row["field"],
        old_value=_load(row["old_value"]),
        new_value=_load(row["new_value"]),
        hlc=row["hlc"],
        device_id=row["device_id"],
        user_id=row["user_id"],
        timestamp=row["timestamp"],
        synced=bool(row["synced"]),
    )
