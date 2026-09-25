"""程序固定参数与条码层级规则。

本文件中的所有取值均由 backend/tests/golden/ 下的两个真实 XML
基准文件反推得出，**不得由用户输入，也不随实际包装结构变化**。

关键事实（实测，任何现有文档均未记载）：
    一箱一罐.xml 实际只有 1 罐 400 粒，但 cascade 仍是 "1:5:2500"。
    因此 cascade 是固定字面量；任何"按实际罐数/粒子数计算 cascade"
    的实现都会生成与基准不符的 XML。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# 条码层级规则（由两个基准文件实测反推）
# ---------------------------------------------------------------------------

CODE_LENGTH: Final[int] = 20
"""箱号 / 罐号 / 粒子号全部为定长 20 位 ASCII 数字。"""

LAYER_BOX: Final[int] = 3
LAYER_CAN: Final[int] = 2
LAYER_PARTICLE: Final[int] = 1

LAYER_LABELS: Final[dict[int, str]] = {
    LAYER_BOX: "箱",
    LAYER_CAN: "罐",
    LAYER_PARTICLE: "粒子",
}

LAYER_PREFIXES: Final[dict[int, str]] = {
    LAYER_BOX: "8021761",
    LAYER_CAN: "8021762",
    LAYER_PARTICLE: "8206233",
}
"""层级白名单：条码前缀唯一决定其所属层级。

用于在扫入瞬间拦截"把粒子码当罐号扫"等层级错误，
比"识别到多个条码"这类事后校验更早、更准。
"""

TRACE_BRAND_LENGTH: Final[int] = 7
"""药品追溯码标签上的"药品标识码"位数（照片实测：8206233）。"""

TRACE_SERIAL_LENGTH: Final[int] = 13
"""药品追溯码标签上的"序列号"位数（照片实测：0000110295569）。"""

# ---------------------------------------------------------------------------
# 规模边界（V1.1 第 13 章）
# ---------------------------------------------------------------------------

MIN_CANS: Final[int] = 1
MAX_CANS: Final[int] = 5
MAX_PARTICLES_PER_CAN: Final[int] = 2500
MAX_PARTICLES_PER_BATCH: Final[int] = 12500

BOX_COUNT: Final[int] = 1
"""一期固定 1 箱。"""

# ---------------------------------------------------------------------------
# XML 模板常量
# ---------------------------------------------------------------------------

XML_DECLARATION: Final[str] = '<?xml version="1.0" encoding="utf-8"?>'
XSI_NAMESPACE: Final[str] = "http://www.w3.org/2001/XMLSchema-instance"


@dataclass(frozen=True, slots=True)
class FixedParams:
    """写入 XML 的程序固定参数，全部为不可编辑字面量。"""

    product_code: str = "9999999"
    sub_type_no: str = "9500000001"
    cascade: str = "1:5:2500"
    package_spec: str = "粒1粒"
    comment: str = "0"
    flag: str = "2"
    workshop: str = "一号车间"
    line_name: str = "一号生产线"
    line_manager: str = "操作员甲"
    license: str = "1001123"
    schema_location: str = "关联关系XML Schema-3.0.xsd"
    events_version: str = "3.0"
    event_name: str = "RelationCreate"


FIXED_PARAMS: Final[FixedParams] = FixedParams()


# ---------------------------------------------------------------------------
# 条码校验工具
# ---------------------------------------------------------------------------


def looks_like_code(value: str) -> bool:
    """是否为合法条码外形：定长 20 位 ASCII 数字。"""

    return len(value) == CODE_LENGTH and value.isascii() and value.isdigit()


def classify_code(value: str) -> int | None:
    """返回条码所属层级（3/2/1）；无法识别时返回 None。"""

    if not looks_like_code(value):
        return None
    for layer, prefix in LAYER_PREFIXES.items():
        if value.startswith(prefix):
            return layer
    return None


def layer_label(layer: int | None) -> str:
    if layer is None:
        return "未知"
    return LAYER_LABELS.get(layer, f"未知({layer})")


def split_trace_code(value: str) -> tuple[str, str] | None:
    """把 20 位粒子码拆成（药品标识码, 序列号）；格式不符返回 None。

    用于条码解码值与标签 OCR 文本的双段交叉校验。
    """

    if not looks_like_code(value):
        return None
    head = TRACE_BRAND_LENGTH
    return value[:head], value[head:]
