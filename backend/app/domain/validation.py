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


def validate_batch(batch: Batch) -> list[BatchIssue]:
    """返回该批次的全部校验问题，按严重程度与出现顺序排列。"""

    issues: list[BatchIssue] = []

    # ---- 基础信息 ----
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

    # ---- 包装结构 ----
    can_count = batch.can_count
    if not MIN_CANS <= can_count <= MAX_CANS:
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "CAN_COUNT_RANGE",
                "box.cans",
                f"罐数必须在 {MIN_CANS}～{MAX_CANS} 之间，当前为 {can_count}。",
            )
        )

    # ---- 箱号 ----
    issues.extend(_check_code(batch.box.code, 3, "box.code"))

    # ---- 罐号与粒子 ----
    for can in batch.box.cans:
        prefix = f"box.cans[{can.index - 1}]"
        issues.extend(_check_code(can.code, 2, f"{prefix}.code"))

        if can.planned_particle_count < 1:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_PLAN_RANGE",
                    f"{prefix}.plannedParticleCount",
                    f"罐 {can.index} 的计划粒子数必须 ≥ 1，当前为 {can.planned_particle_count}。",
                )
            )
        elif can.planned_particle_count > MAX_PARTICLES_PER_CAN:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_PLAN_RANGE",
                    f"{prefix}.plannedParticleCount",
                    f"罐 {can.index} 的计划粒子数不得超过 {MAX_PARTICLES_PER_CAN}，"
                    f"当前为 {can.planned_particle_count}。",
                )
            )

        if len(can.particles) > can.planned_particle_count > 0:
            issues.append(
                BatchIssue(
                    SEVERITY_ERROR,
                    "PARTICLE_OVERFILL",
                    f"{prefix}.particles",
                    f"罐 {can.index} 计划 {can.planned_particle_count} 粒，"
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


def has_blocking_issue(issues: list[BatchIssue]) -> bool:
    return any(issue.severity == SEVERITY_ERROR for issue in issues)
