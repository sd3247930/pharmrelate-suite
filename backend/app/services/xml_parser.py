"""XML → 数据模型 解析器（阶段 0）。

用途：
    1. 阶段 0 验证"基准文件 → 模型 → 基准文件"字节级往返一致；
    2. 二期"拉取历史批次重新导出"的前置能力。

解析采取严格策略：遇到固定参数不符、层级未知、父子关系断裂等情况直接报错，
而不是静默产出错误 XML。
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from ..domain.constants import (
    FIXED_PARAMS,
    LAYER_BOX,
    LAYER_CAN,
    LAYER_PARTICLE,
    XSI_NAMESPACE,
    FixedParams,
)
from ..domain.models import Batch, BoxCode, CanCode


class XmlParseError(ValueError):
    """XML 结构或固定参数不符合基准。"""


def _require(value: str | None, what: str, source: str) -> str:
    if value is None or value == "":
        raise XmlParseError(f"{source}: 缺少必需属性 {what}")
    return value


def _check_fixed(actual: str | None, expected: str, tag: str, scope: str, source: str) -> None:
    if actual is not None and actual != expected:
        raise XmlParseError(
            f"{source}: {scope} 固定参数 {tag} 期望 {expected!r}，实际 {actual!r}"
        )


def parse_bytes(
    data: bytes,
    *,
    source: str = "<bytes>",
    params: FixedParams = FIXED_PARAMS,
) -> Batch:
    """解析 XML 字节串为 Batch。失败时抛出 XmlParseError。"""

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise XmlParseError(f"{source}: XML 解析失败：{exc}") from exc

    if root.tag != "Document":
        raise XmlParseError(f"{source}: 根节点应为 Document，实际为 {root.tag!r}")

    _check_fixed(root.get("License"), params.license, "License", "Document", source)
    # ElementTree 会把 xmlns:xsi 前缀解析成完整命名空间 URI。
    schema_attr = f"{{{XSI_NAMESPACE}}}noNamespaceSchemaLocation"
    _check_fixed(
        root.get(schema_attr),
        params.schema_location,
        "xsi:noNamespaceSchemaLocation",
        "Document",
        source,
    )

    events = root.find("Events")
    if events is None:
        raise XmlParseError(f"{source}: 缺少 <Events> 节点")
    _check_fixed(events.get("Version"), params.events_version, "Version", "Events", source)

    event_elements = events.findall("Event")
    if len(event_elements) != 1:
        raise XmlParseError(f"{source}: 期望恰好 1 个 <Event>，实际 {len(event_elements)} 个")
    event_element = event_elements[0]
    _check_fixed(event_element.get("Name"), params.event_name, "Name", "Event", source)

    relation = event_element.find("Relation")
    if relation is None:
        raise XmlParseError(f"{source}: 缺少 <Relation> 节点")
    _check_fixed(relation.get("productCode"), params.product_code, "productCode", "Relation", source)
    _check_fixed(relation.get("subTypeNo"), params.sub_type_no, "subTypeNo", "Relation", source)
    _check_fixed(relation.get("cascade"), params.cascade, "cascade", "Relation", source)
    _check_fixed(relation.get("packageSpec"), params.package_spec, "packageSpec", "Relation", source)
    _check_fixed(relation.get("comment"), params.comment, "comment", "Relation", source)

    batch_element = relation.find("Batch")
    if batch_element is None:
        raise XmlParseError(f"{source}: 缺少 <Batch> 节点")

    box: BoxCode | None = None
    cans_by_code: dict[str, CanCode] = {}

    for element in batch_element:
        if element.tag != "Code":
            raise XmlParseError(f"{source}: <Batch> 下出现未知节点 {element.tag!r}")

        cur_code = _require(element.get("curCode"), "curCode", source)
        raw_layer = _require(element.get("packLayer"), "packLayer", source)
        try:
            pack_layer = int(raw_layer)
        except ValueError as exc:
            raise XmlParseError(f"{source}: packLayer 非整数：{raw_layer!r}") from exc

        parent_code = element.get("parentCode")
        flag = element.get("flag")
        if flag is not None and flag != params.flag:
            raise XmlParseError(
                f"{source}: 条码 {cur_code} 的 flag={flag!r} 不是固定值 {params.flag!r}；"
                "当前模型尚不支持非 flag=2 的历史文件"
            )

        if pack_layer == LAYER_BOX:
            if parent_code is not None:
                raise XmlParseError(f"{source}: 箱节点 {cur_code} 不应带 parentCode")
            if box is not None:
                raise XmlParseError(f"{source}: 出现第 2 个箱节点；一期仅支持 1 箱")
            box = BoxCode(code=cur_code)

        elif pack_layer == LAYER_CAN:
            if box is None:
                raise XmlParseError(f"{source}: 罐节点 {cur_code} 出现在箱节点之前")
            if parent_code != box.code:
                raise XmlParseError(
                    f"{source}: 罐节点 {cur_code} 的 parentCode={parent_code!r} "
                    f"与箱号 {box.code!r} 不符"
                )
            if cur_code in cans_by_code:
                raise XmlParseError(f"{source}: 罐号 {cur_code} 重复出现")
            can = CanCode(index=len(box.cans) + 1, code=cur_code)
            box.cans.append(can)
            cans_by_code[cur_code] = can

        elif pack_layer == LAYER_PARTICLE:
            if parent_code is None:
                raise XmlParseError(f"{source}: 粒子节点 {cur_code} 缺少 parentCode")
            can = cans_by_code.get(parent_code)
            if can is None:
                raise XmlParseError(
                    f"{source}: 粒子节点 {cur_code} 的 parentCode={parent_code!r} "
                    "未匹配到任何已出现的罐节点"
                )
            can.particles.append(cur_code)

        else:
            raise XmlParseError(f"{source}: 未知 packLayer={pack_layer}（条码 {cur_code}）")

    if box is None:
        raise XmlParseError(f"{source}: 未找到箱节点（packLayer=3）")

    # XML 不携带计划粒子数；按实际数回填，界面上再做"计划 vs 实际"对照。
    for can in box.cans:
        can.planned_particle_count = len(can.particles)

    _check_fixed(batch_element.get("workshop"), params.workshop, "workshop", "Batch", source)
    _check_fixed(batch_element.get("lineName"), params.line_name, "lineName", "Batch", source)
    _check_fixed(batch_element.get("lineManager"), params.line_manager, "lineManager", "Batch", source)

    return Batch(
        batch_no=_require(batch_element.get("batchNo"), "batchNo", source),
        made_date=_require(batch_element.get("madeDate"), "madeDate", source),
        validate_date=_require(batch_element.get("validateDate"), "validateDate", source),
        box=box,
    )


def parse_file(path: Path, *, params: FixedParams = FIXED_PARAMS) -> Batch:
    target = Path(path)
    return parse_bytes(target.read_bytes(), source=str(target), params=params)
