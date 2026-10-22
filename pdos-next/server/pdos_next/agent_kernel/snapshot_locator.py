"""Whole-region snapshot evidence locators backed by one actual registered page."""

import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from pdos_next.domain.preproject.access import fail

from .deterministic_proofs import _historical_read
from .models import PublicWebSnapshot
from .snapshot_read_ledger import TOOL, SnapshotPage, validate_snapshot_read


@dataclass(frozen=True)
class VerifiedSnapshotLocator:
    call_id: UUID
    snapshot_id: UUID
    version: int
    content_hash: str
    registration_receipt_id: UUID
    locator: str
    start: int
    end: int


def _deny(reason="snapshot_locator_not_read"):
    fail("SOURCE_UNAVAILABLE", reason, "快照定位须完整落在当前运行实际读取的页面内。")


def validate_snapshot_locator(session, scope, snapshot_id, version, locator, *, call_id):
    """Validate a complete line or half-open character range, without caller quotes.

    ``call_id`` comes from the host's same-Run read ledger lookup, never a model
    execution binding. Character offsets are Python/JSON Unicode code points,
    matching SnapshotPage; line locators cover the text without its line ending.
    A verified fragment proves page provenance only. Explicit bounds separately
    establish that every character designated by the locator was actually read.
    """
    try:
        if type(locator) is not str:
            _deny("snapshot_locator_invalid")
        line_match = re.fullmatch(r"line:([1-9][0-9]*)", locator)
        chars_match = re.fullmatch(r"chars:(0|[1-9][0-9]*):(0|[1-9][0-9]*)", locator)
        if not line_match and not chars_match:
            _deny("snapshot_locator_invalid")
        _, call, _, _ = _historical_read(
            session, scope, call_id, "registered_snapshot/v1",
            deny=lambda reason: _deny("snapshot_read_" + reason),
        )
        if call.tool != TOOL:
            _deny("snapshot_read_not_bound")
        page = SnapshotPage.model_validate(call.result)
        snapshot = session.get(PublicWebSnapshot, snapshot_id)
        if snapshot is None or page.snapshot_id != snapshot_id:
            _deny("snapshot_unavailable")
        body = snapshot.markdown
        lines = body.splitlines(keepends=True)
        plain_lines = body.splitlines()
        if line_match:
            line = int(line_match[1])
            if not 1 <= line <= len(lines) or not plain_lines[line - 1].strip():
                _deny("snapshot_locator_invalid")
            start = sum(len(part) for part in lines[:line - 1])
            end = start + len(plain_lines[line - 1])
        else:
            start, end = int(chars_match[1]), int(chars_match[2])
        if not 0 <= start < end <= len(body):
            _deny("snapshot_locator_invalid")
        if not page.cursor <= start < end <= page.end:
            _deny()
        # Find a literal nonblank line fragment *inside this region*. Newline-
        # only or whitespace-only ranges cannot manufacture a quote witness.
        offset = 0
        for index, (full_line, plain_line) in enumerate(zip(lines, plain_lines, strict=True), 1):
            fragment_start = max(start, offset)
            fragment_end = min(end, offset + len(plain_line))
            quote = body[fragment_start:fragment_end] if fragment_start < fragment_end else ""
            if quote.strip():
                proof = validate_snapshot_read(
                    session, scope, snapshot_id, version, index, quote, call_id=call_id,
                )
                return VerifiedSnapshotLocator(
                    proof.call_id, proof.snapshot_id, proof.version, proof.content_hash,
                    proof.registration_receipt_id, locator, start, end,
                )
            offset += len(full_line)
        _deny("snapshot_locator_invalid")
    except (ValidationError, AttributeError, TypeError, ValueError):
        _deny("snapshot_locator_invalid")
