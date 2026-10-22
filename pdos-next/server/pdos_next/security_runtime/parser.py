"""Fixed-image OS-isolated parser, reusing the existing located-text algorithm."""

import asyncio
import base64
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path

from pdos_next.evidence_processing.parsers import SUPPORTED_MEDIA
from pdos_next.evidence_processing.types import (
    ParseFailure,
    ParseLimits,
    ParseResult,
    SourceLocation,
    TextSegment,
)

from .docker import DockerFailure, run_container

_CONFIG_PATH = Path(__file__).with_name("parser-image.json")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CODE = re.compile(r"[A-Z0-9_]{1,80}\Z")


def _image_id() -> str:
    """Read only this installed server-owned artifact; no payload/env image override."""
    try:
        if _CONFIG_PATH.is_symlink() or _CONFIG_PATH.stat().st_size > 8_192:
            raise ValueError("Invalid server artifact")
        config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        image = config["image_id"]
        if not isinstance(image, str) or _IMAGE.fullmatch(image) is None:
            raise ValueError("No built immutable image")
        source = Path(__file__).parents[1] / "evidence_processing"
        for name in ("types.py", "parsers.py"):
            if (
                hashlib.sha256((source / name).read_bytes()).hexdigest()
                != config["source_sha256"][name]
            ):
                raise ValueError("Image parser differs from current server parser")
        if config["parser_version"] != "pdos-evidence-v1":
            raise ValueError("Unsupported parser version")
        return image
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ParseFailure(
            "ISOLATION_UNAVAILABLE",
            "A verified local parser container image is unavailable",
            retryable=True,
        ) from exc


def _validate(content: bytes, media_type: str, limits: ParseLimits) -> None:
    if not isinstance(limits, ParseLimits):
        raise ValueError("Typed server-owned parser budgets required")
    for name, value in asdict(limits).items():
        if name == "timeout_seconds":
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("A finite parser deadline is required")
        elif type(value) is not int:
            raise ValueError("Exact integer parser budgets required")
    if not isinstance(content, bytes) or not content:
        raise ParseFailure("EMPTY_CONTENT", "A nonempty original byte sequence is required")
    if len(content) > limits.max_input_bytes:
        raise ParseFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
    if media_type not in SUPPORTED_MEDIA:
        raise ParseFailure("UNSUPPORTED_MEDIA_TYPE", "Original media type is not supported")


def _decode(output: bytes, content: bytes, media_type: str, limits: ParseLimits) -> ParseResult:
    try:
        response = json.loads(output)
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise ValueError("Invalid envelope")
        if response["ok"] is False:
            error = response["error"]
            if not isinstance(error, dict) or _CODE.fullmatch(error["code"]) is None:
                raise ValueError("Invalid failure")
            if type(error["retryable"]) is not bool:
                raise ValueError("Invalid retry status")
            # The fixed image has static parser errors. Never propagate a raw
            # subprocess diagnostic or arbitrary text as a domain error message.
            raise ParseFailure(
                error["code"],
                "Original parsing failed in the isolated container",
                retryable=error["retryable"],
            )
        result = response["result"]
        if (
            result["source_sha256"] != hashlib.sha256(content).hexdigest()
            or result["media_type"] != media_type
            or result["scan_status"] != "not_scanned"
            or result["status"] not in ("parsed", "needs_ocr")
            or result["parser_version"] != "pdos-evidence-v1"
            or not isinstance(result["text"], str)
            or len(result["text"]) > limits.max_text_chars
            or not isinstance(result["segments"], list)
            or len(result["segments"]) > limits.max_segments
            or not isinstance(result["warnings"], list)
            or len(result["warnings"]) > limits.max_sheets + limits.max_pdf_pages + 10
            or any(not isinstance(value, str) or len(value) > 512 for value in result["warnings"])
        ):
            raise ValueError("Invalid original/result binding")
        segments = []
        total_chars = 0
        for raw in result["segments"]:
            if not isinstance(raw["text"], str) or not isinstance(raw["value_kind"], str):
                raise ValueError("Invalid segment")
            total_chars += len(raw["text"])
            if total_chars > limits.max_text_chars or len(raw["value_kind"]) > 32:
                raise ValueError("Invalid segment budget")
            location = SourceLocation(**raw["location"])
            if location.kind not in ("line", "page", "cell"):
                raise ValueError("Invalid source location")
            for value in (location.line, location.page, location.row, location.column):
                if value is not None and (type(value) is not int or value < 1):
                    raise ValueError("Invalid source position")
            if location.kind == "line" and location.line is None:
                raise ValueError("Missing source line")
            if location.kind == "page" and (
                location.page is None or location.page > limits.max_pdf_pages
            ):
                raise ValueError("Missing source page")
            if location.kind == "cell" and (
                location.row is None
                or location.column is None
                or location.row > limits.max_rows_per_sheet
                or location.column > limits.max_columns_per_sheet
                or not isinstance(location.sheet, str)
                or not isinstance(location.cell, str)
            ):
                raise ValueError("Missing source cell")
            segments.append(TextSegment(raw["text"], location, raw["value_kind"]))
        return ParseResult(
            source_sha256=result["source_sha256"],
            media_type=result["media_type"],
            text=result["text"],
            segments=tuple(segments),
            status=result["status"],
            parser_version=result["parser_version"],
            scan_status="not_scanned",
            warnings=tuple(result["warnings"]),
        )
    except ParseFailure:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ParseFailure("PARSER_PROTOCOL_ERROR", "Parser returned an invalid response") from exc


