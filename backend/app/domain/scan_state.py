"""扫码采集状态机（V1.1 第 14 章 / PRD 4.3）。

状态名与阶段计划书保持一致：
    idle → box_scanning → can_scanning → particle_scanning
         → can_review → next_can_prompt → overall_review → completed

权威在后端：前端只读状态、只提交"识别到了什么"和"操作员点了什么"，
不允许本地推进状态。所有非法推进一律返回明确原因。
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_IDLE = "idle"
STATUS_BOX_SCANNING = "box_scanning"
STATUS_BOX_CONFIRM = "box_confirm"
STATUS_CAN_SCANNING = "can_scanning"
STATUS_CAN_CONFIRM = "can_confirm"
STATUS_PARTICLE_SCANNING = "particle_scanning"
STATUS_CAN_REVIEW = "can_review"
STATUS_NEXT_CAN_PROMPT = "next_can_prompt"
STATUS_OVERALL_REVIEW = "overall_review"
STATUS_EARLY_END = "early_end"
STATUS_COMPLETED = "completed"

SCAN_STATUSES: tuple[str, ...] = (
    STATUS_IDLE,
    STATUS_BOX_SCANNING,
    STATUS_BOX_CONFIRM,
    STATUS_CAN_SCANNING,
    STATUS_CAN_CONFIRM,
    STATUS_PARTICLE_SCANNING,
    STATUS_CAN_REVIEW,
    STATUS_NEXT_CAN_PROMPT,
    STATUS_OVERALL_REVIEW,
    STATUS_EARLY_END,
    STATUS_COMPLETED,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_IDLE: "待开始",
    STATUS_BOX_SCANNING: "拍箱号",
    STATUS_BOX_CONFIRM: "箱号确认",
    STATUS_CAN_SCANNING: "拍罐号",
    STATUS_CAN_CONFIRM: "罐号确认",
    STATUS_PARTICLE_SCANNING: "拍粒子",
    STATUS_CAN_REVIEW: "本罐核对",
    STATUS_NEXT_CAN_PROMPT: "是否继续下一罐",
    STATUS_OVERALL_REVIEW: "整体核对",
    STATUS_EARLY_END: "已提前结束",
    STATUS_COMPLETED: "已完成",
}

# ---------------------------------------------------------------------------
# 事件码：既用于界面提示，也用于审计
# ---------------------------------------------------------------------------

EVENT_OK = "OK"
EVENT_NO_CODE = "NO_CODE"
EVENT_MULTI_CODE = "MULTI_CODE"
EVENT_WRONG_LAYER = "WRONG_LAYER"
EVENT_DUPLICATE_CODE = "DUPLICATE_CODE"
EVENT_OVERFLOW = "OVERFLOW"
EVENT_CONFLICT = "CONFLICT"
EVENT_WRONG_STATE = "WRONG_STATE"

BLOCKING_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_NO_CODE,
        EVENT_MULTI_CODE,
        EVENT_WRONG_LAYER,
        EVENT_DUPLICATE_CODE,
        EVENT_OVERFLOW,
        EVENT_CONFLICT,
        EVENT_WRONG_STATE,
    }
)

EVENT_LABELS: dict[str, str] = {
    EVENT_OK: "已识别",
    EVENT_NO_CODE: "未识别到条码",
    EVENT_MULTI_CODE: "检测到多个条码",
    EVENT_WRONG_LAYER: "条码层级不符",
    EVENT_DUPLICATE_CODE: "条码已被使用",
    EVENT_OVERFLOW: "超出本罐计划数量",
    EVENT_CONFLICT: "同位置解出多个不同条码",
    EVENT_WRONG_STATE: "当前状态不允许该操作",
}

ALARM_EVENTS: frozenset[str] = frozenset(
    {EVENT_MULTI_CODE, EVENT_CONFLICT, EVENT_DUPLICATE_CODE, EVENT_WRONG_LAYER, EVENT_OVERFLOW}
)
"""需要"声音 + 视觉"双重提示的事件。"""


@dataclass(frozen=True, slots=True)
class ScanEvent:
    """一次扫码动作的结果。"""

    code: str
    label: str
    message: str
    blocking: bool = False
    needs_alarm: bool = False
    detail: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "message": self.message,
            "blocking": self.blocking,
            "needsAlarm": self.needs_alarm,
            "detail": self.detail or {},
        }


def event(code: str, message: str = "", detail: dict[str, object] | None = None) -> ScanEvent:
    return ScanEvent(
        code=code,
        label=EVENT_LABELS.get(code, code),
        message=message or EVENT_LABELS.get(code, code),
        blocking=code in BLOCKING_EVENTS,
        needs_alarm=code in ALARM_EVENTS,
        detail=detail,
    )


def label_of(status: str) -> str:
    return STATUS_LABELS.get(status, status)


class ScanError(RuntimeError):
    """当前状态下不允许该操作。"""

    def __init__(self, status: str, action: str) -> None:
        super().__init__(
            f"当前状态为「{label_of(status)}」，不能执行「{action}」。"
        )
        self.status = status
        self.action = action
