"""D71/D190 follow-up and D75 deterministic templates as the project owner's attention.

Every business fact goes through its registered command. To cross “one working day”
without a fake server clock, the only direct change is moving one recorded version's
`created_at` back a week on the isolated superuser connection (triggers off for that
statement). Reads are checked to be side-effect free. No model is called.
"""

# ruff: noqa: F811 - imported fixtures intentionally register their dependency tree

from datetime import UTC, datetime, timedelta
from uuid import UUID

from my_work.attention_pg.test_work import page
from sqlalchemy import text

from pdos_next.core.models import now
from pdos_next.domain.projects.work import business_days
from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN, COMMIT, CREATE, START
from projects.external_wait_pg import test_workflow as waits
from projects.fulfillment_pg import test_workflow as fulfillment
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import (
    original_security_work,  # noqa: F401
    work,  # noqa: F401
)

LABEL = "按周一至周五估算，未扣节假日与停线"


def backdate(work, table, key, identity, revision=None, days=7):
    clause = f"{key}=:identity" + (" AND revision=:revision" if revision is not None else "")
    with work.setup.admin.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        moved = connection.execute(
            text(
                f"UPDATE public.{table} SET created_at=created_at-make_interval(days=>:days) "
                f"WHERE tenant_id=:tenant AND {clause}"
            ),
            {
                "days": days,
                "tenant": work.setup.tenant,
                "identity": identity,
                "revision": revision,
            },
        )
        assert moved.rowcount == 1


def decide(work, actor=None):
    return {item["id"]: item for item in page(work, "decide", actor=actor)["items"]}


def step(work, operation, *, actor=None, **fields):
    return flow.execute(work, operation, flow.payload(work, **fields), actor=actor)[1]


def test_sql_weekday_twin_matches_python_and_is_app_only(work):
    start = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)
    cases = [
        (start + timedelta(hours=7 * i + 3), count, zone)
        for i in range(40)
        for count in (0, 1, 2, 5)
        for zone in ("Asia/Shanghai", "UTC", "Europe/Berlin")
    ]
    with work.setup.engine.connect() as connection:
        for instant, count, zone in cases:
            actual = connection.scalar(
                text("SELECT public.work_weekday_add(:at, :days, :zone)"),
                {"at": instant, "days": count, "zone": zone},
            )
            assert actual == business_days.add_weekdays(instant, count, zone), (
                instant,
                count,
                zone,
            )
    with work.setup.admin.connect() as connection:
        rights = connection.execute(
            text(
                "SELECT r, has_function_privilege(r, "
                "'public.work_weekday_add(timestamptz,integer,text)', 'EXECUTE') "
                "FROM unnest(ARRAY['pdos_next_app','pdos_agent','pdos_next_auth',"
                "'pdos_next_dispatch']) r"
            )
        ).all()
        assert dict(rights) == {
            "pdos_next_app": True,
            "pdos_agent": False,
            "pdos_next_auth": False,
            "pdos_next_dispatch": False,
        }


def test_unanswered_and_not_progressed_are_separate_owner_clocks(work):
    setup = work.setup
    created = step(
        work,
        CREATE,
        title="Synthetic follow-up drawing",
        goal="Deliver a named traceable drawing",
        outcomes=[{"key": "drawing", "text": "Actual drawing", "required": True}],
        plan_task=None,
    )
    task_id = UUID(created["result"]["task_id"])
    work.task_id = task_id
    assigned = step(
        work,
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    unanswered = f"followup_unanswered:{task_id}"
    not_progressed = f"followup_not_progressed:{task_id}"
    assert unanswered not in decide(work)  # Not yet one working day.

    backdate(work, "work_task_versions", "task_id", task_id, assigned["subject_revision"])
    items = decide(work)
    item = items[unanswered]
    assert not_progressed not in items
    assert item["kind"] == "followup_unanswered" and item["state"] == "assigned"
    assert item["source"]["id"] == str(task_id) and item["target"] == "project"
    assert item["responsibility"] == "project_owner_followup"
    assert item["blocked"] is None and LABEL in item["reason"]
    details = item["details"]
    assert details["rule"] == "followup_unanswered" and details["assignee_id"] == str(setup.peer)
    assert details["basis_label"] == LABEL and details["model_calls"] is False
    assert "task_id" not in details  # Never folds the owner's own task rows (my-work dedupe).
    # Only the project owner is escalated to; the assignee sees nothing here.
    assert unanswered not in decide(work, actor=setup.peer)

    accepted = step(work, ACCEPT, task=fulfillment._task_ref(assigned), actor=setup.peer)
    items = decide(work)
    # Accepting answers the assignment; the not-progressed clock starts fresh.
    assert unanswered not in items and not_progressed not in items

    backdate(work, "work_task_versions", "task_id", task_id, accepted["subject_revision"])
    items = decide(work)
    assert unanswered not in items
    assert items[not_progressed]["state"] == "accepted"
    assert "“收到”不算推进" in items[not_progressed]["reason"]

    due = now() + timedelta(hours=2)
    step(
        work,
        COMMIT,
        task=fulfillment._task_ref(accepted),
        actor=setup.peer,
        recipient_id=str(setup.human),
        outcome_keys=["drawing"],
        promised_at=due.isoformat(),
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        replaces=None,
    )
    promise = next(i for k, i in decide(work).items() if k.startswith("commitment_due:"))
    assert promise["details"]["phase"] == "due_soon"
    assert promise["details"]["promisor_id"] == str(setup.peer)
    assert abs(datetime.fromisoformat(promise["due_at"]) - due) < timedelta(seconds=1)

    step(
        work,
        START,
        task=fulfillment._task_ref(accepted),
        actor=setup.peer,
        **flow.clock_fields(),
    )
    items = decide(work)
    assert not_progressed not in items and unanswered not in items
    # Starting is progress, but the promise is still due and unsubmitted.
    assert any(key.startswith("commitment_due:") for key in items)


def test_owner_is_not_escalated_to_themself(work):
    created = step(
        work,
        CREATE,
        title="Synthetic owner task",
        goal="Owner's own deliverable",
        outcomes=[{"key": "note", "text": "Actual note", "required": True}],
        plan_task=None,
    )
    task_id = UUID(created["result"]["task_id"])
    assigned = step(
        work,
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(work.setup.human),
        recipient_id=str(work.setup.peer),
    )
    backdate(work, "work_task_versions", "task_id", task_id, assigned["subject_revision"])
    assert f"followup_unanswered:{task_id}" not in decide(work)


def test_external_wait_past_its_check_without_reply_escalates_to_the_owner(work):
    setup = work.setup
    record = waits.create_record()
    record["next_check_at"] = (now() - timedelta(days=7)).isoformat()
    _, receipt = waits.execute(work, record, actor=setup.peer)
    wait_id = receipt["result"]["wait_id"]
    key = f"external_wait_overdue:{wait_id}"
    item = decide(work)[key]
    assert item["kind"] == "external_wait_overdue" and LABEL in item["reason"]
    assert item["details"]["wait_responsible_id"] == str(setup.peer)
    assert item["details"]["next_check_is_internal"] is True
    # The responsible person keeps their own “等外部回复” item, not this escalation.
    assert key not in decide(work, actor=setup.peer)
    row = waits.waiting(work, wait_id, actor=setup.peer)
    waits.execute(
        work,
        {
            "action": "reply",
            "status": "received",
            "at": now().isoformat(),
            "text": "Actual synthetic reply record",
            "original_timezone": waits.TIMEZONE,
        },
        wait=waits.reference(row),
        actor=setup.peer,
    )
    assert key not in decide(work)
