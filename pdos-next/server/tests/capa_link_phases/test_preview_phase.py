"""No-DB phase protocol checks with explicit synthetic loader/new-write stubs.

Positive tests show protocol/call sequencing only, never live bytes, grants,
qualifications, host proof consumption or a publicly connected business action.
"""

import copy
import pickle
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.contracts import Command
from pdos_next.domain.capa_verification import preview_phase as phase
from pdos_next.domain.capa_verification.schemas import (
    ActionBinding,
    FollowupBasis,
    FollowupLinkPayload,
    OutputReading,
    OutputRef,
    ResolvedOutputs,
    SourceRead,
)
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.quality_issues.contracts import EffectivenessRequirement
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.fixture
def work(monkeypatch):
    tenant, actor, product_id, project, category = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, actor, actor, category_id=category)
    engine = SimpleNamespace()
    session = Session(bind=engine)
    product = Product(
        id=product_id,
        tenant_id=tenant,
        category_id=category,
        created_at=NOW,
        owner_id=actor,
        name="Synthetic phase protocol product",
        purpose="Protocol checks only",
        revision=1,
        lifecycle_epoch=1,
        status="draft",
        visibility="category",
    )
    make_transient_to_detached(product)
    session.add(product)
    source = SourceRead(artifact_id=uuid4(), expected_revision=1)
    action = ActionBinding(action_id=uuid4(), executor_id=actor, action_sha256="c" * 64)
    basis = FollowupBasis(
        scope=Scope(tenant_id=tenant, product_id=product_id, project_id=project),
        issue_id=uuid4(),
        issue_version_id=uuid4(),
        issue_revision=6,
        capa_id=uuid4(),
        purpose="Protocol checks only",
        owner_id=actor,
        visibility="category",
        nature="synthetic",
        requirement=EffectivenessRequirement(
            method="Not verified by this test",
            acceptance="No effectiveness granted",
            observation_until=NOW,
            required_failure_ids=("failure-a",),
        ),
        requirement_sha256="a" * 64,
        failure_ids=("failure-a",),
        failure_basis_sha256="b" * 64,
        actions=(action,),
        sources=(),
        required_source_read_set=(source,),
        source_basis_sha256="d" * 64,
        basis_sha256="e" * 64,
    )
    output = OutputReading(
        ref=OutputRef(kind="verification_request", id=uuid4(), revision=1),
        owner_id=actor,
        visibility="category",
        project_id=project,
        title="Synthetic structural option",
        status="draft",
        meaning="planned",
        source_status="current",
        snapshot={"not_live": True},
        required_source_read_set=(source,),
        owner_basis_sha256="f" * 64,
    )
    resolution = ResolvedOutputs(
        basis=basis,
        action_id=action.action_id,
        outputs=(output,),
        visibility="category",
        owner_id=actor,
        required_source_read_set=(source,),
        source_basis_sha256="d" * 64,
        resolution_sha256="a" * 64,
    )
    payload = FollowupLinkPayload(
        issue_id=basis.issue_id,
        expected_issue_revision=basis.issue_revision,
        capa_id=basis.capa_id,
        action_id=action.action_id,
        output_refs=(output.ref,),
        reason="No actual authorization in this protocol test",
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key="synthetic-preview-key",
        operation=phase.OPERATION,
        category_id=category,
        product_id=product_id,
        expected_revision=1,
        source_read_set=[source.model_dump()],
        payload=payload.model_dump(mode="json"),
    )
    counts = {"load": 0, "new_write": 0, "refresh": 0, "proof": 0}
    clock = [NOW]

    def proof(*args):
        counts["proof"] += 1
        pytest.fail("Preview must not consume or assert a shared proof")

    engine._pdos_capa_link_consumed_proof = proof
    authority_fact = {
        "role": "quality",
        "nature": "synthetic",
        "state": "active",
        "operations": [phase.OPERATION],
        "purposes": [basis.purpose],
        "valid_from": (NOW - timedelta(days=1)).isoformat(),
        "valid_until": (NOW + timedelta(minutes=10)).isoformat(),
    }
    policy_id = str(uuid4())
    bound = phase.link.Bound(
        resolution,
        {
            "valid_until": None,
            "epoch": 1,
            "operation": phase.OPERATION,
            "purpose": basis.purpose,
            "synthetic": True,
            "roles": ["quality"],
            "fact_refs": [{**authority_fact, "kind": kind} for kind in ("duty", "qualification")],
        },
        {
            "valid_until": None,
            "epoch": 1,
            "id": policy_id,
            "revision": 1,
            "source_basis": [
                {
                    "id": policy_id,
                    "revision": 1,
                    "state": "active",
                    "valid_from": (NOW - timedelta(days=1)).isoformat(),
                    "valid_until": (NOW + timedelta(minutes=8)).isoformat(),
                }
            ],
        },
        (),
        [source.model_dump(mode="json")],
        {"artifact_sources": [{"synthetic": True, "epoch": 1}]},
        "category",
        proof,
    )

    def refresh(*args):
        counts["refresh"] += 1

    def load(*args, **kwargs):
        counts["load"] += 1
        phase.link._refresh(*args, value.bound)
        return value.bound

    def new_write(s, c, cmd, p, pay, b):
        counts["new_write"] += 1
        if cmd.expected_revision != p.revision:
            raise DomainError("VERSION_CONFLICT", "Synthetic Current CAS rejected")
        phase.link._refresh(s, c, cmd, p, pay, b)

    monkeypatch.setattr(phase.link, "_load", load)
    monkeypatch.setattr(phase.link, "_new_write", new_write)
    monkeypatch.setattr(phase.link, "_refresh", refresh)
    monkeypatch.setattr(phase.link.owners, "now", lambda: clock[0])
    value = SimpleNamespace(
        s=session,
        ctx=ctx,
        command=command,
        product=product,
        payload=payload,
        bound=bound,
        counts=counts,
        clock=clock,
        engine=engine,
        refresh=refresh,
    )
    yield value
    session.close()


