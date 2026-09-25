"""三级包装关联的领域模型。

层级固定关系：
    箱 packLayer=3
    └── 罐 packLayer=2（1～5 个）
        └── 粒子 packLayer=1（每罐 1～2500 粒）

模型刻意保留每个罐的 `planned_particle_count`：XML 本身不携带"计划数"，
该字段用于界面上的"计划 vs 实际"核对，导出时被忽略。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from .constants import LAYER_BOX, LAYER_CAN, LAYER_PARTICLE


@dataclass(slots=True)
class EarlyEnd:
    """「提前结束」记录。

    V1.1 10.5 要求：缺漏状态下禁止导出，除非执行提前结束流程，
    且必须记录原因、实际罐数、实际粒子数、操作人签名。
    签名形式已确认为「操作人下拉选择 + 备注文本」。

    导出 XML 时只包含实际录入的数据；early_end 本身**不写入 XML**，
    只进审计日志与本地库。
    """

    reason: str
    """提前结束原因（必填）。"""

    operator: str
    """操作人（从下拉列表选择）。"""

    note: str = ""
    """补充备注。"""

    at: str = ""
    """记录时间，ISO 8601。"""

    actual_can_count: int = 0
    """办理当时实际完成的罐数。"""

    actual_particle_count: int = 0
    """办理当时实际录入的粒子数。"""


@dataclass(slots=True)
class CanCode:
    """罐（packLayer=2）及其粒子。"""

    index: int
    """罐序号，从 1 开始。"""

    code: str
    """罐号。"""

    planned_particle_count: int = 0
    """计划粒子数；XML 不携带，解析时默认等于实际粒子数。"""

    particles: list[str] = field(default_factory=list)
    """粒子码，**必须保持采集原始顺序，禁止排序**。"""


@dataclass(slots=True)
class BoxCode:
    """箱（packLayer=3）。一期固定 1 箱，仍以结构承载以便二期扩展。"""

    code: str
    cans: list[CanCode] = field(default_factory=list)


@dataclass(slots=True)
class Batch:
    """一个批次的完整关联数据。"""

    batch_no: str
    made_date: str
    validate_date: str
    box: BoxCode
    early_end: EarlyEnd | None = None
    """提前结束记录。为 None 表示本批次按计划正常采集完成。"""

    @property
    def can_count(self) -> int:
        return len(self.box.cans)

    @property
    def actual_particle_total(self) -> int:
        return sum(len(can.particles) for can in self.box.cans)

    @property
    def planned_particle_total(self) -> int:
        return sum(can.planned_particle_count for can in self.box.cans)

    def iter_export_nodes(self) -> Iterator[tuple[str, int, str | None]]:
        """按 XML 基准文件的顺序产出 (curCode, packLayer, parentCode)。

        顺序规则（由两个基准文件反推）：
            箱 → 罐1 → 罐1 的粒子（原序）→ 罐2 → 罐2 的粒子（原序）→ …
        """

        yield self.box.code, LAYER_BOX, None
        for can in self.box.cans:
            yield can.code, LAYER_CAN, self.box.code
            for particle in can.particles:
                yield particle, LAYER_PARTICLE, can.code

    def all_codes(self) -> list[str]:
        return [code for code, _layer, _parent in self.iter_export_nodes()]

    def find_duplicate_codes(self) -> list[str]:
        """返回重复出现的条码，按首次重复顺序。"""

        seen: set[str] = set()
        duplicates: list[str] = []
        for code in self.all_codes():
            if code in seen and code not in duplicates:
                duplicates.append(code)
            seen.add(code)
        return duplicates
