"""Consume an actual verified extraction row without granting truth or write scope.

An AI-recorded extracted Claim citing a customer original must bind the settled
evidence.extract call and its host-verified row. Registered knowledge documents
have no extraction pipeline and keep the existing read-pinning path.
"""

from uuid import UUID

from pdos_next.domain.preproject.access import fail
from pdos_next.domain.preproject.claim_access import load_source
from pdos_next.domain.preproject.schemas import Reference

from .deterministic_proofs import _historical_read, canonical_hash
from .execution import scope_for_run
from .extract_read_ledger import SourceLocation, locator_from_text
from .models import AgentToolCall

_SPEC_CONTENT_KEYS = (
    "parameter_id",
    "parameter_version",
    "value",
    "lower",
    "upper",
    "unit",
    "condition_note",
    "modality",
    "exceptions",
    "verification_method",
    "acceptance_criterion",
)


def _deny(reason="extraction_proof_required"):
    fail(
        "SOURCE_UNAVAILABLE",
        reason,
        "抽取事实须绑定实际结算的隔离抽取调用及其已核对行。",
    )


def _reference(raw):
    # Reference normally trims strings. A source proof must preserve the literal
    # quote in the actual model tool arguments, including significant spaces.
    return Reference.model_validate(raw).model_copy(update={"quote": raw.get("quote")})


def expected_content(fields):
    """The only ClaimContent a verified row can substantiate; no fabrication room."""
    if not isinstance(fields, dict):
        _deny("extraction_row_invalid")
    statement = fields.get("statement")
    if not isinstance(statement, str) or not statement:
        _deny("extraction_row_invalid")
    content = {"text": statement}
    kind = fields.get("kind")
    if kind == "spec":
        spec = fields.get("spec")
        if not isinstance(spec, dict):
            _deny("extraction_row_invalid")
        for key in _SPEC_CONTENT_KEYS:
            value = spec.get(key)
            if value is not None and value != []:
                content[key] = value
    return content


def expected_availability(fields):
    if fields.get("kind") == "spec":
        availability = fields["spec"].get("availability")
        if availability in {"known", "unknown", "conflicted", "not_applicable"}:
            return availability
        _deny("extraction_row_invalid")
    return "known"


def verify_extracted_claim(session, ctx, run, payload):
    """Validate only; never rewrite caller content or grant qualification.

    Claims citing registered knowledge documents (no original root) keep the
    existing pinned-read path; customer-original citations must consume a
    settled extraction row from this actual Run.
    """
    if run is None or payload.nature != "extracted":
        _deny()
    canonical = payload.source is not None
    if canonical:
        if payload.source.kind != "artifact":
            return  # Snapshot citations keep their own registered-read proof path.
        artifact_id, version = payload.source.id, payload.source.version
        locator, quote = payload.source.locator, payload.source.quote
        statement = None
    else:
        artifact_id, locator = payload.artifact_id, f"line:{payload.line}"
        quote, statement = payload.quote, payload.statement
        bound = [
            raw
            for raw in run.read_sources
            if isinstance(raw, dict)
            and UUID(str(raw.get("artifact_id"))) == artifact_id
        ]
        versions = {raw.get("expected_revision") for raw in bound}
        if len(versions) != 1 or not isinstance(version := next(iter(versions)), int):
            _deny("extraction_citation_mismatch")
    from pdos_next.service import source_for

    source = source_for(session, ctx, run.product_id, artifact_id, version)
    if source.original_id is None:
        return  # Registered knowledge document: no extraction pipeline exists here.
    try:
        derived = locator_from_text(locator)
    except ValueError:
        _deny("extraction_citation_mismatch")
    if derived.kind == "line":
        line = derived.line
    else:
        from pdos_next.models import UploadedOriginal

        original = session.get(UploadedOriginal, source.original_id)
        if original is None:
            _deny("extraction_citation_mismatch")
        matches = [
            entry
            for entry in original.locator_map
            if isinstance(entry, dict)
            and SourceLocation.from_mapping(dict(entry["location"])) == derived
        ]
        if len(matches) != 1:
            _deny("extraction_citation_mismatch")
        line = matches[0]["derived_line_start"]
    reference = _reference(
        {
            "type": "artifact",
            "id": str(artifact_id),
            "version": version,
            "line": line,
            "quote": quote,
        }
    )
    load_source(session, ctx, reference, product_id=run.product_id, lock=True)
    raw_ref = payload.extraction_ref
    if not isinstance(raw_ref, dict) or set(raw_ref) != {"call_id", "row_index"}:
        _deny("extraction_ref_required")
    if type(raw_ref["row_index"]) is not int or raw_ref["row_index"] < 0:
        _deny("extraction_ref_required")
    try:
        identity = UUID(str(raw_ref["call_id"]))
    except (ValueError, AttributeError, TypeError):
        _deny("extraction_ref_required")
    actual, call, binding, arguments = _historical_read(
        session,
        scope_for_run(run),
        identity,
        "ordinary/v1",
        deny=lambda reason: _deny("extraction_" + reason),
    )
    if call.tool != "evidence.extract":
        _deny("extraction_call_invalid")
    rows = call.result.get("rows")
    if not isinstance(rows, list) or raw_ref["row_index"] >= len(rows):
        _deny("extraction_row_missing")
    row = rows[raw_ref["row_index"]]
    if (
        not isinstance(row, dict)
        or row.get("artifact_id") != str(source.id)
        or row.get("revision") != source.revision
        or row.get("locator") != locator
        or row.get("quote") != quote
    ):
        _deny("extraction_citation_mismatch")
    if not canonical:
        bound = [
            raw
            for raw in run.read_sources
            if isinstance(raw, dict)
            and UUID(str(raw.get("artifact_id"))) == source.id
        ]
        versions = {raw.get("expected_revision") for raw in bound}
        if versions != {row["revision"]}:
            _deny("extraction_citation_mismatch")
    if statement is not None and row.get("fields", {}).get("statement") != statement:
        _deny("extraction_content_mismatch")
    fields = row.get("fields")
    if canonical_hash(payload.content) != canonical_hash(expected_content(fields)):
        _deny("extraction_content_mismatch")
    if payload.availability != expected_availability(fields):
        _deny("extraction_availability_mismatch")
    read_ids = row.get("read_call_ids")
    if not isinstance(read_ids, list) or not read_ids:
        _deny("extraction_row_invalid")
    for raw_id in read_ids:
        try:
            read_call = session.get(AgentToolCall, UUID(str(raw_id)))
        except (ValueError, AttributeError, TypeError):
            _deny("extraction_read_invalid")
        if (
            read_call is None
            or read_call.tenant_id != actual.tenant_id
            or read_call.run_id != actual.id
            or read_call.tool != "evidence.artifact.read"
            or read_call.state != "completed"
            or read_call.error_code is not None
            or read_call.receipt_id is not None
        ):
            _deny("extraction_read_invalid")
    return {
        "call_id": str(call.id),
        "run_id": str(actual.id),
        "row_index": raw_ref["row_index"],
        "result_digest": canonical_hash(call.result),
    }
