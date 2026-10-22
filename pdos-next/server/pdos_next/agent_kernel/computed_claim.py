"""Consume an actual deterministic read without granting truth or write qualification."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.domain.preproject.access import fail
from pdos_next.domain.preproject.claim_access import load_source, resolve, source_reference
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.errors import DomainError

from .deterministic_proofs import resolve_compute_proof
from .domain_reads import _outbound_unavailable
from .execution import scope_for_run
from .m3_calculators import ENGINES, CostSubtotalInput
from .m3_object_reads import _public_sources
from .models import AgentToolCall
from .read_execution import ReadBinding
from .snapshot_read_ledger import validate_snapshot_read


def _deny(reason="deterministic_proof_required"):
    fail("SOURCE_UNAVAILABLE", reason, "计算事实须绑定实际计算及全部输入来源的可信读取证明。")


def _reference(raw):
    # Reference normally trims strings. A source proof must preserve the literal
    # quote in the actual model tool arguments, including significant spaces.
    return Reference.model_validate(raw).model_copy(update={"quote": raw.get("quote")})


def _artifact(session, ctx, run, ref):
    source = load_source(session, ctx, ref, product_id=run.product_id, lock=True)
    matches = []
    for raw in run.read_sources:
        if not isinstance(raw, dict):
            _deny("run_source_binding_invalid")
        if UUID(str(raw.get("artifact_id"))) != ref.id:
            continue
        if (
            type(raw.get("expected_revision")) is not int
            or raw["expected_revision"] != ref.version
            or "product_id" not in raw
        ):
            _deny("source_read_not_bound")
        product_id = UUID(str(raw["product_id"])) if raw["product_id"] is not None else None
        if product_id != source.product_id or product_id not in (None, run.product_id):
            _deny("run_source_binding_invalid")
        matches.append(raw)
    if not matches:
        _deny("source_read_not_bound")
    _public_sources(session, ctx, [ref])


def _snapshot(session, ctx, run, ref):
    load_source(session, ctx, ref, product_id=run.product_id, lock=True)
    # Registration alone does not establish what this Run read. Query only real
    # completed reads, then let the ledger verify the full graph/page/receipt.
    calls = session.scalars(
        select(AgentToolCall).where(
            AgentToolCall.tenant_id == ctx.tenant_id,
            AgentToolCall.run_id == run.id,
            AgentToolCall.tool == "research.read",
            AgentToolCall.state == "completed",
            AgentToolCall.execution_binding["read_kind"].astext == "registered_snapshot/v1",
            AgentToolCall.result["snapshot_id"].astext == str(ref.id),
        )
    ).all()
    for call in calls:
        # Also filter in Python: no trust in search results or partial binding.
        if (
            call.tenant_id != ctx.tenant_id or call.run_id != run.id
            or call.tool != "research.read" or call.state != "completed"
            or not isinstance(call.result, dict)
            or call.result.get("snapshot_id") != str(ref.id)
        ):
            continue
        try:
            validate_snapshot_read(
                session, scope_for_run(run), ref.id, ref.version, ref.line, ref.quote,
                call_id=call.id,
            )
        except DomainError:
            continue
        return
    _deny("snapshot_read_not_bound")


def _source(session, ctx, run, ref):
    if ref.type in {"artifact", "original"}:
        _artifact(session, ctx, run, ref.model_copy(update={"type": "artifact"}))
    elif ref.type == "snapshot":
        _snapshot(session, ctx, run, ref)
    else:
        from pdos_next.domain.preproject.service import _references

        # Reuse ordinary-RLS/version checks and recursively inspect actual roots,
        # including private knowledge/definitions. Model privacy labels grant nothing.
        _references(session, ctx, [ref])
        _public_sources(session, ctx, [ref])
        if ref.type == "claim":
            claim = resolve(session, ctx, ref.id, ref.version, approved=True)
            _source(session, ctx, run, source_reference(claim))


def _primary_matches(payload, refs):
    source = payload.source
    if source is None:
        # Legacy commands carry their authoritative revision outside the payload.
        # Require exactly one matching pinned input version; prepared() will also
        # verify that version against the command read set before registration.
        versions = {
            ref.version for ref in refs
            if ref.type == "artifact" and ref.id == payload.artifact_id
            and ref.line == payload.line and ref.quote == payload.quote
        }
        return len(versions) == 1
    return source.locator == f"line:{source.line}" and any(
        ref.type == source.kind and ref.id == source.id and ref.version == source.version
        and ref.line == source.line and ref.quote == source.quote
        for ref in refs
    )


def verify_computed_claim(session, ctx, run, payload):
    """Validate only; never rewrite caller content, extraction_ref, or qualification.

    A Human confirmation retains its actual prepared Run. A plain Human entry has
    no deterministic provenance and cannot bypass this boundary. Only the engine's
    complete single-currency ClaimContent projection currently has a trusted path.
    """
    if (
        run is None or payload.nature != "computed" or payload.vendor_claimed is not False
        or payload.availability != "known"
    ):
        _deny()
    try:
        proof = resolve_compute_proof(
            session, ctx, run, payload.extraction_ref, payload.content, engines=ENGINES,
        )
        if (
            run.private_context or run.customer_identities
            or {"customer", "customer_original"}.intersection(run.data_categories)
        ):
            _outbound_unavailable()
        call = session.get(AgentToolCall, UUID(proof["call_id"]))
        binding = ReadBinding.model_validate(call.execution_binding)
        model = session.get(AgentToolCall, binding.model_call_id)
        arguments = model.result["calls"][binding.response_index]["arguments"]
        if call.tool != "calc.cost_subtotal":
            _deny()
        CostSubtotalInput.model_validate(arguments)
        refs = [_reference(line["source_ref"]) for line in arguments["lines"]]
        fx_refs = [_reference(rate["source_ref"]) for rate in arguments.get("fx", [])]
        if not _primary_matches(payload, refs):
            _deny("compute_primary_source_mismatch")
        for ref in [*refs, *fx_refs]:
            _source(session, ctx, run, ref)
        return proof
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, ValidationError):
        _deny()
