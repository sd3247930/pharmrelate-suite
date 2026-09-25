"""导出服务（阶段 4）。

三件事必须同时成立才算导出成功：
    1. 内容正确 —— XML 与阶段 0 冻结的基准**字节级一致**，不是"看起来对"；
    2. 闸门通过 —— 缺漏未签名等情况下拒绝导出（复用 ReviewService）；
    3. 可追溯 —— 每次导出留一条含 SHA-256 的不可变记录。

HTML 按 PRD 4.4.2 的模板结构生成：XML 原文放进 `white-space: pre-wrap` 的容器里，
浏览器打开即可看到与 XML 文件完全一致的字符。
"""

from __future__ import annotations

import hashlib
import html as html_escape
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..db import Database
from ..domain import batch_state as state
from ..repositories.audit_repository import AuditRepository
from ..repositories.batch_repository import BatchRepository
from ..services.review_service import EXPORT_KIND_EARLY_END, ReviewService
from ..services.xml_builder import render_bytes

KIND_XML = "xml"
KIND_HTML = "html"

EXPORTABLE_STATUSES: frozenset[str] = frozenset(
    {
        state.STATUS_VERIFIED,
        state.STATUS_EXPORTED,
        state.STATUS_LOCKED,
        state.STATUS_ARCHIVED,
    }
)
"""可导出的批次状态。

"已核对"之前的数据还没经过计划与实际核对，导出没有意义；
已归档仍允许导出（V1.1 8.2），但需要权限，权限体系在二期。
"""


