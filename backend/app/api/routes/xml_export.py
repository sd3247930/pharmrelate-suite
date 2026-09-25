from __future__ import annotations

from fastapi import APIRouter

from ...schemas.batch import BatchStats, IssuePayload, XmlPreviewResponse
from ...services.xml_builder import render
from ...services.golden import sha256_of
from ...domain.validation import has_blocking_issue, validate_batch
from ..errors import ValidationFailedError
from ...schemas.batch import BatchPayload

router = APIRouter(prefix="/xml", tags=["xml"])


@router.post("/preview", response_model=XmlPreviewResponse, summary="按数据模型生成 XML 预览")
def preview(payload: BatchPayload) -> XmlPreviewResponse:
    """把批次数据渲染成 XML 字符串（复用阶段 0 的生成器）。

    校验不通过时返回 422 与完整问题清单，不返回半成品 XML。
    """

    batch = payload.to_domain()
    issues = validate_batch(batch)
    if has_blocking_issue(issues):
        raise ValidationFailedError(
            "数据校验未通过，无法生成 XML。",
            detail={"issues": [IssuePayload.from_domain(issue).model_dump(by_alias=True) for issue in issues]},
        )

    xml_text = render(batch)
    raw = xml_text.encode("utf-8")
    return XmlPreviewResponse(
        xml=xml_text,
        sha256=sha256_of(raw),
        byte_length=len(raw),
        stats=BatchStats(
            can_count=batch.can_count,
            planned_particle_total=batch.planned_particle_total,
            actual_particle_total=batch.actual_particle_total,
            box_code=batch.box.code,
        ),
    )


@router.post("/validate", summary="仅做校验，不生成 XML")
def validate(payload: BatchPayload) -> dict[str, object]:
    issues = validate_batch(payload.to_domain())
    return {
        "ok": not has_blocking_issue(issues),
        "issues": [IssuePayload.from_domain(issue).model_dump(by_alias=True) for issue in issues],
    }
