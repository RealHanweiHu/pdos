"""Workflow command harness: no Temporal service, database, model or wall-clock sleeps."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.exceptions import ApplicationError

from pdos_next.workflows import automation

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)


def reference():
    return {key: str(uuid4()) for key in automation.REFERENCE_KEYS}


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "not-a-uuid"},
        {"grant_id": uuid4()},
        {"grant_id": None},
        {"requester_id": str(uuid4())},
        {"approval_token": "client authority"},
    ],
)
def test_only_fixed_uuid_reference_envelope_reaches_any_activity(monkeypatch, change):
    execute = AsyncMock()
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(automation.AutomationRuleWork().run(reference() | change))
    assert error.value.type == "AUTOMATION_REFERENCE_INVALID" and error.value.non_retryable
    execute.assert_not_awaited()


def test_missing_reference_is_explicit_and_stopped_result_finishes_without_waiting(monkeypatch):
    ref = reference()
    stopped = {"state": "stopped", "wake_at": None, "reason": "grant_expired"}
    execute, wait = AsyncMock(return_value=stopped), AsyncMock()
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    incomplete = {key: value for key, value in ref.items() if key != "grant_id"}
    with pytest.raises(ApplicationError):
        asyncio.run(automation.AutomationRuleWork().run(incomplete))
    assert asyncio.run(automation.AutomationRuleWork().run(ref)) == stopped
    assert execute.await_count == 1 and execute.await_args.args == ("automation_rule_tick", ref)
    wait.assert_not_awaited()


def test_signals_during_activity_are_coalesced_and_cannot_be_lost_or_alter_fixed_scope(monkeypatch):
    work, ref, observed = automation.AutomationRuleWork(), reference(), []
    work.wake()
    work.wake()  # Signals already present are covered by the initial tick.

    async def execute(name, payload, **options):
        assert name == "automation_rule_tick"
        observed.append(dict(payload))
        assert options["start_to_close_timeout"] == timedelta(minutes=1)
        assert options["retry_policy"].maximum_attempts == 0
        assert options["retry_policy"].maximum_interval == timedelta(minutes=1)
        if len(observed) == 1:
            work.wake()
            work.wake()
            work.wake()
            payload["grant_id"] = str(uuid4())  # The next tick gets a fresh original envelope.
            return {"state": "active", "wake_at": (AT + timedelta(hours=1)).isoformat()}
        return {"state": "stopped", "wake_at": None}

    wait = AsyncMock(side_effect=AssertionError("Pending wake must retick before waiting"))
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    assert asyncio.run(work.run(ref))["state"] == "stopped"
    assert observed == [ref, ref]
    wait.assert_not_awaited()


def test_future_activity_instant_uses_durable_timeout_and_wake_interrupts_it(monkeypatch):
    work, waits = automation.AutomationRuleWork(), []
    # A non-UTC ISO representation of the same fixed instant is accepted.
    execute = AsyncMock(
        side_effect=[
            {"state": "active", "wake_at": "2026-10-18T18:00:30+08:00"},
            {"state": "stopped", "wake_at": None},
        ]
    )

    async def wait(predicate, *, timeout):
        waits.append(timeout)
        assert not predicate()
        work.wake()  # Delivery while the durable wait is being installed is retained.
        work.wake()
        assert predicate()

    monkeypatch.setattr(automation.workflow, "now", lambda: AT)
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    assert asyncio.run(work.run(reference()))["state"] == "stopped"
    assert waits == [timedelta(seconds=30)] and execute.await_count == 2


def test_timer_expiry_reticks_and_no_schedule_waits_only_for_a_signal(monkeypatch):
    work, waits, clock = automation.AutomationRuleWork(), [], [AT]
    execute = AsyncMock(
        side_effect=[
            {"state": "active", "wake_at": (AT + timedelta(seconds=10)).isoformat()},
            {"state": "active", "wake_at": None},
            {"state": "stopped", "wake_at": None},
        ]
    )

    async def wait(predicate, *, timeout):
        waits.append(timeout)
        assert not predicate()
        if timeout is not None:
            clock[0] += timeout
            raise TimeoutError
        work.wake()
        assert predicate()

    monkeypatch.setattr(automation.workflow, "now", lambda: clock[0])
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    assert asyncio.run(work.run(reference()))["state"] == "stopped"
    assert waits == [timedelta(seconds=10), None] and execute.await_count == 3


def test_due_boundary_reticks_without_creating_a_zero_timeout_timer(monkeypatch):
    execute = AsyncMock(
        side_effect=[
            {"state": "active", "wake_at": AT.isoformat()},
            {"state": "stopped", "wake_at": None},
        ]
    )
    wait = AsyncMock(side_effect=AssertionError("Due now must not create a zero timer"))
    monkeypatch.setattr(automation.workflow, "now", lambda: AT)
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    assert asyncio.run(automation.AutomationRuleWork().run(reference()))["state"] == "stopped"
    assert execute.await_count == 2
    wait.assert_not_awaited()


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"state": "active"},
        {"state": "unknown", "wake_at": None},
        {"state": "active", "wake_at": "not-a-time"},
        {"state": "active", "wake_at": "2026-10-18T10:00:00"},
        {"state": "active", "wake_at": AT},
        {"state": "active", "wake_at": None, "reason": ["ignored"]},
        {"state": "stopped", "wake_at": None, "run_payload": {"authorized": True}},
    ],
)
def test_invalid_activity_output_is_a_visible_contract_failure(monkeypatch, result):
    execute = AsyncMock(return_value=result)
    wait = AsyncMock()
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    monkeypatch.setattr(automation.workflow, "wait_condition", wait)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(automation.AutomationRuleWork().run(reference()))
    assert error.value.type == "AUTOMATION_TICK_INVALID" and error.value.non_retryable
    assert execute.await_count == 1
    wait.assert_not_awaited()


def test_technical_activity_failure_is_not_caught_and_locally_reexecuted(monkeypatch):
    failure = RuntimeError("synthetic Activity transport failure")
    execute = AsyncMock(side_effect=failure)
    monkeypatch.setattr(automation.workflow, "execute_activity", execute)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(automation.AutomationRuleWork().run(reference()))
    assert error.value is failure and execute.await_count == 1
    assert execute.await_args.kwargs["retry_policy"].maximum_attempts == 0


def test_same_recorded_ticks_signals_and_workflow_clock_produce_same_command_trace(monkeypatch):
    ref = reference()

    def replay_script():
        work, observed, clock = automation.AutomationRuleWork(), [], [AT]
        work.wake()

        async def execute(name, payload, **_options):
            observed.append((name, dict(payload)))
            if len(observed) == 1:
                work.wake()
                work.wake()
            return (
                {"state": "active", "wake_at": (AT + timedelta(seconds=1)).isoformat()}
                if len(observed) < 3
                else {"state": "stopped", "wake_at": None}
            )

        async def wait(predicate, *, timeout):
            assert not predicate()
            observed.append(("timer", timeout))
            clock[0] += timeout
            raise TimeoutError

        monkeypatch.setattr(automation.workflow, "execute_activity", execute)
        monkeypatch.setattr(automation.workflow, "wait_condition", wait)
        monkeypatch.setattr(automation.workflow, "now", lambda: clock[0])
        result = asyncio.run(work.run(ref))
        return result, observed

    first = replay_script()
    assert replay_script() == first
    assert first[1] == [
        ("automation_rule_tick", ref),
        ("automation_rule_tick", ref),
        ("timer", timedelta(seconds=1)),
        ("automation_rule_tick", ref),
    ]
