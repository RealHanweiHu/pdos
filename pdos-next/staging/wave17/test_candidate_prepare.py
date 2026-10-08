"""Actual owner chains with explicit no-DB source/authority test substitutes.

No successful synthetic SELECT/bridge return is production evidence or a gate.
"""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import candidate_prepare as prepare
import pytest
import test_anchor_owner as upstream
from pdos_next import service as common
from pdos_next.domain.capa_verification.schemas import DefinitionReference
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, digest
from test_anchor_storage import uid


@pytest.fixture
def origin_sample(monkeypatch):
    yield from upstream.origin_work.__wrapped__(monkeypatch)


@pytest.fixture
def source_owner(origin_sample, monkeypatch):
    return upstream.actual.__wrapped__(origin_sample, monkeypatch)


@pytest.fixture
def work(source_owner, monkeypatch):
    actual = source_owner
    w = actual.work
    w.grant.can_write = True
    w.grant.access_epoch, w.principal.access_epoch = 1, 1
    monkeypatch.setattr(prepare, "_clock", lambda: w.clock.at)
    monkeypatch.setattr(prepare.followup, "now", lambda: w.clock.at)
    monkeypatch.setattr(common, "now", lambda: w.clock.at)
    monkeypatch.setattr(w.s, "scalar", w.memory.scalar)
    monkeypatch.setattr(
        w.s,
        "get",
        lambda model, identity: next((r for r in w.memory.rows[model] if r.id == identity), None),
    )
    old_bridge = w.s.get_bind()._pdos_quality_result_bridge

    def bridge(s, ctx, pid, **binding):
        binding.setdefault("event_id", None)
        binding.setdefault("write", False)
        return old_bridge(s, ctx, pid, **binding)

    w.s.get_bind()._pdos_quality_result_bridge = bridge
    refs = tuple(SourceRef.model_validate(r) for r in w.row.sources)
    raw = [
        {k: v for k, v in r.items() if v is not None}
        for r in deepcopy(w.row.source_basis["artifact_sources"])
    ]
    state = SimpleNamespace(
        basis_hook=None,
        authority_hook=None,
        policy_hook=None,
        source_hook=None,
        authority_calls=0,
        policy_calls=0,
        basis_calls=0,
    )

    def basis(s, ctx, pid, reads):
        assert (s, ctx, pid) == (w.s, w.ctx, w.pid)
        state.basis_calls += 1
        selected = prepare.evidence.merge_reads(reads)
        values = []
        for read in selected:
            value = next((r for r in raw if r["id"] == read["artifact_id"]), None)
            if value is None:
                value = deepcopy(raw[0])
                value["id"] = read["artifact_id"]
                value["revision"] = read["expected_revision"]
            values.append(deepcopy(value))
        if state.basis_hook:
            values = state.basis_hook(values, state.basis_calls)
        return values, any(v["visibility"] == "private" for v in values)

    monkeypatch.setattr(prepare.evidence, "source_basis", basis)
    monkeypatch.setattr(prepare.followup, "source_basis", basis)

    def exact(s, ctx, pid, references):
        assert (s, ctx, pid) == (w.s, w.ctx, w.pid)
        if state.source_hook:
            state.source_hook()
        return tuple(
            SourceRef(
                kind="artifact",
                id=r.artifact_id,
                revision=r.expected_revision,
                position=f"line:{r.line};quote_sha256:{digest(r.quote)}",
            )
            for r in references
        )

    monkeypatch.setattr(prepare.evidence, "refs_from_exact", exact)
    fact = ProfessionalFact(
        id=uid("candidate-professional"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        project_id=w.row.project_id,
        subject_id=w.ctx.requester_id,
        revision=1,
        state="active",
        valid_from=w.clock.at - timedelta(hours=1),
        valid_until=w.clock.at + timedelta(hours=2),
    )
    w.memory.add(fact)
    authority = {
        "scope": {
            "tenant_id": str(w.ctx.tenant_id),
            "product_id": str(w.pid),
            "project_id": str(w.row.project_id),
        },
        "subject_id": str(w.ctx.requester_id),
        "operation": prepare.commands.OPERATION,
        "purpose": w.row.purpose,
        "authorized": True,
        "qualified": True,
        "roles": ["quality"],
        "reason_codes": [],
        "fact_refs": [{"id": str(fact.id), "revision": 1}],
        "facts_revision": digest("synthetic current professional test return"),
        "valid_until": fact.valid_until.isoformat(),
        "synthetic": True,
        "required_source_read_set": [],
    }
    published = {
        "id": str(uid("candidate-policy")),
        "revision": 1,
        "risk": "high",
        "independent_verification": True,
        "nature": "synthetic",
        "valid_until": (w.clock.at + timedelta(hours=2)).isoformat(),
        "facts_revision": digest("synthetic policy test return"),
        "private": False,
        "required_source_read_set": [],
        "sources": [],
        "source_basis": [],
    }

    def assess(s, ctx, pid, project, op, purpose, at, write=False):
        assert (s, ctx, pid, project, op, purpose, write) == (
            w.s,
            w.ctx,
            w.pid,
            w.row.project_id,
            prepare.commands.OPERATION,
            w.row.purpose,
            False,
        )
        state.authority_calls += 1
        value = deepcopy(authority)
        if state.authority_hook:
            value = state.authority_hook(value, state.authority_calls)
        return value

    def policy(s, ctx, pid, project, purpose):
        assert (s, ctx, pid, project, purpose) == (
            w.s,
            w.ctx,
            w.pid,
            w.row.project_id,
            w.row.purpose,
        )
        state.policy_calls += 1
        value = deepcopy(published)
        if state.policy_hook:
            value = state.policy_hook(value, state.policy_calls)
        return value

    monkeypatch.setitem(
        prepare.professional.OPERATION_ROLES, prepare.commands.OPERATION, frozenset({"quality"})
    )
    monkeypatch.setattr(prepare.professional, "assess", assess)
    monkeypatch.setattr(prepare.policy, "assess", policy)
    payload = prepare.commands.CandidateRecordPayload(
        issue_id=w.logical,
        expected_issue_revision=w.row.revision,
        capa_id=prepare.anchor_storage.Issue.model_validate(w.row.issue_snapshot).capa.id,
        reason="Synthetic candidate investigation",
        visibility="product",
        sources=(
            DefinitionReference(
                artifact_id=refs[0].id,
                expected_revision=refs[0].revision,
                line=1,
                quote="Synthetic exact source",
            ),
        ),
    )
    return SimpleNamespace(
        actual=actual,
        w=w,
        payload=payload,
        state=state,
        raw=raw,
        authority=authority,
        policy=published,
        fact=fact,
    )


def run(work, **changes):
    w = work.w
    return prepare.prepare_candidate(
        w.s,
        changes.get("ctx", w.ctx),
        changes.get("pid", w.pid),
        changes.get("payload", work.payload),
        origin_ref=changes.get("origin_ref", w.ref),
    )


def rejected(code, action):
    with pytest.raises(DomainError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def test_real_read_owner_chain_keeps_original_full_anchor_and_incomplete_inspection(work):
    out = run(work)
    assert out.owner_id == work.w.row.owner_id != work.w.ctx.requester_id
    assert out.visibility == "product" and out.current_issue_revision == work.w.row.revision
    assert out.binding.basis.source_basis_sha256 == digest(work.raw)
    assert out.inspection.binding == out.binding
    assert out.inspection.result == "indeterminate"
    assert (
        out.inspection.applicable
        is out.inspection.independently_verified
        is out.inspection.observation_complete
        is None
    )
    assert out.inspection.capabilities == {"effectiveness_decide": False, "issue_close": False}
    assert out.inspection.missing
    assert out.inspection.required_source_read_set == out.required_source_read_set
    assert out.inspection.source_basis_sha256 == digest(out.raw_source_basis)
    raw = out.inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
    assert out.inspection.inspection_sha256 == digest(raw)
    review = prepare.reviewed_candidate(out)
    assert review["stable_anchor"] == out.anchor.model_dump(mode="json")
    assert "checked_at" not in review and "session" not in review
    assert work.state.authority_calls == work.state.policy_calls == 2
    assert not work.w.s.new and not work.w.s.dirty and not work.w.s.deleted


def test_current_and_origin_are_separate_and_successor_requires_missing_lineage(work, monkeypatch):
    actual_read = prepare.anchor_owner.read_anchor_from_actual_owner

    def missing(*args):
        value = actual_read(*args)
        return value.model_copy(update={"needs_lineage_owner": True})

    monkeypatch.setattr(prepare.anchor_owner, "read_anchor_from_actual_owner", missing)
    rejected("CANDIDATE_LINEAGE_OWNER_REQUIRED", lambda: run(work))


def test_exact_current_cas_rejects_old_revision(work):
    payload = work.payload.model_copy(
        update={"expected_issue_revision": work.payload.expected_issue_revision - 1}
    )
    rejected("VERSION_CONFLICT", lambda: run(work, payload=payload))


def test_audience_default_private_is_not_silently_promoted(work):
    payload = work.payload.model_copy(update={"visibility": "private"})
    rejected("CANDIDATE_AUDIENCE_MISMATCH", lambda: run(work, payload=payload))


def test_missing_actual_candidate_matrix_is_503_not_link_qualification(work, monkeypatch):
    monkeypatch.delitem(prepare.professional.OPERATION_ROLES, prepare.commands.OPERATION)
    assert rejected("PROFESSIONAL_OPERATION_NOT_CONFIGURED", lambda: run(work)).status == 503


@pytest.mark.parametrize("value", [False, None])
def test_unqualified_or_unknown_actual_assessor_does_not_prepare(work, value):
    work.authority["qualified"] = value
    rejected("QUALIFICATION_REQUIRED", lambda: run(work))


def test_unknown_policy_does_not_default_low_risk(work):
    work.state.policy_hook = lambda *_args: (_ for _ in ()).throw(
        DomainError("INTEGRATION_REQUIRED", "Missing policy", 503)
    )
    assert rejected("INTEGRATION_REQUIRED", lambda: run(work)).status == 503


@pytest.mark.parametrize("key", ["facts_revision", "subject_id", "purpose"])
def test_authority_post_io_changed_requires_recheck(work, key):
    work.state.authority_hook = lambda value, call: (
        {**value, key: "changed"} if call == 2 else value
    )
    expected = "INTEGRATION_REQUIRED" if key in {"subject_id", "purpose"} else "SOURCE_STALE"
    rejected(expected, lambda: run(work))


def test_policy_post_io_epoch_changed_requires_recheck(work):
    work.state.policy_hook = lambda value, call: (
        {**value, "facts_revision": digest("changed")} if call == 2 else value
    )
    rejected("SOURCE_STALE", lambda: run(work))


def test_any_private_source_cannot_enter_product_candidate(work):
    work.raw[0]["visibility"] = "private"
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_complete_closure_adds_professional_policy_reads_and_preserves_sparse_keys(work):
    work.authority["required_source_read_set"] = [
        {"artifact_id": str(uid("new authority source")), "expected_revision": 1}
    ]
    work.policy["required_source_read_set"] = [
        {"artifact_id": str(uid("new policy source")), "expected_revision": 1}
    ]
    out = run(work)
    assert len(out.required_source_read_set) == len(work.raw) + 2
    assert out.binding.basis.source_basis_sha256 == digest(work.raw)
    assert out.inspection.source_basis_sha256 != out.binding.basis.source_basis_sha256
    assert all("original" not in row for row in out.raw_source_basis)


def test_twenty_one_complete_sources_are_rejected_without_truncation(work):
    work.authority["required_source_read_set"] = [
        {"artifact_id": str(uid(f"additional-{i}")), "expected_revision": 1} for i in range(21)
    ]
    rejected("MISSING_REQUIRED_EVIDENCE", lambda: run(work))


def test_exact_source_revision_conflict_is_not_merged(work):
    work.authority["required_source_read_set"] = [
        {"artifact_id": work.raw[0]["id"], "expected_revision": work.raw[0]["revision"] + 1}
    ]
    rejected("SOURCE_STALE", lambda: run(work))


def test_runtime_changed_by_user_source_io_is_rejected(work):
    work.state.source_hook = lambda: setattr(work.w.s.get_bind(), "_pdos_results_store", object())
    rejected("SOURCE_STALE", lambda: run(work))


def test_final_caller_query_expiry_is_checked_after_io(work):
    before = work.w.memory.hook
    count = 0

    def hook(model, query):
        nonlocal count
        if model is prepare.Grant:
            count += 1
            if count == 12:
                work.w.clock.at = work.w.grant.expires_at
        if before:
            before(model, query)

    work.w.memory.hook = hook
    # The hook may hit within an earlier owner, all such expiry guards must fail.
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_future_professional_activation_is_real_final_deadline(work):
    work.fact.valid_from = work.w.clock.at + timedelta(seconds=10)
    out = run(work)
    assert out.valid_until == work.fact.valid_from
    work.w.clock.at = out.valid_until
    rejected(
        "SOURCE_STALE",
        lambda: prepare.require_prepared_candidate_clock(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out, work.w.clock.at
        ),
    )


def test_professional_fact_query_crossing_future_activation_is_rejected(work):
    work.fact.valid_from = work.w.clock.at + timedelta(seconds=10)
    work.w.memory.hook = lambda model, query: (
        setattr(work.w.clock, "at", work.fact.valid_from) if model is ProfessionalFact else None
    )
    rejected("SOURCE_STALE", lambda: run(work))


def test_only_actual_registered_same_session_phase_can_be_used(work):
    out = run(work)
    forged = replace(out)
    rejected(
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, forged
        ),
    )
    rejected(
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, copy(out)
        ),
    )