def prepare(w):
    return phase.prepare_preview(w.s, w.ctx, w.command, w.product, w.payload)


def preview(w, prepared):
    return phase.preview_prepared(w.s, w.ctx, w.command, w.product, w.payload, prepared)


def test_one_load_still_has_cas_and_independent_refresh_without_proof(work):
    original_info = dict(work.s.info)
    prepared = prepare(work)
    review = preview(work, prepared)
    assert work.counts == {"load": 1, "new_write": 1, "refresh": 2, "proof": 0}
    assert review == phase.link._review(work.command, work.payload, work.bound)
    assert review["after"]["action_fulfilled"] is None
    assert work.s.info == original_info and not work.s.new and not work.s.dirty
    with pytest.raises(DomainError, match="只能"):
        preview(work, prepared)


@pytest.mark.parametrize("field", ["command_id", "idempotency_key", "expected_revision"])
def test_complete_command_identity_cannot_change(work, field):
    prepared = prepare(work)
    setattr(
        work.command,
        field,
        uuid4() if field == "command_id" else "changed-key" if field == "idempotency_key" else 2,
    )
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


def test_command_payload_or_extra_read_cannot_change(work):
    prepared = prepare(work)
    work.command.source_read_set.append(
        phase.link.owners.SourceRead(artifact_id=uuid4(), expected_revision=1)
    )
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


def test_full_payload_token_and_source_fields_remain_bound(work):
    prepared = prepare(work)
    work.payload = work.payload.model_copy(update={"confirmation_token": "new-token-" * 4})
    work.command.payload = work.payload.model_dump(mode="json")
    with pytest.raises(DomainError):
        preview(work, prepared)


@pytest.mark.parametrize(
    "field", ["tenant_id", "actor_id", "requester_id", "run_id", "cancel_epoch"]
)
def test_context_all_identity_and_epoch_fields_bound(work, field):
    prepared = prepare(work)
    work.ctx = replace(work.ctx, **{field: 2 if field == "cancel_epoch" else uuid4()})
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


def test_other_session_cannot_use_phase(work):
    prepared = prepare(work)
    with Session(bind=work.engine) as other, other.begin():
        with pytest.raises(DomainError):
            phase.preview_prepared(
                other, work.ctx, work.command, work.product, work.payload, prepared
            )


@pytest.mark.parametrize("transition", ["new_transaction", "enter_nested", "leave_nested"])
def test_main_or_nested_uow_identity_cannot_change(work, transition):
    nested = work.s.begin_nested() if transition == "leave_nested" else None
    prepared = prepare(work)
    if transition == "new_transaction":
        work.s.rollback()
        work.s.begin()
    elif transition == "enter_nested":
        work.s.begin_nested()
    else:
        nested.rollback()
    with pytest.raises(DomainError):
        preview(work, prepared)


@pytest.mark.parametrize("field", ["authority", "policy", "source_basis", "reads"])
def test_full_mutable_bound_material_not_only_resolution_hash(work, field):
    prepared = prepare(work)
    target = getattr(work.bound, field)
    if isinstance(target, dict):
        target["changed"] = True
    else:
        target.append({"artifact_id": str(uuid4()), "expected_revision": 1})
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


@pytest.mark.parametrize(
    "runtime", ["proof", "professional_aba", "policy_aba", "operational_aba", "security"]
)
def test_runtime_issuer_epoch_and_host_identity_cannot_change(work, runtime):
    prepared = prepare(work)
    name = {
        "proof": "_pdos_capa_link_consumed_proof",
        "professional_aba": "_pdos_professional_issuer_epochs",
        "policy_aba": "_pdos_quality_policy_epochs",
        "operational_aba": "_pdos_operational_issuer_epochs",
        "security": "_pdos_security_runtime",
    }[runtime]
    setattr(work.engine, name, {"issuer": 2} if runtime.endswith("aba") else object())
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


