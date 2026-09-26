"""导入一期格式的关联关系 XML。

方向与导出让正好相反：把一份已存在的 XML 读回系统，落成一个批次，
让界面各字段（基础信息 / 包装结构 / 条码）就位。

三条设计决定：

1. **复用同一个解析器。** 用的是导出侧"基准往返一致"验证过的那一个
   （`xml_parser.parse_bytes`），严格策略：固定参数不符、层级未知、
   父子断裂一律拒绝，并给中文原因。属性顺序不参与校验 —— 属性顺序不是语义，
   导出时会规范化回基准顺序。
2. **计划由文件推断。** XML 里没有"计划"字段，只有已经采到的条码；
   导入一份完成的 XML，等于声明"实际结构就是计划结构"，
   因此 `planned_particle_counts = 每罐实际粒子数`。
3. **只新建批次。** 不覆盖已有批次（药品追溯不允许悄悄改历史），
   批号重复时把"三选一"交回给操作员，与创建草稿的行为一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import batch_state as state
from ..domain.validation import has_blocking_issue, validate_structure
from ..repositories.batch_repository import BatchRecord, BatchRepository
from .batch_creation import BatchNoDecision, decide_batch_no
from .xml_parser import XmlParseError, parse_bytes


@dataclass(frozen=True, slots=True)
class ImportSummary:
    """导入结果的摘要，用于界面上"导入了什么"的一行说明。"""

    source_name: str
    batch_no: str
    box_code: str
    can_count: int
    particle_total: int
    planned_particle_counts: list[int]
    status: str
    status_label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceName": self.source_name,
            "batchNo": self.batch_no,
            "boxCode": self.box_code,
            "canCount": self.can_count,
            "particleTotal": self.particle_total,
            "plannedParticleCounts": list(self.planned_particle_counts),
            "status": self.status,
            "statusLabel": self.status_label,
        }


class XmlImportRejected(Exception):
    """导入被拒绝：解析失败或结构校验未通过。问题清单随异常带出。"""

    def __init__(self, message: str, *, reason: str, issues: list[dict[str, object]]) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.issues = issues


class XmlImportConflict(Exception):
    """批号已被占用：把"三选一"上下文交回调用方。"""

    def __init__(self, message: str, *, detail: dict[str, object]) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


def _issue(code: str, field: str, message: str) -> dict[str, object]:
    return {"severity": "error", "code": code, "field": field, "message": message}


def parse_import(xml_bytes: bytes, *, source_name: str):
    """解析 + 推断计划 + 结构校验。返回可直接入库的 Batch。"""

    try:
        batch = parse_bytes(xml_bytes, source=source_name or "<导入的 XML>")
    except XmlParseError as exc:
        raise XmlImportRejected(
            "XML 不符合一期格式，已拒绝导入。",
            reason="XML_INVALID",
            issues=[_issue("XML_INVALID", "xml", str(exc))],
        ) from exc

    # 计划由文件推断：导入的是一份"结构已定"的 XML
    batch.planned_particle_counts = [len(can.particles) for can in batch.box.cans]

    issues = validate_structure(batch)
    if has_blocking_issue(issues):
        raise XmlImportRejected(
            "XML 结构校验未通过，已拒绝导入。",
            reason="STRUCTURE_INCOMPLETE",
            issues=[issue.to_dict() for issue in issues],
        )
    return batch


def import_batch(
    xml_bytes: bytes,
    *,
    source_name: str = "",
    repository: BatchRepository,
    force_new_version: bool = False,
) -> tuple[BatchRecord, ImportSummary]:
    """导入并新建批次。冲突与拒绝通过异常交回调用方。"""

    batch = parse_import(xml_bytes, source_name=source_name)

    decision: BatchNoDecision = decide_batch_no(
        repository, batch.batch_no, force_new_version=force_new_version
    )
    if decision.conflict is not None:
        raise XmlImportConflict(f"批号 {batch.batch_no} 已存在。", detail=decision.conflict)
    if decision.exhausted:  # pragma: no cover
        raise XmlImportConflict(
            f"新版本批号 {decision.batch_no} 已被占用，请重试。",
            detail={"reason": "BATCH_NO_EXISTS"},
        )
    batch.batch_no = decision.batch_no

    record = repository.create(batch, status=state.STATUS_DRAFT)
    summary = ImportSummary(
        source_name=source_name,
        batch_no=record.batch.batch_no,
        box_code=record.batch.box.code,
        can_count=record.batch.can_count,
        particle_total=record.batch.actual_particle_total,
        planned_particle_counts=list(record.batch.planned_particle_counts),
        status=record.status,
        status_label=state.label_of(record.status),
    )
    return record, summary
