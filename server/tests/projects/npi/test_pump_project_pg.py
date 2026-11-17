from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.agent.kernel.skills import SkillCatalog
from pdos_next.core.dispatch.outbox import Envelope
from pdos_next.core.models import Outbox
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.npi.continuation import queue
from pdos_next.errors import DomainError
from tests.projects.npi.test_framework import FRAMEWORK
from tests.projects.test_project_first_plan import accepted, cmd, post


def framework_command(setup, operation, payload):
    command = cmd(setup, operation, payload)
    command["product_id"] = None
    return command


def test_g0_pins_published_framework_and_t1_rejects_redline_gap(setup, engines):
    admin, _, _ = engines
    with Session(admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human, active=True))
    draft, _ = accepted(
        setup,
        framework_command(
            setup,
            "work.framework.draft",
            {
                "project_type": "new_product",
                "expected_framework_revision": 0,
                "framework": FRAMEWORK,
                "reason": "隔离合成汽车充气泵框架草稿",
            },
        ),
    )
    published, _ = accepted(
        setup,
        framework_command(
            setup,
            "work.framework.publish",
            {
                "project_type": "new_product",
                "expected_framework_revision": 1,
                "framework_id": draft["subject_id"],
                "action": "publish",
                "reason": "隔离验证具名发布",
            },
        ),
    )
    skill = SkillCatalog().configuration("work_management")
    accepted(
        setup,
        framework_command(
            setup,
            "ai.skill.enable",
            {
                "skill_key": "work_management",
                "expected_revision": 0,
                "enabled": True,
                "skill_version": skill.version,
                "skill_digest": skill.digest,
            },
        ),
    )
    project = create_g0_project(setup)
    with Session(admin) as s:
        assert (
            str(s.get(Project, UUID(str(project.project_id))).framework_id)
            == published["subject_id"]
        )
        event = s.scalar(
            select(Outbox).where(
                Outbox.tenant_id == setup.tenant,
                Outbox.type == "project.created",
                Outbox.subject_id == UUID(str(project.project_id)),
            )
        )
    envelope = Envelope(
        event_id=str(event.id),
        tenant_id=str(event.tenant_id),
        category_id=str(event.category_id),
        product_id=None,
        subject_id=str(event.subject_id),
        subject_revision=event.subject_revision,
        event_type=event.type,
        schema_version=event.schema_version,
        correlation_id=str(event.correlation_id),
        lease_id=str(uuid4()),
        actor_id=str(event.actor_id),
        requester_id=str(setup.peer),
    )
    _, app, _ = engines
    run = queue(app, envelope)
    assert run is not None
    assert queue(app, envelope) == run
    root = f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project.project_id}"
    response = setup.client.get(root + "/npi", headers=setup.headers)
    assert response.status_code == 200, response.text
    npi = response.json()
    assert npi["path"] == "full"
    assert npi["generation"]["run_id"] == run["subject_id"]
    assert npi["framework"]["id"] == published["subject_id"]

    tasks, basis, milestones = [], {}, {}
    for stage in npi["stages"]:
        outcomes = [o for o in npi["outcomes"] if o["stage"] == stage["key"]]
        if not outcomes:
            continue
        key = "task_" + stage["key"]
        tasks.append({"key": key, "title": outcomes[0]["name"], "discipline": "npi"})
        basis[key] = {
            "role": outcomes[0]["role"],
            "deliverable": outcomes[0]["name"],
            "outcome_keys": [o["key"] for o in outcomes],
            "sources": [
                {
                    "kind": "framework_outcome",
                    "id": published["subject_id"],
                    "revision": 2,
                    "key": o["key"],
                }
                for o in outcomes
            ],
        }
        milestones[stage["key"]] = key
    tasks[0]["depends_on"] = ["review_controls"]
    tasks.append({"key": "review_controls", "title": "核对泵控制逻辑", "discipline": "engineering"})
    basis["review_controls"] = {
        "role": "software",
        "deliverable": "控制逻辑核对记录",
        "outcome_keys": [],
        "sources": [
            next(item["ref"] for item in npi["sources"] if item["ref"]["kind"] == "definition")
        ],
    }
    payload = {
        "project_id": str(project.project_id),
        "expected_project_revision": 1,
        "draft": {
            "project_id": str(project.project_id),
            "expected_project_revision": 1,
            "reason": "隔离合成汽车充气泵计划",
            "schedule": {
                "start": "2026-11-16T01:00:00Z",
                "tasks": tasks,
                "calendar": {
                    "version": "ignored",
                    "timezone": "UTC",
                    "working_weekdays": [0],
                    "intervals": [{"start_minute": 0, "end_minute": 60}],
                },
            },
            "npi": {
                "framework_id": published["subject_id"],
                "framework_revision": 2,
                "tasks": basis,
                "milestones": milestones,
            },
        },
    }
    invalid = deepcopy(payload)
    invalid["draft"]["npi"]["tasks"]["task_pvt"]["outcome_keys"] = []
    rejected = post(setup, cmd(setup, "work.plan.apply", invalid), True)
    assert rejected.status_code == 422, rejected.text
    assert any(i["code"] == "REDLINE_UNCOVERED" for i in rejected.json()["detail"]["issues"])

    bootstrap = app._pdos_category_candidate_owner
    scope = bootstrap.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=UUID(run["subject_id"]),
    )
    spec = bootstrap.registry.get("work.plan.apply")
    for intent in ("synthetic-bad-plan-1", "synthetic-bad-plan-1", "synthetic-bad-plan-2"):
        with pytest.raises(DomainError, match="框架检查"):
            bootstrap.prepare_candidate(scope, spec, invalid, intent)
    with pytest.raises(DomainError, match="两次框架检查未通过"):
        bootstrap.prepare_candidate(scope, spec, payload, "synthetic-third-plan")
    stopped = setup.client.get(root + "/npi", headers=setup.headers).json()["generation"]
    assert len(stopped["failures"]) == 2 and stopped["candidate"] is None
    cancelled = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{run['subject_id']}/cancel",
        headers=setup.headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    retry = {"expected_project_revision": 1, "previous_run_id": run["subject_id"]}
    resumed = setup.client.post(root + "/npi/retry", headers=setup.headers, json=retry)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run_id"] != run["subject_id"]
    replay = setup.client.post(root + "/npi/retry", headers=setup.headers, json=retry)
    assert replay.json()["run_id"] == resumed.json()["run_id"]

    command = cmd(setup, "work.plan.apply", payload)
    result, verified = accepted(setup, command)
    assert post(setup, verified).json()["id"] == result["id"]
    assert len(result["result"]["task_ids"]) == len(tasks)
    overview = setup.client.get(root, headers=setup.headers).json()["items"][0]
    assert overview["plan"]["forecast"]["calendar_basis"]["basis"] == "weekdays_estimate"
    assert overview["tasks"][0]["forecast"]["role"]

    team = setup.client.get(root + "/team", headers=setup.headers).json()
    updated_team = setup.client.post(
        root + "/team",
        headers=setup.headers,
        json={
            "expected_revision": team["revision"],
            "request_key": str(uuid4()),
            "changes": [
                {
                    "action": "set_roles",
                    "principal_id": str(setup.peer),
                    "roles": [{"key": "test_engineering"}],
                }
            ],
        },
    )
    assert updated_team.status_code == 200, updated_team.text
    evt = next(task for task in overview["tasks"] if task["forecast"]["key"] == "task_evt")
    source = {
        "project_id": str(project.project_id),
        "sources": [],
        "reason": "合成泵任务验证",
        "plan_task": {"id": evt["id"], "revision": 1},
        "title": evt["forecast"]["title"],
        "goal": evt["forecast"]["deliverable"],
        "outcomes": [{"key": "performance_report", "text": "泵性能报告", "required": True}],
    }
    creation_cmd = cmd(setup, "work.task.create", source)
    new_task = post(setup, creation_cmd)
    assert new_task.status_code == 200, new_task.text
    assert post(setup, creation_cmd).json()["id"] == new_task.json()["id"]
    assert post(setup, cmd(setup, "work.task.create", source)).json()["id"] == new_task.json()["id"]
    second_intent = cmd(setup, "work.task.create", {**source, "reason": "尝试重复建立同一执行任务"})
    assert post(setup, second_intent).status_code == 409
    task_ref = {"id": new_task.json()["subject_id"], "revision": 1}
    assign_payload = {
        "project_id": str(project.project_id),
        "sources": [],
        "reason": "按测试工程角色分派",
        "task": task_ref,
        "assignee_id": str(setup.peer),
        "recipient_id": str(setup.human),
    }
    rejected = post(
        setup,
        cmd(
            setup,
            "work.task.assign",
            {
                **assign_payload,
                "assignee_id": str(setup.human),
            },
        ),
        True,
    )
    assert rejected.status_code == 403, rejected.text
    assignment, _ = accepted(setup, cmd(setup, "work.task.assign", assign_payload))
    assert assignment["operation"] == "work.task.assign"
    work_route = f"/v1/categories/{setup.category}/products/{setup.product}/project-work"
    work_read = work_route + f"?project_id={project.project_id}"
    assert setup.client.get(work_read, headers=setup.headers).json()["commitments"] == []
    accept = cmd(
        setup,
        "work.task.accept",
        {
            "project_id": str(project.project_id),
            "sources": [],
            "reason": "本人承接及确认日期",
            "task": {**task_ref, "revision": 2},
            "promise": {"promised_at": "2026-12-03T12:00:00Z", "original_timezone": "UTC"},
        },
    )
    assert post(setup, accept, True).status_code == 403
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    command_path = f"/v1/categories/{setup.category}/commands"
    preview = setup.client.post(command_path + "/preview", headers=peer_headers, json=accept)
    assert preview.status_code == 200, preview.text
    recorded = setup.client.post(command_path, headers=peer_headers, json=preview.json()["command"])
    assert recorded.status_code == 200, recorded.text
    work = setup.client.get(work_read, headers=setup.headers).json()
    assert work["tasks"][0]["state"] == "accepted"
    assert work["tasks"][0]["checked_plan_source"]["task"] == source["plan_task"]
    assert work["commitments"][0]["promisor_id"] == str(setup.peer)
    assert work["commitments"][0]["receipt_id"] != recorded.json()["id"]

    adoption, _ = accepted(
        setup,
        cmd(
            setup,
            "work.stage.adopt",
            {
                "project_id": str(project.project_id),
                "expected_project_revision": 2,
                "expected_governance_revision": 0,
                "template": "framework",
                "reason": "采用已核对的阶段路径",
            },
        ),
    )
    assert adoption["operation"] == "work.stage.adopt"
    baseline = post(
        setup,
        cmd(
            setup,
            "work.baseline.approve",
            {
                "project_id": str(project.project_id),
                "expected_project_revision": 2,
                "expected_governance_revision": 1,
                "reason": "验证规格冻结顺序",
                "plan": {"id": result["subject_id"], "revision": 1},
            },
        ),
        True,
    )
    assert baseline.status_code == 409, baseline.text
    assert "规格冻结" in baseline.json()["message"]

    catalog = setup.client.get("/v1/role-catalog", headers=setup.headers).json()
    deletion = setup.client.post(
        "/v1/role-catalog",
        headers=setup.headers,
        json={
            "expected_revision": catalog["revision"],
            "request_key": str(uuid4()),
            "roles": [role for role in catalog["roles"] if role["key"] != "software"],
        },
    )
    assert deletion.status_code == 409, deletion.text
    assert deletion.json()["detail"]["role_keys"] == ["software"]

    governance = setup.client.get(root + "/governance", headers=setup.headers)
    assert governance.status_code == 200, governance.text
    stage_id = governance.json()["current_stage"]["id"]
    new_framework = deepcopy(FRAMEWORK)
    new_framework["outcomes"].append(
        {
            "key": "serial_trace",
            "stage": "pvt",
            "name": "试产追溯批号",
            "role": "quality",
            "redline": True,
        }
    )
    draft, _ = accepted(
        setup,
        framework_command(
            setup,
            "work.framework.draft",
            {
                "project_type": "new_product",
                "framework": new_framework,
                "expected_framework_revision": 2,
                "reason": "新增试产追溯红线",
            },
        ),
    )
    published2, _ = accepted(
        setup,
        framework_command(
            setup,
            "work.framework.publish",
            {
                "project_type": "new_product",
                "framework_id": draft["subject_id"],
                "expected_framework_revision": 3,
                "action": "publish",
                "reason": "隔离合成新版发布",
            },
        ),
    )
    fixed = setup.client.get(root + "/npi", headers=setup.headers).json()
    assert fixed["framework"]["id"] == published["subject_id"]
    assert fixed["new_framework"]["id"] == published2["subject_id"]
    assert fixed["differences"][0]["key"] == "serial_trace"
    with pytest.raises(IntegrityError, match="Framework upgrade requires"):
        with Session(admin) as s, s.begin():
            s.execute(
                text("UPDATE projects SET framework_id=:framework WHERE id=:project"),
                {
                    "framework": published2["subject_id"],
                    "project": str(project.project_id),
                },
            )

    change = deepcopy(payload["draft"])
    change.update(expected_project_revision=2, base_plan_id=result["subject_id"])
    change["npi"].update(framework_id=published2["subject_id"], framework_revision=4)
    for task in change["npi"]["tasks"].values():
        for source in task["sources"]:
            if source["kind"] == "framework_outcome":
                source.update(id=published2["subject_id"], revision=4)
    assert post(setup, cmd(setup, "work.plan.propose", change)).status_code == 422
    pvt = change["npi"]["tasks"]["task_pvt"]
    pvt["outcome_keys"].append("serial_trace")
    pvt["sources"].append(
        {
            "kind": "framework_outcome",
            "id": published2["subject_id"],
            "revision": 4,
            "key": "serial_trace",
        }
    )
    candidate = post(setup, cmd(setup, "work.plan.propose", change))
    assert candidate.status_code == 200, candidate.text
    assert (
        setup.client.get(root + "/npi", headers=setup.headers).json()["framework"]
        == fixed["framework"]
    )
    upgrade, verified_upgrade = accepted(
        setup,
        cmd(
            setup,
            "work.plan.apply",
            {
                "project_id": str(project.project_id),
                "expected_project_revision": 2,
                "proposal_id": candidate.json()["subject_id"],
            },
        ),
    )
    assert post(setup, verified_upgrade).json()["id"] == upgrade["id"]
    assert upgrade["result"]["framework_upgrade"]["to"]["id"] == published2["subject_id"]
    updated = setup.client.get(root + "/npi", headers=setup.headers).json()
    assert updated["framework"]["id"] == published2["subject_id"]
    stages = setup.client.get(root + "/governance", headers=setup.headers).json()
    assert stages["current_stage"]["id"] == stage_id
    assert stages["baseline"] is None
    assert stages["gate"]["framework_review"]["redlines"][0]["key"] == "serial_trace"
