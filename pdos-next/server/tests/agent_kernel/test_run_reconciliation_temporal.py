"""Real local Temporal timer/retry exit; synthetic lost calls, zero model/provider I/O."""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, ValidationBudget
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.test_run_reconciliation import lost, reference


@pytest.mark.skipif(
    not os.environ.get("PDOS_RECONCILE_TEMPORAL_ADDRESS"),
    reason="Explicit existing local Temporal target required",
)
def test_real_temporal_five_minute_timer_and_exhausted_retry_both_close_without_inference(setup):
    address = os.environ["PDOS_RECONCILE_TEMPORAL_ADDRESS"]
    assert address == "127.0.0.1:61596"
    delayed, exhausted = lost(setup, admin=False), lost(setup, admin=False, waiting=False)
    attempts, timeline = [], []
    evidence = os.environ.get("PDOS_RUN_RECONCILIATION_EVIDENCE_DIR")
    prefix = (
        "temporal-final" if os.environ.get("PDOS_RECONCILIATION_FINAL_CANDIDATE") else "temporal"
    )

    def note(phase, **details):
        item = {"phase": phase, "at": datetime.now(UTC).isoformat(), **details}
        timeline.append(item)
        if evidence:
            with (Path(evidence) / (prefix + "-timeline.jsonl")).open("a") as output:
                output.write(json.dumps(item) + "\n")

    @activity.defn(name="advance_xiaopai_run")
    async def interrupted(ref):
        attempts.append({"run_id": ref["subject_id"], "attempt": activity.info().attempt})
        note("advance", **attempts[-1])
        if ref["subject_id"] == str(delayed.scope.run_id):
            return {"status": "needs_reconciliation"}
        raise ApplicationError(
            "Synthetic interrupted worker", type="SyntheticInfrastructureFailure"
        )

    async def actual():
        async with asyncio.timeout(15):
            client = await Client.connect(address)
            assert await client.service_client.check_health()
        queue = "reconcile-fixture-" + str(uuid4())
        activities = KernelActivities(setup.engine, technical_engine=setup.dispatch)
        handles, finished = [], False
        with ThreadPoolExecutor(max_workers=3) as executor:
            async with Worker(
                client,
                task_queue=queue,
                workflows=[XiaopaiWork],
                activities=[interrupted, activities.reconcile],
                activity_executor=executor,
            ):
                try:
                    for item in [delayed, exhausted]:
                        handles.append(
                            await client.start_workflow(
                                XiaopaiWork.run,
                                reference(setup, item),
                                id="reconcile-fixture-" + str(item.scope.run_id),
                                task_queue=queue,
                            )
                        )
                    note(
                        "started",
                        delayed_run=str(delayed.scope.run_id),
                        exhausted_run=str(exhausted.scope.run_id),
                    )
                    results = await asyncio.wait_for(
                        asyncio.gather(*(handle.result() for handle in handles)), timeout=420
                    )
                    assert all(row["status"] == "failed" for row in results)
                    history = await handles[0].fetch_history()
                    timers = [
                        event.timer_started_event_attributes.start_to_fire_timeout.seconds
                        for event in history.events
                        if event.HasField("timer_started_event_attributes")
                    ]
                    assert 300 in timers
                    assert any(
                        event.HasField("timer_fired_event_attributes") for event in history.events
                    )
                    scheduled = [
                        event.activity_task_scheduled_event_attributes.activity_type.name
                        for event in history.events
                        if event.HasField("activity_task_scheduled_event_attributes")
                    ]
                    assert scheduled == ["advance_xiaopai_run", "reconcile_xiaopai_run"]
                    finished = True
                    note("completed", results=results, timer_seconds=timers, activities=scheduled)
                finally:
                    if not finished:
                        await asyncio.gather(
                            *(handle.cancel() for handle in handles), return_exceptions=True
                        )
        return results

    results = asyncio.run(actual())
    assert [row["attempt"] for row in attempts if row["run_id"] == str(exhausted.scope.run_id)] == [
        1,
        2,
        3,
    ]
    assert len([row for row in attempts if row["run_id"] == str(delayed.scope.run_id)]) == 1
    with Session(setup.admin) as session:
        for item in [delayed, exhausted]:
            row, budget = (
                session.get(AgentRun, item.scope.run_id),
                session.get(ValidationBudget, item.budget),
            )
            assert row.state == "failed" and row.held_tokens == 0 and row.cancel_epoch == 1
            assert budget.held_micro_usd == 0 and budget.spent_micro_usd == item.charge
            events = list(
                session.scalars(
                    select(AgentEvent).where(
                        AgentEvent.run_id == row.id,
                        AgentEvent.body["type"].astext == "run_reconciled",
                    )
                )
            )
            assert len(events) == 1
    if evidence:
        (Path(evidence) / (prefix + "-result.json")).write_text(
            json.dumps(
                {
                    "target": address,
                    "reused_existing_service": True,
                    "actual_durable_timer_seconds": 300,
                    "advance_attempts": attempts,
                    "results": results,
                    "real_model_calls": 0,
                    "real_external_calls": 0,
                    "own_worker_stopped": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


@pytest.mark.skipif(
    not os.environ.get("PDOS_RECONCILE_TEMPORAL_ADDRESS"),
    reason="Explicit existing local Temporal target required",
)
def test_real_temporal_technical_cleanup_survives_more_than_three_outage_attempts(setup):
    address = os.environ["PDOS_RECONCILE_TEMPORAL_ADDRESS"]
    assert address == "127.0.0.1:61596"
    item = lost(setup, admin=False, waiting=False)
    attempts = []
    actual_cleanup = KernelActivities(setup.engine, technical_engine=setup.dispatch)

    @activity.defn(name="advance_xiaopai_run")
    async def interrupted(ref):
        raise ApplicationError("Synthetic exhausted execution", non_retryable=True)

    @activity.defn(name="reconcile_xiaopai_run")
    def temporary_outage(ref):
        attempts.append(activity.info().attempt)
        if len(attempts) <= 3:
            raise ApplicationError("Synthetic temporary database unavailability")
        return actual_cleanup.reconcile(ref)

    async def actual():
        async with asyncio.timeout(15):
            client = await Client.connect(address)
            assert await client.service_client.check_health()
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                client,
                task_queue="reconcile-outage-" + str(item.scope.run_id),
                workflows=[XiaopaiWork],
                activities=[interrupted, temporary_outage],
                activity_executor=executor,
            ):
                handle = await client.start_workflow(
                    XiaopaiWork.run,
                    reference(setup, item),
                    id="reconcile-outage-" + str(item.scope.run_id),
                    task_queue="reconcile-outage-" + str(item.scope.run_id),
                )
                try:
                    result = await asyncio.wait_for(handle.result(), timeout=45)
                    history = await handle.fetch_history()
                except BaseException:
                    await handle.cancel()
                    raise
        scheduled = [
            event.activity_task_scheduled_event_attributes
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        assert [row.activity_type.name for row in scheduled] == [
            "advance_xiaopai_run",
            "reconcile_xiaopai_run",
        ]
        assert scheduled[-1].retry_policy.maximum_attempts == 0
        assert scheduled[-1].retry_policy.maximum_interval.seconds == 60
        return result

    result = asyncio.run(actual())
    assert attempts == [1, 2, 3, 4]
    assert result["status"] == "failed" and result["reconciliation"]["held_tokens"] == 0
    with Session(setup.admin) as session:
        row = session.get(AgentRun, item.scope.run_id)
        assert row.state == "failed" and row.cancel_epoch == 1
    evidence = os.environ.get("PDOS_RUN_RECONCILIATION_EVIDENCE_DIR")
    if evidence:
        filename = (
            "temporal-outage-final-result.json"
            if os.environ.get("PDOS_RECONCILIATION_OUTAGE_FINAL")
            else "temporal-outage-result.json"
        )
        target = Path(evidence) / filename
        assert not target.exists()
        target.write_text(
            json.dumps(
                {
                    "target": address,
                    "reused_existing_service": True,
                    "technical_cleanup_attempts": attempts,
                    "advance_calls": 1,
                    "technical_retry_maximum_attempts": 0,
                    "technical_retry_maximum_interval_seconds": 60,
                    "result": result,
                    "real_model_calls": 0,
                    "real_external_calls": 0,
                    "own_worker_stopped": True,
                    "ordinary_definer_owner": "pdos_next_owner",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
