"""Validate server-persisted snapshot page reads before cross-Run consumption.

Integration contract: a registered research read port must create a ``read``
ToolCall binding and settle ``SnapshotPage`` only after RLS/outbound checks and an
actual page read. Existing unbound/search/model results are deliberately refused.
The registered research port persists this proof through the bound host, with the
database guarding its fixed page and registration receipt. Validation grants no access.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationError

from pdos_next.domain.preproject.access import fail
from pdos_next.models import Principal, Receipt
from pdos_next.schema_base import StrictModel

from .deterministic_proofs import _historical_read
from .models import PublicWebSnapshot
from .read_execution import ReadBinding

TOOL = "research.read"


class SnapshotReadInput(StrictModel):
    url: str = Field(min_length=1)
    cursor: int = Field(default=0, strict=True, ge=0)


# Import compatibility only: the former partial shape is no longer trusted.
SnapshotReadBinding = ReadBinding


class SnapshotPage(StrictModel):
    """The trusted port's complete persisted result, including the returned body."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    proof_kind: Literal["registered_snapshot_page"]
    proof_version: int = Field(strict=True, ge=1, le=1)
    snapshot_id: UUID
    version: int = Field(strict=True, ge=1, le=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    registration_receipt_id: UUID
    source_status: Literal["ok", "partial"]
    cursor: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=1)
    locator: str
    markdown: str = Field(min_length=1)
    page_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    next_cursor: int | None = Field(default=None, strict=True, ge=1)


@dataclass(frozen=True)
class VerifiedSnapshotRead:
    call_id: UUID
    snapshot_id: UUID
    version: int
    content_hash: str
    registration_receipt_id: UUID
    line: int
    quote: str


def _unavailable(reason="snapshot_read_not_bound"):
    fail("SOURCE_UNAVAILABLE", reason, "快照引用缺少当前运行的可信逐字读取证明。")


def page_result(snapshot, *, cursor, page_chars):
    """Build trusted metadata for the actual character page after authorization.

    Persist this as the read Call result after RLS and outbound checks. No model
    output or arguments may supply it. Validation reloads all source/ledger rows.
    """
    if (
        type(cursor) is not int
        or cursor < 0
        or type(page_chars) is not int
        or not 1 <= page_chars <= 200_000
    ):
        _unavailable("snapshot_page_invalid")
    end = min(cursor + page_chars, len(snapshot.markdown))
    if cursor >= end:
        _unavailable("snapshot_page_empty")
    body = snapshot.markdown[cursor:end]
    try:
        return SnapshotPage(
            proof_kind="registered_snapshot_page",
            proof_version=1,
            snapshot_id=snapshot.id,
            version=1,
            content_hash=snapshot.content_hash,
            registration_receipt_id=snapshot.receipt_id,
            source_status=snapshot.status,
            cursor=cursor,
            end=end,
            locator=f"chars:{cursor}:{end}",
            markdown=body,
            page_hash=sha256(body.encode("utf-8")).hexdigest(),
            next_cursor=end if end < len(snapshot.markdown) else None,
        ).model_dump(mode="json")
    except (ValidationError, UnicodeError):
        _unavailable("snapshot_page_invalid")


