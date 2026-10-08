"""Deterministic budget/type checks, explicitly distinct from malware certification."""

import hashlib
import io
import stat
import struct
import time
import zipfile
import zlib
from pathlib import PurePosixPath

from .types import ScanRequest, SecurityFailure

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SUPPORTED_MEDIA = frozenset({"text/plain", "text/markdown", "application/pdf", XLSX})


def _bounded_directory(content: bytes, max_entries: int) -> None:
    """Bound central-directory entry allocation before ZipFile builds its in-memory list."""
    end = content.rfind(b"PK\x05\x06", max(0, len(content) - 65_557))
    if end < 0 or end + 22 > len(content):
        raise SecurityFailure("MALFORMED_ARCHIVE")
    _, disk, directory_disk, count_disk, count, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", content, end
    )
    if (
        disk
        or directory_disk
        or count_disk != count
        or end + 22 + comment != len(content)
        or count == 0xFFFF
        or size == 0xFFFFFFFF
        or offset == 0xFFFFFFFF
        or offset + size != end
    ):
        raise SecurityFailure("UNSUPPORTED_ARCHIVE_LAYOUT")
    if count > max_entries:
        raise SecurityFailure("ARCHIVE_ENTRY_LIMIT")
    position, actual = offset, 0
    while position < end:
        actual += 1
        if actual > max_entries:
            raise SecurityFailure("ARCHIVE_ENTRY_LIMIT")
        if position + 46 > end or content[position : position + 4] != b"PK\x01\x02":
            raise SecurityFailure("MALFORMED_ARCHIVE")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", content, position + 28)
        if name_size > 1024:
            raise SecurityFailure("UNSAFE_ARCHIVE_ENTRY")
        position += 46 + name_size + extra_size + comment_size
    if position != end or actual != count:
        raise SecurityFailure("MALFORMED_ARCHIVE")


def check_content(request: ScanRequest, content: bytes, *, deadline: float | None = None) -> None:
    """No script/macro execution, extraction, XML parsing, or malware scan occurs here."""
    ref, limits = request.binding.object_ref, request.policy.limits
    if type(content) is not bytes or not content:
        raise SecurityFailure("INVALID_BYTES")
    if len(content) > limits.max_input_bytes or ref.size_bytes > limits.max_input_bytes:
        raise SecurityFailure("FILE_TOO_LARGE")
    if len(content) != ref.size_bytes or hashlib.sha256(content).hexdigest() != ref.content_sha256:
        raise SecurityFailure("INTEGRITY_MISMATCH")
    if ref.media_type not in SUPPORTED_MEDIA:
        raise SecurityFailure("UNSUPPORTED_MEDIA_TYPE")
    deadline = deadline if deadline is not None else time.monotonic() + limits.timeout_seconds

    def remaining():
        if time.monotonic() >= deadline:
            raise SecurityFailure("SCAN_TIMEOUT")

    remaining()
    if ref.media_type in {"text/plain", "text/markdown"}:
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SecurityFailure("TYPE_MISMATCH") from exc
        if b"\x00" in content or content.startswith((b"MZ", b"PK\x03\x04", b"%PDF-")):
            raise SecurityFailure("TYPE_MISMATCH")
    elif ref.media_type == "application/pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-4096:]:
            raise SecurityFailure("TYPE_MISMATCH")
    else:
        if not content.startswith(b"PK\x03\x04"):
            raise SecurityFailure("TYPE_MISMATCH")
        _bounded_directory(content, limits.max_zip_entries)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > limits.max_zip_entries:
                    raise SecurityFailure("ARCHIVE_ENTRY_LIMIT")
                names, declared_total = set(), 0
                for entry in entries:
                    remaining()
                    name = entry.filename
                    path = PurePosixPath(name)
                    if (
                        entry.orig_filename != name
                        or name in names
                        or len(name) > 1024
                        or "\\" in name
                        or path.is_absolute()
                        or any(part in {"..", "."} for part in name.split("/"))
                        or any(ord(c) < 32 or c == ":" for c in name)
                    ):
                        raise SecurityFailure("UNSAFE_ARCHIVE_ENTRY")
                    names.add(name)
                    mode = (entry.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode) or entry.flag_bits & 1:
                        raise SecurityFailure("UNSAFE_ARCHIVE_ENTRY")
                    lowered = name.lower()
                    if any(s in lowered for s in ("vbaproject", "activex/", "embeddings/")):
                        raise SecurityFailure("ACTIVE_CONTENT_REJECTED")
                    if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                        raise SecurityFailure("UNSUPPORTED_COMPRESSION")
                    declared_total += entry.file_size
                    if entry.file_size > limits.max_zip_entry_bytes:
                        raise SecurityFailure("ARCHIVE_ENTRY_BYTES_LIMIT")
                    if declared_total > limits.max_zip_expanded_bytes:
                        raise SecurityFailure("ARCHIVE_EXPANDED_LIMIT")
                    if entry.file_size > max(1, entry.compress_size) * limits.max_zip_ratio:
                        raise SecurityFailure("ARCHIVE_RATIO_LIMIT")
                if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
                    raise SecurityFailure("TYPE_MISMATCH")
                actual_total = 0
                for entry in entries:
                    entry_total = 0
                    with archive.open(entry) as stream:
                        while chunk := stream.read(65_536):
                            remaining()
                            entry_total += len(chunk)
                            actual_total += len(chunk)
                            if entry_total > limits.max_zip_entry_bytes:
                                raise SecurityFailure("ARCHIVE_ENTRY_BYTES_LIMIT")
                            if actual_total > limits.max_zip_expanded_bytes:
                                raise SecurityFailure("ARCHIVE_EXPANDED_LIMIT")
                    if entry_total != entry.file_size:
                        raise SecurityFailure("ARCHIVE_SIZE_MISMATCH")
        except SecurityFailure:
            raise
        except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError, zlib.error) as exc:
            raise SecurityFailure("MALFORMED_ARCHIVE") from exc
    remaining()