def test_payload_phase_mutation_and_actor_context_are_rejected(work):
    out = run(work)
    out.payload_semantic["reason"] = "tampered"
    rejected(
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out
        ),
    )
    out2 = run(work)
    foreign = Context(work.w.ctx.tenant_id, uid("other"), uid("other"))
    rejected(
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, foreign, work.w.pid, work.payload, out2
        ),
    )


def test_uow_change_cannot_reuse_original_phase(work):
    out = run(work)
    work.w.s.rollback()
    work.w.s.begin()
    rejected(
        "FACT_CALLER_UOW_CHANGED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out
        ),
    )


def test_independent_refresh_preserves_first_full_anchor_and_single_use(work):
    out = run(work)
    original = out.anchor.model_dump(mode="json")
    work.actual.state.mutate_bridge = lambda value: value.model_copy(
        update={"retained": {**value.retained, "checked_at": work.w.clock.at.isoformat()}}
    )
    fresh = prepare.require_prepared_candidate(work.w.s, work.w.ctx, work.w.pid, work.payload, out)
    assert fresh is out and fresh.anchor.model_dump(mode="json") == original
    prepare.invalidate_prepared_candidate(out)
    rejected(
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out
        ),
    )
    rejected(
        "CANDIDATE_PREPARED_OWNER_REQUIRED", lambda: prepare.invalidate_prepared_candidate(out)
    )


