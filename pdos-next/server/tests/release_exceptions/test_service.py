"""Real phase/common hooks over no-connect ORM history, not a persisted T2."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.contracts import Command
from pdos_next.domain.release import service as releases
from pdos_next.domain.release_exceptions import rules, service
from pdos_next.domain.release_exceptions.constants import DECIDE, WITHDRAW
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import Context, digest, material_digest

from .test_rules import case as rule_case  # noqa: F401
from .test_rules import release_case  # noqa: F401


@pytest.fixture
def work(request):
    case = request.getfixturevalue("rule_case")
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*args):
        raise AssertionError("Pure exception phase must never connect")

    service.configure(engine)
    s = Session(engine)
    s.begin()
    ctx = case.base.ctx
    s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    payload = case.payload.model_copy(
        update={"approval_token": "explicit-no-connect-confirmation-substitute"}
    )
    command = Command(
        command_id=uuid4(),
        operation=DECIDE,
        category_id=ctx.category_id,
        product_id=case.base.scope.product_id,
        expected_revision=3,
        idempotency_key="private-no-connect-key-" + str(uuid4()),
        payload=payload.model_dump(mode="json"),
        source_read_set=case.data.required_source_read_set,
    )
    product = SimpleNamespace(id=command.product_id, revision=3)
    bound = service.Bound(
        material=case.data,
        basis={"artifact_sources": {str(case.base.source.id): {"revision": 1}}},
        plan=case.plan,
        candidate=case.plan,
        reads=case.data.required_source_read_set,
        authority={"authorized": True, "qualified": True},
    )
    value = SimpleNamespace(**locals())
    value.phase = lambda: service.Prepared(
        service._CAPABILITY, s, ctx, value.command, product, value.payload, value.bound
    )
    yield value
    s.close()
    engine.dispose()


def attach_proof(work, phase):
    proof = Confirmation(
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.product.id,
        actor_id=work.ctx.actor_id,
        subject_id=work.product.id,
        operation=work.command.operation,
        revision=work.command.expected_revision,
        consumed=False,
        token_hash=digest(work.payload.approval_token),
        payload_digest=material_digest(work.ctx, work.command, work.payload, service),
        snapshot=deepcopy(phase.review),
        created_at=datetime.now(UTC) - timedelta(seconds=1),
        expires_at=None,
    )
    # Explicit ORM-history fixture: no stored confirmation or authority is claimed.
    make_transient_to_detached(proof)
    work.s.add(proof)
    return proof


def test_preview_reuses_bound_phase_without_loading_or_consuming_confirmation(work, monkeypatch):
    phase = work.phase()
    proof = attach_proof(work, phase)

    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must not reload, consume or write")

    monkeypatch.setattr(service, "_load", forbidden)
    monkeypatch.setattr(service, "_still_current", forbidden)
    monkeypatch.setattr(
        work.engine._pdos_release_exceptions.consumption, "bind_before_transition", forbidden
    )
    view = service.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    assert view["after"]["prepared_at"] is None
    assert (
        view["after"]["expiry"] is None
        and view["after"]["selected_checks"][0]["state"] == "blocked"
    )
    assert proof.consumed is False and not (work.s.new or work.s.dirty or work.s.deleted)
    view["after"]["reason"] = "caller changed returned copy"
    assert phase.review["after"]["reason"] != view["after"]["reason"]
    with pytest.raises(DomainError) as error:
        service.preview_prepared(work.s, work.ctx, work.command, work.product, work.payload, phase)
    assert error.value.reason == "INVALID_PHASE"


@pytest.mark.parametrize("fault", ["uow", "caller", "command", "review", "bound", "runtime"])
def test_real_phase_seal_rejects_transaction_caller_and_material_changes(work, fault):
    phase = work.phase()
    command, ctx = work.command, work.ctx
    reason = "INVALID_PHASE"
    if fault == "uow":
        work.s.rollback()
        work.s.begin()
        reason = "FACT_CALLER_UOW_CHANGED"
    elif fault == "caller":
        other = uuid4()
        ctx = Context(ctx.tenant_id, other, other, category_id=ctx.category_id)
        reason = "FACT_CALLER_UOW_CHANGED"
    elif fault == "command":
        command = command.model_copy(update={"command_id": uuid4()})
    elif fault == "review":
        phase.review["after"]["check_keys"] = ["not-the-selected-rule"]
    elif fault == "bound":
        work.bound.basis["artifact_sources"][str(work.case.base.source.id)]["revision"] = 2
    else:
        service.configure(work.engine)
    with pytest.raises(DomainError) as error:
        service._phase(work.s, ctx, command, work.product, work.payload, phase)
    assert error.value.reason == reason


@pytest.mark.parametrize("operation", [DECIDE, WITHDRAW])
def test_both_operations_use_actual_common_t2_hooks_and_optional_null_expiry(work, operation):
    if operation == WITHDRAW:
        work.payload = work.case.withdraw.model_copy(
            update={"approval_token": work.payload.approval_token}
        )
        work.command = work.command.model_copy(
            update={"operation": WITHDRAW, "payload": work.payload.model_dump(mode="json")}
        )
        plan = rules.prepare_withdraw(
            work.payload, work.case.withdrawal_data, ctx=work.ctx, at=work.case.plan.prepared_at
        )
        work.bound = service.Bound(
            material=work.case.withdrawal_data,
            basis=work.bound.basis,
            plan=plan,
            candidate=plan,
            reads=work.bound.reads,
            authority=work.bound.authority,
        )
    phase = work.phase()
    proof = attach_proof(work, phase)
    binding = service.bind_consumption(
        work.s, work.ctx, work.command, work.product, work.payload, phase, proof
    )
    assert proof.consumed is False
    proof.consumed = True  # Actual ORM False -> True transition, replacing only SQL persistence.
    marker = service.record_consumption(
        work.s, work.ctx, work.command, work.product, work.payload, phase, proof, binding
    )
    host = work.engine._pdos_release_exceptions.consumption
    assert (
        host.require_live(
            work.s,
            work.ctx,
            work.command,
            work.payload,
            service,
            proof,
            binding=binding,
            marker=marker,
        )
        is marker
    )
    assert marker.tier == "T2" and marker.expires_at is None
    assert marker.storage_columns()["proof_expires_at"] is None
    assert marker.material_sha256 == material_digest(work.ctx, work.command, work.payload, service)
    # Compare independent existing release consumer against the shared host's
    # actual formula; this does not invent another exception confirmation engine.
    assert marker.common_intent_sha256 == releases._intent(work.ctx, work.command, work.payload)
    saved = service._saved_input(work.command, work.payload, phase)
    assert "approval_token" not in saved["semantic"]
    assert "idempotency_key" not in saved["command"]
    assert work.payload.approval_token not in str(saved)
    assert work.command.idempotency_key not in str(saved)
    assert saved["original_key_sha256"] == digest(work.command.idempotency_key)


def test_unconfirmed_direct_apply_is_rejected_before_io(work):
    with pytest.raises(DomainError) as error:
        service.apply_validated(work.s, work.ctx, work.command, work.product, work.payload, None)
    assert error.value.reason == "NAMED_DECISION_REQUIRED"
