"""Bounded located wire pages and an explicit internal derived-line projection."""

import json
import re
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.service import digest

from .extract_read_ledger import SourceLocation
from .extract_schemas import ArtifactReadInput


def locator_text(location):
    if location.kind == "line":
        return f"line:{location.line}"
    if location.kind == "page":
        return f"page:{location.page}"
    return "cell:" + json.dumps(
        [location.sheet, location.cell], ensure_ascii=False, separators=(",", ":")
    )


def resolve_locator(seal, locator):
    if match := re.fullmatch(r"line:([1-9][0-9]*)", locator):
        if int(match[1]) <= seal.total_lines:
            return locator
    matches = [
        entry.location for entry in seal.locator_map if locator_text(entry.location) == locator
    ]
    if len(matches) == 1:
        return matches[0]
    raise DomainError(
        "VALIDATION_FAILED",
        "定位不在当前固定原件中。",
        422,
        detail={"reason": "locator_not_in_source"},
    )


def absolute_cursor(seal, data):
    if str(data.artifact_version_id) != seal.artifact_id:
        raise DomainError("FORBIDDEN_SCOPE", "读取版本不在固定来源中。", 403)
    if data.locator is None:
        return data.cursor
    location = resolve_locator(seal, data.locator)
    if isinstance(location, str):
        base = int(location.split(":", 1)[1]) - 1
    else:
        base = next(
            entry.derived_line_start - 1 for entry in seal.locator_map if entry.location == location
        )
    return base + data.cursor


def located_page(seal, arguments):
    data = ArtifactReadInput.model_validate(arguments)
    start = absolute_cursor(seal, data)
    end = min(seal.total_lines, start + data.page_size)
    fragments = seal.text.splitlines(keepends=True)
    native_locations = {}
    for entry in seal.locator_map:
        for line in range(
            max(start + 1, entry.derived_line_start), min(end, entry.derived_line_end) + 1
        ):
            if line in native_locations:
                raise DomainError("INTEGRITY_MISMATCH", "原件定位存在重叠，需核对。")
            native_locations[line] = entry.location
    blocks = []
    for index in range(start, end):
        native = native_locations.get(index + 1, SourceLocation("line", line=index + 1))
        blocks.append(
            {
                "locator": locator_text(native),
                "text": fragments[index],
                "derived_line_start": index + 1,
                "derived_line_end": index + 1,
            }
        )
    return {
        "artifact_version_id": seal.artifact_id,
        "revision": seal.revision,
        "content_hash": seal.content_hash,
        "parse_status": seal.parse_status,
        "parse_code": seal.parse_code,
        "blocks": blocks,
        "next_cursor": data.cursor + len(blocks) if end < seal.total_lines else None,
    }


def project_page(seal, arguments, wire):
    """Never accept an older wire as a new located page or repair a stored page."""
    data = ArtifactReadInput.model_validate(arguments)
    expected = located_page(seal, arguments)
    if not isinstance(wire, dict) or digest(wire) != digest(expected):
        raise DomainError("SOURCE_STALE", "读取页与固定原件、定位或版本不一致。")
    start = absolute_cursor(seal, data)
    end = min(seal.total_lines, start + data.page_size)
    lines = seal.text.splitlines()
    internal = {
        "artifact_id": seal.artifact_id,
        "revision": seal.revision,
        "content_hash": seal.content_hash,
        "lines": [{"line": index + 1, "text": lines[index]} for index in range(start, end)],
        "next_cursor": end if end < seal.total_lines else None,
    }
    return (
        UUID(seal.artifact_id),
        internal,
        tuple(dict.fromkeys(block["locator"] for block in wire["blocks"])),
    )
