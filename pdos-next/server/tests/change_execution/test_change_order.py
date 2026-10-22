"""Offline actual-kernel/ORM/control tests; source/SQL/qualification owners are substitutes."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import httpx
import psycopg
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import change_implementation_owner as implementation
from pdos_next import change_order_integration as integration
from pdos_next import change_order_service as owner
from pdos_next import change_order_store as store
from pdos_next.change_order_consumption import ConsumptionHost
from pdos_next.contracts import Command
from pdos_next.domain.change_control.rules import digest, replace
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import Context, material_digest
from pdos_next.service import digest as common_digest

from . import kernel_helpers as helper


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No database/HTTP permitted in owned pure checks")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (httpx.Client, "request")):
        monkeypatch.setattr(cls, name, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(helper, "NOW", datetime.now(UTC))


def rejected(code, call):
    with pytest.raises(DomainError) as caught:
        call()
    assert caught.value.reason == code


def payload(kind="approve"):
    raw = {
        "change_id": str(helper.uid("request")),
        "expected_change_revision": 3,
        "visibility": "category",
    }
    if kind == "prepare":
        cls = store.OrderPreparePayload
        raw.update(
            assessment_id=str(helper.uid("assessment")),
            plan=helper.plan().model_dump(mode="json"),
            reason="Controlled actual plan",
        )
    elif kind == "approve":
        cls = store.OrderApprovePayload
        raw.update(
            discipline="engineering",
            text="Actual named approval",
            expires_at=(helper.NOW + timedelta(hours=1)).isoformat(),
            sources=[helper.SOURCE.model_dump(mode="json")],
        )
    else:
        cls = store.ImplementationPayload
        raw.update(item_id=str(helper.uid("item")), fact_id=str(helper.uid("actualfact")))
    return cls, raw


@pytest.mark.parametrize("kind", ["prepare", "approve", "implement"])
@pytest.mark.parametrize(
    "field",
    ["scope", "actor_id", "qualified", "decision_id", "authority_snapshot", "implementation_fact"],
)
def test_client_cannot_fill_server_gates(kind, field):
    cls, raw = payload(kind)
    raw[field] = True
    with pytest.raises(ValidationError):
        cls.model_validate(raw)


@pytest.mark.parametrize("bad", [True, 1.0, "1", 0, -1])
def test_exact_current_and_nested_ref_revisions_cannot_coerce(bad):
    cls, raw = payload()
    raw["sources"][0]["revision"] = bad
    with pytest.raises(ValidationError):
        cls.model_validate(raw)


def test_real_semantic_omits_only_proof_and_keeps_full_plan_and_audience():
    cls, raw = payload("prepare")
    first = cls.model_validate(raw)
    second = cls.model_validate({**raw, "confirmation_token": "actual-token-123456789"})
    assert owner.semantic(first) == owner.semantic(second)
    assert owner.semantic(first)["visibility"] == "category"
    assert owner.semantic(first)["plan"] == first.plan.model_dump(mode="json")
    assert owner.semantic(first)["expected_change_revision"] == 3
    reordered = deepcopy(raw)
    reordered["plan"]["items"].reverse()
    assert owner.semantic(cls.model_validate(reordered)) != owner.semantic(first)


def consumed_work(kind="approve"):
    cls, raw = payload(kind)
    token = "actual-tx-token-1234567890"
    raw["approval_token" if kind == "approve" else "confirmation_token"] = token
    p = cls.model_validate(raw)
    ctx = Context(
        helper.SCOPE.tenant_id,
        helper.uid("maker"),
        helper.uid("maker"),
        category_id=CategoryUUID(int=1000000),
    )
    op = {
        "approve": "change.order.approve",
        "prepare": "change.order.prepare",
        "implement": "change.implementation.record",
    }[kind]
    cmd = Command(
        command_id=uuid4(),
        idempotency_key="fixed-command-key",
        operation=op,
        product_id=helper.SCOPE.product_id,
        expected_revision=7,
        source_read_set=[{"artifact_id": helper.SOURCE.id, "expected_revision": 1}],
        payload=p.model_dump(mode="json"),
        category_id=CategoryUUID(int=1000000),
    )
    s = Session(bind=SimpleNamespace())
    s.begin()
    at = datetime.now(UTC)
    proof = Confirmation(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=cmd.product_id,
        actor_id=ctx.actor_id,
        subject_id=cmd.product_id,
        operation=op,
        revision=7,
        token_hash=common_digest(token),
        payload_digest=material_digest(ctx, cmd, p, integration),
        snapshot={"actual": "review"},
        created_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(minutes=10),
        consumed=False,
    )
    make_transient_to_detached(proof)
    s.add(proof)
    host = ConsumptionHost({op: integration})
    return s, ctx, cmd, p, proof, host


@pytest.mark.parametrize("kind", ["prepare", "approve", "implement"])
def test_actual_consumption_marker_is_same_session_false_true_and_no_sql(kind, monkeypatch):
    s, ctx, cmd, p, proof, host = consumed_work(kind)
    monkeypatch.setattr(
        s,
        "flush",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("hook must not flush")),
    )
    binding = host.bind_before_transition(
        s, ctx, cmd, p, integration, proof, reviewed_snapshot=proof.snapshot
    )
    proof.consumed = True
    marker = host.capture_after_transition(s, ctx, cmd, p, integration, proof, binding=binding)
    assert marker.proof_id == proof.id
    assert marker.tier == ("T2" if kind == "approve" else "T1")
    assert (
        host.require_live(s, ctx, cmd, p, integration, proof, binding=binding, marker=marker)
        is marker
    )
    # Creating the isolated active SAVEPOINT chain would flush in real SQL.
    # Here only that SQL is a substitute; hooks above were guarded against it.
    monkeypatch.setattr(s, "flush", lambda *args, **kwargs: None)
    with s.begin_nested() as nested:
        rejected(
            "FACT_CALLER_UOW_CHANGED",
            lambda: host.require_live(
                s, ctx, cmd, p, integration, proof, binding=binding, marker=marker
            ),
        )
        nested.rollback()
    s.close()


def test_historical_consumed_true_is_not_a_current_transaction_marker():
    s, ctx, cmd, p, proof, host = consumed_work()
    proof.consumed = True
    rejected(
        "FACT_UNCONSUMED_MATERIAL_BINDING_REQUIRED",
        lambda: host.bind_before_transition(
            s, ctx, cmd, p, integration, proof, reviewed_snapshot=proof.snapshot
        ),
    )
    s.close()


def test_forged_current_marker_or_changed_snapshot_rejected():
    s, ctx, cmd, p, proof, host = consumed_work()
    binding = host.bind_before_transition(
        s, ctx, cmd, p, integration, proof, reviewed_snapshot=proof.snapshot
    )
    proof.consumed = True
    marker = host.capture_after_transition(s, ctx, cmd, p, integration, proof, binding=binding)
    proof.snapshot = {"mutated": "after consume"}
    rejected(
        "FACT_CONSUMPTION_MATERIAL_CHANGED",
        lambda: host.require_live(
            s, ctx, cmd, p, integration, proof, binding=binding, marker=marker
        ),
    )
    s.close()


def test_real_kernel_keeps_unknown_self_approval_and_dual_discipline_gates():
    h = helper.FakeHost()
    h.prepare()
    rejected(
        "SELF_APPROVAL_FORBIDDEN",
        lambda: h.run(
            "change.order.approve",
            {
                "discipline": "engineering",
                "text": "My own proposal",
                "expires_at": helper.NOW + timedelta(hours=1),
            },
        ),
    )
    h.actor("other-engineer", ("engineering",))
    h.run(
        "change.order.approve",
        {
            "discipline": "engineering",
            "text": "Actual engineering",
            "expires_at": helper.NOW + timedelta(hours=1),
        },
    )
    assert h.request_value.status == "review"
    h.actor("other-maker", ("manufacturing",))
    h.run(
        "change.order.approve",
        {
            "discipline": "manufacturing",
            "text": "Actual manufacturing",
            "expires_at": helper.NOW + timedelta(hours=1),
        },
    )
    assert h.request_value.status == "approved"
    assert {v.discipline for v in h.order.approvals} == {"engineering", "manufacturing"}


def test_actual_orm_stage_appends_same_chain_and_retains_proof_uuid(monkeypatch):
    h = helper.FakeHost()
    h.prepare()
    before = h.request_value
    h.actor("maker", ("engineering",))
    # Domain preview carries a proposal; real execution gets the shared proof UUID.
    s, ctx, cmd, p, proof, host = consumed_work()
    raw = {
        **p.model_dump(mode="json"),
        "change_id": str(before.id),
        "expected_change_revision": before.revision,
    }
    p = store.OrderApprovePayload.model_validate(raw)
    cmd = cmd.model_copy(update={"payload": p.model_dump(mode="json")})
    proof.payload_digest = material_digest(ctx, cmd, p, integration)
    # Re-attach pristine proof as the actual loaded persistent common object.
    s.expunge(proof)
    make_transient_to_detached(proof) if not __import__("sqlalchemy").inspect(
        proof
    ).detached else None
    s.add(proof)
    __import__("sqlalchemy").orm.attributes.set_committed_value(
        proof, "payload_digest", material_digest(ctx, cmd, p, integration)
    )
    binding = host.bind_before_transition(
        s, ctx, cmd, p, integration, proof, reviewed_snapshot=proof.snapshot
    )
    proof.consumed = True
    marker = host.capture_after_transition(s, ctx, cmd, p, integration, proof, binding=binding)

    before_row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=cmd.product_id,
        project_id=before.scope.project_id,
        change_id=before.id,
        revision=before.revision,
        owner_id=before.requester_id,
        visibility="category",
        operation="change.order.prepare",
        status=before.status,
        request_snapshot=before.model_dump(mode="json"),
        request_sha256=digest(before),
        sources=[],
        required_source_read_set=[],
        source_basis={},
        authority_snapshot={},
    )
    pointer = ChangeCurrent(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=cmd.product_id,
        change_id=before.id,
        version_id=before_row.id,
        revision=before.revision,
    )
    parent = store.ChangeOrderRecord(id=uuid4(), order_id=h.order.id)
    phase = SimpleNamespace(
        row=before_row,
        request=before,
        scope=before.scope,
        valid_until=helper.NOW + timedelta(hours=1),
        sources=(helper.SOURCE,),
        reads=[{"artifact_id": str(helper.SOURCE.id), "expected_revision": 1}],
        source_basis={},
        authority={"authorized": True, "qualified": True},
        policy=SimpleNamespace(model_dump=lambda **kwargs: {"actual": "policy owner substitute"}),
    )
    monkeypatch.setattr(owner, "current_fixed", lambda *args, **kwargs: (pointer, before_row))
    monkeypatch.setattr(owner, "_one", lambda *args, **kwargs: parent)
    monkeypatch.setattr(owner, "_review", lambda *args: proof.snapshot)
    flushed = []
    monkeypatch.setattr(s, "flush", lambda values=None: flushed.extend(values or []))
    staged = []

    def save(uow, invocation, mutation):
        host.require_live(s, ctx, cmd, p, integration, proof, binding=binding, marker=marker)
        staged.append(
            owner.stage_mutation(s, ctx, cmd, p, phase, mutation, marker, at=datetime.now(UTC))
        )
        from pdos_next.domain.change_control.ports import Outcome

        return Outcome(
            subject_id=mutation.change.id,
            revision=mutation.change.revision,
            status=mutation.change.status,
        )

    monkeypatch.setattr(h, "record", save)
    monkeypatch.setattr(
        h,
        "confirm",
        lambda *args: host.require_live(
            s, ctx, cmd, p, integration, proof, binding=binding, marker=marker
        ),
    )
    invocation = h.invocation(cmd.operation, owner.parsed_payload(p), command=cmd.command_id)
    invocation = replace(invocation, decision_id=proof.id, confirmation_token=p.approval_token)
    h.execute(invocation, owner.parsed_payload(p))
    atoms = [v for v in s.new if isinstance(v, store.ChangeApprovalRecord)]
    assert len(atoms) == 1 and atoms[0].shared_proof_id == proof.id
    assert atoms[0].approval_snapshot["decision_id"] == str(proof.id)
    assert atoms[0].change_version_id == staged[0].id
    assert staged[0].previous_version_id == before_row.id
    assert staged[0].owner_id == before.requester_id and staged[0].owner_id != ctx.actor_id
    assert pointer.version_id == staged[0].id and pointer.revision == before.revision + 1
    assert flushed == [staged[0]]  # parent exact before Current/atom broad flush
    assert before_row.request_snapshot == before.model_dump(mode="json")
    assert not any(type(v).__name__ in {"Receipt", "Audit", "Outbox"} for v in s.new)
    s.rollback()
    assert not s.new
    rejected(
        "FACT_ACTIVE_TRANSACTION_REQUIRED",
        lambda: host.require_live(
            s, ctx, cmd, p, integration, proof, binding=binding, marker=marker
        ),
    )
    s.close()


def test_missing_policy_selection_or_common_consumption_fail_closed():
    engine = SimpleNamespace()
    rejected("CHANGE_OWNER_INTEGRATION_REQUIRED", lambda: integration.configure_integration(engine))
    assert not hasattr(engine, "_pdos_change_order_runtime")
    rejected("CHANGE_COMMON_PHASE_REQUIRED", lambda: integration.apply(None))


def test_explicit_unknown_execution_cannot_be_retried_as_a_new_attempt():
    h = helper.FakeHost()
    h.approve()
    item = h.order.plan.items[0]
    unknown = h.implementation_fact(item, outcome="unknown", outputs=())
    h.run("change.implementation.record", {"item_id": item.id, "fact_id": unknown.id})
    successor = h.implementation_fact(item, outcome="succeeded")
    rejected(
        "IMPLEMENTATION_RECONCILE_REQUIRED",
        lambda: h.run(
            "change.implementation.record", {"item_id": item.id, "fact_id": successor.id}
        ),
    )
    reconciled = replace(successor, reconciles_id=unknown.id, occurred_at=unknown.occurred_at)
    h.implementations[reconciled.id] = reconciled
    h.run("change.implementation.record", {"item_id": item.id, "fact_id": reconciled.id})
    assert (
        h.order.implementations[0] == unknown
        and h.order.implementations[-1].reconciles_id == unknown.id
    )


def test_original_occurrence_rejects_duplicate_keys_and_uploaded_surrogate(monkeypatch):
    src = helper.SOURCE.model_copy(
        update={
            "position": "line:1;quote_sha256:"
            + __import__("hashlib").sha256(b'{"scope":1,"scope":2}').hexdigest()
        }
    )
    row = SimpleNamespace(
        original_id=None,
        content='{"scope":1,"scope":2}',
        content_hash=common_digest('{"scope":1,"scope":2}'),
    )
    monkeypatch.setattr(implementation, "source_for", lambda *args: row)
    monkeypatch.setattr(implementation.old, "_native_registration", lambda *args: None)
    rejected(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: implementation.original_occurrence(None, None, None, src),
    )
    row.original_id = uuid4()
    rejected(
        "IMPLEMENTATION_ORIGINAL_OWNER_REQUIRED",
        lambda: implementation.original_occurrence(None, None, None, src),
    )


def test_new_capture_cannot_widen_or_claim_qualified_body():
    raw = {
        "change_id": str(helper.uid("request")),
        "expected_change_revision": 5,
        "order_id": str(helper.uid("order")),
        "item_id": str(helper.uid("item")),
        "capture_key": "exact-material-key",
        "source": helper.SOURCE.model_dump(mode="json"),
        "fact": {"outcome": "succeeded"},
    }
    with pytest.raises(ValidationError):
        store.CaptureInput.model_validate(raw)


def test_scoped_parent_and_capture_fks_are_real_composite_metadata():
    for model in (
        store.ChangeOrderRecord,
        store.ChangeApprovalRecord,
        store.ChangeImplementationRecord,
        store.ImplementationCapture,
    ):
        table = model.__table__
        parents = [
            v
            for v in table.foreign_key_constraints
            if v.referred_table.name == "change_request_versions"
        ]
        assert len(parents) == 1
        assert tuple(e.parent.name for e in parents[0].elements) == store.PARENT
        assert parents[0].deferrable and parents[0].initially == "DEFERRED"
    captures = [
        v
        for v in store.ChangeImplementationRecord.__table__.foreign_key_constraints
        if v.referred_table.name == "change_implementation_captures"
    ]
    assert tuple(e.parent.name for e in captures[0].elements) == (
        *store.BOUND,
        "order_id",
        "item_id",
        "fact_id",
        "capture_id",
    )


@pytest.mark.parametrize(
    "field,value",
    [("outcome", "succeeded"), ("note", "Changed note"), ("nature", "real"), ("outputs", ())],
)
def test_saved_capture_fact_must_match_all_observed_fields(field, value):
    h = helper.FakeHost()
    h.approve()
    item = h.order.plan.items[0]
    fact = h.implementation_fact(item, outcome="failed")
    raw = {
        "schema_version": "pdos-change-implementation-occurrence-v2",
        "scope": helper.SCOPE.model_dump(mode="json"),
        "issue_id": str(helper.uid("issue")),
        "capa_id": str(helper.uid("capa")),
        "action_id": str(helper.uid("action")),
        "action_sha256": "a" * 64,
        "purpose": "Actual controlled repair",
        "change_id": str(h.subject),
        "order_id": str(h.order.id),
        "implementation_id": str(fact.id),
        "reconciles_id": None,
        "item_id": str(fact.item_id),
        "intent_id": str(fact.intent_id),
        "executor_id": str(fact.executor_id),
        "operation": "change.implementation.record",
        "outcome": fact.outcome,
        "occurred_at": fact.occurred_at.isoformat(),
        "original_timezone": "America/Los_Angeles",
        "sources": [s.model_dump(mode="json") for s in fact.sources],
        "outputs": [r.model_dump(mode="json") for r in fact.outputs],
        "note": fact.note,
        "nature": fact.nature,
    }
    occurrence = implementation.Occurrence.model_validate(raw)
    implementation.fact_matches_occurrence(fact, occurrence)
    changed = replace(fact, **{field: value})
    if changed != fact:
        rejected(
            "IMPLEMENTATION_MATERIAL_MISMATCH",
            lambda: implementation.fact_matches_occurrence(changed, occurrence),
        )


def test_original_unknown_impact_still_blocks_formal_approval():
    h = helper.FakeHost()
    h.snapshot = replace(
        h.snapshot, coverage=tuple(v for v in h.snapshot.coverage if v.facet != "training")
    )
    h.prepare()
    h.actor("other-engineer", ("engineering",))
    rejected(
        "IMPACT_UNKNOWN",
        lambda: h.run(
            "change.order.approve",
            {
                "discipline": "engineering",
                "text": "Cannot make unknown complete",
                "expires_at": helper.NOW + timedelta(hours=1),
            },
        ),
    )
    assert not h.order.approvals


def test_pure_kernel_requires_actual_executor_and_after_approval_clock():
    h = helper.FakeHost()
    h.approve()
    item = h.order.plan.items[0]
    fact = h.implementation_fact(item, occurred_at=helper.NOW - timedelta(seconds=1))
    rejected(
        "EXECUTION_BEFORE_APPROVAL",
        lambda: h.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id}),
    )