class ExportBlockedError(RuntimeError):
    """导出被闸门拒绝。message 面向操作员。"""

    def __init__(self, message: str, *, detail: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_filename(batch_no: str, kind: str, *, at: datetime | None = None) -> str:
    """统一命名：Relation_{batchNo}_{yyyyMMddHHmmss}.{xml|html}（D-003）。"""

    stamp = (at or datetime.now()).strftime("%Y%m%d%H%M%S")
    return f"Relation_{batch_no}_{stamp}.{kind}"


def render_html(xml_text: str, batch_no: str) -> bytes:
    """按 PRD 4.4.2 的模板生成 HTML。

    模板结构与 PRD 中给出的完全一致，不额外加导航、按钮或样式系统的东西 ——
    这份 HTML 的用途是"用任意浏览器打开就能看到 XML 原文"，
    加得越多，与 XML 不一致的风险越大。
    """

    safe_batch = html_escape.escape(batch_no)
    safe_xml = html_escape.escape(xml_text, quote=False)
    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>包装关联关系导出 - 批号: {safe_batch}</title>
    <style>
        body {{ font-family: monospace; padding: 20px; background-color: #f5f5f5; }}
        .xml-container {{ background: #ffffff; padding: 15px; border: 1px solid #ccc; white-space: pre-wrap; word-break: break-all; }}
    </style>
</head>
<body>
    <h3>三级包装关联数据预览 (批号: {safe_batch})</h3>
    <div class="xml-container">{safe_xml}</div>
</body>
</html>
"""
    return document.encode("utf-8")


@dataclass(slots=True)
class ExportArtifact:
    kind: str
    filename: str
    content: bytes
    sha256: str
    byte_length: int
    record_id: str
    created_at: str
    export_kind: str
    path: str = ""

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.record_id,
            "kind": self.kind,
            "filename": self.filename,
            "sha256": self.sha256,
            "byteLength": self.byte_length,
            "createdAt": self.created_at,
            "exportKind": self.export_kind,
            # 相对于 API 根（前端会用 apiBaseUrl() 拼前缀），
            # 这里带上 /api 会让客户端拼成 /api/api/... 而 404。
            "downloadUrl": f"/exports/{self.record_id}/download",
            "storedAt": self.path,
        }
        if include_content:
            payload["content"] = self.content.decode("utf-8")
        return payload


class ExportService:
    def __init__(
        self,
        database: Database,
        repository: BatchRepository,
        audit: AuditRepository,
        review: ReviewService,
    ) -> None:
        self._db = database
        self._db.initialise()
        self._repository = repository
        self._audit = audit
        self._review = review
        self._lock = threading.RLock()
        self._cache: dict[str, ExportArtifact] = {}
        """最近一次导出的内容缓存，用于省掉一次磁盘读。真正的持久化是落盘。"""

    # ------------------------------------------------------------------ 落盘

    def export_dir(self, batch_no: str) -> Path:
        """导出目录：数据目录下的 exports/{batchNo}/。

        与数据库同在用户数据目录，因此覆盖安装、升级都不会影响已导出的文件；
        卸载也保留（D-033）。
        """

        return self._db.path.parent / "exports" / batch_no

    def _write_file(self, batch_no: str, filename: str, content: bytes) -> Path:
        directory = self.export_dir(batch_no)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename

        # 文件名精确到秒，同一秒内重复导出会重名。内容相同就直接复用文件；
        # 内容不同（例如同一秒内改过数据）则加序号，绝不覆盖已有文件 ——
        # 追溯链上"上一个导出被悄悄覆盖掉"是不可接受的。
        if path.exists():
            if path.read_bytes() == content:
                return path
            stem, suffix = path.stem, path.suffix
            counter = 2
            while path.exists():
                path = directory / f"{stem}_{counter}{suffix}"
                counter += 1
        path.write_bytes(content)

        actual = hashlib.sha256(content).hexdigest()

        # 落盘后重新读回并计算哈希：磁盘写入是最容易出问题的一环
        # （磁盘满、权限、杀软拦截），不校验就会出现
        # "记录说哈希是 X、文件其实是 Y"。
        written = hashlib.sha256(path.read_bytes()).hexdigest()
        if written != actual:
            raise ExportBlockedError(
                f"导出文件写入后校验失败：{path.name}",
                detail={"path": str(path), "expected": actual, "actual": written},
            )
        return path

    # ------------------------------------------------------------------ 闸门

    def _assert_exportable(self, record) -> str:
        if record.status not in EXPORTABLE_STATUSES:
            raise ExportBlockedError(
                f"批次当前状态为「{state.label_of(record.status)}」，"
                "需先完成「计划与实际核对」才能导出。",
                detail={
                    "reason": "STATUS_NOT_VERIFIED",
                    "status": record.status,
                    "statusLabel": state.label_of(record.status),
                    "hint": "在预览导出页完成核对：待核对 → 已核对。",
                },
            )

        review = self._review.review(record)
        if not review.can_export:
            raise ExportBlockedError(
                "核对未通过，导出已被禁止。",
                detail={
                    "reason": "REVIEW_BLOCKED",
                    "blocking": [item.to_dict() for item in review.blocking],
                },
            )
        return review.export_kind

    # ------------------------------------------------------------------ 导出

    def export(self, batch_id: str, kinds: list[str], *, operator: str = "local-user"):
        record = self._repository.get(batch_id)
        if record is None:
            raise ExportBlockedError(
                f"批次 {batch_id} 不存在。", detail={"batchId": batch_id}
            )

        wanted = [kind for kind in dict.fromkeys(kinds) if kind in (KIND_XML, KIND_HTML)]
        if not wanted:
            raise ExportBlockedError(
                "未指定导出格式。", detail={"available": [KIND_XML, KIND_HTML]}
            )

        with self._lock:
            export_kind = self._assert_exportable(record)
            batch = record.batch
            xml_bytes = render_bytes(batch)
            xml_text = xml_bytes.decode("utf-8")
            created_at = _now()

            artifacts: list[ExportArtifact] = []
            for kind in wanted:
                content = xml_bytes if kind == KIND_XML else render_html(xml_text, batch.batch_no)
                artifact = self._store(
                    batch_id=batch_id,
                    batch_no=batch.batch_no,
                    kind=kind,
                    export_kind=export_kind,
                    content=content,
                    particle_total=batch.actual_particle_total,
                    operator=operator,
                    created_at=created_at,
                )
                artifacts.append(artifact)

            self._audit.append(
                action="export",
                entity="batch",
                entity_id=batch_id,
                result="success",
                new_value={
                    "exportKind": export_kind,
                    "files": [
                        {
                            "kind": item.kind,
                            "filename": item.filename,
                            "sha256": item.sha256,
                            "byteLength": item.byte_length,
                        }
                        for item in artifacts
                    ],
                },
                reason="提前结束导出" if export_kind == EXPORT_KIND_EARLY_END else "正常导出",
            )

            # 首次成功导出后推进状态：verified → exported
            if record.status == state.STATUS_VERIFIED:
                self._repository.set_status(batch_id, state.STATUS_EXPORTED)

            return artifacts

    def _store(
        self,
        *,
        batch_id: str,
        batch_no: str,
        kind: str,
        export_kind: str,
        content: bytes,
        particle_total: int,
        operator: str,
        created_at: str,
    ) -> ExportArtifact:
        digest = hashlib.sha256(content).hexdigest()
        record_id = str(uuid.uuid4())
        filename = build_filename(batch_no, kind)
        path = self._write_file(batch_no, filename, content)
        # 落盘可能因重名而调整文件名，记录里必须写最终落盘的那个名字
        filename = path.name

        with self._db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO export_record
                    (id, batch_id, kind, export_kind, filename, sha256, byte_length,
                     batch_no, particle_total, operator, device_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'windows-main', ?)
                """,
                (
                    record_id,
                    batch_id,
                    kind,
                    export_kind,
                    filename,
                    digest,
                    len(content),
                    batch_no,
                    particle_total,
                    operator,
                    created_at,
                ),
            )

        artifact = ExportArtifact(
            kind=kind,
            filename=filename,
            content=content,
            sha256=digest,
            byte_length=len(content),
            record_id=record_id,
            created_at=created_at,
            export_kind=export_kind,
            path=str(path),
        )
        self._cache[record_id] = artifact
        return artifact

    # ------------------------------------------------------------------ 查询

    def history(self, batch_id: str, limit: int = 50) -> list[dict[str, object]]:
        with self._db.read() as connection:
            rows = connection.execute(
                """
                SELECT id, kind, export_kind, filename, sha256, byte_length, batch_no,
                       particle_total, operator, created_at
                FROM export_record WHERE batch_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (batch_id, max(1, min(limit, 500))),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "exportKind": row["export_kind"],
                "filename": row["filename"],
                "sha256": row["sha256"],
                "byteLength": row["byte_length"],
                "particleTotal": row["particle_total"],
                "operator": row["operator"],
                "createdAt": row["created_at"],
                "downloadUrl": f"/exports/{row['id']}/download",
                "storedAt": str(self.export_dir(row["batch_no"]) / row["filename"]),
            }
            for row in rows
        ]

    def artifact(self, record_id: str) -> ExportArtifact | None:
        cached = self._cache.get(record_id)
        if cached is not None:
            return cached

        # 缓存丢失（进程重启）时从磁盘读回 —— 落盘就是为了这一步
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT batch_no, kind, export_kind, filename, sha256, byte_length, "
                "created_at FROM export_record WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return None

        path = self.export_dir(row["batch_no"]) / row["filename"]
        if not path.is_file():
            return None

        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            # 文件被外部改动过：宁可报不可用，也不给出一份哈希对不上的文件
            return None

        artifact = ExportArtifact(
            kind=row["kind"],
            filename=row["filename"],
            content=content,
            sha256=row["sha256"],
            byte_length=row["byte_length"],
            record_id=record_id,
            created_at=row["created_at"],
            export_kind=row["export_kind"],
            path=str(path),
        )
        self._cache[record_id] = artifact
        return artifact

    def record_exists(self, record_id: str) -> bool:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT 1 FROM export_record WHERE id = ?", (record_id,)
            ).fetchone()
        return row is not None
