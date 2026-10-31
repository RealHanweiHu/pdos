"""CTX-04's synthetic forecast, written only through native Human commands.

The explicit seven-day calendar is a fixture estimate, not a real organization
calendar or a commitment. Source prose never becomes a fabricated tool result.
"""

from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post

from pdos_next.domain.projects.schemas import PlanProposePayload
from pdos_next.domain.projects.service import calculate
from pdos_next.domain.work_management.models import WorkCommitmentVersion
from pdos_next.models import Principal
from tests.work_management_pg import test_workflow as flow

TITLES = {"pressure": "接头耐压复验", "humidity": "密封圈湿热复验"}
UNKNOWN_DURATION = {"DURATION_MIN_UNKNOWN", "DURATION_MAX_UNKNOWN"}


def proposal_payload(project_id, revision):
    return {
        "project_id": str(project_id), "expected_project_revision": revision,
        "reason": "CTX04 合成计划预测，仅建议不承诺；七日日历仅供本题原生回放。",
        "schedule": {
            "start": "2026-11-08T01:00:00Z",
            "calendar": {
                "key": "ctx04-synthetic-seven-day", "version": "ctx04-seven-day@1",
                "timezone": "Asia/Shanghai", "working_weekdays": list(range(7)),
                "intervals": [{"start_minute": 540, "end_minute": 720},
                              {"start_minute": 780, "end_minute": 1020}],
            },
            "tasks": [
                {"key": "pressure", "title": TITLES["pressure"],
                 "discipline": "engineering", "duration_min_minutes": 60,
                 "duration_max_minutes": 60,
                 "estimate_source": "CTX04 合成负责人估计；建议日期，不是承诺"},
                {"key": "humidity", "title": TITLES["humidity"],
                 "discipline": "engineering"},
            ],
        },
    }


def assert_forecast(tasks):
    """Both the production pure calculation and native saved forecast must agree."""
    assert set(tasks) == set(TITLES)
    pressure, humidity = tasks["pressure"], tasks["humidity"]
    for field in ("earliest_finish", "latest_finish"):
        assert pressure[field] == "2026-11-08T02:00:00Z"
        assert humidity[field] is None
    assert pressure["unknown_reasons"] == []
    assert set(humidity["unknown_reasons"]) == UNKNOWN_DURATION


