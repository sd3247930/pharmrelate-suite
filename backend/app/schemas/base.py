from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """对外 camelCase、对内 snake_case 的基类。

    `extra="forbid"` 让多余字段直接报错，避免前端字段名写错却被静默忽略。
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
