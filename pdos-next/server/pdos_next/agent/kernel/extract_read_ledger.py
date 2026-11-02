"""Exact page and quotation bookkeeping after host authorization and read proof."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from uuid import UUID


def _integer(value, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Expected a bounded integer")
    return value


def _identity(value):
    identity = str(UUID(str(value)))
    if str(value) != identity:
        raise ValueError("Expected a canonical source or execution UUID")
    return identity


def _freeze(value):
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Expected finite JSON data")


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class SourceLocation:
    """The existing evidence_processing.SourceLocation fields and representation."""

    kind: str
    line: int | None = None
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    column: int | None = None
    cell: str | None = None

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError("Unsupported original location")
        location = cls(**value)
        if location.kind == "line":
            _integer(location.line, minimum=1)
            allowed = {"kind", "line"}
        elif location.kind == "page":
            _integer(location.page, minimum=1)
            allowed = {"kind", "page"}
        elif location.kind == "cell":
            _integer(location.row, minimum=1)
            _integer(location.column, minimum=1)
            if not isinstance(location.sheet, str) or not location.sheet:
                raise ValueError("Cell location requires a worksheet")
            if not isinstance(location.cell, str) or not re.fullmatch(
                r"[A-Z]+[1-9][0-9]*", location.cell
            ):
                raise ValueError("Cell location requires the original coordinate")
            allowed = {"kind", "sheet", "row", "column", "cell"}
        else:
            raise ValueError("Unsupported original location")
        if any(item is not None for key, item in asdict(location).items() if key not in allowed):
            raise ValueError("Original location has conflicting coordinate fields")
        return location


@dataclass(frozen=True)
class LocatorEntry:
    derived_line_start: int
    derived_line_end: int
    location: SourceLocation
    value_kind: str


def locator_from_text(value):
    """Parse the wire locator form (line:N, page:N, cell:["sheet","B2"])."""
    if not isinstance(value, str):
        return SourceLocation.from_mapping(value)
    if match := re.fullmatch(r"line:([1-9][0-9]*)", value):
        return SourceLocation("line", line=int(match[1]))
    if match := re.fullmatch(r"page:([1-9][0-9]*)", value):
        return SourceLocation("page", page=int(match[1]))
    if value.startswith("cell:"):
        try:
            parsed = json.loads(value[5:])
        except ValueError:
            raise ValueError("Invalid cell locator") from None
        if (
            isinstance(parsed, list)
            and len(parsed) == 2
            and all(isinstance(item, str) for item in parsed)
        ):
            sheet, coordinate = parsed
            match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", coordinate)
            if match is not None:
                letters, digits = match.groups()
                column = 0
                for char in letters:
                    column = column * 26 + (ord(char) - 64)
                return SourceLocation(
                    "cell", sheet=sheet, row=int(digits), column=column, cell=coordinate
                )
    raise ValueError("Unsupported locator text")


@dataclass(frozen=True)
class ParseManifest:
    """Optional parser-produced inventory, never a model completeness declaration.

    basis is the existing location kind: lines, native-text PDF pages, or populated
    XLSX cells. An inventory does not prove visual/OCR or semantic requirement
    coverage. Empty cells and generated page separators are not invented locations.
    """

    parser_version: str
    basis: str
    expected_locations: tuple[SourceLocation, ...]

    def __post_init__(self):
        if not isinstance(self.parser_version, str) or not self.parser_version:
            raise ValueError("Parser inventory requires its actual version")
        if self.basis not in {"line", "page", "cell"}:
            raise ValueError("Unsupported parser inventory basis")
        if not isinstance(self.expected_locations, tuple) or any(
            not isinstance(location, SourceLocation) or location.kind != self.basis
            for location in self.expected_locations
        ):
            raise ValueError("Parser inventory does not match its location basis")
        for location in self.expected_locations:
            SourceLocation.from_mapping(asdict(location))
        if len(set(self.expected_locations)) != len(self.expected_locations):
            raise ValueError("Parser inventory contains duplicate locations")


@dataclass(frozen=True)
class ArtifactSeal:
    artifact_id: str
    revision: int
    content_hash: str
    text: str
    total_lines: int
    locator_map: tuple[LocatorEntry, ...]
    parse_status: str
    parse_code: str | None
    parse_manifest: ParseManifest | None = None

    @classmethod
    def from_server(
        cls,
        *,
        artifact_id,
        revision,
        content_hash,
        text,
        total_lines,
        locator_map,
        parse_status,
        parse_code=None,
        parse_manifest=None,
    ):
        identity = _identity(artifact_id)
        _integer(revision, minimum=1)
        _integer(total_lines)
        if not isinstance(content_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", content_hash):
            raise ValueError("Source content hash is not canonical")
        if not isinstance(text, str) or len(text.splitlines()) != total_lines:
            raise ValueError("Source text differs from its sealed total line count")
        # service.digest(str) hashes the original UTF-8 text without JSON encoding.
        if hashlib.sha256(text.encode()).hexdigest() != content_hash:
            raise ValueError("Sealed text differs from the actual Artifact content hash")
        if parse_status not in {"uploaded", "parsed", "needs_ocr", "failed"}:
            raise ValueError("Unknown UploadedOriginal parse status")
        if parse_code is not None and (not isinstance(parse_code, str) or not parse_code):
            raise ValueError("Invalid original parser code")
        if parse_manifest is not None and not isinstance(parse_manifest, ParseManifest):
            raise ValueError("Expected a parser-produced inventory")
        entries = []
        for raw in locator_map:
            if not isinstance(raw, Mapping) or set(raw) != {
                "derived_line_start",
                "derived_line_end",
                "location",
                "value_kind",
            }:
                raise ValueError("Invalid persisted original locator map")
            start = _integer(raw["derived_line_start"], minimum=1)
            end = _integer(raw["derived_line_end"], minimum=start)
            if end > total_lines or not isinstance(raw["value_kind"], str):
                raise ValueError("Original location is outside the sealed text")
            entries.append(
                LocatorEntry(
                    start, end, SourceLocation.from_mapping(raw["location"]), raw["value_kind"]
                )
            )
        return cls(
            identity,
            revision,
            content_hash,
            text,
            total_lines,
            tuple(entries),
            parse_status,
            parse_code,
            parse_manifest,
        )


@dataclass(frozen=True)
class SuccessfulPage:
    call_id: str
    artifact_id: str
    revision: int
    cursor: int
    page_size: int
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True)
class QuoteFailure:
    input_index: int
    code: str


@dataclass(frozen=True)
class VerifiedRow:
    artifact_id: str
    revision: int
    locator: str | SourceLocation
    quote: str
    fields: Mapping
    read_call_ids: tuple[str, ...]

    def as_dict(self):
        return {
            "artifact_id": self.artifact_id,
            "revision": self.revision,
            "locator": asdict(self.locator)
            if isinstance(self.locator, SourceLocation)
            else self.locator,
            "quote": self.quote,
            "fields": _thaw(self.fields),
            "read_call_ids": list(self.read_call_ids),
        }


@dataclass(frozen=True)
class VerifiedRows:
    rows: tuple[VerifiedRow, ...]
    failures: tuple[QuoteFailure, ...]


def _union(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _unread(total_lines, ranges):
    result, cursor = [], 1
    for start, end in ranges:
        if cursor < start:
            result.append((cursor, start - 1))
        cursor = end + 1
    if cursor <= total_lines:
        result.append((cursor, total_lines))
    return tuple(result)


def _covered(start, end, ranges):
    return any(left <= start and end <= right for left, right in ranges)


def _line_bounds(text):
    offset, result = 0, []
    for line, chunk in zip(text.splitlines(), text.splitlines(keepends=True), strict=True):
        result.append((offset, offset + len(line)))
        offset += len(chunk)
    return tuple(result)


class ExtractReadLedger:
    """Accept only host-supplied completed pages, then verify quotations and coverage."""

    def __init__(self, sources: Iterable[ArtifactSeal]):
        self._sources, self._pages = {}, {}
        for source in sources:
            if not isinstance(source, ArtifactSeal) or source.artifact_id in self._sources:
                raise ValueError("Sources must be unique server seals")
            self._sources[source.artifact_id] = source

    def has_page(self, call_id):
        """Whether this exact completed call is already recorded (replay idempotency)."""
        return str(call_id) in self._pages

    def record_successful_page(self, result, *, call_id, cursor, page_size):
        """The host verifies the actual call's success/provenance before invoking this.

        Match the internal exact derived-line projection exactly. A read at/past EOF adds no
        coverage. Supplying an EOF cursor cannot stand in for reading earlier text.
        """
        identity = _identity(call_id)
        _integer(cursor)
        _integer(page_size, minimum=1)
        if page_size > 200:
            raise ValueError("Page size differs from the new read tool contract")
        if not isinstance(result, Mapping) or set(result) != {
            "artifact_id",
            "revision",
            "content_hash",
            "lines",
            "next_cursor",
        }:
            raise ValueError("Expected the persisted artifact-read result")
        source = self._sources.get(result["artifact_id"])
        if source is None or source.parse_status != "parsed":
            raise ValueError("Source is not an assigned parsed Artifact")
        end = min(source.total_lines, cursor + page_size)
        expected = [
            {"line": index + 1, "text": line}
            for index, line in enumerate(source.text.splitlines()[cursor:end], start=cursor)
        ]
        if (
            type(result["revision"]) is not int
            or result["revision"] != source.revision
            or result["content_hash"] != source.content_hash
            or not isinstance(result["lines"], list)
            or result["lines"] != expected
            or any(type(line.get("line")) is not int for line in result["lines"])
            or result["next_cursor"] != (end if end < source.total_lines else None)
            or result["next_cursor"] is not None
            and type(result["next_cursor"]) is not int
        ):
            raise ValueError("Completed page differs from its sealed source or requested range")
        page = SuccessfulPage(
            identity,
            source.artifact_id,
            source.revision,
            cursor,
            page_size,
            cursor + 1 if expected else None,
            end if expected else None,
        )
        previous = self._pages.get(identity)
        if previous is not None and previous != page:
            raise ValueError("A completed call cannot be rebound to another page")
        self._pages[identity] = page
        return page

    def _ranges(self, artifact_id):
        return _union(
            (page.start_line, page.end_line)
            for page in self._pages.values()
            if page.artifact_id == artifact_id and page.start_line is not None
        )

    def _quote(self, source, locator, quote):
        bounds = _line_bounds(source.text)
        if isinstance(locator, str):
            match = re.fullmatch(r"line:([1-9][0-9]*)", locator)
            if match is not None:
                if int(match[1]) > source.total_lines:
                    return None, "locator_not_in_source"
                start = end = int(match[1])
            else:
                try:
                    locator = locator_from_text(locator)
                except ValueError:
                    return None, "locator_not_in_source"
        if not isinstance(locator, str):
            entries = [entry for entry in source.locator_map if entry.location == locator]
            if not entries:
                return None, "locator_not_in_source"
            if len(entries) != 1:
                return None, "ambiguous_locator"
            start, end = entries[0].derived_line_start, entries[0].derived_line_end
        left, right = bounds[start - 1][0], bounds[end - 1][1]
        body = source.text[left:right]
        offset = body.find(quote)
        if offset < 0:
            return None, "quote_not_in_source"
        ranges = self._ranges(source.artifact_id)
        while offset >= 0:
            quote_left, quote_right = left + offset, left + offset + len(quote)
            touched = [
                index + 1
                for index, (line_left, line_right) in enumerate(bounds)
                if line_left < quote_right and quote_left < line_right
            ]
            if touched and _covered(touched[0], touched[-1], ranges):
                calls = tuple(
                    sorted(
                        page.call_id
                        for page in self._pages.values()
                        if page.artifact_id == source.artifact_id
                        and page.start_line is not None
                        and page.start_line <= touched[-1]
                        and touched[0] <= page.end_line
                    )
                )
                return calls, None
            offset = body.find(quote, offset + 1)
        return None, "source_location_not_read"

    def verify_rows(self, rows):
        """Keep citation-verified rows; code owns all failures, not model status/error."""
        accepted, failures = [], []
        for index, raw in enumerate(rows):
            try:
                if not isinstance(raw, Mapping) or set(raw) != {
                    "artifact_id",
                    "revision",
                    "locator",
                    "quote",
                    "fields",
                }:
                    raise ValueError("Invalid extraction row")
                source = self._sources.get(raw["artifact_id"])
                if source is None:
                    code = "source_not_assigned"
                elif type(raw["revision"]) is not int or raw["revision"] != source.revision:
                    code = "source_version_mismatch"
                elif source.parse_status != "parsed":
                    code = "source_not_parsed"
                elif not isinstance(raw["quote"], str) or not raw["quote"]:
                    code = "quote_required"
                else:
                    locator = (
                        raw["locator"]
                        if isinstance(raw["locator"], str)
                        else SourceLocation.from_mapping(raw["locator"])
                    )
                    if not isinstance(raw["fields"], Mapping):
                        raise ValueError("Expected structured extraction fields")
                    fields = _freeze(raw["fields"])
                    calls, code = self._quote(source, locator, raw["quote"])
                    if code is None:
                        accepted.append(
                            VerifiedRow(
                                source.artifact_id,
                                source.revision,
                                locator,
                                raw["quote"],
                                fields,
                                calls,
                            )
                        )
                        continue
            except (TypeError, KeyError, ValueError):
                code = "invalid_extraction_row"
            failures.append(QuoteFailure(index, code))
        return VerifiedRows(tuple(accepted), tuple(failures))

    def coverage(self, artifact_id):
        """Report parsed reading and parser-declared location integrity separately."""
        source = self._sources[artifact_id]
        ranges = self._ranges(artifact_id)
        unread = _unread(source.total_lines, ranges)
        mapped = {entry.location for entry in source.locator_map}
        manifest = source.parse_manifest
        represented = tuple(dict.fromkeys(entry.location for entry in source.locator_map))
        read_locations = tuple(
            location
            for location in represented
            if all(
                _covered(entry.derived_line_start, entry.derived_line_end, ranges)
                for entry in source.locator_map
                if entry.location == location
            )
        )
        expected = manifest.expected_locations if manifest else ()
        missing = tuple(location for location in expected if location not in mapped)
        unlisted = tuple(
            location for location in represented if manifest and location not in expected
        )
        known = manifest is not None and bool(expected)
        fully_represented = (
            (
                not missing
                and not unlisted
                and source.parse_status == "parsed"
                and source.parse_code != "PARTIAL_TEXT"
            )
            if known
            else None
        )
        return {
            "artifact_id": source.artifact_id,
            "revision": source.revision,
            "content_hash": source.content_hash,
            "parse_status": source.parse_status,
            "parse_code": source.parse_code,
            "parsed_text": {
                "total_lines": source.total_lines,
                "read_ranges": [list(pair) for pair in ranges],
                "unread_ranges": [list(pair) for pair in unread],
                "fully_read": source.parse_status == "parsed"
                and source.total_lines > 0
                and not unread,
            },
            "original_locations": {
                "parser_version": manifest.parser_version if manifest else None,
                "basis": manifest.basis if manifest else None,
                "extent_known": known,
                "represented": [asdict(location) for location in represented],
                "read": [asdict(location) for location in read_locations],
                "unrepresented": [asdict(location) for location in missing],
                "unlisted": [asdict(location) for location in unlisted],
                "fully_represented": fully_represented,
                "fully_read": fully_represented and set(expected).issubset(read_locations)
                if known
                else None,
                "limitation": (
                    "Parser-declared text locations only; visual/OCR and semantic extraction "
                    "completeness are not established."
                ),
                "reason": "partial_text_extent_unknown"
                if source.parse_code == "PARTIAL_TEXT" and not known
                else "parse_manifest_missing"
                if not known
                else source.parse_code,
            },
        }
