"""Actual ORM shapes/Session ancestry, substituted SELECTs; no DB or live gates."""

import sys
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import anchor
import anchor_storage
import candidate_storage as storage
import pytest
import test_anchor_lineage as samples
import test_anchor_storage as origins
from facts import FactRef
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.capa_verification.service import basis_from_issue
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Grant, Outbox, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import DTO
from pdos_next.service import digest
from pydantic import BaseModel

OPERATION = storage.OPERATION


class TestOnlyPayload(DTO):
    """Explicit fake server module schema, NOT the future public payload."""

    __test__ = False
    binding_sha256: anchor.Sha256
    reason: anchor.Text
    confirmation_token: str | None = None


def semantic(payload):
    assert isinstance(payload, TestOnlyPayload)
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@pytest.fixture
def work(monkeypatch):
    upstream = origins.work.__wrapped__(monkeypatch)
    w = next(upstream)
    original = anchor_storage.read_origin_descriptor(w.s, w.ctx, w.pid, w.logical, w.ref)
    failure = samples.origin_fixture().failures
    stable = anchor.build_anchor(
        original.origin, failure, source_basis=original.origin.source_basis
    )
    raw_safety = deepcopy(w.row.source_basis["artifact_sources"])
    # The actual raw evidence writer omits the opposite origin field. Preserve
    # those omissions; typed validation must not silently add nulls to its hash.
    for value in raw_safety:
        value.pop("original")
    basis = basis_from_issue(
        w.row,
        original.origin.issue,
        sources=original.origin.sources,
        reads=original.origin.required_source_read_set,
        source_basis=raw_safety,
    )
    binding = CandidateBinding(basis=basis)
    inspect = CandidateInspect(
        binding=binding,
        current=True,
        required_source_read_set=basis.required_source_read_set,
        source_basis_sha256=digest(raw_safety),
        inspection_sha256="0" * 64,
        missing=(),
    )
    inspect = inspect.model_copy(
        update={
            "inspection_sha256": digest(
                inspect.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
            ),
        }
    )
    at = w.row.created_at + timedelta(minutes=5)
    row = CapaVerificationEvidence(
        id=samples.uid("candidate"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        project_id=w.row.project_id,
        issue_id=w.logical,
        issue_version_id=w.row.id,
        issue_revision=w.row.revision,
        capa_id=basis.capa_id,
        owner_id=w.row.owner_id,
        writer_id=w.row.writer_id,
        visibility="product",
        purpose=basis.purpose,
        nature="synthetic",
        revision=1,
        created_at=at,
        basis_snapshot=basis.model_dump(mode="json"),
        basis_sha256=basis.basis_sha256,
        sources=[v.model_dump(mode="json") for v in basis.sources],
        required_source_read_set=[
            v.model_dump(mode="json") for v in basis.required_source_read_set
        ],
        source_basis={
            "artifact_sources": raw_safety,
            "owner_declarations": {"complete": "stored only"},
        },
        input_snapshot={
            "semantic": {
                "binding_sha256": digest(binding.model_dump(mode="json")),
                "reason": "Synthetic candidate",
            },
            "shared_proof": {"id": str(samples.uid("candidate-proof")), "tier": "T1"},
            "proof_consumed_at": (at - timedelta(microseconds=123456)).isoformat(),
            "stable_anchor": stable.model_dump(mode="json"),
        },
        intent_digest="0" * 64,
        reason="Synthetic candidate",
        remediation_link_id=None,
        candidate_binding=binding.model_dump(mode="json"),
        binding_sha256=digest(binding.model_dump(mode="json")),
        candidate_snapshot=inspect.model_dump(mode="json"),
        inspection_sha256=inspect.inspection_sha256,
        status="candidate",
        result="indeterminate",
        applicable=None,
        independently_verified=None,
        observation_complete=None,
    )
    receipt = Receipt(
        id=samples.uid("candidate-receipt"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        created_at=at + timedelta(microseconds=1),
        actor_id=row.writer_id,
        requester_id=row.writer_id,
        command_id=samples.uid("candidate-command"),
        operation=OPERATION,
        subject_type=storage.SUBJECT,
        subject_id=row.id,
        subject_revision=1,
        visibility="product",
        run_id=None,
        request_digest=digest("actual original candidate full request"),
        intent_digest="0" * 64,
        result={},
    )
    proof = Confirmation(
        id=samples.uid("candidate-proof"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        actor_id=row.writer_id,
        subject_id=w.pid,
        operation=OPERATION,
        revision=42,
        consumed=True,
        created_at=at - timedelta(minutes=1),
        expires_at=at + timedelta(minutes=10),
        token_hash=digest("private token never read"),
        payload_digest="0" * 64,
        snapshot={
            "exact_candidate_review": {
                "binding": row.candidate_binding,
                "inspection": row.candidate_snapshot,
            }
        },
    )
    audit = Audit(
        id=samples.uid("candidate-audit"),
        tenant_id=w.ctx.tenant_id,
        created_at=receipt.created_at,
        receipt_id=receipt.id,
        actor_id=row.writer_id,
        operation=OPERATION,
    )
    outbox = Outbox(
        id=samples.uid("candidate-outbox"),
        tenant_id=w.ctx.tenant_id,
        created_at=receipt.created_at,
        receipt_id=receipt.id,
        actor_id=row.writer_id,
        type=storage.EVENT,
        subject_id=row.id,
        subject_revision=1,
        schema_version=1,
        correlation_id=receipt.command_id,
        delivered_at=None,
        lease_id=None,
        lease_until=None,
        attempts=0,
        last_error=None,
    )
    key = RequestKey(
        id=samples.uid("candidate-key"),
        tenant_id=w.ctx.tenant_id,
        created_at=receipt.created_at,
        actor_id=row.writer_id,
        key="actual-original-key",
        receipt_id=receipt.id,
        digest=receipt.request_digest,
    )
    for item in (row, receipt, proof, audit, outbox, key):
        w.memory.add(item)
    w.original = w.row
    w.candidate, w.candidate_receipt, w.candidate_proof = row, receipt, proof
    w.candidate_audit, w.candidate_outbox, w.candidate_key = audit, outbox, key
    w.owner = storage.CandidateSemanticOwner(TestOnlyPayload, sys.modules[__name__], semantic)
    seal(w)
    yield w
    try:
        next(upstream)
    except StopIteration:
        pass


def seal(w):
    row = w.candidate
    row.binding_sha256 = digest(row.candidate_binding)
    row.candidate_snapshot["binding"] = deepcopy(row.candidate_binding)
    row.inspection_sha256 = digest(
        {
            k: v
            for k, v in row.candidate_snapshot.items()
            if k not in {"inspection_sha256", "candidate_ref"}
        }
    )
    row.candidate_snapshot["inspection_sha256"] = row.inspection_sha256
    row.input_snapshot["semantic"]["binding_sha256"] = row.binding_sha256
    row.intent_digest = digest(
        {
            "operation": OPERATION,
            "category": w.ctx.category_id,
            "product": row.product_id,
            "payload": row.input_snapshot["semantic"],
            "named_actor": row.writer_id,
            "source_revision": None,
            "private_owner": row.writer_id,
        }
    )
    receipt = w.candidate_receipt
    receipt.intent_digest = row.intent_digest
    receipt.result = {
        "id": str(row.id),
        "revision": 1,
        "status": row.status,
        "candidate_binding_sha256": row.binding_sha256,
        "inspection_sha256": row.inspection_sha256,
    }
    w.candidate_proof.payload_digest = digest(
        {
            "tenant": row.tenant_id,
            "actor": row.writer_id,
            "requester": row.writer_id,
            "operation": OPERATION,
            "category": w.ctx.category_id,
            "product": row.product_id,
            "expected_revision": w.candidate_proof.revision,
            "read_set": sorted(
                row.required_source_read_set,
                key=lambda v: (v["artifact_id"], v["expected_revision"]),
            ),
            "payload": row.input_snapshot["semantic"],
        }
    )


def read(w, expected=None, **kwargs):
    return storage.read_candidate(
        w.s,
        w.ctx,
        w.pid,
        w.candidate.id,
        expected,
        semantic_owner=kwargs.pop("owner", w.owner),
        **kwargs,
    )


def error(code, callback):
    with pytest.raises(DomainError) as caught:
        callback()
    assert caught.value.code == code
    return caught.value


def test_full_reference_preserves_every_row_and_immutable_group_column(work):
    value = read(work)
    assert value.ref.sha256 == digest(
        {
            "schema_version": "pdos-capa-candidate-full-v1",
            "candidate": value.candidate,
            "group": value.group,
        }
    )
    assert set(value.candidate) == set(work.candidate.__table__.columns.keys())
    assert set(value.group["receipt"]) == set(Receipt.__table__.columns.keys())
    assert set(value.group["audit"]) == set(Audit.__table__.columns.keys())
    assert set(value.group["confirmation"]) == set(Confirmation.__table__.columns.keys())
    assert (
        set(value.group["outbox"]) == set(Outbox.__table__.columns.keys()) - storage.DELIVERY_FIELDS
    )
    assert value.candidate["source_basis"] == work.candidate.source_basis
    assert all("original" not in v for v in value.candidate["source_basis"]["artifact_sources"])
    assert value.inspection.candidate_ref is None
    assert value.ref.sha256 not in {work.candidate.binding_sha256, work.candidate.inspection_sha256}
    assert read(work, value.ref).ref == value.ref
    assert value.registry.session is work.s and value.registry.caller is work.ctx
    assert (
        storage.candidate_owner(work.owner)(work.s, work.ctx, work.pid, value.ref) == value.registry
    )
    assert not value.current_evidence_authorized and not value.same_uow_consumption_attested
    assert not value.source_bytes_verified and not value.original_failures_verified
    assert value.needs_lineage_owner and "seven_live_fact_reader_gates" in value.missing


def test_original_proof_revision_and_expiry_are_historical_not_current_product(work):
    assert work.candidate_proof.revision == 42
    assert work.candidate_proof.expires_at < work.clock.at
    assert read(work).group["confirmation"]["revision"] == 42


def test_delivery_changes_and_later_aliases_do_not_change_full_reference(work):
    before = read(work).ref
    work.candidate_outbox.delivered_at = work.clock.at
    work.candidate_outbox.lease_id = samples.uid("lease")
    work.candidate_outbox.lease_until = work.clock.at + timedelta(minutes=1)
    work.candidate_outbox.attempts, work.candidate_outbox.last_error = 9, "RETRY"
    work.memory.add(
        RequestKey(
            id=samples.uid("alias"),
            tenant_id=work.ctx.tenant_id,
            actor_id=work.candidate.writer_id,
            receipt_id=work.candidate_receipt.id,
            key="later-key",
            digest=digest("later full request"),
            created_at=work.clock.at,
        )
    )
    assert read(work, before).ref == before


@pytest.mark.parametrize("field", ["reason", "source_basis", "input_snapshot"])
def test_all_other_actual_row_material_changes_full_hash(work, field):
    before = read(work).ref
    if field == "reason":
        work.candidate.reason = "Changed preserved reason"
    elif field == "source_basis":
        work.candidate.source_basis["owner_declarations"]["complete"] = "changed"
    else:
        work.candidate.input_snapshot["semantic"]["reason"] = "Changed semantic reason"
        seal(work)
    error("CANDIDATE_FULL_REF_MISMATCH", lambda: read(work, before))


@pytest.mark.parametrize("hash_field", ["binding_sha256", "inspection_sha256"])
def test_binding_or_inspection_hash_is_never_a_full_reference(work, hash_field):
    error(
        "CANDIDATE_FULL_REF_MISMATCH",
        lambda: read(
            work,
            FactRef(id=work.candidate.id, revision=1, sha256=getattr(work.candidate, hash_field)),
        ),
    )


@pytest.mark.parametrize("missing", ["shared_proof", "proof_consumed_at", "stable_anchor"])
def test_legacy_wrapper_never_fills_missing_consumption_or_anchor(work, missing):
    del work.candidate.input_snapshot[missing]
    assert error("CANDIDATE_NEW_WRAPPER_REQUIRED", lambda: read(work)).status == 503


def test_extra_wrapper_field_and_client_positive_fields_rejected(work):
    work.candidate.input_snapshot["current"] = True
    error("CANDIDATE_NEW_WRAPPER_REQUIRED", lambda: read(work))


@pytest.mark.parametrize("owner", [None, {}, "identity_json"])
def test_missing_or_client_shaped_semantic_owner_is_503(work, owner):
    assert error("CANDIDATE_SEMANTIC_OWNER_REQUIRED", lambda: read(work, owner=owner)).status == 503


def test_strict_payload_unknown_key_and_token_are_rejected(work):
    work.candidate.input_snapshot["semantic"]["client_current"] = True
    error("CANDIDATE_TYPED_MATERIAL_INVALID", lambda: read(work))
    del work.candidate.input_snapshot["semantic"]["client_current"]
    work.candidate.input_snapshot["semantic"]["confirmation_token"] = None
    error("CANDIDATE_SEMANTIC_HAS_TOKEN", lambda: read(work))


@pytest.mark.parametrize("field", ["applicable", "independently_verified", "observation_complete"])
def test_saved_positive_booleans_do_not_grant_candidate_evidence(work, field):
    setattr(work.candidate, field, True)
    error("CANDIDATE_RESULT_NOT_UNKNOWN", lambda: read(work))


@pytest.mark.parametrize("model", [Receipt, Audit, Outbox, Confirmation, RequestKey])
def test_exact_common_group_must_exist_not_only_inspection_hash(work, model):
    target = {
        Receipt: work.candidate_receipt,
        Audit: work.candidate_audit,
        Outbox: work.candidate_outbox,
        Confirmation: work.candidate_proof,
        RequestKey: work.candidate_key,
    }[model]
    work.memory.rows[model].remove(target)
    error(
        "CANDIDATE_ORIGINAL_REQUEST_KEY_MISSING"
        if model is RequestKey
        else "FACT_EXACT_GROUP_ROW_MISSING",
        lambda: read(work),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", samples.uid("other")),
        ("subject_id", samples.uid("wrong-product")),
        ("operation", "quality.capa.followup.link"),
        ("consumed", False),
        ("payload_digest", "0" * 64),
    ],
)
def test_proof_scope_operation_actor_consumption_material_binding(work, field, value):
    setattr(work.candidate_proof, field, value)
    error("CANDIDATE_SAVED_COMMON_GROUP_MISMATCH", lambda: read(work))


@pytest.mark.parametrize("offset", [-61, 1, 601])
def test_saved_consume_clock_cannot_be_invented_outside_actual_interval(work, offset):
    work.candidate.input_snapshot["proof_consumed_at"] = (
        work.candidate.created_at + timedelta(seconds=offset)
    ).isoformat()
    error("CANDIDATE_SAVED_CLOCK_INVALID", lambda: read(work))


def test_original_microseconds_and_timezone_are_preserved(work):
    stamp = work.candidate.input_snapshot["proof_consumed_at"]
    instant = storage.datetime.fromisoformat(stamp)
    work.candidate.input_snapshot["proof_consumed_at"] = instant.astimezone(
        ZoneInfo("America/Los_Angeles")
    ).isoformat()
    value = read(work)
    assert value.candidate["input_snapshot"]["proof_consumed_at"].endswith("-07:00")
    assert value.body.proof_consumed_at == instant
    assert value.body.stable_anchor.origin.issue.capa.actions[0].completion.at == (
        anchor_storage.Issue.model_validate(work.original.issue_snapshot)
        .capa.actions[0]
        .completion.at
    )


@pytest.mark.parametrize("model", ["candidate_proof", "candidate_receipt", "candidate_audit"])
def test_naive_actual_group_clocks_are_explicitly_rejected(work, model):
    row = getattr(work, model)
    row.created_at = row.created_at.replace(tzinfo=None)
    error("CANDIDATE_CLOCK_INVALID", lambda: read(work))


def test_complete_child_refs_are_retained_without_latest_substitution(work):
    refs = [
        {"id": str(samples.uid("fixed-link-b")), "revision": 7},
        {"id": str(samples.uid("fixed-link-a")), "revision": 2},
    ]
    work.candidate.candidate_binding["remediation_link_refs"] = deepcopy(refs)
    seal(work)
    value = read(work)
    assert value.candidate["candidate_binding"]["remediation_link_refs"] == refs
    assert value.inspection.binding.remediation_link_refs[0].revision == 7
    assert "candidate_applicability_owner" in value.missing
    # Registry data alone says nothing about the child Link's actual source,
    # applicability or ownership. No callback or full child proof was invented.
    before = value.ref
    work.candidate.candidate_binding["remediation_link_refs"][0]["revision"] = 8
    seal(work)
    error("CANDIDATE_FULL_REF_MISMATCH", lambda: read(work, before))


def test_resealed_anchor_still_requires_actual_full_origin_descriptor(work):
    value = read(work)
    forged = value.body.stable_anchor.origin.model_copy(
        update={
            "authority_snapshot": {"rewritten_original_authority": True},
        }
    )
    forged_anchor = anchor.build_anchor(
        forged,
        value.body.stable_anchor.failures,
        source_basis=value.body.stable_anchor.origin_source_basis,
    )
    work.candidate.input_snapshot["stable_anchor"] = forged_anchor.model_dump(mode="json")
    error("CANDIDATE_ACTUAL_ORIGIN_MISMATCH", lambda: read(work))


def test_real_current_private_audience_change_is_not_ignored(work):
    newer = origins.successor(work)
    newer.visibility = "private"
    error("FORBIDDEN_SCOPE", lambda: read(work))


def test_non_strict_payload_module_is_not_a_semantic_owner(work):
    class ClientPayload(BaseModel):
        confirmation_token: str | None = None

    owner = storage.CandidateSemanticOwner(ClientPayload, sys.modules[__name__], semantic)
    error("CANDIDATE_SEMANTIC_OWNER_REQUIRED", lambda: read(work, owner=owner))


def test_terminal_host_semantic_replacement_is_not_cached(work, monkeypatch):
    count = 0

    def changed(payload):
        return semantic(payload)

    def hook(model, _statement):
        nonlocal count
        if model is Grant:
            count += 1
            if count == 6:
                monkeypatch.setattr(sys.modules[__name__], "semantic", changed)

    # Replacement happens in the last actual caller IO, after all saved groups.
    work.memory.hook = hook
    error("CANDIDATE_SEMANTIC_OWNER_REQUIRED", lambda: read(work))


@pytest.mark.parametrize("kind", ["ctx", "run", "agent"])
def test_actual_named_context_is_mandatory(work, kind):
    if kind == "ctx":
        error(
            "FACT_ACTUAL_NAMED_CALLER_REQUIRED",
            lambda: storage.read_candidate(
                work.s, {}, work.pid, work.candidate.id, semantic_owner=work.owner
            ),
        )
    elif kind == "run":
        work.ctx = replace(work.ctx, run_id=samples.uid("agent-run"))
        error("FACT_ACTUAL_NAMED_CALLER_REQUIRED", lambda: read(work))
    else:
        work.principal.kind = "agent"
        error("FORBIDDEN_SCOPE", lambda: read(work))


def test_private_candidate_and_project_never_inherit_product_grant(work):
    work.candidate.visibility = "private"
    error("FORBIDDEN_SCOPE", lambda: read(work))
    work.candidate.visibility = "product"
    work.project.visibility = "private"
    error("FORBIDDEN_SCOPE", lambda: read(work))


def test_source_closure_cannot_omit_original_artifact_even_with_resealed_hash(work):
    work.candidate.required_source_read_set.pop()
    error("RECHECK_REQUIRED", lambda: read(work))


def test_resealed_wrong_completion_basis_still_compares_to_actual_origin(work):
    basis = work.candidate.candidate_binding["basis"]
    basis["actions"][0]["completion_sha256"] = digest("different completion")
    basis["basis_sha256"] = digest({k: v for k, v in basis.items() if k != "basis_sha256"})
    work.candidate.basis_snapshot = deepcopy(basis)
    work.candidate.basis_sha256 = basis["basis_sha256"]
    seal(work)
    error("CANDIDATE_BASIS_SHA_MISMATCH", lambda: read(work))


def test_fixed_origin_group_is_real_and_later_current_does_not_replace_it(work):
    before = read(work).ref
    newer = origins.successor(work)
    value = read(work, before)
    assert value.origin.origin.ref.id == work.original.id
    assert value.origin.current.ref.id == newer.id and value.origin.needs_lineage_owner
    assert value.ref == before and value.needs_lineage_owner


def test_terminal_project_change_is_detected_after_group_io(work):
    count = 0

    def hook(model, _statement):
        nonlocal count
        if model is Project:
            count += 1
            if count == 7:
                work.project.scope = "changed actual project scope"

    work.memory.hook = hook
    error("CANDIDATE_PROJECT_CHANGED", lambda: read(work))


def test_final_caller_io_crossing_expiry_cannot_use_earlier_clock(work):
    count = 0

    def hook(model, _statement):
        nonlocal count
        if model is Grant:
            count += 1
            if count == 6:
                work.clock.at = work.grant.expires_at

    work.memory.hook = hook
    error("FORBIDDEN_SCOPE", lambda: read(work))


def test_post_io_group_mutation_is_rejected_with_no_trusted_cache(work):
    count = 0

    def hook(model, statement):
        nonlocal count
        if model is Confirmation:
            count += 1
            if count == 4:
                work.candidate_proof.snapshot["extra_fresh_change"] = True

    work.memory.hook = hook
    error("CANDIDATE_POST_IO_CHANGED", lambda: read(work))


def test_real_session_swap_during_terminal_read_is_rejected(work):
    count = 0

    def hook(model, _statement):
        nonlocal count
        if model is Grant:
            count += 1
            if count == 6:
                work.s.rollback()
                work.s.begin()

    work.memory.hook = hook
    error("FACT_CALLER_UOW_CHANGED", lambda: read(work))


def test_no_sql_writes_flush_commit_or_connection_and_all_selects_bounded(work):
    read(work)
    assert not work.s.new and not work.s.dirty and not work.s.deleted
    for query in work.memory.queries:
        assert query.is_select and query._limit_clause.value in {1, 2}
        assert query.get_execution_options().get("autoflush") is False
