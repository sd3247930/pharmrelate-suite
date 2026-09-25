"""批次生命周期状态机（V1.1 第 8 章）。

唯一权威实现在后端；前端只读状态、只发流转请求，禁止在本地改状态。
非法流转一律抛 `IllegalTransitionError`，禁止静默通过。
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_DRAFT = "draft"
STATUS_COLLECTING = "collecting"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_VERIFIED = "verified"
STATUS_EXPORTED = "exported"
STATUS_LOCKED = "locked"
STATUS_ARCHIVED = "archived"
STATUS_VOID = "void"

BATCH_STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_COLLECTING,
    STATUS_PENDING_REVIEW,
    STATUS_VERIFIED,
    STATUS_EXPORTED,
    STATUS_LOCKED,
    STATUS_ARCHIVED,
    STATUS_VOID,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_DRAFT: "草稿",
    STATUS_COLLECTING: "采集中",
    STATUS_PENDING_REVIEW: "待核对",
    STATUS_VERIFIED: "已核对",
    STATUS_EXPORTED: "已导出",
    STATUS_LOCKED: "已锁定",
    STATUS_ARCHIVED: "已归档",
    STATUS_VOID: "已作废",
}

STATUS_ORDER: dict[str, int] = {status: index for index, status in enumerate(BATCH_STATUSES)}

# ---------------------------------------------------------------------------
# 流转规则
# ---------------------------------------------------------------------------

TRANSITIONS: dict[str, frozenset[str]] = {
    # 生成扫码网格
    STATUS_DRAFT: frozenset({STATUS_COLLECTING, STATUS_VOID}),
    # 完成步骤 3 核对
    STATUS_COLLECTING: frozenset({STATUS_PENDING_REVIEW, STATUS_VOID}),
    # 返回修改 / 确认一致
    STATUS_PENDING_REVIEW: frozenset({STATUS_VERIFIED, STATUS_COLLECTING, STATUS_VOID}),
    # 导出成功 / 退回核对
    STATUS_VERIFIED: frozenset({STATUS_EXPORTED, STATUS_PENDING_REVIEW, STATUS_VOID}),
    # 自动或手动锁定 / 管理员解锁退回已核对
    STATUS_EXPORTED: frozenset({STATUS_LOCKED, STATUS_VERIFIED, STATUS_VOID}),
    # 超期归档 / 管理员解锁
    STATUS_LOCKED: frozenset({STATUS_ARCHIVED, STATUS_EXPORTED, STATUS_VOID}),
    # 已归档是只读终态，只允许管理员解锁回到已锁定
    STATUS_ARCHIVED: frozenset({STATUS_LOCKED}),
    # 作废是终态
    STATUS_VOID: frozenset(),
}

READONLY_STATUSES: frozenset[str] = frozenset(
    {STATUS_EXPORTED, STATUS_LOCKED, STATUS_ARCHIVED, STATUS_VOID}
)
"""这些状态下业务数据只读（V1.1 8.5）。"""

FINAL_STATUSES: frozenset[str] = frozenset({STATUS_ARCHIVED, STATUS_VOID})

ADMIN_ONLY_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # 解锁：已导出 / 已锁定 / 已归档 都需要管理员并填写原因
        (STATUS_EXPORTED, STATUS_VERIFIED),
        (STATUS_LOCKED, STATUS_EXPORTED),
        (STATUS_ARCHIVED, STATUS_LOCKED),
        # 作废只允许管理员
        (STATUS_DRAFT, STATUS_VOID),
        (STATUS_COLLECTING, STATUS_VOID),
        (STATUS_PENDING_REVIEW, STATUS_VOID),
        (STATUS_VERIFIED, STATUS_VOID),
        (STATUS_EXPORTED, STATUS_VOID),
        (STATUS_LOCKED, STATUS_VOID),
    }
)
"""需要管理员权限的流转。二期接入权限体系后由服务端再次校验。"""


class IllegalTransitionError(ValueError):
    """尝试执行状态机不允许的流转。"""

    def __init__(self, current: str, target: str, allowed: frozenset[str]) -> None:
        super().__init__(
            f"批次不能从「{label_of(current)}」直接变为「{label_of(target)}」。"
            f"允许的目标状态：{allowed_labels(allowed)}"
        )
        self.current = current
        self.target = target
        self.allowed = allowed


def label_of(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def allowed_labels(allowed: frozenset[str]) -> str:
    if not allowed:
        return "无（终态）"
    return "、".join(label_of(item) for item in sorted(allowed, key=lambda item: STATUS_ORDER[item]))


def is_known_status(status: str) -> bool:
    return status in STATUS_ORDER


def allowed_transitions(status: str) -> frozenset[str]:
    return TRANSITIONS.get(status, frozenset())


def can_transition(current: str, target: str) -> bool:
    return target in allowed_transitions(current)


def requires_admin(current: str, target: str) -> bool:
    return (current, target) in ADMIN_ONLY_TRANSITIONS


def is_readonly(status: str) -> bool:
    """该状态下是否禁止修改业务数据。"""

    return status in READONLY_STATUSES


def is_editable(status: str) -> bool:
    return not is_readonly(status)


def assert_transition(current: str, target: str) -> None:
    """非法流转直接抛错，绝不静默通过。"""

    if not is_known_status(current):
        raise ValueError(f"未知的当前状态：{current!r}")
    if not is_known_status(target):
        raise ValueError(f"未知的目标状态：{target!r}")

    allowed = allowed_transitions(current)
    if target not in allowed:
        raise IllegalTransitionError(current, target, allowed)


@dataclass(frozen=True, slots=True)
class StatusDescriptor:
    """给前端使用的状态描述：颜色语义 + 图标语义 + 中文文字。"""

    status: str
    label: str
    editable: bool
    terminal: bool
    allowed: tuple[str, ...]


def describe(status: str) -> StatusDescriptor:
    return StatusDescriptor(
        status=status,
        label=label_of(status),
        editable=is_editable(status),
        terminal=status in FINAL_STATUSES,
        allowed=tuple(
            sorted(allowed_transitions(status), key=lambda item: STATUS_ORDER[item])
        ),
    )
