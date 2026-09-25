"""数据模型 → XML 文本（阶段 0 核心纯函数）。

输出必须与 backend/tests/golden/ 下的基准文件**字节级一致**：
    1. 无 BOM、UTF-8、纯 LF、文件末尾恰好一个换行
    2. 第 1 行 = XML 声明紧接 <Document>，中间无换行
    3. 无缩进，每个 <Code/> 独占一行
    4. Document 属性顺序：xmlns:xsi → xsi:noNamespaceSchemaLocation → License
    5. Relation 属性顺序：productCode → subTypeNo → cascade → packageSpec → comment
    6. Batch 属性顺序：batchNo → madeDate → validateDate → workshop → lineName → lineManager
    7. Code 属性顺序：curCode → packLayer → parentCode → flag
    8. 箱节点无 parentCode
"""

from __future__ import annotations

from pathlib import Path

from ..domain.constants import FIXED_PARAMS, XML_DECLARATION, XSI_NAMESPACE, FixedParams
from ..domain.models import Batch

LINE_SEPARATOR = "\n"


def _attr(value: str) -> str:
    """属性值转义。基准文件中无特殊字符，此函数对其为无操作。"""

    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _code_line(cur_code: str, pack_layer: int, parent_code: str | None, flag: str) -> str:
    parts = [f'curCode="{_attr(cur_code)}"', f'packLayer="{pack_layer}"']
    if parent_code is not None:
        parts.append(f'parentCode="{_attr(parent_code)}"')
    parts.append(f'flag="{_attr(flag)}"')
    return "<Code " + " ".join(parts) + "/>"


def render(batch: Batch, params: FixedParams = FIXED_PARAMS) -> str:
    """生成 XML 文本。粒子顺序原样保留，绝不排序。"""

    lines: list[str] = [
        XML_DECLARATION
        + "<Document "
        + f'xmlns:xsi="{XSI_NAMESPACE}" '
        + f'xsi:noNamespaceSchemaLocation="{_attr(params.schema_location)}" '
        + f'License="{_attr(params.license)}">',
        f'<Events Version="{_attr(params.events_version)}">',
        f'<Event Name="{_attr(params.event_name)}">',
        "<Relation "
        + f'productCode="{_attr(params.product_code)}" '
        + f'subTypeNo="{_attr(params.sub_type_no)}" '
        + f'cascade="{_attr(params.cascade)}" '
        + f'packageSpec="{_attr(params.package_spec)}" '
        + f'comment="{_attr(params.comment)}">',
        "<Batch "
        + f'batchNo="{_attr(batch.batch_no)}" '
        + f'madeDate="{_attr(batch.made_date)}" '
        + f'validateDate="{_attr(batch.validate_date)}" '
        + f'workshop="{_attr(params.workshop)}" '
        + f'lineName="{_attr(params.line_name)}" '
        + f'lineManager="{_attr(params.line_manager)}">',
    ]

    for cur_code, pack_layer, parent_code in batch.iter_export_nodes():
        lines.append(_code_line(cur_code, pack_layer, parent_code, params.flag))

    lines.extend(["</Batch>", "</Relation>", "</Event>", "</Events>", "</Document>"])

    return LINE_SEPARATOR.join(lines) + LINE_SEPARATOR


def render_bytes(batch: Batch, params: FixedParams = FIXED_PARAMS) -> bytes:
    """生成 XML 字节串。UTF-8 且**不带 BOM**，换行恒为 LF。"""

    return render(batch, params).encode("utf-8")


def write_file(batch: Batch, path: Path, params: FixedParams = FIXED_PARAMS) -> Path:
    """以字节方式落盘，绕开 Windows 文本模式的 CRLF 转换与 BOM 追加。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_bytes(batch, params))
    return target
