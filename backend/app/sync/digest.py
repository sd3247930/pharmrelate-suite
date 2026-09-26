"""批次摘要（V1.1 11.6）。

同步完成后两端交换摘要，不一致就触发全量拉取 ——
这是"同步到底有没有对上"的唯一客观判据，不能靠人工抽查。

**关键：算法只有一份。** 假实现、真实 WebSocket 通道、Android 端都调这里，
否则两端各自实现一个哈希，迟早会因为排序或分隔符不同而永远比对不上。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass


def code_set_hash(codes: Iterable[str]) -> str:
    """条码集合哈希：**排序后再哈希**，与采集顺序无关。

    用换行分隔：条码是定长数字串，换行不会出现在其中，
    因此不会出现 "ab"+"c" 与 "a"+"bc" 撞哈希的情况。
    """

    ordered = "\n".join(sorted(codes))
    return hashlib.sha256(ordered.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SyncDigest:
    box_count: int = 0
    can_count: int = 0
    particle_count: int = 0
    code_hash: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "boxCount": self.box_count,
            "canCount": self.can_count,
            "particleCount": self.particle_count,
            "codeHash": self.code_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SyncDigest:
        return cls(
            box_count=int(data.get("boxCount") or 0),
            can_count=int(data.get("canCount") or 0),
            particle_count=int(data.get("particleCount") or 0),
            code_hash=str(data.get("codeHash") or ""),
        )

    def differences(self, other: SyncDigest) -> list[str]:
        """逐项列出差异字段，而不是只回一句"不一致"。

        同步排查时，"哪个维度对不上"决定下一步查什么：
        数量对但哈希不对 → 条码内容问题；数量不对 → 丢操作。
        """

        fields = (
            ("boxCount", self.box_count, other.box_count),
            ("canCount", self.can_count, other.can_count),
            ("particleCount", self.particle_count, other.particle_count),
            ("codeHash", self.code_hash, other.code_hash),
        )
        return [
            f"{name}: 本地 {local} ≠ 远端 {remote}"
            for name, local, remote in fields
            if local != remote
        ]

    def matches(self, other: SyncDigest) -> bool:
        return self == other


def digest_of_batch(batch) -> SyncDigest:
    """从一期领域模型 `Batch` 计算摘要。

    只读，不改一期任何结构 —— 与 `batch.iter_export_nodes()` 同一个数据源。
    """

    codes: list[str] = []
    for can in batch.box.cans:
        codes.extend(can.particles)
    return SyncDigest(
        box_count=1 if batch.box.code.strip() else 0,
        can_count=sum(1 for can in batch.box.cans if can.code.strip()),
        particle_count=len(codes),
        code_hash=code_set_hash(codes),
    )


def compare(local: SyncDigest, remote: SyncDigest) -> tuple[bool, list[str]]:
    """返回 (是否一致, 差异清单)。"""

    return local.matches(remote), local.differences(remote)
