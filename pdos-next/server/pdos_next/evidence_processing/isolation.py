import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .parsers import SUPPORTED_MEDIA
from .types import ParseFailure, ParseLimits, ParseResult, SourceLocation, TextSegment


def _rss_bytes(pid: int) -> int:
    """Darwin's address-space rlimit is unavailable; independently monitor child RSS."""
    try:
        probe = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            timeout=1,
            env={"LANG": "C"},
            check=False,
        )
        # A child that completed between polls has no RSS; its result is read next.
        if probe.returncode == 1 and not probe.stdout.strip():
            return 0
        if probe.returncode != 0:
            raise ValueError("RSS probe failed")
        return int(probe.stdout.strip() or b"0") * 1024
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ParseFailure("ISOLATION_UNAVAILABLE", "Parser memory monitor is unavailable") from exc


def _communicate(process: subprocess.Popen, request: bytes, limits: ParseLimits) -> bytes:
    deadline = time.monotonic() + limits.timeout_seconds
    first = True
    try:
        if sys.platform == "darwin" and _rss_bytes(process.pid) > limits.memory_bytes:
            raise ParseFailure("RESOURCE_LIMIT", "Parser memory budget was exceeded")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ParseFailure(
                    "PARSER_TIMEOUT", "Parser exceeded its time budget", retryable=True
                )
            try:
                output, _ = process.communicate(
                    request if first else None,
                    timeout=min(0.1, remaining),
                )
                return output
            except subprocess.TimeoutExpired:
                first = False
                if sys.platform == "darwin" and _rss_bytes(process.pid) > limits.memory_bytes:
                    raise ParseFailure(
                        "RESOURCE_LIMIT", "Parser memory budget was exceeded"
                    ) from None
    except ParseFailure:
        process.kill()
        process.communicate()
        raise


def parse_original(
    content: bytes,
    *,
    media_type: str,
    limits: ParseLimits | None = None,
) -> ParseResult:
    """Derive located text without changing original bytes, credentials or domain state.

    The calling service must verify object ACL and reserve its parser budget first.
    This is process/resource isolation, not a malware scanner or OS security sandbox.
    """
    limits = limits or ParseLimits()
    if not isinstance(content, bytes) or not content:
        raise ParseFailure("EMPTY_CONTENT", "A nonempty original byte sequence is required")
    if len(content) > limits.max_input_bytes:
        raise ParseFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
    if media_type not in SUPPORTED_MEDIA:
        raise ParseFailure("UNSUPPORTED_MEDIA_TYPE", "Original media type is not supported")
    package_root = str(Path(__file__).resolve().parents[2])
    # The script and import directory are server-owned; no document content enters code.
    script = (
        "import sys; sys.path.insert(0, " + repr(package_root) + "); "
        "from pdos_next.evidence_processing.worker import main; main()"
    )
    request = json.dumps(
        {
            "content": base64.b64encode(content).decode("ascii"),
            "media_type": media_type,
            "limits": asdict(limits),
            "parent_memory_monitored": sys.platform == "darwin",
        }
    ).encode("ascii")
    with tempfile.TemporaryDirectory(prefix="pdos-parse-") as directory:
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=directory,
                env={"LANG": "C.UTF-8", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                start_new_session=True,
            )
        except OSError as exc:
            raise ParseFailure(
                "ISOLATION_UNAVAILABLE", "Parser child could not start", retryable=True
            ) from exc
        output = _communicate(process, request, limits)
    if process.returncode != 0:
        raise ParseFailure("RESOURCE_LIMIT", "Parser stopped before completing within its budget")
    # ASCII JSON may escape Unicode to six bytes per character, plus located metadata.
    if len(output) > limits.max_text_chars * 14 + limits.max_segments * 500 + 20_000:
        raise ParseFailure("OUTPUT_LIMIT", "Parser response exceeds the configured output limit")
    try:
        response = json.loads(output)
        if response["ok"] is not True:
            error = response["error"]
            raise ParseFailure(error["code"], error["message"], retryable=error["retryable"])
        result = response["result"]
        if result["source_sha256"] != hashlib.sha256(content).hexdigest():
            raise ValueError("Parser returned a different source identity")
        if result["scan_status"] != "not_scanned":
            raise ValueError("Parser cannot certify malware cleanliness")
        return ParseResult(
            source_sha256=result["source_sha256"],
            media_type=result["media_type"],
            text=result["text"],
            status=result["status"],
            parser_version=result["parser_version"],
            warnings=tuple(result["warnings"]),
            segments=tuple(
                TextSegment(
                    segment["text"],
                    SourceLocation(**segment["location"]),
                    segment["value_kind"],
                )
                for segment in result["segments"]
            ),
            expected_locations=tuple(
                SourceLocation(**location) for location in result["expected_locations"]
            ),
        )
    except ParseFailure:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise ParseFailure("PARSER_PROTOCOL_ERROR", "Parser returned an invalid response") from exc
