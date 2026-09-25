from __future__ import annotations

from pydantic import Field

from .base import CamelModel


class FramePayload(CamelModel):
    """一帧的识别结果。

    `conflicts` 来自识别层的同区域冲突判定；只要非空，整帧都会被拒绝。
    """

    codes: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
    engine_version: str = ""
    variants: list[str] = Field(default_factory=list)


class NextCanPayload(CamelModel):
    proceed: bool
