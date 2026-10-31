"""Candidate views preserve native command/receipt identity and fail closed."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.enterprise_search import verification_candidate_views as views
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.service import Context
from tests.enterprise_search.test_verification_candidates import fixture as candidate_fixture


@pytest.fixture
def case(monkeypatch):
    run, selected, command, preparation, receipt = candidate_fixture()
    run.state, run.reverted_at = "completed", None
    receipt.actor_id = receipt.requester_id
    receipt.agent_run_id = None  # Native Human confirmation is not an AI domain execution.
    receipt.created_at = datetime(2026, 10, 29, tzinfo=UTC)
    receipt.result = {"preparation_id": str(preparation.id)}
    ctx = Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id)
    event = SimpleNamespace(id=uuid4(), sequence=9, body={
        "type": "verification_candidate", "cancel_epoch": run.cancel_epoch,
        "selection": selected.model_dump(mode="json"),
    })
    state = SimpleNamespace(key=None, receipt=receipt, calls=[], error=None)
    proof = {"discussion_sources": [{"citation_id": str(uuid4())}],
             "execution_sources": [{"reference": command.payload["sources"][0]}]}

    def read(_session, actual_ctx, run_id, event_id):
        assert actual_ctx is ctx and run_id == run.id and event_id == event.id
        state.calls.append("read")
        if state.error is not None:
            raise state.error
        return {"command": command.model_dump(mode="json"), "source_proof": proof}

    def scalar(statement):
        values = statement.compile().params.values()
        assert ctx.tenant_id in values and ctx.actor_id in values
        assert command.idempotency_key in values
        state.calls.append("request_key")
        return state.key

    def get(model, identity):
        assert model is Receipt and identity == receipt.id
        state.calls.append("receipt")
        return state.receipt

    def get_preparation(_session, actual_ctx, product_id, identity, **kwargs):
        assert actual_ctx is ctx and product_id == run.product_id and identity == preparation.id
        assert kwargs == {"include_capabilities": False}
        state.calls.append("preparation")
        return preparation, None

    def no_write(*_args, **_kwargs):
        pytest.fail("Candidate listing attempted a write or execution")

    monkeypatch.setattr(views.bridge, "read", read)
    monkeypatch.setattr(views, "get_preparation", get_preparation)
    session = SimpleNamespace(scalar=scalar, get=get, add=no_write, execute=no_write,
                              commit=no_write, flush=no_write)
    return SimpleNamespace(run=run, selected=selected, command=command, preparation=preparation,
                           receipt=receipt, ctx=ctx, event=event, state=state, session=session)


def item(case):
    return views.item(case.session, case.ctx, case.run, case.event)


def test_pending_candidate_preserves_native_command_and_real_selected_build(case):
    value = item(case)
    assert value["kind"] == "verification_preparation" and value["state"] == "pending"
    assert value["command"] == case.command.model_dump(mode="json")
    assert value["target"] == case.selected.model_dump(mode="json")
    assert value["receipt"] is value["preparation"] is None
    assert value["basis_count"] == 2
    assert case.state.calls == ["read", "request_key"]
    assert "prepared_by_run_id" not in value["command"]["payload"]


def test_adopted_candidate_uses_real_human_receipt_and_exact_preparation_snapshot(case):
    case.state.key = SimpleNamespace(receipt_id=case.receipt.id)
    value = item(case)
    assert value["state"] == "adopted"
    assert value["command"] == case.command.model_dump(mode="json")
    assert value["receipt"]["id"] == str(case.receipt.id)
    assert value["receipt"]["agent_run_id"] is None
    assert value["preparation"] == {
        "receipt_id": str(case.receipt.id), "preparation_id": str(case.preparation.id),
        "expected_preparation_revision": case.preparation.revision,
        "preparation_sha256": case.preparation.snapshot_sha256,
    }
    assert case.state.calls == ["read", "request_key", "receipt", "preparation"]


def test_hidden_receipt_is_unavailable_and_never_becomes_pending(case):
    case.state.key = SimpleNamespace(receipt_id=case.receipt.id)
    case.state.receipt = None
    value = item(case)
    assert value["state"] == "unavailable"
    assert value["command"] is value["receipt"] is value["target"] is None
    assert value["basis_count"] == 0 and "preparation" not in case.state.calls


@pytest.mark.parametrize("field", [
    "tenant_id", "command_id", "requester_id", "category_id", "product_id", "operation",
    "subject_revision", "subject_type",
])
def test_other_or_changed_receipt_cannot_claim_candidate_adoption(case, field):
    case.state.key = SimpleNamespace(receipt_id=case.receipt.id)
    if field == "operation":
        case.receipt.operation = "verification.request.create"
    elif field == "subject_revision":
        case.receipt.subject_revision += 1
    elif field == "subject_type":
        case.receipt.subject_type = "other"
    else:
        setattr(case.receipt, field, uuid4())
    value = item(case)
    assert value["state"] == "unavailable" and value["command"] is value["receipt"] is None


@pytest.mark.parametrize("change", ["snapshot", "payload", "build_revision"])
def test_changed_preparation_cannot_be_projected_as_actual_adoption(case, change):
    case.state.key = SimpleNamespace(receipt_id=case.receipt.id)
    if change == "snapshot":
        case.preparation.snapshot_sha256 = "0" * 64
    elif change == "payload":
        case.preparation.input_snapshot = deepcopy(case.preparation.input_snapshot)
        case.preparation.input_snapshot["items"][0]["sample_count"] += 1
    else:
        case.preparation.build_revision += 1
    value = item(case)
    assert value["state"] == "unavailable" and value["preparation"] is None


@pytest.mark.parametrize("reason", ["SOURCE_UNAVAILABLE", "SOURCE_STALE", "FORBIDDEN_SCOPE"])
def test_revoked_or_changed_source_leaves_list_readable_without_candidate_disclosure(case, reason):
    case.state.error = DomainError(reason, "source is unavailable")
    value = item(case)
    assert value["state"] == "unavailable" and value["command"] is value["target"] is None
    assert case.state.calls == ["read"]


@pytest.mark.parametrize("reason", ["reverted", "cancelled", "epoch"])
def test_cancelled_candidate_never_rechecks_sources_or_discloses_command(case, reason):
    if reason == "reverted":
        case.run.reverted_at = datetime(2026, 10, 29, tzinfo=UTC)
    elif reason == "cancelled":
        case.run.state = "cancelled"
    else:
        case.run.cancel_epoch += 1
    value = item(case)
    assert value["state"] == "cancelled" and value["command"] is value["target"] is None
    assert not case.state.calls


def test_current_preparation_access_denial_does_not_reveal_old_adopted_receipt(case, monkeypatch):
    case.state.key = SimpleNamespace(receipt_id=case.receipt.id)

    def denied(*_args, **_kwargs):
        raise DomainError("FORBIDDEN_SCOPE", "preparation no longer readable")

    monkeypatch.setattr(views, "get_preparation", denied)
    value = item(case)
    assert value["state"] == "unavailable" and value["receipt"] is value["preparation"] is None