class DockerParserRunner:
    """Linux namespace/cgroup isolation, not a guarantee against all kernel exploits.

    No host parsing fallback, no arbitrary image, no source scripts, no credentials
    and no host mounts are available to a document. A clean scan receipt remains a
    separate prerequisite owned by the common original service.
    """

    def parse(
        self, content: bytes, *, media_type: str, limits: ParseLimits | None = None
    ) -> ParseResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.parse_async(content, media_type=media_type, limits=limits))
        raise ParseFailure(
            "ISOLATION_UNAVAILABLE", "Use the asynchronous container parser in an event loop"
        )

    async def parse_async(
        self, content: bytes, *, media_type: str, limits: ParseLimits | None = None
    ) -> ParseResult:
        limits = limits or ParseLimits()
        _validate(content, media_type, limits)
        image = _image_id()
        request = json.dumps(
            {
                "content": base64.b64encode(content).decode("ascii"),
                "media_type": media_type,
                "limits": asdict(limits),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        try:
            result = await run_container(
                image=image,
                entrypoint="python",
                arguments=("-I", "-B", "/app/parser_worker.py"),
                content=request,
                timeout_seconds=limits.timeout_seconds,
                stdout_maximum=limits.max_text_chars * 14 + limits.max_segments * 500 + 20_000,
                user="65532:65532",
                memory_bytes=limits.memory_bytes,
                pids=16,
                cpus=1,
            )
            if result.returncode in (125, 126, 127):
                raise ParseFailure(
                    "ISOLATION_UNAVAILABLE",
                    "The local parser container could not start",
                    retryable=True,
                )
            if result.returncode != 0:
                raise ParseFailure(
                    "RESOURCE_LIMIT", "Parser stopped before completing within its budget"
                )
            return _decode(result.stdout, content, media_type, limits)
        except DockerFailure as exc:
            if exc.code == "TIMEOUT":
                raise ParseFailure(
                    "PARSER_TIMEOUT", "Parser exceeded its time budget", retryable=True
                ) from exc
            if exc.code == "OUTPUT_LIMIT":
                raise ParseFailure(
                    "OUTPUT_LIMIT", "Parser response exceeds its output budget"
                ) from exc
            raise ParseFailure(
                "ISOLATION_UNAVAILABLE", "Parser isolation could not be confirmed", retryable=True
            ) from exc


def parse_original_container(
    content: bytes, *, media_type: str, limits: ParseLimits | None = None
) -> ParseResult:
    return DockerParserRunner().parse(content, media_type=media_type, limits=limits)