def _registration(session, snapshot):
    """Verify sealed receipt facts without widening another user's Run RLS.

    The original Run may legitimately be invisible to this requester. Its exact
    identity is committed in the snapshot and its immutable registration receipt;
    the database registration guard must establish that original provenance.
    """
    receipt = session.get(Receipt, snapshot.receipt_id)
    if (
        not receipt or receipt.id != snapshot.receipt_id
        or receipt.tenant_id != snapshot.tenant_id
        or receipt.category_id != snapshot.category_id
        or receipt.requester_id != snapshot.owner_id or receipt.subject_revision != 1
        or not isinstance(receipt.result, dict) or receipt.run_id is not None
        or type(receipt.result.get("proof_version")) is not int
        or receipt.result["proof_version"] != 1
    ):
        _unavailable("snapshot_registration_mismatch")
    actor = session.get(Principal, receipt.actor_id)
    if not actor or actor.id != receipt.actor_id or actor.tenant_id != snapshot.tenant_id:
        _unavailable("snapshot_registration_mismatch")
    result = receipt.result
    if result.get("registered_by_run_id") != str(snapshot.registered_by_run_id):
        _unavailable("snapshot_registration_mismatch")
    if receipt.operation == "research.snapshot.register":
        if (
            receipt.subject_type != "public_web_snapshot" or receipt.subject_id != snapshot.id
            or result.get("snapshot_id") != str(snapshot.id)
            or result.get("content_hash") != snapshot.content_hash
        ):
            _unavailable("snapshot_registration_mismatch")
        if actor.kind == "agent":
            if receipt.agent_run_id != snapshot.registered_by_run_id:
                _unavailable("snapshot_registration_mismatch")
        elif (
            actor.kind != "human" or receipt.actor_id != receipt.requester_id
            or receipt.agent_run_id not in {None, snapshot.registered_by_run_id}
            or result.get("prepared_by_run_id") != str(snapshot.registered_by_run_id)
        ):
            _unavailable("snapshot_registration_mismatch")
    elif receipt.operation == "category.create":
        if (
            receipt.subject_type != "category" or receipt.subject_id != snapshot.category_id
            or receipt.product_id is not None or receipt.agent_run_id is not None
            or actor.kind != "human" or receipt.actor_id != receipt.requester_id
            or result.get("category_id") != str(snapshot.category_id)
            or result.get("prepared_by_run_id") != str(snapshot.registered_by_run_id)
            or not isinstance(result.get("snapshot_refs"), list)
        ):
            _unavailable("snapshot_registration_mismatch")
        matches = [ref for ref in result["snapshot_refs"] if (
            isinstance(ref, dict) and ref.get("snapshot_id") == str(snapshot.id)
        )]
        if (
            len(matches) != 1 or set(matches[0]) != {"snapshot_id", "content_hash", "call_id"}
            or matches[0]["content_hash"] != snapshot.content_hash
        ):
            _unavailable("snapshot_registration_mismatch")
        try:
            if str(UUID(matches[0]["call_id"])) != matches[0]["call_id"]:
                _unavailable("snapshot_registration_mismatch")
        except (TypeError, ValueError, AttributeError):
            _unavailable("snapshot_registration_mismatch")
    else:
        _unavailable("snapshot_registration_mismatch")
    return receipt


def validate_snapshot_read(session, scope, snapshot_id, version, line, quote, *, call_id):
    """Reload ordinary-RLS rows; verify a persisted read page covers this exact quote.

    The consumer may be in main isolation; the proof must come from this same
    Run's registered research graph. Source registration may belong to another
    Run/requester. Private outbound snapshot reuse remains unavailable until its
    dedicated port implements a verifiable outbound authorization contract.
    """
    reasons = {
        "call_invalid": "snapshot_read_not_bound",
        "binding_invalid": "snapshot_read_not_bound",
        "scope_mismatch": "snapshot_read_scope_mismatch",
    }
    try:
        run, call, binding, arguments = _historical_read(
            session, scope, call_id, "registered_snapshot/v1",
            deny=lambda reason: _unavailable(reasons.get(reason, "snapshot_read_graph_mismatch")),
        )
        if call.tool != TOOL:
            _unavailable()
        page = SnapshotPage.model_validate(call.result)
    except (ValidationError, AttributeError, TypeError, ValueError):
        _unavailable()
    try:
        payload = SnapshotReadInput.model_validate(arguments)
    except ValidationError:
        _unavailable("snapshot_read_graph_mismatch")
    snapshot = session.get(PublicWebSnapshot, snapshot_id)
    if (
        not snapshot
        or snapshot.id != snapshot_id
        or snapshot.tenant_id != run.tenant_id
        or snapshot.category_id != run.category_id
        or snapshot.status not in {"ok", "partial"}
        or type(version) is not int
        or version != 1
        or payload.url not in {snapshot.url, snapshot.final_url}
    ):
        _unavailable("snapshot_unavailable")
    if snapshot.visibility != "category":
        _unavailable("snapshot_private_outbound_unbound")
    receipt = _registration(session, snapshot)
    try:
        actual_hash = sha256(snapshot.markdown.encode("utf-8")).hexdigest()
    except (AttributeError, UnicodeError):
        _unavailable("snapshot_content_mismatch")
    if actual_hash != snapshot.content_hash:
        _unavailable("snapshot_content_mismatch")
    expected = page_result(snapshot, cursor=payload.cursor, page_chars=binding.page_chars)
    if page.model_dump(mode="json") != expected:
        _unavailable("snapshot_page_mismatch")
    lines = snapshot.markdown.splitlines(keepends=True)
    if (
        type(line) is not int
        or not 1 <= line <= len(lines)
        or not isinstance(quote, str)
        or not quote
    ):
        _unavailable("snapshot_quote_not_read")
    actual_line = snapshot.markdown.splitlines()[line - 1]
    offset = sum(len(part) for part in lines[: line - 1])
    # A quote may repeat on a line: at least one exact occurrence must have been
    # wholly returned. A page boundary cannot manufacture an unread full quote.
    start = max(0, page.cursor - offset)
    end = min(len(actual_line), page.end - offset)
    if start >= end or quote not in actual_line[start:end]:
        _unavailable("snapshot_quote_not_read")
    return VerifiedSnapshotRead(
        call.id, snapshot.id, version, snapshot.content_hash, receipt.id, line, quote
    )
