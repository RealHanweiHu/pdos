"""Only a failed native send fence plus actual lost-Run proof cancels delivery."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next.dingtalk import graph, runtime
from pdos_next.dingtalk.workflow import ChannelActivities
from sqlalchemy.exc import DBAPIError

FENCE = "SELECT dingtalk_lock_message_binding(%(tenant)s,%(message)s)"
MESSAGE = "DingTalk service binding required"


def failure(*, state="42501", primary=MESSAGE, statement=FENCE):
    original = RuntimeError(primary)
    original.sqlstate = state
    original.diag = SimpleNamespace(message_primary=primary)
    return DBAPIError(statement, {}, original)


def environment(monkeypatch, error, *, proof):
    reference = {"tenant_id": str(uuid4()), "message_id": str(uuid4())}
    state = SimpleNamespace(active=False, rolled_back=False, calls=[])

    @contextmanager
    def uow():
        state.active = True
        try:
            yield
        finally:
            state.active, state.rolled_back = False, True
            state.calls.append("rollback")

    def execute(_service, actual):
        assert actual == reference
        with uow():
            raise error

    def cancel_lost(ref):
        assert not state.active and state.rolled_back
        assert str(ref.tenant_id) == reference["tenant_id"]
        assert str(ref.message_id) == reference["message_id"]
        state.calls.append("actual_lost_run_check")
        return proof

    def no_metadata(*_args):
        pytest.fail("The rolled-back/revoked service must not write metadata or send")

    service = SimpleNamespace(cancel_lost=cancel_lost, metadata=no_metadata)
    monkeypatch.setattr(runtime, "ChannelService", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(graph, "execute", execute)
    activity = ChannelActivities(object(), object(), None)
    return activity, reference, state


def test_native_service_loss_is_cancelled_only_after_rollback_and_exact_dispatcher_proof(
    monkeypatch,
):
    activity, reference, state = environment(monkeypatch, failure(), proof=uuid4())
    assert activity.deliver(reference) == {"state": "cancelled", "error_code": "CANCELLED_RUN"}
    assert state.calls == ["rollback", "actual_lost_run_check"]


@pytest.mark.parametrize("proof", [None, True, "not-an-actual-uuid"])
def test_helper_denial_without_actual_lost_run_uuid_remains_the_original_sql_error(
    monkeypatch, proof
):
    error = failure()
    activity, reference, state = environment(monkeypatch, error, proof=proof)
    with pytest.raises(DBAPIError) as failed:
        activity.deliver(reference)
    assert failed.value is error
    assert state.calls == ["rollback", "actual_lost_run_check"]


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "40001"},
        {"state": "23514"},
        {"primary": "permission denied for function dingtalk_lock_message_binding"},
        {"statement": "SELECT some_other_helper()"},
    ],
)
def test_other_sql_or_permission_configuration_errors_are_not_relabelled_as_cancelled(
    monkeypatch, changes
):
    error = failure(**changes)
    activity, reference, state = environment(monkeypatch, error, proof=uuid4())
    with pytest.raises(DBAPIError) as failed:
        activity.deliver(reference)
    assert failed.value is error and state.calls == ["rollback"]


def test_existing_app_disable_cancelled_result_uses_no_sql_error_recovery(monkeypatch):
    service = SimpleNamespace(
        cancel_lost=lambda _ref: pytest.fail("Normal cancellation needs no SQL failure recovery"),
    )
    monkeypatch.setattr(runtime, "ChannelService", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(graph, "execute", lambda *_args: {"state": "cancelled"})
    reference = {"tenant_id": str(uuid4()), "message_id": str(uuid4())}
    assert ChannelActivities(object(), object(), None).deliver(reference) == {"state": "cancelled"}
