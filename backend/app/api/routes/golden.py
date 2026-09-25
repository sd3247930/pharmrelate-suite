from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ...schemas.batch import GoldenInfoPayload
from ...services import golden
from ..errors import NotFoundError

router = APIRouter(prefix="/golden", tags=["golden"])


@router.get("", summary="列出黄金基准文件及其往返校验结果")
def list_golden() -> dict[str, object]:
    infos = golden.inspect_all()
    return {
        "items": [GoldenInfoPayload(**info.to_dict()).model_dump(by_alias=True) for info in infos],
        "allOk": all(info.roundtrip_ok for info in infos),
    }


@router.get("/{name}/xml", summary="读取某个黄金基准的原始 XML 文本")
def read_golden_xml(name: str) -> PlainTextResponse:
    try:
        text = golden.read_text(name)
    except golden.GoldenNotFoundError as exc:
        raise NotFoundError(str(exc), detail={"name": name, "available": list(golden.GOLDEN_NAMES)}) from exc
    return PlainTextResponse(text, media_type="application/xml; charset=utf-8")
