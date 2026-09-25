from __future__ import annotations

from .base import CamelModel


class ReplaceParticlePayload(CamelModel):
    code: str
    new_code: str


class DeleteParticlePayload(CamelModel):
    code: str


class RescanCanPayload(CamelModel):
    new_can_code: str


class RescanBoxPayload(CamelModel):
    new_box_code: str = ""
