"""Deterministic forecast composition (D47, P82 D181 fixed case, AT-18/19); no DB.

The D181 case: A slips 6 days, B 3 days and C 3 days. Only each task's own
successors move; C's slip is absorbed by float because Z still waits for L.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from pdos_next.domain.projects.forecast_refresh.inputs import (
    NO_CALENDAR_LABEL,
    Inputs,
    compute,
)
from pdos_next.domain.projects.planning.scheduling import schedule
from pdos_next.schemas.planning import ScheduleInput

DAY = 480  # one 09:00-17:00 working day in minutes
START = "2026-11-02T01:00:00Z"  # Monday 09:00 Asia/Shanghai


def plan_input(**durations):
    base = {"A": 2 * DAY, "B": 2 * DAY, "C": DAY, "L": 6 * DAY, "X": DAY, "Y": DAY, "Z": DAY}
    base.update(durations)
    depends = {"X": ["A"], "Y": ["B"], "Z": ["L", "C"]}
    return ScheduleInput.model_validate(
        {
            "start": START,
            "calendar": {
                "version": "synthetic-weekday@1",
                "timezone": "Asia/Shanghai",
                "working_weekdays": [0, 1, 2, 3, 4],
                "intervals": [{"start_minute": 540, "end_minute": 1020}],
            },
            "tasks": [
                {
                    "key": key,
                    "title": f"Synthetic task {key}",
                    "discipline": "engineering",
                    "depends_on": depends.get(key, []),
                    "duration_min_minutes": minutes,
                    "duration_max_minutes": minutes,
                    "estimate_source": "Synthetic fixed estimate",
                }
                for key, minutes in base.items()
            ],
        }
    )


def inputs(current, baseline, *, facts=None, commitments=(), as_of=START):
    planned = schedule(baseline).model_dump(mode="json")
    plan = SimpleNamespace(id=uuid4(), revision=1, forecast=planned)
    return Inputs(
        plan=plan,
        proposal=None,
        schedule=current,
        task_ids={task.key: uuid4() for task in current.tasks},
        facts=facts or {},
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")),
        as_of_day="2026-11-02",
        input_sha256="0" * 64,
        commitments=list(commitments),
    )


def finish(result, key):
    row = next(row for row in result["tasks"] if row["key"] == key)
    return datetime.fromisoformat(row["finish"]["earliest"].replace("Z", "+00:00")), row


def local(day, hour=17):
    # Shanghai local 17:00 on 2026-11-<day> is 09:00 UTC.
    return datetime(2026, 11, day, hour - 8, tzinfo=UTC)


def test_d181_slips_reach_only_their_own_successors_and_float_absorbs_c():
    baseline = plan_input()
    delayed = plan_input(A=8 * DAY, B=5 * DAY, C=4 * DAY)
    before = baseline.model_dump(mode="json")
    result = compute(inputs(delayed, baseline))
    assert baseline.model_dump(mode="json") == before
    # X follows A: planned Wed 4th, now Thu 12th. Y follows B: Wed 4th -> Mon 9th.
    assert finish(result, "X")[0] == local(12)
    assert finish(result, "Y")[0] == local(9)
    # Z still waits for the on-time L (Mon 9th) and finishes Tue 10th as planned.
    z_finish, z = finish(result, "Z")
    assert z_finish == local(10) and z["shift_minutes"] == 0
    assert finish(result, "X")[1]["shift_minutes"] > finish(result, "Y")[1]["shift_minutes"] > 0
    # C's three-day slip stays inside its float (four working days against the new
    # finish set by A -> X); only A -> X is critical.
    _, c = finish(result, "C")
    assert c["working_float_minutes"] == 4 * DAY and c["critical"] is False
    assert result["float_status"] == "calculated"
    assert result["critical_path"] == ["A", "X"]
    assert result["status"] == "complete"
    assert result["project_finish"]["earliest"] == result["project_finish"]["latest"]
    assert result["calendar"]["label"] == NO_CALENDAR_LABEL


def test_unknown_duration_stays_unknown_instead_of_an_invented_date():
    current = plan_input()
    tasks = [
        task.model_copy(update={"duration_max_minutes": None}) if task.key == "B" else task
        for task in current.tasks
    ]
    current = current.model_copy(update={"tasks": tuple(tasks)})
    result = compute(inputs(current, plan_input()))
    _, b = finish(result, "B")
    _, y = finish(result, "Y")
    assert b["finish"]["latest"] is None and y["finish"]["latest"] is None
    assert result["project_finish"]["latest"] is None and result["status"] == "partial"
    assert result["float_status"] == "not_calculated" and result["critical_path"] == []


def test_actual_finish_fixes_a_task_and_releases_its_successor_at_that_time():
    current = plan_input()
    facts = {
        "A": {
            "start": "2026-11-02T01:00:00+00:00",
            "finish": "2026-11-02T05:00:00+00:00",
            "work_tasks": [],
        }
    }
    result = compute(inputs(current, current, facts=facts))
    _, a = finish(result, "A")
    assert a["origin"] == "actual_anchor" and a["status"] == "exact"
    x_row = next(row for row in result["tasks"] if row["key"] == "X")
    assert x_row["start"]["earliest"].startswith("2026-11-02T05:00:00")


def test_started_task_without_a_remaining_estimate_is_unknown():
    current = plan_input()
    facts = {
        "A": {
            "start": "2026-11-02T01:00:00+00:00",
            "finish": None,
            "work_tasks": [
                {
                    "task_id": str(uuid4()),
                    "version_id": str(uuid4()),
                    "revision": 4,
                    "state": "in_progress",
                    "start": "2026-11-02T01:00:00+00:00",
                    "finish": None,
                    "timezone": "Asia/Shanghai",
                }
            ],
        }
    }
    result = compute(inputs(current, current, facts=facts))
    a = next(row for row in result["tasks"] if row["key"] == "A")
    assert a["origin"] == "actual_and_remaining" and a["finish"]["latest"] is None
    assert "remaining_estimate_required" in a["issues"]
    assert result["status"] == "partial"


def test_forecast_later_than_a_commitment_is_shown_and_the_commitment_is_kept():
    baseline = plan_input()
    delayed = plan_input(A=8 * DAY)
    commitments = [
        {
            "commitment_id": "c1",
            "task_id": "t1",
            "plan_task_id": None,
            "key": "X",
            "promised_at": "2026-11-05T09:00:00+00:00",
            "fulfilled": False,
        },
        {
            "commitment_id": "c2",
            "task_id": "t2",
            "plan_task_id": None,
            "key": "Z",
            "promised_at": "2026-11-20T09:00:00+00:00",
            "fulfilled": False,
        },
        {
            "commitment_id": "c3",
            "task_id": "t3",
            "plan_task_id": None,
            "key": "Y",
            "promised_at": None,
            "fulfilled": False,
        },
    ]
    result = compute(inputs(delayed, baseline, commitments=commitments))
    impacts = {row["commitment_id"]: row["impact"] for row in result["commitments"]}
    assert impacts == {"c1": "later", "c2": "within", "c3": "unknown"}
    kept = {row["commitment_id"]: row["promised_at"] for row in result["commitments"]}
    assert kept["c1"] == "2026-11-05T09:00:00+00:00"
    assert "承诺都不变" in result["effect"]
