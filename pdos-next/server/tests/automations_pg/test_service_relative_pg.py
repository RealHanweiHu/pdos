"""Actual per-recipient promise clocks drive one bounded service rule.

Only root runs this isolated PG/HTTP case. Real work/confirmation/source owners
remain in the path; explicit past due declarations do not backdate recorded facts
or change the server clock. No model, network or business-row insertion is used.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    SUBMIT,
)
from pdos_next.domain.work_management.models import WorkCommitmentCurrent, WorkCommitmentVersion
from pdos_next.models import now
from tests.automations_pg.test_manual_workflow import reading
from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec, _state
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work  # noqa: F401
from tests.work_management_pg.test_workflow import work as work_case  # noqa: F401


@pytest.fixture
def relative_work(request):
    return request.getfixturevalue("work_case")


def _save(work, operation, *, actor=None, **values):
    _, receipt = flow.execute(work, operation, flow.payload(work, **values), actor=actor)
    return receipt


def _commit(work, recipient, promised_at, previous=None):
    return _save(
        work,
        COMMIT,
        actor=work.setup.peer,
        task=flow.task(work, "accepted"),
        recipient_id=str(recipient),
        outcome_keys=["drawing"],
        promised_at=promised_at,
        original_timezone=flow.TIMEZONE,
        calendar_id=None,
        replaces=(
            {"id": previous["subject_id"], "revision": previous["subject_revision"]}
            if previous
            else None
        ),
    )


def _attempts(setup, grant_id):
    with Session(setup.admin) as session:
        return list(
            session.execute(
                select(AutomationServiceAttempt.__table__)
                .where(AutomationServiceAttempt.service_grant_id == UUID(grant_id))
                .order_by(AutomationServiceAttempt.created_at, AutomationServiceAttempt.id)
            ).mappings()
        )


def _retained_promises(work):
    with Session(work.setup.admin) as session:
        rows = session.scalars(
            select(WorkCommitmentVersion).where(WorkCommitmentVersion.task_id == work.task_id)
        ).all()
        return {str(row.id): deepcopy(row.body) for row in rows}


def test_actual_recipient_null_then_revised_due_clocks_and_completed_condition_stop(relative_work):
    work, setup = relative_work, relative_work.setup
    wallet = _ready(setup)
    created = _save(
        work,
        CREATE,
        title="Synthetic independently promised drawing",
        goal="Keep the actual recipient, clock and fixed promise source traceable",
        outcomes=[{"key": "drawing", "text": "Traceable drawing outcome", "required": True}],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    _save(
        work,
        ASSIGN,
        task=flow.task(work, "proposed"),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    _save(work, ACCEPT, actor=setup.peer, task=flow.task(work, "assigned"))
    # The other receiver already has a due date: the selected null receiver must
    # stay unknown rather than accidentally borrowing that sibling promise.
    unknown = _commit(work, setup.human, None)
    sibling = _commit(work, setup.peer, (now() - timedelta(minutes=10)).isoformat())
    original = _retained_promises(work)
    assert original[unknown["subject_id"]]["promised_at"] is None
    assert original[sibling["subject_id"]]["recipient_id"] == str(setup.peer)
    spec = _spec(
        setup,
        wallet,
        kind="relative_milestone",
        config={
            "source_kind": "commitment",
            "project_id": str(work.project_id),
            "task_id": str(work.task_id),
            "clock": "promised_at",
            "promisor_id": str(setup.peer),
            "recipient_id": str(setup.human),
            "offset_seconds": 0,
            "expires_at": None,
        },
    )
    spec["conditions"] = {
        "task_id": str(work.task_id),
        "only_states": ["accepted", "in_progress", "submitted"],
        "stop_states": ["completed"],
    }
    rule_id, ref = _activate(setup, spec)
    before_unknown = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    assert _state(setup) == before_unknown
    assert _attempts(setup, ref["grant_id"]) == []
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 0
    with Session(setup.admin) as session:
        assert session.scalar(select(AgentRun.id).where(AgentRun.tenant_id == setup.tenant)) is None

    first_at = now() - timedelta(minutes=5)
    first = _commit(work, setup.human, first_at.isoformat(), unknown)
    assert first["subject_revision"] == 2
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    first_attempts = _attempts(setup, ref["grant_id"])
    assert len(first_attempts) == 1 and first_attempts[0]["state"] == "admitted"
    first_origin = first_attempts[0]["origin"]
    assert first_origin["commitment_id"] == first["subject_id"]
    assert first_origin["commitment_revision"] == 2
    assert first_origin["promisor_id"] == str(setup.peer)
    assert first_origin["recipient_id"] == str(setup.human)
    assert datetime.fromisoformat(first_origin["source_at"]) == first_at
    assert first_origin["original_timezone"] == flow.TIMEZONE
    before_repeat = _state(setup)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    assert _state(setup) == before_repeat

    second_at = now() - timedelta(minutes=2)
    second = _commit(work, setup.human, second_at.isoformat(), first)
    assert second["subject_revision"] == 3
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    admitted = _attempts(setup, ref["grant_id"])
    assert len(admitted) == 2 and all(row["state"] == "admitted" for row in admitted)
    assert len({row["trigger_key"] for row in admitted}) == 2
    assert len({row["run_id"] for row in admitted}) == 2
    by_source = {row["origin"]["commitment_id"]: row for row in admitted}
    assert set(by_source) == {first["subject_id"], second["subject_id"]}
    assert by_source[first["subject_id"]]["origin"] == first_origin
    assert (
        datetime.fromisoformat(by_source[second["subject_id"]]["origin"]["source_at"]) == second_at
    )
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 2
    retained_before_completion = _retained_promises(work)
    assert all(retained_before_completion[key] == body for key, body in original.items())

    _save(
        work,
        START,
        actor=setup.peer,
        task=flow.task(work, "accepted"),
        **flow.clock_fields(),
    )
    _save(
        work,
        SUBMIT,
        actor=setup.peer,
        task=flow.task(work, "in_progress"),
        **flow.clock_fields(),
        results=[
            {
                "key": "drawing",
                "text": "Recorded synthetic drawing outcome with its actual original source",
                "status": "present",
                "sources": [work.source],
            }
        ],
    )
    _save(
        work,
        REVIEW,
        task=flow.task(work, "submitted"),
        decision="accepted",
        **flow.clock_fields(),
        checks=[
            {"key": "drawing", "decision": "accepted", "reason": "Named synthetic outcome review"}
        ],
    )
    flow.task(work, "completed")
    assert service_runtime.tick(setup.engine, ref) == {
        "state": "stopped",
        "wake_at": None,
        "reason": "GOAL_REACHED",
    }
    final = reading(setup, rule_id)
    assert final["rule"]["service_grant"]["state"] == "stopped"
    assert final["rule"]["admitted_count"] == 2
    assert {row["run_id"] for row in final["runs"]} == {str(row["run_id"]) for row in admitted}
    assert any(
        row["decision"] == "suppressed" and row["error_code"] == "GOAL_REACHED"
        for row in final["triggers"]
    )
    assert _retained_promises(work) == retained_before_completion
    with Session(setup.admin) as session:
        currents = session.scalars(
            select(WorkCommitmentCurrent).where(WorkCommitmentCurrent.task_id == work.task_id)
        ).all()
        assert {row.recipient_id for row in currents} == {setup.human, setup.peer}
        assert {str(row.version_id) for row in currents} == {
            second["subject_id"],
            sibling["subject_id"],
        }
        for row in admitted:
            run = session.get(AgentRun, row["run_id"])
            assert run.state == "queued" and run.cancel_epoch == 0
