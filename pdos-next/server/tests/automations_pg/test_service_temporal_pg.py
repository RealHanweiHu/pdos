"""Real local Temporal timer recovery against the guarded isolated PG target.

Only root runs this opt-in case. Its dedicated Worker has no Xiaopai/model
Activity: the real rule tick can admit a queued Run, but cannot execute it.
"""

import asyncio
import os
from contextlib import suppress
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.client import Client
from temporalio.service import RPCError
from temporalio.worker import Worker

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import PAUSE
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.models import now
from pdos_next.service import digest
from pdos_next.workflows.automation import AutomationRuleWork
from tests.automations_pg.test_manual_workflow import assert_common_group, reading, save
from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec


def _admission(setup, ref, scheduled_at, wallet):
    """Inspect actual rows; no direct setup or business writes occur here."""
    with Session(setup.admin) as session:
        attempts = session.scalars(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"])
            )
        ).all()
        runs = session.scalars(select(AgentRun).where(AgentRun.tenant_id == setup.tenant)).all()
        assert len(attempts) == len(runs) == 1
        attempt, run = attempts[0], runs[0]
        assert attempt.state == "admitted" and attempt.error_code is None
        assert attempt.trigger_kind == attempt.origin["kind"] == "schedule"
        assert datetime.fromisoformat(attempt.origin["scheduled_at"]) == scheduled_at
        assert attempt.due_at == scheduled_at and attempt.admitted_at >= scheduled_at
        assert attempt.origin["original_timezone"] == "UTC"
        assert attempt.run_id == run.id and attempt.depth == 0
        assert attempt.parent_run_id is None
        assert attempt.owner_id == run.requester_id == setup.human
        assert attempt.writer_id == run.writer_id == setup.agent
        assert attempt.category_id == run.category_id == setup.category
        assert run.product_id == setup.product and run.tenant_id == setup.tenant
        assert run.trigger == service_runtime.TRIGGER and run.state == "queued"
        assert run.intent_digest == attempt.request_digest and run.cancel_epoch == 0
        assert run.validation_budget_id == UUID(wallet["subject_id"])
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.tenant_id == setup.tenant))
            is None
        )
        return tuple(
            digest({column.name: getattr(row, column.name) for column in row.__table__.c})
            for row in (attempt, run)
        )


def _not_admitted(setup, ref):
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(AutomationServiceAttempt.id).where(
                    AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"])
                )
            )
            is None
        )
        assert session.scalar(select(AgentRun.id).where(AgentRun.tenant_id == setup.tenant)) is None


