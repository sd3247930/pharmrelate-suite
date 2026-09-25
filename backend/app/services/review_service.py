"""整体核对与导出闸门（阶段 3.5）。

核对的原则是**计划 vs 实际逐罐对照**，而不是给一个"完成"了事：
缺漏必须能指出缺在哪一罐、缺几个，否则操作员无从补救。

导出闸门是硬规则，不是界面提示：
    实际粒子数少于计划 → 禁止导出，除非已办理提前结束并留下签名。
闸门实现在服务端，前端置灰只是体验。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import batch_state as state
from ..domain.models import Batch
from .scan_service import ScanService

CHECK_PLAN_COMPLETE = "PLAN_COMPLETE"
CHECK_COUNT_MATCHES = "COUNT_MATCHES"
CHECK_NO_DUPLICATE = "NO_DUPLICATE_CODES"
CHECK_CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
CHECK_EARLY_END_SIGNED = "EARLY_END_SIGNED"

BLOCK_MISSING_PARTICLES = "MISSING_PARTICLES"
BLOCK_PLAN_INCOMPLETE = "PLAN_INCOMPLETE"
BLOCK_DUPLICATE_CODES = "DUPLICATE_CODES"
BLOCK_UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
BLOCK_READONLY_FOR_EXPORT = "STATUS_NOT_EXPORTABLE"

EXPORT_KIND_NORMAL = "normal"
EXPORT_KIND_EARLY_END = "early_end"


@dataclass(slots=True)
class Check:
    code: str
    label: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(slots=True)
class Blocking:
    code: str
    message: str
    action: str

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "action": self.action}


@dataclass(slots=True)
class CanComparison:
    index: int
    planned: int
    scanned: int
    missing: int
    can_code: str
    complete: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "planned": self.planned,
            "scanned": self.scanned,
            "missing": self.missing,
            "canCode": self.can_code,
            "complete": self.complete,
        }


@dataclass(slots=True)
class Review:
    batch_id: str
    batch_no: str
    status: str
    status_label: str
    editable: bool
    plan_can_count: int
    plan_particle_total: int
    actual_can_count: int
    actual_particle_total: int
    missing_particles: int
    per_can: list[CanComparison] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    blocking: list[Blocking] = field(default_factory=list)
    can_export: bool = False
    export_kind: str = EXPORT_KIND_NORMAL
    early_end: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "batchId": self.batch_id,
            "batchNo": self.batch_no,
            "status": self.status,
            "statusLabel": self.status_label,
            "editable": self.editable,
            "plan": {
                "canCount": self.plan_can_count,
                "particleTotal": self.plan_particle_total,
            },
            "actual": {
                "canCount": self.actual_can_count,
                "particleTotal": self.actual_particle_total,
            },
            "missingParticles": self.missing_particles,
            "perCan": [item.to_dict() for item in self.per_can],
            "checks": [item.to_dict() for item in self.checks],
            "blocking": [item.to_dict() for item in self.blocking],
            "canExport": self.can_export,
            "exportKind": self.export_kind,
            "earlyEnd": self.early_end,
        }


class ReviewService:
    def __init__(self, scan_service: ScanService) -> None:
        self._scan = scan_service

    def _compare(self, batch: Batch) -> list[CanComparison]:
        plan = batch.planned_particle_counts
        rows: list[CanComparison] = []
        for offset, planned in enumerate(plan):
            index = offset + 1
            can = next((item for item in batch.box.cans if item.index == index), None)
            scanned = len(can.particles) if can else 0
            rows.append(
                CanComparison(
                    index=index,
                    planned=planned,
                    scanned=scanned,
                    missing=max(0, planned - scanned),
                    can_code=can.code if can else "",
                    complete=bool(can and can.code.strip() and scanned >= planned),
                )
            )
        return rows

    def review(self, record) -> Review:
        batch = record.batch
        rows = self._compare(batch)
        plan_total = sum(batch.planned_particle_counts)
        actual_total = batch.actual_particle_total
        missing = max(0, plan_total - actual_total)
        overdue = max(0, actual_total - plan_total)

        duplicates = batch.find_duplicate_codes()

        session = self._scan.session(record.id)
        last_event = session.last_event
        unresolved_conflict = bool(
            last_event and last_event.code == "CONFLICT" and last_event.blocking
        )

        early_end = batch.early_end
        early_end_dict = None
        if early_end is not None:
            early_end_dict = {
                "reason": early_end.reason,
                "operator": early_end.operator,
                "note": early_end.note,
                "at": early_end.at,
                "actualCanCount": early_end.actual_can_count,
                "actualParticleCount": early_end.actual_particle_count,
            }

        plan_complete = bool(batch.planned_particle_counts) and all(
            count >= 1 for count in batch.planned_particle_counts
        )

        checks = [
            Check(
                code=CHECK_PLAN_COMPLETE,
                label="包装结构计划完整",
                passed=plan_complete,
                detail=f"计划 {len(batch.planned_particle_counts)} 罐 / {plan_total} 粒"
                if plan_complete
                else "尚未设定罐数与每罐粒子数",
            ),
            Check(
                code=CHECK_COUNT_MATCHES,
                label="计划与实际一致",
                passed=missing == 0 and overdue == 0,
                detail=f"计划 {plan_total} 粒，实际 {actual_total} 粒",
            ),
            Check(
                code=CHECK_NO_DUPLICATE,
                label="无重复条码",
                passed=not duplicates,
                detail="条码全局唯一" if not duplicates else f"重复 {len(duplicates)} 个",
            ),
            Check(
                code=CHECK_CONFLICT_RESOLVED,
                label="无未处理冲突",
                passed=not unresolved_conflict,
                detail=(
                    "最近一次识别未出现同区域歧义"
                    if not unresolved_conflict
                    else "最近一次识别出现同区域歧义，请重扫该处"
                ),
            ),
        ]

        blocking: list[Blocking] = []
        if not plan_complete:
            blocking.append(
                Blocking(
                    code=BLOCK_PLAN_INCOMPLETE,
                    message="包装结构计划不完整，无法导出。",
                    action="回到包装结构页设定罐数与每罐粒子数",
                )
            )
        if duplicates:
            blocking.append(
                Blocking(
                    code=BLOCK_DUPLICATE_CODES,
                    message=f"存在 {len(duplicates)} 个重复条码，无法导出。",
                    action="在槽位面板定位重复条码并删除或替换",
                )
            )
        if unresolved_conflict:
            blocking.append(
                Blocking(
                    code=BLOCK_UNRESOLVED_CONFLICT,
                    message="最近一次识别出现同区域歧义且尚未重扫，无法导出。",
                    action="重新拍摄该处条码",
                )
            )

        export_kind = EXPORT_KIND_NORMAL
        if missing > 0:
            if early_end is None:
                blocking.append(
                    Blocking(
                        code=BLOCK_MISSING_PARTICLES,
                        message=(
                            f"尚有 {missing} 个槽位未完成，普通导出已禁止。"
                        ),
                        action="继续扫码补足，或办理「提前结束」并填写原因与操作人",
                    )
                )
            else:
                export_kind = EXPORT_KIND_EARLY_END
                checks.append(
                    Check(
                        code=CHECK_EARLY_END_SIGNED,
                        label="提前结束已签名",
                        passed=True,
                        detail=f"原因：{early_end.reason}；操作人：{early_end.operator}",
                    )
                )
        if missing == 0:
            checks.append(
                Check(
                    code=CHECK_EARLY_END_SIGNED,
                    label="提前结束已签名",
                    passed=True,
                    detail="无缺漏，无需提前结束",
                )
            )

        return Review(
            batch_id=record.id,
            batch_no=batch.batch_no,
            status=record.status,
            status_label=state.label_of(record.status),
            editable=state.is_editable(record.status),
            plan_can_count=len(batch.planned_particle_counts),
            plan_particle_total=plan_total,
            actual_can_count=batch.can_count,
            actual_particle_total=actual_total,
            missing_particles=missing,
            per_can=rows,
            checks=checks,
            blocking=blocking,
            can_export=not blocking,
            export_kind=export_kind,
            early_end=early_end_dict,
        )
