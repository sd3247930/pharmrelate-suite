"""黄金基准文件的只读访问。

基准文件是阶段 0 冻结的合同，本模块只读不写，且用**白名单**而非路径拼接，
避免外部传入的名称穿越目录。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .xml_builder import render_bytes
from .xml_parser import XmlParseError, parse_file

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "tests" / "golden"

GOLDEN_NAMES: tuple[str, ...] = ("1箱3罐.xml", "一箱一罐.xml")


class GoldenNotFoundError(LookupError):
    """基准文件不可用。

    两种情况分开报："名称不在白名单"与"白名单里有但磁盘上没有"。
    先前两种都报同一句、且"可用"列的是常量而不是目录实况，
    结果排查时被误导成文件名编码问题 —— 实际是打包漏了文件。
    """

    def __init__(self, name: str, message: str | None = None) -> None:
        super().__init__(message or f"基准文件 {name!r} 不可用")
        self.name = name


def _available_names() -> list[str]:
    """目录里实际存在的文件名，用于报错时给出真实线索。"""

    try:
        return sorted(entry.name for entry in GOLDEN_DIR.iterdir() if entry.is_file())
    except OSError:
        return []


@dataclass(frozen=True, slots=True)
class GoldenInfo:
    name: str
    byte_length: int
    sha256: str
    roundtrip_ok: bool
    batch_no: str | None
    can_count: int | None
    particle_count: int | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "byteLength": self.byte_length,
            "sha256": self.sha256,
            "roundtripOk": self.roundtrip_ok,
            "batchNo": self.batch_no,
            "canCount": self.can_count,
            "particleCount": self.particle_count,
            "error": self.error,
        }


def _resolve(name: str) -> Path:
    if name not in GOLDEN_NAMES:
        raise GoldenNotFoundError(
            name,
            f"基准文件名 {name!r} 不在白名单，允许：{'、'.join(GOLDEN_NAMES)}",
        )
    path = GOLDEN_DIR / name
    if not path.is_file():
        found = _available_names()
        raise GoldenNotFoundError(
            name,
            f"基准文件 {name!r} 在白名单中，但磁盘上不存在。"
            f"目录 {GOLDEN_DIR} 实际内容：{'、'.join(found) or '（空或目录不存在）'}",
        )
    return path


def read_bytes(name: str) -> bytes:
    return _resolve(name).read_bytes()


def read_text(name: str) -> str:
    return read_bytes(name).decode("utf-8")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect(name: str) -> GoldenInfo:
    """读取基准文件并现场验证"解析 → 重建"是否仍然字节级一致。"""

    path = _resolve(name)
    raw = path.read_bytes()
    digest = sha256_of(raw)

    try:
        batch = parse_file(path)
    except (XmlParseError, OSError, ValueError) as exc:
        return GoldenInfo(name, len(raw), digest, False, None, None, None, str(exc))

    rebuilt = render_bytes(batch)
    return GoldenInfo(
        name=name,
        byte_length=len(raw),
        sha256=digest,
        roundtrip_ok=rebuilt == raw,
        batch_no=batch.batch_no,
        can_count=batch.can_count,
        particle_count=batch.actual_particle_total,
    )


def inspect_all() -> list[GoldenInfo]:
    return [inspect(name) for name in GOLDEN_NAMES]