@pytest.mark.parametrize("stage", ["load", "refresh"])
def test_owner_io_uow_binding_change_rejected_at_tail(work, monkeypatch, stage):
    if stage == "load":
        original = phase.link._load

        def changed(*args):
            value = original(*args)
            work.command.idempotency_key = "io-changed-key"
            return value

        monkeypatch.setattr(phase.link, "_load", changed)
        with pytest.raises(DomainError):
            prepare(work)
    else:
        original = phase.link._refresh

        def changed(*args):
            original(*args)
            if work.counts["new_write"]:
                work.engine._pdos_professional_issuer_epochs = {"issuer": 3}

        monkeypatch.setattr(phase.link, "_refresh", changed)
        prepared = prepare(work)
        with pytest.raises(DomainError):
            preview(work, prepared)


@pytest.mark.parametrize("stage", ["load", "refresh", "review"])
@pytest.mark.parametrize("proof", ["authority", "policy"])
def test_professional_or_policy_expiry_after_io_fails_closed(work, monkeypatch, stage, proof):
    actual_facts = getattr(work.bound, proof)[
        "fact_refs" if proof == "authority" else "source_basis"
    ]
    for fact in actual_facts:
        fact["valid_until"] = (NOW + timedelta(seconds=1)).isoformat()
    name = {"load": "_load", "refresh": "_refresh", "review": "_review"}[stage]
    original = getattr(phase.link, name)

    def expires(*args):
        value = original(*args)
        if stage != "refresh" or work.counts["new_write"]:
            work.clock[0] = NOW + timedelta(seconds=1)
        return value

    monkeypatch.setattr(phase.link, name, expires)
    if stage == "load":
        with pytest.raises(DomainError) as failure:
            prepare(work)
    else:
        prepared = prepare(work)
        with pytest.raises(DomainError) as failure:
            preview(work, prepared)
    assert failure.value.code == "SOURCE_STALE"


def test_exact_cas_failure_is_preserved_and_phase_is_spent(work, monkeypatch):
    def conflict(*args):
        raise DomainError("VERSION_CONFLICT", "Real path CAS remains necessary")

    monkeypatch.setattr(phase.link, "_new_write", conflict)
    prepared = prepare(work)
    with pytest.raises(DomainError) as failure:
        preview(work, prepared)
    assert failure.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError):
        preview(work, prepared)


def test_missing_real_loader_configuration_is_not_synthetic_positive(work, monkeypatch):
    def missing(*args):
        raise DomainError("INTEGRATION_REQUIRED", "Actual bridge/host is missing", 503)

    monkeypatch.setattr(phase.link, "_load", missing)
    with pytest.raises(DomainError) as failure:
        prepare(work)
    assert failure.value.reason == "INTEGRATION_REQUIRED"
    assert work.counts["new_write"] == 0


def test_phase_cannot_be_constructed_copied_or_serialized(work):
    with pytest.raises(TypeError):
        phase.PreviewPhase()
    prepared = prepare(work)
    for serialize in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            serialize(prepared)
    with pytest.raises(AttributeError):
        prepared._spent = False
    with pytest.raises(DomainError):
        preview(work, {"authorized": True, "bound": work.bound})


def test_clock_cannot_go_backwards(work):
    prepared = prepare(work)
    work.clock[0] = NOW - timedelta(seconds=1)
    with pytest.raises(DomainError):
        preview(work, prepared)


def test_nested_bound_mutation_during_new_write_io_is_rejected(work, monkeypatch):
    original = phase.link._refresh

    def changed(*args):
        original(*args)
        if work.counts["new_write"]:
            work.bound.source_basis["artifact_sources"][0]["epoch"] = 2

    monkeypatch.setattr(phase.link, "_refresh", changed)
    prepared = prepare(work)
    with pytest.raises(DomainError) as failure:
        preview(work, prepared)
    assert failure.value.code == "SOURCE_STALE"
    assert work.counts["load"] == 1 and work.counts["new_write"] == 1


def test_session_close_rejects_phase_before_any_new_write(work):
    prepared = prepare(work)
    work.s.close()
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 0


def test_real_fresh_gate_error_propagates_and_cannot_be_retried(work, monkeypatch):
    def withdrew(*args):
        if work.counts["new_write"]:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic withdrawal from fresh gate")

    monkeypatch.setattr(phase.link, "_refresh", withdrew)
    prepared = prepare(work)
    with pytest.raises(DomainError) as failure:
        preview(work, prepared)
    assert failure.value.code == "SOURCE_UNAVAILABLE"
    with pytest.raises(DomainError):
        preview(work, prepared)
    assert work.counts["new_write"] == 1


def test_extra_private_source_can_narrow_but_never_broaden_visibility(work):
    work.bound = replace(work.bound, visibility="private")
    # The real Link loader permits extra private sources to narrow a public
    # resolution. Protocol checks must not reject that legitimate distinction.
    prepared = prepare(work)
    assert preview(work, prepared)["after"]["visibility"] == "private"


def test_other_operation_never_enters_actual_loader(work):
    work.command.operation = "quality.capa.actions.complete"
    with pytest.raises(DomainError):
        prepare(work)
    assert work.counts["load"] == 0
