"""批次相关 DTO 与领域模型互转。"""

from __future__ import annotations

from pydantic import Field

from ..domain.models import Batch, BoxCode, CanCode
from ..domain.validation import BatchIssue
from .base import CamelModel


class CanPayload(CamelModel):
    index: int = Field(ge=1, le=5)
    code: str
    planned_particle_count: int = Field(default=0, ge=0)
    particles: list[str] = Field(default_factory=list)


class BoxPayload(CamelModel):
    code: str
    cans: list[CanPayload] = Field(default_factory=list)


class BatchPayload(CamelModel):
    """一个批次的完整数据（箱 → 罐 → 粒子）。"""

    batch_no: str
    made_date: str
    validate_date: str
    box: BoxPayload

    def to_domain(self) -> Batch:
        return Batch(
            batch_no=self.batch_no,
            made_date=self.made_date,
            validate_date=self.validate_date,
            box=BoxCode(
                code=self.box.code,
                cans=[
                    CanCode(
                        index=can.index,
                        code=can.code,
                        planned_particle_count=can.planned_particle_count,
                        particles=list(can.particles),
                    )
                    for can in self.box.cans
                ],
            ),
        )


class BatchCreatePayload(BatchPayload):
    """创建批次。

    `force_new_version=True` 表示用户已在「重复批号三选一」中明确选择
    「创建新版本」，此时允许服务端把批号改写为 batchNo-VN。
    """

    force_new_version: bool = False


class BatchStatusPayload(CamelModel):
    target: str
    reason: str = ""
    operator: str = ""


class EarlyEndPayload(CamelModel):
    """提前结束签名：操作人下拉选择 + 备注文本。"""

    reason: str
    operator: str
    note: str = ""


def serialize_batch_data(batch: Batch) -> dict[str, object]:
    payload: dict[str, object] = {
        "batchNo": batch.batch_no,
        "madeDate": batch.made_date,
        "validateDate": batch.validate_date,
        "box": {
            "code": batch.box.code,
            "cans": [
                {
                    "index": can.index,
                    "code": can.code,
                    "plannedParticleCount": can.planned_particle_count,
                    "particles": list(can.particles),
                }
                for can in batch.box.cans
            ],
        },
    }
    if batch.early_end is not None:
        payload["earlyEnd"] = {
            "reason": batch.early_end.reason,
            "operator": batch.early_end.operator,
            "note": batch.early_end.note,
            "at": batch.early_end.at,
            "actualCanCount": batch.early_end.actual_can_count,
            "actualParticleCount": batch.early_end.actual_particle_count,
        }
    return payload


class BatchStats(CamelModel):
    can_count: int
    planned_particle_total: int
    actual_particle_total: int
    box_code: str


class XmlPreviewResponse(CamelModel):
    xml: str
    sha256: str
    byte_length: int
    stats: BatchStats


class IssuePayload(CamelModel):
    severity: str
    code: str
    field: str
    message: str

    @classmethod
    def from_domain(cls, issue: BatchIssue) -> IssuePayload:
        return cls(
            severity=issue.severity,
            code=issue.code,
            field=issue.field,
            message=issue.message,
        )


class GoldenInfoPayload(CamelModel):
    name: str
    byte_length: int
    sha256: str
    roundtrip_ok: bool
    batch_no: str | None = None
    can_count: int | None = None
    particle_count: int | None = None
    error: str | None = None
