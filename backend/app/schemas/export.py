from __future__ import annotations

from pydantic import Field

from .base import CamelModel


class ExportPayload(CamelModel):
    kinds: list[str] = Field(default_factory=lambda: ["xml"])
    operator: str = "local-user"