def native_plan(work):
    setup = work.setup
    path = flow.root(work) + f"/projects/{work.project_id}"

    def read():
        response = setup.client.get(path, headers=setup.headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["has_more"] is False and result["unavailable_count"] == 0
        assert [row["id"] for row in result["items"]] == [str(work.project_id)]
        return result["items"][0]

    before = read()
    assert before["plan"] is None
    payload = proposal_payload(work.project_id, before["revision"])
    forecast = calculate(PlanProposePayload.model_validate(payload))
    assert_forecast({row["key"]: row for row in forecast["tasks"]})
    propose = cmd(setup, "work.plan.propose", payload)
    propose["source_read_set"] = before["required_source_read_set"]
    saved = post(setup, propose)
    assert saved.status_code == 200, saved.text
    proposed = saved.json()
    assert proposed["operation"] == "work.plan.propose"
    candidate = read()
    assert candidate["plan"] is None and candidate["revision"] == before["revision"]
    assert [row["id"] for row in candidate["proposals"]] == [proposed["subject_id"]]
    apply = cmd(setup, "work.plan.apply", {
        "project_id": str(work.project_id), "proposal_id": proposed["subject_id"],
        "expected_project_revision": candidate["revision"],
    })
    apply["source_read_set"] = candidate["required_source_read_set"]
    applied, _ = accepted(setup, apply)
    assert applied["operation"] == "work.plan.apply"
    current = read()
    plan = current["plan"]
    assert plan["id"] == applied["subject_id"]
    assert plan["proposal_id"] == proposed["subject_id"]
    assert current["revision"] == before["revision"] + 1
    assert plan["forecast"] == forecast
    assert current["timeline"]["commitment"] is None
    tasks = {row["key"]: row for row in current["tasks"]}
    assert_forecast({key: row["forecast"] for key, row in tasks.items()})
    assert {row["id"] for row in tasks.values()} == set(applied["result"]["task_ids"])
    return {"id": plan["id"], "revision": plan["revision"], "tasks": tasks,
            "project_revision": current["revision"], "forecast": forecast,
            "calendar": plan["input_snapshot"]["calendar"],
            "proposal_id": proposed["subject_id"],
            "propose_receipt_id": proposed["id"], "apply_receipt_id": applied["id"]}


def assert_native_tasks(work, plan, latest_receipts, facts):
    """Compare actual provider input against ordinary native API/DB reads."""
    assert facts["version"] == "project-current-facts/v2"
    assert facts["project_revision"] == plan["project_revision"]
    assert facts["complete"] is True and facts["missing"] == []
    assert facts["tasks_has_more"] is False
    assert facts["commitments"] == [] and facts["commitments_has_more"] is False
    workspace = flow.workspace(work)
    assert workspace["commitments"] == []
    actual = {row["title"]: row for row in workspace["tasks"]}
    assert set(actual) == set(TITLES.values())
    tasks = {row["title"]: row for row in facts["tasks"]}
    assert set(tasks) == set(TITLES.values()) and len(facts["tasks"]) == 2
    with flow.scoped(work) as session:
        peer = session.get(Principal, work.setup.peer)
        assert peer is not None and peer.kind == "human"
        peer_name = peer.name
        count = session.scalar(select(func.count()).select_from(WorkCommitmentVersion).where(
            WorkCommitmentVersion.tenant_id == work.setup.tenant,
            WorkCommitmentVersion.category_id == work.setup.category,
            WorkCommitmentVersion.product_id == work.setup.product,
            WorkCommitmentVersion.project_id == work.project_id,
        ))
        assert count == 0
    for key, title in TITLES.items():
        row, native, receipt = tasks[title], actual[title], latest_receipts[key]
        assert row["task_id"] == native["id"] == receipt["result"]["task_id"]
        assert row["reference"]["kind"] == "work_task"
        assert row["reference"]["id"] == native["version_id"] == receipt["subject_id"]
        assert row["reference"]["revision"] == native["revision"]
        assert row["reference"]["receipt_id"] == receipt["id"]
        assert row["reference"] in facts["references"]
        assert row["record_status"] == native["state"]
        assert native["state"] == ("assigned" if key == "pressure" else "proposed")
        assert row["assignee_id"] == native["assignee_id"] == (
            str(work.setup.peer) if key == "pressure" else None)
        assert row["assignee_name"] == (peer_name if key == "pressure" else None)
        assert native["plan_task"] == {
            "id": plan["tasks"][key]["id"], "revision": plan["revision"]}
        assert row["commitments"] == [] and row["commitments_has_more"] is False
        projected = row["plan"]
        assert projected["state"] == "available" and projected["date_nature"] == "forecast"
        for reference, kind, identity in (
            (projected["task_reference"], "plan_task", plan["tasks"][key]["id"]),
            (projected["plan_reference"], "plan", plan["id"]),
        ):
            assert (reference["kind"], reference["id"], reference["revision"],
                    reference["receipt_id"]) == (kind, identity, plan["revision"], None)
            assert "project=" + str(work.project_id) in reference["url"]
            assert reference in facts["references"]
        assert "promised_at" not in row and "promised_at" not in projected
        expected = plan["tasks"][key]["forecast"]
        for field in ("earliest_finish", "latest_finish", "unknown_reasons"):
            assert projected[field] == expected[field]
    assert_forecast({key: tasks[title]["plan"] for key, title in TITLES.items()})
    return {"tasks": facts["tasks"], "commitment_versions": count,
            "assignee_alias_basis": "题内周柯映射到实际合成人员ID；不把项目owner当负责人",
            "actual_assignee_name": peer_name}
