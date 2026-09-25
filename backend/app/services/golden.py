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
    def __init__(self, name: str) -> None:
        super().__init__(f"未知基准文件 {name!r}，可用：{'、'.join(GOLDEN_NAMES)}")
        self.name = name


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
        raise GoldenNotFoundError(name)
    path = GOLDEN_DIR / name
    if not path.is_file():
        raise GoldenNotFoundError(name)
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