async def _history_until(handle, predicate):
    async with asyncio.timeout(10):
        while True:
            history = await handle.fetch_history(rpc_timeout=timedelta(seconds=2))
            if predicate(history.events):
                return history
            await asyncio.sleep(0.05)


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS") or not os.environ.get("PDOS_TEMPORAL_NAMESPACE"),
    reason="Explicit PDOS_TEMPORAL_ADDRESS and PDOS_TEMPORAL_NAMESPACE are required",
)
def test_actual_schedule_timer_survives_own_worker_restart_and_http_pause(setup):
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    namespace = os.environ["PDOS_TEMPORAL_NAMESPACE"]
    target = urlsplit(address if "://" in address else "//" + address)
    assert target.hostname in {"127.0.0.1", "localhost", "::1"}, "Local Temporal required"
    assert target.port is not None and namespace.strip()

    async def actual():
        # Includes actual explicit independent pdos_test guards, within this deadline.
        wallet = await asyncio.to_thread(_ready, setup)
        client = await Client.connect(address, namespace=namespace)
        assert await client.service_client.check_health()
        queue = "automation-rule-restart-" + str(uuid4())
        handle, finished = None, False
        generation = 1
        calls = []
        first_tick, restarted_tick = asyncio.Event(), asyncio.Event()

        @activity.defn(name="automation_rule_tick")
        async def tick(reference):
            current_generation = generation
            started_at = now()
            attempt = activity.info().attempt
            result = await asyncio.to_thread(service_runtime.tick, setup.engine, reference)
            calls.append(
                {
                    "generation": current_generation,
                    "started_at": started_at,
                    "attempt": attempt,
                    "reference": dict(reference),
                    "result": result,
                }
            )
            (first_tick if current_generation == 1 else restarted_tick).set()
            return result

        def worker():
            return Worker(
                client,
                task_queue=queue,
                workflows=[AutomationRuleWork],
                activities=[tick],
                sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
                graceful_shutdown_timeout=timedelta(0),
            )

        try:
            async with worker():
                scheduled_at = now() + timedelta(seconds=5)
                spec = _spec(
                    setup,
                    wallet,
                    config={
                        "first_at": scheduled_at.isoformat(),
                        "original_timezone": "UTC",
                        "interval_seconds": None,
                        "expires_at": None,
                    },
                )
                rule_id, ref = await asyncio.to_thread(_activate, setup, spec)
                handle = await client.start_workflow(
                    AutomationRuleWork.run,
                    ref,
                    id="automation-rule-restart-" + ref["grant_id"],
                    task_queue=queue,
                )
                await first_tick.wait()
                assert len(calls) == 1 and calls[0]["attempt"] == 1
                assert calls[0]["reference"] == ref
                assert calls[0]["started_at"] < scheduled_at
                assert calls[0]["result"]["state"] == "active"
                assert datetime.fromisoformat(calls[0]["result"]["wake_at"]) == scheduled_at
                history = await _history_until(
                    handle,
                    lambda events: (
                        any(
                            event.HasField("activity_task_completed_event_attributes")
                            for event in events
                        )
                        and any(
                            event.HasField("timer_started_event_attributes") for event in events
                        )
                    ),
                )
                timers = [
                    event.timer_started_event_attributes
                    for event in history.events
                    if event.HasField("timer_started_event_attributes")
                ]
                assert len(timers) == 1
                assert timers[0].start_to_fire_timeout.ToTimedelta() > timedelta(0)
                timer_id = timers[0].timer_id
                await asyncio.to_thread(_not_admitted, setup, ref)

            # No Worker for this unique queue exists while the original timer fires.
            assert now() < scheduled_at, "Initial Worker must stop before the due instant"
            await _history_until(
                handle,
                lambda events: any(
                    event.HasField("timer_fired_event_attributes")
                    and event.timer_fired_event_attributes.timer_id == timer_id
                    for event in events
                ),
            )
            assert len(calls) == 1
            await asyncio.to_thread(_not_admitted, setup, ref)

            generation = 2
            async with worker():
                await restarted_tick.wait()
                assert calls[1]["generation"] == 2 and calls[1]["attempt"] == 1
                assert calls[1]["started_at"] >= scheduled_at
                assert calls[1]["reference"] == ref and calls[1]["result"]["state"] == "active"
                admitted = await asyncio.to_thread(_admission, setup, ref, scheduled_at, wallet)
                active = (await asyncio.to_thread(reading, setup, rule_id))["rule"]
                assert active["admitted_count"] == 1
                command, receipt = await asyncio.to_thread(
                    save,
                    setup,
                    PAUSE,
                    {
                        "rule_id": rule_id,
                        "expected_rule_revision": active["revision"],
                        "version_id": active["published"]["id"],
                    },
                )
                await handle.signal(AutomationRuleWork.wake, rpc_timeout=timedelta(seconds=2))
                result = await handle.result(rpc_timeout=timedelta(seconds=10))
                assert result == {"state": "stopped", "wake_at": None, "reason": "PAUSED"}
                finished = True
                history = await handle.fetch_history(rpc_timeout=timedelta(seconds=2))

            assert calls[-1]["result"] == result and calls[-1]["generation"] == 2
            assert all(call["reference"] == ref for call in calls)
            scheduled = [
                event.activity_task_scheduled_event_attributes.activity_type.name
                for event in history.events
                if event.HasField("activity_task_scheduled_event_attributes")
            ]
            assert len(scheduled) >= 3 and set(scheduled) == {"automation_rule_tick"}
            with Session(setup.admin) as session:
                assert_common_group(session, setup, command, receipt)
            assert _admission(setup, ref, scheduled_at, wallet) == admitted
            paused = reading(setup, rule_id)["rule"]
            assert paused["state"] == "paused" and paused["admitted_count"] == 1
        finally:
            if handle is not None and not finished:
                # Cancel this test's Workflow only; the shared Temporal stays running.
                with suppress(RPCError, TimeoutError):
                    await asyncio.wait_for(
                        handle.cancel(rpc_timeout=timedelta(seconds=2)), timeout=3
                    )

    async def bounded():
        async with asyncio.timeout(45):
            await actual()

    asyncio.run(bounded())
