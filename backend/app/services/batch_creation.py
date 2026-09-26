"""新建批次的公共逻辑。

草稿创建与 XML 导入要做同一件事：批号唯一性检查，冲突时给出"三选一"
（打开已有 / 创建新版本 / 取消）。抽成一份，避免两处各写一遍后
文案与建议版本号慢慢漂移。

这里只做决策，不抛 HTTP 异常 —— 由调用方（路由）决定怎么表达成响应。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import batch_state as state
from ..repositories.batch_repository import BatchRecord, BatchRepository

REASON_BATCH_NO_EXISTS = "BATCH_NO_EXISTS"


@dataclass(frozen=True, slots=True)
class BatchNoDecision:
    """批号的最终取值，或"为什么不能用"。"""

    batch_no: str
    conflict: dict[str, object] | None = None
    """非空表示批号已被占用，内容即"三选一"的完整上下文。"""

    exhausted: bool = False
    """显式要求新版本号，但候选版本号也被占用了。"""


def conflict_detail(repository: BatchRepository, existing: BatchRecord) -> dict[str, object]:
    suggested = repository.next_version_no(existing.batch.batch_no)
    return {
        "reason": REASON_BATCH_NO_EXISTS,
        "existing": {
            "id": existing.id,
            "batchNo": existing.batch.batch_no,
            "status": existing.status,
            "statusLabel": state.label_of(existing.status),
            "updatedAt": existing.updated_at,
            "canCount": existing.batch.can_count,
            "actualParticleTotal": existing.batch.actual_particle_total,
        },
        "suggestedBatchNo": suggested,
        "options": [
            {"action": "open_existing", "label": "打开已有批次"},
            {"action": "create_new_version", "label": f"创建新版本 {suggested}"},
            {"action": "cancel", "label": "取消并返回修改"},
        ],
    }


def decide_batch_no(
    repository: BatchRepository,
    batch_no: str,
    *,
    force_new_version: bool,
) -> BatchNoDecision:
    """决定这次创建用哪个批号。

    - 批号没人用：原样返回；
    - 批号被占用且未确认新建版本：返回冲突上下文；
    - 已确认新建版本：返回 `-Vn` 候选号；候选也被占用则标记 exhausted。
    """

    existing = repository.find_by_batch_no(batch_no)
    if existing is None:
        return BatchNoDecision(batch_no=batch_no)
    if not force_new_version:
        return BatchNoDecision(batch_no=batch_no, conflict=conflict_detail(repository, existing))

    candidate = repository.next_version_no(batch_no)
    if repository.find_by_batch_no(candidate) is not None:
        return BatchNoDecision(batch_no=batch_no, exhausted=True)
    return BatchNoDecision(batch_no=candidate)