def test_refresh_source_changed_is_not_resealed_as_original(work):
    out = run(work)
    work.raw[0]["hash"] = digest("changed source")
    rejected(
        "SOURCE_STALE",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out
        ),
    )


@pytest.mark.parametrize("field", ["checked_at", "valid_until", "runtime_binding"])
def test_frozen_phase_intrusion_cannot_widen_clock_or_runtime(work, field):
    out = run(work)
    value = getattr(out, field)
    value = value + timedelta(days=1) if field != "runtime_binding" else "different runtime"
    object.__setattr__(out, field, value)
    rejected(
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        lambda: prepare.require_prepared_candidate(
            work.w.s, work.w.ctx, work.w.pid, work.payload, out
        ),
    )


def test_missing_actual_bytes_owner_is_503(work):
    work.w.s.get_bind()._pdos_quality_result_bridge = None
    assert rejected("INTEGRATION_REQUIRED", lambda: run(work)).status == 503


def test_product_read_grant_does_not_become_candidate_write_authority(work):
    work.w.grant.can_write = False
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_private_project_rejects_non_owner_even_for_product_issue(work):
    work.w.project.visibility = "private"
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_project_scope_change_after_all_source_reads_is_rejected(work):
    def change(values, call):
        # First anchor takes three; our actual Basis and two Inspect reads take
        # more. Trigger on the final caller phase by a direct Project query hook.
        return values

    work.state.basis_hook = change
    counter = 0

    def project_read(model, query):
        nonlocal counter
        if model is type(work.w.project):
            counter += 1
            if counter >= 5:
                work.w.project.visibility = "private"

    work.w.memory.hook = project_read
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_policy_registry_revoke_restore_aba_inside_source_io_is_stale(work):
    def revoke_restore():
        engine = work.w.s.get_bind()
        # Equal final enabled/registry values do not hide a monotonic epoch.
        engine._pdos_quality_policy_epochs = {"synthetic-test-issuer": 2}

    work.state.source_hook = revoke_restore
    rejected("SOURCE_STALE", lambda: run(work))


