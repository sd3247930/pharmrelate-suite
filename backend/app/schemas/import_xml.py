"""导入 XML 的请求 DTO。"""

from __future__ import annotations

from pydantic import Field

from .base import CamelModel


class XmlImportPayload(CamelModel):
    """导入一期格式的关联关系 XML。

    用 JSON 文本而不是 multipart：格式是文本、体积可控（12,500 粒的
    XML 约 1.2 MB），复用现有 `request()` 客户端即可，不必新增上传通道。
    """

    xml: str = Field(min_length=1)
    source_name: str = ""
    """文件名，仅用于回显与审计，不参与解析。"""

    force_new_version: bool = False
    """批号冲突时是否按"创建新版本"处理（与创建草稿同一语义）。"""
