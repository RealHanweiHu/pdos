"""Actual helper/common executor; all SQL/domain truth are substitutes."""

# ruff: noqa: F811 - shared explicit offline fixture registration

import sys
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

import pdos_next.models  # noqa: F401 - complete model registration
from pdos_next import change_order_integration as integration
from pdos_next import change_order_service as formal
from pdos_next import change_publication_finalization as candidate_guard
from pdos_next import service as actual_common
from pdos_next.change_coverage_binding import covered_graph
from pdos_next.change_graph_closure import closure_stamp
from pdos_next.change_order_consumption import ConsumptionHost
from pdos_next.domain.change_execution import service as impact
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Product

from .helpers import case, existing  # noqa: F401 - shared explicit offline fixture

candidate_common = actual_common

COMPLETION_OPERATIONS = (
    "change.effectivity.record",
    "change.verification.record",
    "change.close",
)


@pytest.mark.parametrize("case", COMPLETION_OPERATIONS, indirect=True)
def test_native_completion_actual_common_tail_accepts_retained_publication(candidate):
    result = candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert result["id"] == str(candidate.receipt.id)
    assert candidate.trace[-1] == "after_full_common_flush"
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)


@pytest.mark.parametrize("case", COMPLETION_OPERATIONS, indirect=True)
def test_native_completion_rejects_current_projection_as_retained_proof(candidate, monkeypatch):
    original = candidate.module.validate

    def wrong_kind(*args):
        original(*args)
        candidate.current = existing.read(candidate)

    monkeypatch.setattr(candidate.module, "validate", wrong_kind)
    with pytest.raises(DomainError) as caught:
        candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert caught.value.reason == "RECHECK_REQUIRED"


def test_tail_requires_operation_specific_opaque_coverage(candidate, monkeypatch):
    from pdos_next.domain.change_coverage_owner import owner

    e = candidate
    original = e.module.validate

    def wrong_kind(*args):
        original(*args)
        current = existing.read(e)
        e.current = (
            current
            if e.command.operation == "change.implementation.record"
            else owner.read_retained(
                e.s,
                e.ctx,
                e.pid,
                change_id=e.material.change_id,
                purpose=e.material.purpose,
                graph=covered_graph(e.graph, current),
                saved=current.source_basis,
            )
        )

    monkeypatch.setattr(e.module, "validate", wrong_kind)
    with pytest.raises(DomainError) as caught:
        candidate_common.execute(e.s, e.ctx, e.command)
    assert caught.value.reason == "RECHECK_REQUIRED"


