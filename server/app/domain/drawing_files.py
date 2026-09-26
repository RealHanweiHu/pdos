"""Original-only engineering formats; geometry is parsed by the bounded browser viewer."""

import re
from pathlib import PurePath

from app.domain.documents import DocumentExtractionError

STEP_MEDIA_TYPE = "application/step"
GERBER_MEDIA_TYPE = "application/x-gerber"
DRAWING_MEDIA_TYPES = {".step": STEP_MEDIA_TYPE, ".stp": STEP_MEDIA_TYPE} | {
    extension: GERBER_MEDIA_TYPE
    for extension in (
        ".gbr",
        ".ger",
        ".gerber",
        ".gtl",
        ".gbl",
        ".gts",
        ".gbs",
        ".gto",
        ".gbo",
        ".gko",
        ".gm1",
        ".gml",
    )
}


def original_drawing_type(filename: str, content: bytes) -> str | None:
    media = DRAWING_MEDIA_TYPES.get(PurePath(filename).suffix.lower())
    if media is None:
        return None
    if b"\x00" in content:
        raise DocumentExtractionError("当前仅支持文本STEP或Gerber原件，不支持压缩包或二进制变体")
    if media == STEP_MEDIA_TYPE:
        if (
            not content.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"ISO-10303-21;")
            or b"END-ISO-10303-21;" not in content[-4096:]
        ):
            raise DocumentExtractionError("文件缺少STEP Part 21起止标记，请核对原件格式")
    elif not re.search(rb"(?:%FS|%MO|%AD|G04)", content[:100000]):
        raise DocumentExtractionError("未找到Gerber文件头，暂不将此文件作为图层解析")
    return media
