"""批次数据校验（防错规则集中地）。

阶段 1 先落地"结构 + 条码层级"两类硬校验；阶段 3 再叠加扫码状态机相关的校验。
所有校验只返回问题清单，不抛异常，便于前端一次性展示全部问题。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .constants import (
    MAX_CANS,
    MAX_PARTICLES_PER_BATCH,
    MAX_PARTICLES_PER_CAN,
    MIN_CANS,
    classify_code,
    layer_label,
    looks_like_code,
)
from .models import Batch

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True, slots=True)
class BatchIssue:
    """一条校验问题。severity=error 时阻断导出。"""

    severity: str
    code: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "field": self.field,
            "message": self.message,
        }


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_code(value: str, expected_layer: int, field: str) -> list[BatchIssue]:
    issues: list[BatchIssue] = []

    if not looks_like_code(value):
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "CODE_FORMAT",
                field,
                f"条码 {value!r} 不是 20 位数字，无法识别。",
            )
        )
        return issues

    actual_layer = classify_code(value)
    if actual_layer != expected_layer:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "CODE_LAYER_MISMATCH",
                field,
                f"条码 {value} 的层级为「{layer_label(actual_layer)}」，"
                f"但此处需要「{layer_label(expected_layer)}」。",
            )
        )
    return issues


def validate_base_info(batch: Batch) -> list[BatchIssue]:
    """只校验界面 1 的基础信息。

    draft 状态的定义就是「界面 1 已保存，尚未生成包装结构」，
    因此这个阶段绝不能因为结构为空而拦下保存。
    """

    issues: list[BatchIssue] = []

    if not batch.batch_no.strip():
        issues.append(
            BatchIssue(SEVERITY_ERROR, "BATCH_NO_REQUIRED", "batchNo", "批号不能为空。")
        )

    made = _parse_date(batch.made_date)
    valid = _parse_date(batch.validate_date)
    if made is None:
        issues.append(
            BatchIssue(SEVERITY_ERROR, "DATE_FORMAT", "madeDate", f"生产日期 {batch.made_date!r} 不是 YYYY-MM-DD 格式。")
        )
    if valid is None:
        issues.append(
            BatchIssue(SEVERITY_ERROR, "DATE_FORMAT", "validateDate", f"有效期 {batch.validate_date!r} 不是 YYYY-MM-DD 格式。")
        )
    if made is not None and valid is not None and valid <= made:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "DATE_ORDER",
                "validateDate",
                f"有效期 {batch.validate_date} 必须晚于生产日期 {batch.made_date}。",
            )
        )

    return issues


def validate_plan(batch: Batch) -> list[BatchIssue]:
    """校验包装结构计划：罐数范围、每罐计划粒子数、单批次总量。

    这是界面 2 的产出，纯粹是计划，不含任何真实条码。
    """

    issues: list[BatchIssue] = []

    counts = batch.planned_particle_counts
    if not counts:
        # 还没有计划：允许（草稿阶段），由调用方决定是否要求完整
        return issues

    can_count = len(counts)
    if not MIN_CANS <= can_count <= MAX_CANS:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "CAN_COUNT_RANGE",
                "plannedParticleCounts",
                f"罐数必须在 {MIN_CANS}～{MAX_CANS} 之间，当前为 {can_count}。",
            )
        )

    for index, planned in enumerate(counts, start=1):
        if planned < 1:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_PLAN_RANGE",
                    f"plannedParticleCounts[{index - 1}]",
                    f"罐 {index} 的计划粒子数必须 ≥ 1，当前为 {planned}。",
                )
            )
        elif planned > MAX_PARTICLES_PER_CAN:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_PLAN_RANGE",
                    f"plannedParticleCounts[{index - 1}]",
                    f"罐 {index} 的计划粒子数不得超过 {MAX_PARTICLES_PER_CAN}，当前为 {planned}。",
                )
            )

    total = sum(counts)
    if total > MAX_PARTICLES_PER_BATCH:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "PARTICLE_TOTAL_RANGE",
                "plannedParticleCounts",
                f"计划总粒子数 {total} 已超过单批次上限 {MAX_PARTICLES_PER_BATCH}，请拆分为多个批次。",
            )
        )

    return issues


def _planned_for(batch: Batch, can_index: int) -> int:
    counts = batch.planned_particle_counts
    if 1 <= can_index <= len(counts):
        return counts[can_index - 1]
    if 1 <= can_index <= batch.can_count:
        return batch.box.cans[can_index - 1].planned_particle_count
    return 0


def validate_actual_codes(batch: Batch) -> list[BatchIssue]:
    """校验实际扫到的条码：箱号、罐号、粒子码的格式/层级/去重/溢出。"""

    issues: list[BatchIssue] = []

    if batch.box.code.strip():
        issues.extend(_check_code(batch.box.code, 3, "box.code"))

    for can in batch.box.cans:
        prefix = f"box.cans[{can.index - 1}]"
        if can.code.strip():
            issues.extend(_check_code(can.code, 2, f"{prefix}.code"))

        planned = _planned_for(batch, can.index)
        if planned and len(can.particles) > planned:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_OVERFILL",
                    f"{prefix}.particles",
                    f"罐 {can.index} 计划 {planned} 粒，"
                    f"实际录入 {len(can.particles)} 粒，已超计划。",
                )
            )

        for index, particle in enumerate(can.particles):
            issues.extend(_check_code(particle, 1, f"{prefix}.particles[{index}]"))

    total = batch.actual_particle_total
    if total > MAX_PARTICLES_PER_BATCH:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "PARTICLE_TOTAL_RANGE",
                "box",
                f"总粒子数 {total} 已超过单批次上限 {MAX_PARTICLES_PER_BATCH}，请拆分为多个批次。",
            )
        )

    # ---- 全局去重 ----
    for duplicate in batch.find_duplicate_codes():
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "DUPLICATE_CODE",
                "box",
                f"条码 {duplicate} 在本次数据中重复出现，请检查是否重复扫码。",
            )
        )

    return issues


def validate_structure(batch: Batch) -> list[BatchIssue]:
    """严格模式：计划完整（生成扫码网格用）。

    只在"生成扫码网格"这类真正需要完整计划的时机使用，
    不能拿它当保存草稿的守门人，否则界面 1 一保存就会被拦。
    """

    issues: list[BatchIssue] = []
    if not batch.planned_particle_counts:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "PLAN_REQUIRED",
                "plannedParticleCounts",
                "生成扫码网格前必须设定罐数与每罐粒子数。",
            )
        )
    issues.extend(validate_plan(batch))
    issues.extend(validate_actual_codes(batch))
    return issues


def validate_batch(batch: Batch, *, include_structure: bool = True) -> list[BatchIssue]:
    """返回该批次的全部校验问题，按严重程度与出现顺序排列。"""

    issues = validate_base_info(batch)
    if include_structure:
        issues.extend(validate_structure(batch))
    return issues


def validate_for_export(batch: Batch) -> list[BatchIssue]:
    """导出/预览时的校验：只看实际数据是否自洽。

    计划是否完整不影响 XML 渲染本身（计划不写进 XML），
    "缺漏禁止导出"的判定在阶段 3.5 单独实现。
    """

    return validate_base_info(batch) + validate_actual_codes(batch)


def validate_partial(batch: Batch) -> list[BatchIssue]:
    """保存草稿用的宽松校验：基础信息 + 已填写的部分。

    规则是"填了就检查、没填不追问"：
        - 基础信息：任何时候都必须合法
        - 箱号：填了就验证格式与前缀
        - 罐结构：只有真正动笔（罐号/粒子/计划数）才整体校验
    """

    issues = validate_base_info(batch)
    if batch.planned_particle_counts:
        issues.extend(validate_plan(batch))
    issues.extend(validate_actual_codes(batch))
    return issues


def has_blocking_issue(issues: list[BatchIssue]) -> bool:
    return any(issue.severity == SEVERITY_ERROR for issue in issues)