@pytest.fixture
def candidate(case, monkeypatch):
    e = case
    monkeypatch.setitem(sys.modules, "pdos_next.change_publication_finalization", candidate_guard)
    monkeypatch.setattr(candidate_common, "handler", lambda operation: e.module)
    monkeypatch.setattr(
        candidate_common, "consume_material_confirmation", lambda *a, **k: (object(), object())
    )
    from pdos_next import change_graph_closure as closure

    product = next(row for row in e.rows if isinstance(row, Product))
    monkeypatch.setattr(
        closure,
        "_stamp_rows",
        lambda session, scope: [
            {
                **{
                    c.key: getattr(product, c.key)
                    for c in Product.__table__.columns
                    if c.key != "lifecycle_epoch"
                },
                "dependency_epoch": 7,
            }
        ],
    )
    e.closure = closure_stamp(e.s, e.ctx, scope=e.request.scope, audience=e.request.audience)
    e.deadline = e.at + timedelta(minutes=5)
    if e.command.operation != "change.impact.compute":
        # Existing concrete consumption host, real Session False->True history.
        # The reviewed business material is substituted; not an actual approval.
        payload = formal.PAYLOADS[e.command.operation].model_validate(e.command.payload)
        token = getattr(payload, "approval_token", None) or payload.confirmation_token
        host = ConsumptionHost({e.command.operation: integration})
        review = {"offline": "exact review"}
        at = datetime.now(UTC)
        proof = Confirmation(
            id=uuid4(),
            tenant_id=e.ctx.tenant_id,
            category_id=e.ctx.category_id,
            product_id=e.pid,
            actor_id=e.ctx.actor_id,
            subject_id=e.pid,
            operation=e.command.operation,
            revision=e.command.expected_revision,
            token_hash=actual_common.digest(token),
            payload_digest=actual_common.material_digest(e.ctx, e.command, payload, integration),
            snapshot=review,
            created_at=at,
            expires_at=at + timedelta(minutes=5),
            consumed=False,
        )
        make_transient_to_detached(proof)
        Session.add(e.s, proof)  # Actual identity map, no SQL.
        binding = host.bind_before_transition(
            e.s, e.ctx, e.command, payload, integration, proof, reviewed_snapshot=review
        )
        proof.consumed = True
        marker = host.capture_after_transition(
            e.s, e.ctx, e.command, payload, integration, proof, binding=binding
        )
        formal.configure(
            e.engine,
            policy_read=lambda *a: None,
            policy_refresh=lambda *a: None,
            selection_read=lambda *a: None,
            selection_refresh=lambda *a: None,
        )
        e.engine._pdos_change_order_consumer = integration.Runtime(integration, host)
        e.live = (host, proof, binding, marker)

    def attach(subject):
        if e.command.operation == "change.impact.compute":
            bound = SimpleNamespace(
                graph=e.graph,
                authority={"valid_until": e.deadline.isoformat()},
                coverage=e.current,
                request=e.request,
                purpose=e.material.purpose,
                runtime_stamp=impact._runtime_stamp(e.s),
                source_basis=subject.source_basis,
            )
            candidate_guard.attach_impact(e.s, e.ctx, e.command, subject, bound)
        else:
            host, proof, binding, marker = e.live
            phase = SimpleNamespace(
                coverage=e.current,
                request=e.request,
                purpose=e.material.purpose,
                runtime_stamp=formal.runtime(e.s)[0],
                source_basis=subject.source_basis,
                valid_until=e.deadline,
            )
            candidate_guard.attach_formal(
                e.s,
                e.ctx,
                e.command,
                subject,
                phase,
                consumer=host,
                module=integration,
                proof=proof,
                binding=binding,
                marker=marker,
            )

    e.attach = attach
    yield e


@pytest.mark.parametrize(
    "drift", ["publisher", "grant", "issuer", "runtime", "closure", "command", "subject", "uow"]
)
def test_actual_fixed_common_tail_rejects_drift_and_always_discards_material(
    candidate, monkeypatch, drift
):
    e = candidate

    def mutate():
        if drift == "publisher":
            e.publisher.active = False
            e.publisher.access_epoch += 1
        elif drift == "grant":
            row = next(
                row
                for row in e.rows
                if isinstance(row, Grant) and row.principal_id == e.publisher.id
            )
            row.can_write = False
            row.access_epoch += 1
        elif drift == "issuer":
            from pdos_next.domain.change_coverage_owner import trust

            trust.disable(e.engine, scope=e.scope)
        elif drift == "uow":
            e.s.rollback()
            e.s.begin()
        elif drift == "runtime":
            e.engine._pdos_change_store = object()
        elif drift == "closure":
            from pdos_next import change_graph_closure as closure

            original = closure._stamp_rows
            monkeypatch.setattr(
                closure,
                "_stamp_rows",
                lambda *args: [{**original(*args)[0], "dependency_epoch": 8}],
            )
        elif drift == "command":
            e.command.idempotency_key += "-changed-in-tail"
        else:
            e.subject.status = "changed-in-tail"

    e.drift = mutate
    with pytest.raises(DomainError):
        candidate_common.execute(e.s, e.ctx, e.command)
    assert e.trace[-1] == "after_full_common_flush"
    assert not hasattr(e.subject, candidate_guard._ATTRIBUTE)


def test_actual_complete_common_tail_succeeds_once_and_discards_material(candidate):
    result = candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert result["id"] == str(candidate.receipt.id)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)
    # One-use cleanup makes a second finalize reject saved complete JSON.
    with pytest.raises(DomainError):
        candidate_guard.finalize(candidate.s, candidate.ctx, candidate.command, candidate.subject)


