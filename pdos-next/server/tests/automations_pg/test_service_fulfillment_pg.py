"""Actual recipient fulfillment stops only the selected current promise's grant.

Root alone runs this isolated PG/HTTP slice. Existing HTTP commands create every
task, promise, submission, review and service authorization. Real ticks retain
due targets during cooldown; direct narrow SQL start verifies admission without
an intervening tick. Explicit synthetic host recovery items reuse those actual
resolved origins; they are not business Outbox events. No business-row insertion,
model or external call is used.
"""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    SUBMIT,
)
from pdos_next.domain.work_management.models import WorkCommitmentCurrent
from pdos_next.models import now
from pdos_next.service import digest
from tests.automations_pg.test_manual_workflow import reading
from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec, _state
from tests.automations_pg.test_service_relative_pg import (
    _attempts,
    _retained_promises,
    _save,
)
from tests.work_fulfillment_pg import test_workflow as fulfillment
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work  # noqa: F401
from tests.work_management_pg.test_workflow import work as work_case  # noqa: F401


@pytest.fixture
def relative_work(request):
    return request.getfixturevalue("work_case")


def _accepted(work):
    setup = work.setup
    created = _save(
        work,
        CREATE,
        title="Synthetic separately reviewed promise automation",
        goal="Keep task completion, recipient fulfillment and automatic admission distinct",
        outcomes=[{"key": "drawing", "text": "Traceable drawing outcome", "required": True}],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = _save(
        work,
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    return _save(work, ACCEPT, actor=setup.peer, task=fulfillment._task_ref(assigned))


def _promise(work, task, recipient, promised_at, previous=None):
    # The promise owner reads the real current Task, including submitted state.
    return _save(
        work,
        COMMIT,
        actor=work.setup.peer,
        task=fulfillment._task_ref(task),
        recipient_id=str(recipient),
        outcome_keys=["drawing"],
        promised_at=promised_at,
        original_timezone=flow.TIMEZONE,
        calendar_id=None,
        replaces=fulfillment._ref(previous) if previous else None,
    )


def _submitted(work, accepted):
    started = _save(
        work,
        START,
        actor=work.setup.peer,
        task=fulfillment._task_ref(accepted),
        **flow.clock_fields(),
    )
    return _save(
        work,
        SUBMIT,
        actor=work.setup.peer,
        task=fulfillment._task_ref(started),
        **flow.clock_fields(),
        results=[
            {
                "key": "drawing",
                "text": "Actual synthetic drawing with its original source",
                "status": "present",
                "sources": [work.source],
            }
        ],
    )


def _completed(work, submitted):
    completed = _save(
        work,
        REVIEW,
        task=fulfillment._task_ref(submitted),
        decision="accepted",
        **flow.clock_fields(),
        checks=fulfillment._checks("drawing"),
    )
    flow.task(work, "completed")
    return completed


def _review(work, promise, task, submission, *, actor=None, revision=0, decision="accepted"):
    checks = fulfillment._checks("drawing")
    if decision == "returned":
        checks[0] = {
            "key": "drawing",
            "decision": "unknown",
            "reason": "Recipient has not established fulfillment of this fixed promise",
        }
    _, receipt, _ = fulfillment._save(
        work,
        fulfillment._declaration(
            work,
            fulfillment._ref(promise),
            fulfillment._task_ref(task),
            fulfillment._ref(submission),
            revision=revision,
            decision=decision,
            checks=checks,
        ),
        actor=actor,
    )
    return receipt


def _relative_spec(work, wallet, *, cooldown=0):
    spec = _spec(
        work.setup,
        wallet,
        kind="relative_milestone",
        config={
            "source_kind": "commitment",
            "project_id": str(work.project_id),
            "task_id": str(work.task_id),
            "clock": "promised_at",
            "promisor_id": str(work.setup.peer),
            "recipient_id": str(work.setup.human),
            "offset_seconds": 0,
            "expires_at": None,
        },
    )
    spec["cooldown_seconds"] = cooldown
    return spec


def _target(setup, ref, promise):
    matches = [
        row
        for row in _attempts(setup, ref["grant_id"])
        if row["origin"].get("kind") == "relative_milestone"
        and row["origin"].get("commitment_id") == promise["subject_id"]
        and not row["origin"].get("synthetic_host_queue_fixture")
    ]
    assert len(matches) == 1
    return matches[0]


def _queued_recovery(setup, ref, actual):
    """Host fixture requeues a captured actual clock; no business event is invented."""
    assert actual["origin"]["kind"] == "relative_milestone"
    with service_runtime.session(setup.engine, ref) as session:
        grant, _, spec = service_runtime.saved(session, ref, admission=True)
        attempt = service_runtime.enqueue(
            session,
            grant,
            spec,
            key="synthetic_host_queue_fixture:" + str(actual["id"]),
            origin={**actual["origin"], "synthetic_host_queue_fixture": True},
            due_at=actual["due_at"],
        )
        assert attempt.state == "queued" and attempt.run_id is None
        return attempt.id


def _start(setup, ref, attempt_id):
    with service_runtime.session(setup.engine, ref) as session:
        return session.scalar(
            text("SELECT automation_service_start(:attempt)"), {"attempt": attempt_id}
        )


def _run(setup, run_id):
    with Session(setup.admin) as session:
        value = (
            session.execute(select(AgentRun.__table__).where(AgentRun.id == run_id))
            .mappings()
            .one()
        )
        assert value["state"] == "queued" and value["cancel_epoch"] == 0
        return digest(dict(value))


def _stopped(setup, rule_id, ref, *, admitted_count):
    assert service_runtime.tick(setup.engine, ref) == {
        "state": "stopped",
        "wake_at": None,
        "reason": "GOAL_REACHED",
    }
    current = reading(setup, rule_id)["rule"]
    assert current["service_grant"]["state"] == "stopped"
    assert current["admitted_count"] == admitted_count
    diagnostics = [
        row for row in _attempts(setup, ref["grant_id"]) if row["origin"].get("kind") == "lifecycle"
    ]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["trigger_key"] == "lifecycle:stop"
    assert diagnostic["state"] == "suppressed" and diagnostic["error_code"] == "GOAL_REACHED"
    assert diagnostic["run_id"] is None and diagnostic["admitted_at"] is None
    frozen = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["reason"] == "GOAL_REACHED"
    assert _state(setup) == frozen


def test_actual_recipient_goal_stops_queued_current_and_sql_rejects_superseded_source(
    relative_work,
):
    work, setup = relative_work, relative_work.setup
    wallet = _ready(setup)
    accepted = _accepted(work)
    due = (now() - timedelta(minutes=5)).isoformat()
    first = _promise(work, accepted, setup.human, due)
    sibling = _promise(work, accepted, setup.peer, due)
    retained = _retained_promises(work)
    rule_id, ref = _activate(setup, _relative_spec(work, wallet, cooldown=86_400))
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    original = _target(setup, ref, first)
    assert original["state"] == "admitted" and original["run_id"] is not None
    run_id, run_before = original["run_id"], _run(setup, original["run_id"])
    submitted = _submitted(work, accepted)

    returned = _review(work, first, submitted, submitted, decision="returned")
    assert returned["result"]["status"] == "open"
    other_fulfilled = _review(work, sibling, submitted, submitted, actor=setup.peer)
    assert other_fulfilled["result"]["status"] == "fulfilled"
    # The sibling receiver's fulfillment cannot close this receiver's obligation.
    before_other = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    assert _state(setup) == before_other
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 1
    with Session(setup.admin) as session:
        states = dict(
            session.execute(
                select(
                    WorkCommitmentReviewCurrent.commitment_id, WorkCommitmentReviewCurrent.state
                ).where(WorkCommitmentReviewCurrent.tenant_id == setup.tenant)
            ).all()
        )
        assert states[UUID(first["subject_id"])] == "open"
        assert states[UUID(sibling["subject_id"])] == "fulfilled"

    second = _promise(work, submitted, setup.human, due, first)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    queued_old = _target(setup, ref, second)
    assert queued_old["state"] == "queued" and queued_old["run_id"] is None
    assert queued_old["origin"]["commitment_revision"] == second["subject_revision"] == 2
    third = _promise(work, submitted, setup.human, due, second)
    # No tick between replacement and start: SQL must re-read the actual Current.
    assert _start(setup, ref, queued_old["id"]) is None
    superseded = _target(setup, ref, second)
    assert superseded["state"] == "suppressed" and superseded["error_code"] == "SOURCE_SUPERSEDED"
    assert superseded["run_id"] is None and superseded["admitted_at"] is None
    assert reading(setup, rule_id)["rule"]["service_grant"]["state"] == "active"
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 1
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    queued_current = _target(setup, ref, third)
    assert queued_current["state"] == "queued" and queued_current["run_id"] is None
    assert queued_current["trigger_key"] != queued_old["trigger_key"]
    assert queued_current["origin"]["commitment_revision"] == third["subject_revision"] == 3
    assert queued_current["origin"]["recipient_id"] == str(setup.human)
    assert queued_current["origin"]["series_id"] == original["origin"]["series_id"]
    stale_recovery = _queued_recovery(setup, ref, queued_old)
    current_recovery = _queued_recovery(setup, ref, queued_current)

    fulfilled = _review(work, third, submitted, submitted)
    assert fulfilled["result"]["status"] == "fulfilled"
    # Fulfillment wins before cooldown and before another supervisor tick.
    assert _start(setup, ref, queued_current["id"]) is None
    goal = _target(setup, ref, third)
    assert goal["state"] == "suppressed" and goal["error_code"] == "GOAL_REACHED"
    assert goal["run_id"] is None and goal["admitted_at"] is None
    pending = {row["id"]: row for row in _attempts(setup, ref["grant_id"])}
    assert pending[stale_recovery]["state"] == pending[current_recovery]["state"] == "queued"
    _stopped(setup, rule_id, ref, admitted_count=1)
    recovered = {row["id"]: row for row in _attempts(setup, ref["grant_id"])}
    for identity, reason in (
        (stale_recovery, "SOURCE_SUPERSEDED"),
        (current_recovery, "GOAL_REACHED"),
    ):
        assert recovered[identity]["origin"]["synthetic_host_queue_fixture"] is True
        assert recovered[identity]["state"] == "suppressed"
        assert recovered[identity]["error_code"] == reason
        assert recovered[identity]["run_id"] is None and recovered[identity]["admitted_at"] is None

    # A new real promise changes Current but does not revive an already stopped grant.
    fourth = _promise(work, submitted, setup.human, due, third)
    stopped_before_new_tick = _state(setup)
    _stopped(setup, rule_id, ref, admitted_count=1)
    assert _state(setup) == stopped_before_new_tick
    assert not any(
        row["origin"].get("commitment_id") == fourth["subject_id"]
        for row in _attempts(setup, ref["grant_id"])
    )
    _completed(work, submitted)
    assert _start(setup, ref, original["id"]) == run_id
    assert _run(setup, run_id) == run_before
    final = reading(setup, rule_id)
    assert {row["run_id"] for row in final["runs"]} == {str(run_id)}
    assert all(_retained_promises(work)[key] == value for key, value in retained.items())
    with Session(setup.admin) as session:
        pointers = session.scalars(
            select(WorkCommitmentCurrent).where(
                WorkCommitmentCurrent.tenant_id == setup.tenant,
                WorkCommitmentCurrent.task_id == work.task_id,
            )
        ).all()
        assert {row.recipient_id: str(row.version_id) for row in pointers} == {
            setup.human: fourth["subject_id"],
            setup.peer: sibling["subject_id"],
        }


@pytest.mark.parametrize("source_state", ["null_date", "task_waiting"])
def test_actual_fulfillment_stops_before_unknown_clock_or_explicit_task_wait(
    relative_work, source_state
):
    work, setup = relative_work, relative_work.setup
    wallet = _ready(setup)
    accepted = _accepted(work)
    due = None if source_state == "null_date" else (now() - timedelta(minutes=5)).isoformat()
    promise = _promise(work, accepted, setup.human, due)
    submitted = _submitted(work, accepted)
    completed = _completed(work, submitted)
    returned = _review(work, promise, completed, submitted, decision="returned")
    assert returned["result"]["status"] == "open"
    retained = _retained_promises(work)
    spec = _relative_spec(work, wallet)
    if source_state == "task_waiting":
        spec["conditions"] = {
            "task_id": str(work.task_id),
            "only_states": ["accepted"],
            "stop_states": [],
        }
    rule_id, ref = _activate(setup, spec)
    # Task.completed alone is not fulfillment: no declared stop condition applies.
    before = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    assert _state(setup) == before
    assert _attempts(setup, ref["grant_id"]) == []
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 0
    fulfilled = _review(work, promise, completed, submitted, revision=1)
    assert fulfilled["subject_revision"] == 2 and fulfilled["result"]["status"] == "fulfilled"
    _stopped(setup, rule_id, ref, admitted_count=0)
    assert _retained_promises(work) == retained
    with Session(setup.admin) as session:
        assert session.scalar(select(AgentRun.id).where(AgentRun.tenant_id == setup.tenant)) is None
    assert len(_attempts(setup, ref["grant_id"])) == 1
