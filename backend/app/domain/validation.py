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


def validate_box_code(batch: Batch) -> list[BatchIssue]:
    """只校验箱号。

    箱号在基础信息页就可以录入，此时包装结构往往还是空的，
    因此这里采取"填了就检查、没填不追问"的规则。
    """

    if not batch.box.code.strip():
        return []
    return _check_code(batch.box.code, 3, "box.code")


def structure_started(batch: Batch) -> bool:
    """包装结构是否已经动笔。

    判定依据是**罐层面**有没有数据，而不是箱号：箱号在基础信息页就能填，
    它单独存在并不代表包装结构已经开始配置。
    """

    return any(
        can.code.strip() or can.particles or can.planned_particle_count
        for can in batch.box.cans
    )


def validate_can_structure(batch: Batch) -> list[BatchIssue]:
    """校验罐与粒子：罐数范围、罐号、计划粒子数、层级前缀、全局去重。"""

    issues: list[BatchIssue] = []

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


def validate_structure(batch: Batch) -> list[BatchIssue]:
    """严格模式：箱号必填 + 罐结构完整。

    只在"生成扫码网格"这类真正需要完整结构的时机使用，
    不能拿它当保存草稿的守门人，否则界面 1 一保存就会被拦。
    """

    issues: list[BatchIssue] = []
    if not batch.box.code.strip():
        issues.append(
            BatchIssue(
                SEVERITY_ERROR,
                "BOX_CODE_REQUIRED",
                "box.code",
                "生成扫码网格前必须填写箱号。",
            )
        )
    else:
        issues.extend(_check_code(batch.box.code, 3, "box.code"))
    issues.extend(validate_can_structure(batch))
    return issues


def validate_batch(batch: Batch, *, include_structure: bool = True) -> list[BatchIssue]:
    """返回该批次的全部校验问题，按严重程度与出现顺序排列。"""

    issues = validate_base_info(batch)
    if include_structure:
        issues.extend(validate_structure(batch))
    return issues


def validate_partial(batch: Batch) -> list[BatchIssue]:
    """保存草稿用的宽松校验：基础信息 + 已填写的部分。

    规则是"填了就检查、没填不追问"：
        - 基础信息：任何时候都必须合法
        - 箱号：填了就验证格式与前缀
        - 罐结构：只有真正动笔（罐号/粒子/计划数）才整体校验
    """

    issues = validate_base_info(batch)
    issues.extend(validate_box_code(batch))
    if structure_started(batch):
        issues.extend(validate_can_structure(batch))
    return issues


def has_blocking_issue(issues: list[BatchIssue]) -> bool:
    return any(issue.severity == SEVERITY_ERROR for issue in issues)