def test_actual_scope_caller_and_wrong_capa_are_rejected(work):
    rejected("FACT_EXACT_GROUP_ROW_MISSING", lambda: run(work, pid=uid("other product")))
    payload = work.payload.model_copy(update={"capa_id": uid("another capa")})
    rejected("CANDIDATE_REQUEST_BINDING_MISMATCH", lambda: run(work, payload=payload))


def test_nested_transaction_started_inside_user_io_invalidates_phase(work):
    work.state.source_hook = lambda: work.w.s.begin_nested()
    rejected("FACT_CALLER_UOW_CHANGED", lambda: run(work))


def test_final_authority_source_failure_keeps_no_registered_phase(work):
    before = len(prepare._PHASES)
    work.state.authority_hook = lambda value, call: (
        {**value, "qualified": False} if call == 2 else value
    )
    rejected("QUALIFICATION_REQUIRED", lambda: run(work))
    assert len(prepare._PHASES) == before
    assert not work.w.s.new


def test_fresh_principal_deactivation_inside_last_source_io_is_rejected(work):
    def change(values, call):
        if call >= 15:
            work.w.principal.active = False
        return values

    work.state.basis_hook = change
    rejected("FORBIDDEN_SCOPE", lambda: run(work))


def test_full_anchor_clock_is_not_removed_from_real_review_or_resaved(work):
    out = run(work)
    before = prepare.reviewed_candidate(out)["stable_anchor"]
    work.actual.state.mutate_bridge = lambda value: value.model_copy(
        update={
            "retained": {
                **value.retained,
                "checked_at": work.w.clock.at.isoformat(),
                "execution_window_elapsed": True,
            }
        }
    )
    prepare.require_prepared_candidate(work.w.s, work.w.ctx, work.w.pid, work.payload, out)
    assert prepare.reviewed_candidate(out)["stable_anchor"] == before
    assert out.anchor.anchor_sha256 == before["anchor_sha256"]
    assert out.anchor.full_failure_proofs_sha256 == before["full_failure_proofs_sha256"]


def test_actual_inspection_bad_self_hash_is_not_resealed(work, monkeypatch):
    original = prepare.followup.inspect_candidate

    def corrupted(*args, **kwargs):
        value = original(*args, **kwargs)
        return value.model_copy(update={"inspection_sha256": "f" * 64})

    monkeypatch.setattr(prepare.followup, "inspect_candidate", corrupted)
    rejected("INTEGRITY_MISMATCH", lambda: run(work))


def test_actual_inspection_bad_source_digest_is_not_whitened_by_full_reads(work, monkeypatch):
    original = prepare.followup.inspect_candidate

    def corrupted(*args, **kwargs):
        value = original(*args, **kwargs)
        raw = value.model_dump(mode="json")
        raw["source_basis_sha256"] = "f" * 64
        raw["inspection_sha256"] = digest(
            {k: v for k, v in raw.items() if k not in {"candidate_ref", "inspection_sha256"}}
        )
        return type(value).model_validate(raw)

    monkeypatch.setattr(prepare.followup, "inspect_candidate", corrupted)
    rejected("SOURCE_STALE", lambda: run(work))