def test_actual_common_exception_before_finalizer_also_discards_material(candidate, monkeypatch):
    original = candidate_common.append_receipt

    def fail_after_receipt(*args):
        original(*args)
        raise RuntimeError("offline append failure")

    monkeypatch.setattr(candidate_common, "append_receipt", fail_after_receipt)
    with pytest.raises(RuntimeError, match="offline append failure"):
        candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)


def test_real_clock_expiry_after_common_flush_is_not_extended(candidate):
    candidate.deadline = datetime.now(UTC) + timedelta(seconds=0.03)

    def pass_original_deadline():
        until = getattr(candidate.subject, candidate_guard._ATTRIBUTE).valid_until
        while datetime.now(UTC) < until:
            time.sleep(0.001)

    candidate.drift = pass_original_deadline
    with pytest.raises(DomainError):
        candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)


def test_saved_json_cannot_create_an_opaque_tail_token(case):
    row = SimpleNamespace(source_basis={"coverage": {"fact_id": str(uuid4())}})
    with pytest.raises(DomainError):
        candidate_guard.finalize(case.s, case.ctx, case.command, row)


def test_no_coverage_old_tail_path_performs_no_coverage_read(case, monkeypatch):
    from pdos_next.domain.change_coverage_owner import owner

    monkeypatch.setattr(
        owner, "recheck_access", lambda *a, **k: pytest.fail("No coverage owner read on old path")
    )
    row = SimpleNamespace(source_basis={})
    candidate_guard.finalize(case.s, case.ctx, case.command, row)


def test_context_session_and_opaque_pin_are_not_reusable_in_another_call(candidate):
    captured = []
    original_attach = candidate.attach

    def capture(subject):
        original_attach(subject)
        captured.append(getattr(subject, candidate_guard._ATTRIBUTE))

    candidate.attach = capture
    candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    state = captured[0]
    setattr(candidate.subject, candidate_guard._ATTRIBUTE, state)
    copy_ctx = actual_common.Context(
        candidate.ctx.tenant_id, candidate.ctx.actor_id, candidate.ctx.requester_id
    )
    with pytest.raises(DomainError):
        candidate_guard.finalize(candidate.s, copy_ctx, candidate.command, candidate.subject)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)
    setattr(candidate.subject, candidate_guard._ATTRIBUTE, state)
    with pytest.raises(DomainError):
        candidate_guard.finalize(object(), candidate.ctx, candidate.command, candidate.subject)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)
    assert deepcopy(state.coverage.source_basis) == state.coverage.source_basis


def test_successful_tail_ticket_cannot_be_reattached_in_same_call(candidate):
    captured = []
    original = candidate.attach

    def capture(subject):
        original(subject)
        captured.append(getattr(subject, candidate_guard._ATTRIBUTE))

    candidate.attach = capture
    candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    ticket = captured[0]
    assert ticket.used is True
    setattr(candidate.subject, candidate_guard._ATTRIBUTE, ticket)
    with pytest.raises(DomainError):
        candidate_guard.finalize(candidate.s, candidate.ctx, candidate.command, candidate.subject)
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)


def test_final_closure_sql_side_effect_rechecks_publisher_last(candidate, monkeypatch):
    from pdos_next import change_graph_closure as closure

    expected = deepcopy(candidate.closure)

    def scalar_view_with_same_stamp(*args, **kwargs):
        # Detached mapped row models the fresh SQL view; not pending ORM drift.
        assert candidate.publisher not in candidate.s
        candidate.publisher.active = False
        candidate.publisher.access_epoch += 1
        return deepcopy(expected)

    monkeypatch.setattr(closure, "closure_stamp", scalar_view_with_same_stamp)
    with pytest.raises(DomainError) as error:
        candidate_common.execute(candidate.s, candidate.ctx, candidate.command)
    assert error.value.status == 403
    assert not hasattr(candidate.subject, candidate_guard._ATTRIBUTE)
