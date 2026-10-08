"""Bounded Office extraction with paragraph, slide and cell source locations."""

import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile

from docx import Document
from pptx import Presentation

from app.domain.documents import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARACTERS,
    MAX_EXPANDED_XLSX_BYTES,
    DocumentExtractionError,
    DocumentTooLargeError,
    ExtractedFragment,
    _fragment,
)


class LegacyConversionUnavailable(DocumentExtractionError):
    code = "DOCUMENT_CONVERSION_REQUIRED"


def validate_office_archive(content: bytes) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            if (
                len(archive.infolist()) > 10000
                or sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED_XLSX_BYTES
            ):
                raise DocumentTooLargeError("expanded Office document exceeds extraction limits")
            if any(i.flag_bits & 1 for i in archive.infolist()):
                raise DocumentExtractionError("encrypted Office documents are not supported")
    except BadZipFile as error:
        raise DocumentExtractionError("Office document is not a valid archive") from error


def convert_legacy(content: bytes, suffix: str) -> tuple[bytes, str]:
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if converter is None:
        raise LegacyConversionUnavailable("请另存为DOCX、PPTX或XLSX后上传")
    if not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise DocumentExtractionError("file content is not a legacy Office document")
    target = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}[suffix]
    with TemporaryDirectory(prefix="pdos-office-") as directory:
        root = Path(directory)
        source = root / ("source" + suffix)
        source.write_bytes(content)
        profile = root / "profile"
        profile.mkdir()
        # No macros or automatic linked-document updates in the isolated profile.
        (profile / "registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
            '</item><item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item></oor:items>',
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    converter,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--convert-to",
                    target,
                    "--outdir",
                    str(root),
                    str(source),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LegacyConversionUnavailable("旧版Office转换失败，请另存为新版格式") from error
        output = root / ("source." + target)
        if result.returncode != 0 or not output.is_file():
            raise LegacyConversionUnavailable("旧版Office转换失败，请另存为新版格式")
        if output.stat().st_size > MAX_DOCUMENT_BYTES:
            raise DocumentTooLargeError("converted Office document exceeds 20 MiB")
        return output.read_bytes(), "." + target


def extract_office(
    content: bytes, suffix: str
) -> tuple[tuple[ExtractedFragment, ...], dict[str, Any]]:
    original_suffix = suffix
    if suffix in {".doc", ".ppt", ".xls"}:
        content, suffix = convert_legacy(content, suffix)
    validate_office_archive(content)
    fragments: list[ExtractedFragment] = []
    total = 0

    def add(locator: str, text: str) -> None:
        nonlocal total
        total += len(text)
        if total > MAX_DOCUMENT_CHARACTERS:
            raise DocumentTooLargeError("extracted Office text exceeds extraction limits")
        fragments.extend(_fragment(locator, text, start_ordinal=len(fragments) + 1))

    try:
        if suffix == ".docx":
            doc = Document(BytesIO(content))
            for ordinal, block in enumerate(doc.iter_inner_content(), start=1):
                if hasattr(block, "rows"):
                    for row_number, row in enumerate(block.rows, start=1):
                        add(
                            f"table:{ordinal}:row:{row_number}",
                            " | ".join(cell.text for cell in row.cells),
                        )
                else:
                    add(f"paragraph:{ordinal}", block.text)
        elif suffix == ".pptx":
            deck = Presentation(BytesIO(content))
            if len(deck.slides) > 500:
                raise DocumentTooLargeError("presentation exceeds 500 slides")

            def shapes(items: Any, prefix: str) -> None:
                for ordinal, shape in enumerate(items, start=1):
                    locator = f"{prefix}:shape:{ordinal}"
                    if hasattr(shape, "shapes"):
                        shapes(shape.shapes, locator)
                    if shape.has_text_frame:
                        add(locator, shape.text_frame.text)
                    if shape.has_table:
                        for number, row in enumerate(shape.table.rows, start=1):
                            add(f"{locator}:row:{number}", " | ".join(c.text for c in row.cells))

            for ordinal, slide in enumerate(deck.slides, start=1):
                shapes(slide.shapes, f"slide:{ordinal}")
        elif suffix == ".xlsx":
            from app.domain.documents import _extract_xlsx

            fragments = list(_extract_xlsx(content, include_coordinates=True))
        else:
            raise DocumentExtractionError("unsupported Office conversion result")
    except (KeyError, ValueError, TypeError) as error:
        raise DocumentExtractionError("Office document could not be parsed") from error
    return tuple(fragments), {
        "source_format": original_suffix,
        "converted_format": suffix if suffix != original_suffix else None,
    }
