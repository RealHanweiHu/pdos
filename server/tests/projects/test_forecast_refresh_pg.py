"""T0 deterministic forecast refresh (D47, AT-18/19, P58, P66) on the real command path.

The existing guarded work fixture owns the isolated DB, synthetic original and
real G0 project; the plan and the started task use their registered commands.
No model call, no direct native-fact insertion. Only the root checkpoint runs it.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.core.models import Outbox, Receipt, now
from pdos_next.domain.projects.forecast_refresh.models import (
    WorkForecastCurrent,
    WorkForecastRefresh,
)
from pdos_next.domain.projects.models import PlanRevision, Project, ProjectProductLink, ProjectTask
from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN, CREATE, START
from pdos_next.domain.projects.work.models import WorkCommitmentVersion
from projects.test_project_first_plan import accepted, application, cmd, proposal_command
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import original_security_work  # noqa: F401
from projects.work_pg.test_workflow import work as work  # noqa: F401

OP = "work.forecast.refresh"


def applied_plan(work):
    with flow.scoped(work) as session:
        link = session.scalar(
            select(ProjectProductLink).where(ProjectProductLink.project_id == work.project_id)
        )
        definition = (work.source["id"], str(link.definition_id))
    proposed = flow.send(work, proposal_command(work.setup, definition, str(work.project_id)))
    assert proposed.status_code == 200, proposed.text
    applied, _ = accepted(
        work.setup,
        application(work.setup, definition, str(work.project_id), proposed.json()["subject_id"]),
    )
    return applied


def forecast(work, *, actor=None, expected=200):
    response = work.setup.client.get(
        flow.root(work) + f"/projects/{work.project_id}/forecast",
        headers=flow.headers(work, actor),
    )
    assert response.status_code == expected, response.text
    return response.json()


def refresh(work, value, *, actor=None, expected=200):
    response = flow.send(work, value, actor=actor)
    assert response.status_code == expected, response.text
    return response.json()


def command(work, plan, sha):
    return cmd(
        work.setup,
        OP,
        {"project_id": str(work.project_id), "plan": plan, "expected_input_sha256": sha},
    )


def plan_ref(view):
    return view["inputs"]["plan"]


def frozen(work):
    with Session(work.setup.admin) as session:
        plan = session.scalar(
            select(PlanRevision).where(PlanRevision.project_id == work.project_id)
        )
        project = session.get(Project, work.project_id)
        promises = session.scalar(
            select(func.count())
            .select_from(WorkCommitmentVersion)
            .where(WorkCommitmentVersion.project_id == work.project_id)
        )
        return plan.forecast, project.revision, project.current_plan_id, promises


def test_refresh_writes_only_a_forecast_and_replays_by_input(work):
    applied_plan(work)
    first_view = forecast(work)
    assert first_view["current"] is None and first_view["inputs"]["changed"] is True
    before = frozen(work)
    value = command(work, plan_ref(first_view), first_view["inputs"]["input_sha256"])
    receipt = refresh(work, value)
    assert receipt["operation"] == OP and receipt["subject_type"] == "forecast_refresh"
    assert receipt["result"]["forecast_status"] == "partial"
    # Plan forecast, project revision, current plan and commitments are untouched (I08).
    assert frozen(work) == before
    with flow.scoped(work) as session:
        row = session.get(WorkForecastRefresh, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row.receipt_id == saved.id and saved.confirmation_id is None
        assert row.actor_id == row.writer_id == row.requester_id == work.setup.human
        assert row.revision == 1 and row.previous_id is None
        tasks = {task["key"]: task for task in row.result["tasks"]}
        assert tasks["eng"]["status"] == "range" and tasks["eng"]["origin"] == "estimate"
        # The NPI task has no duration estimate: unknown, never an invented date (AT-18).
        assert tasks["npi"]["finish"]["latest"] is None
        assert row.result["project_finish"]["latest"] is None
        assert row.result["calendar"]["label"] == "未扣节假日与停线"
        event = session.scalar(select(Outbox).where(Outbox.receipt_id == saved.id))
        assert event.type == "forecast.refreshed"
    current = forecast(work)
    assert current["current"]["id"] == receipt["subject_id"]
    assert current["current"]["kind"] == "system_recompute"
    assert current["inputs"]["changed"] is False
    # The same input on the same day is the same intent: replay, even under a new key.
    assert refresh(work, value) == receipt
    again = dict(value, command_id=str(uuid4()), idempotency_key=str(uuid4()))
    assert refresh(work, again)["id"] == receipt["id"]
    stale = refresh(work, command(work, plan_ref(first_view), "f" * 64), expected=409)
    assert stale["code"] == "VERSION_CONFLICT"
    assert stale["detail"]["current_input_sha256"] == first_view["inputs"]["input_sha256"]
    old_plan = {"id": plan_ref(first_view)["id"], "revision": 2}
    wrong = refresh(
        work, command(work, old_plan, first_view["inputs"]["input_sha256"]), expected=409
    )
    assert wrong["code"] == "VERSION_CONFLICT"
    with Session(work.setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkForecastRefresh)
                .where(WorkForecastRefresh.project_id == work.project_id)
            )
            == 1
        )


def test_started_task_changes_the_input_and_stays_unknown_without_remaining(work):
    setup = work.setup
    applied = applied_plan(work)
    first = forecast(work)
    refresh(work, command(work, plan_ref(first), first["inputs"]["input_sha256"]))
    with flow.scoped(work) as session:
        eng = session.scalar(
            select(ProjectTask).where(
                ProjectTask.plan_id == UUID(applied["subject_id"]), ProjectTask.key == "eng"
            )
        )
        plan_revision = session.get(PlanRevision, UUID(applied["subject_id"])).revision
        eng_id = str(eng.id)
    _, created = flow.execute(
        work,
        CREATE,
        flow.payload(
            work,
            title="Synthetic engineering verification work",
            goal="Deliver the planned engineering verification",
            outcomes=[{"key": "report", "text": "Verification report", "required": True}],
            plan_task={"id": eng_id, "revision": plan_revision},
        ),
    )
    work.task_id = UUID(created["result"]["task_id"])
    initial = flow.task(work, "proposed")
    flow.execute(
        work,
        ASSIGN,
        flow.payload(
            work, task=initial, assignee_id=str(setup.peer), recipient_id=str(setup.human)
        ),
    )
    flow.execute(
        work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=setup.peer
    )
    started_at = (now() - timedelta(hours=1)).isoformat()
    flow.execute(
        work,
        START,
        flow.payload(
            work,
            task=flow.task(work, "accepted"),
            actual_at=started_at,
            original_timezone=flow.TIMEZONE,
            calendar_id=None,
        ),
        actor=setup.peer,
    )
    second = forecast(work)
    assert second["inputs"]["changed"] is True
    assert second["inputs"]["facts"]["eng"]["start"] is not None
    assert second["inputs"]["facts"]["eng"]["finish"] is None
    before = frozen(work)
    receipt = refresh(work, command(work, plan_ref(second), second["inputs"]["input_sha256"]))
    assert receipt["subject_revision"] == 2
    assert frozen(work) == before
    with flow.scoped(work) as session:
        row = session.get(WorkForecastRefresh, UUID(receipt["subject_id"]))
        tasks = {task["key"]: task for task in row.result["tasks"]}
        assert tasks["eng"]["origin"] == "actual_and_remaining"
        assert tasks["eng"]["finish"]["latest"] is None
        assert "remaining_estimate_required" in tasks["eng"]["issues"]
        assert row.previous_revision == 1
        pointer = session.scalar(
            select(WorkForecastCurrent).where(WorkForecastCurrent.project_id == work.project_id)
        )
        assert pointer.version_id == row.id and pointer.revision == 2


def test_scope_and_database_guards(work):
    setup = work.setup
    applied_plan(work)
    view = forecast(work)
    forecast(work, actor=setup.other_human, expected=403)
    value = command(work, plan_ref(view), view["inputs"]["input_sha256"])
    outsider = flow.send(work, value, actor=setup.other_human)
    assert outsider.status_code in {401, 403}, outsider.text
    receipt = refresh(work, value)
    with Session(setup.admin) as session:
        for table in ("work_forecast_refreshes", "work_forecast_currents"):
            assert not session.scalar(
                text(f"SELECT has_table_privilege('pdos_agent','{table}','SELECT')")
            )
    with pytest.raises(DBAPIError):
        with flow.scoped(work) as session:
            session.execute(
                text("UPDATE work_forecast_refreshes SET status='complete' WHERE id=:id"),
                {"id": receipt["subject_id"]},
            )
    with pytest.raises(DBAPIError):
        with flow.scoped(work) as session:
            session.execute(
                text("DELETE FROM work_forecast_currents WHERE project_id=:id"),
                {"id": str(work.project_id)},
            )
