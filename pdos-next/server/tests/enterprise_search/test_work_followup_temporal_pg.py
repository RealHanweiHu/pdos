"""Native answer→work candidate→Human create/assign, with an offline provider.

Only root runs these guarded PG/Temporal cases. Sources and projects are created
through original public commands; no Agent ledger, task or business history is seeded.
"""
# ruff: noqa: F401,F811 -- original security/work fixtures keep their native dependency tree

import asyncio
import json
import os
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, TenantSkillEnablement
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management.models import WorkCommitmentVersion, WorkTaskVersion
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_original_security import execute as original_execute
from test_original_security import parsed, uploaded, withdraw_command
from test_original_security import preview as original_preview
from test_original_security import security_work as original_security_work
from tests.agent_kernel.test_work_state_candidates_pg import candidate as state_candidate
from tests.enterprise_search.test_action_footprint_temporal_pg import ParentClient
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.verification_action_harness import (
    VerificationClient,
    actual_runtime,
    call,
    json_messages,
    output,
    question_ready,
    start,
)
from tests.test_project_first_plan import post
from tests.test_trusted_source_work import command
from work_management_pg.test_workflow import SOURCE_LINE

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("PDOS_TEMPORAL_ADDRESS")
        or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
        reason="Explicit guarded PG, verified local Temporal and checkpoint runtime required",
    ),
    pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True),
]


class TaskClient(VerificationClient):
    """Real registered model/read calls; model output never supplies source authority."""

    def __init__(self, source, *, missing=False, extra=None):
        super().__init__(source, "synthetic-task-followup")
        self.missing, self.extra = missing, extra
        self.project_id = self.first_quote = None

    def turn(self, route, **kwargs):
        names = {value["name"] for value in kwargs["tools"]}
        if self.phase == "parent" or names == {"assistant.passage.read", "result.read"}:
            return super().turn(route, **kwargs)
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        assert "work.task.create" in names
        contexts = [
            value["context"]["work_followup_action"]
            for _row, value in json_messages(kwargs["messages"])
            if isinstance(value.get("context"), dict) and "work_followup_action" in value["context"]
        ]
        assert contexts, "Server-frozen work action must survive context projection"
        self.project_id = contexts[-1]["project_id"]
        values = [
            value for row, value in json_messages(kwargs["messages"]) if row["role"] == "tool"
        ]
        if self.step == 0:
            self.step = 1
            return call(
                "assistant.materials.read",
                {
                    "artifact_ids": [
                        self.source["artifact_id"],
                        *([self.extra["artifact_id"]] if self.extra else []),
                    ]
                },
            )
        if self.step == 1:
            self.step = 2
            return call(
                "assistant.extract",
                {"citation_ids": [row["citation_id"] for row in values[-1]["items"]]},
            )
        if self.step == 2:
            if self.missing and not self.waiting:
                self.waiting = True
                return output(
                    "needs_input",
                    questions=[
                        {
                            "id": "outcome",
                            "question": "请明确本次资料跟进需要交付什么成果？",
                            "why": "原讨论没有明确成果要求，不能用默认结果代替。",
                            "options": [],
                            "recommended": None,
                            "allow_free_text": True,
                            "depends_on": [],
                        }
                    ],
                )
            if self.missing:
                assert "提供经核对的资料包" in str(kwargs["messages"])
            self.step = 3
            self.first_quote = values[-1]["rows"][0]["quote"]
            goal = "提供经核对的资料包"
            if self.extra:
                goal += "；原生模型尝试带入未选为任务原件的私有内容：" + (
                    next(
                        row["quote"]
                        for row in values[-1]["rows"]
                        if "PRIVATE_FOLLOWUP_ONLY" in row["quote"]
                    )
                )
            self.arguments = {
                "project_id": self.project_id,
                "title": "补齐测试资料",
                "goal": goal,
                "outcomes": [
                    {
                        "key": "materials",
                        "text": ("实际资料包与原件定位；方法和判据待本人确认"),
                        "required": True,
                    }
                ],
                "sources": [
                    {
                        "kind": "artifact",
                        "id": self.source["artifact_id"],
                        "revision": self.source["expected_revision"],
                        "position": "line:1;quote_sha256:"
                        + sha256(
                            self.source["quote"].encode(),
                        ).hexdigest(),
                    }
                ],
                "reason": "根据原讨论与实际读取原件准备资料跟进",
                "plan_task": None,
                "g0_open_item": None,
            }
            return call("work.task.create", deepcopy(self.arguments))
        return output(summary="已准备资料跟进候选，等待本人核对。")


def register(setup, title, content, *, private=False):
    saved = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": content,
                "source_label": "Native synthetic task fixture",
                "visibility": "private" if private else "category",
            },
        ),
    )
    assert saved.status_code == 200, saved.text
    identity = UUID(saved.json()["subject_id"])
    index(setup, identity)
    return {
        "artifact_id": str(identity),
        "expected_revision": 1,
        "line": 1,
        "quote": content.splitlines()[0],
    }


def totals(setup):
    with Session(setup.admin) as session:
        return tuple(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.tenant_id == setup.tenant,
                )
            )
            for model in (WorkTaskVersion, WorkCommitmentVersion)
        )


async def enable(runtime):
    skill = SkillCatalog().configuration("work_management")
    command = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(runtime.person.category),
        "product_id": None,
        "operation": "ai.skill.enable",
        "expected_revision": 1,
        "source_read_set": [],
        "payload": {
            "skill_key": skill.key,
            "expected_revision": 0,
            "skill_version": skill.version,
            "skill_digest": skill.digest,
            "enabled": True,
        },
    }
    path = f"/v1/categories/{runtime.person.category}/commands"
    preview = await runtime.http.post(
        path + "/preview", headers=runtime.person.headers, json=command
    )
    assert preview.status_code == 200, preview.text
    saved = await runtime.http.post(
        path, headers=runtime.person.headers, json=preview.json()["command"]
    )
    assert saved.status_code == 200, saved.text


async def parent_answer(runtime, project):
    identity, _handle = await start(
        runtime,
        {
            "goal": "以前漏气怎么处理？",
            "idempotency_key": str(uuid4()),
            "product_id": str(runtime.person.product),
            "project_id": str(project),
        },
        accepted_statuses=("completed", "partial"),
    )
    response = await runtime.http.get(runtime.path + f"/{identity}", headers=runtime.person.headers)
    assert response.status_code == 200, response.text
    answer = response.json()["result"]["result"]["assistant"]
    assert answer["lookup"] == "cited" and answer["citation_ids"]
    return identity, answer


def payload(parent, answer, project, source, *, assignment=None, extra=None):
    return {
        "goal": "按明确来源准备资料跟进任务，缺少成果要求时请先问我。",
        "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(parent),
        "sources": [
            {"artifact_id": row["artifact_id"], "expected_revision": row["expected_revision"]}
            for row in (source, *([extra] if extra else []))
        ],
        "work_followup_action": {
            "project_id": str(project),
            "citation_ids": answer["citation_ids"],
            "assignment": assignment,
        },
    }


async def candidate(runtime, identity):
    response = await runtime.http.get(
        runtime.path + f"/{identity}/candidates", headers=runtime.person.headers
    )
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["items"] if row.get("kind") == "work_followup"]
    assert len(rows) == 1, response.text
    return rows[0]


def test_task_follows_real_answer_clarification_native_create_assign_and_fresh_work_state(
    setup,
    monkeypatch,
):
    project = create_g0_project(setup, visibility="category").project_id
    source = register(setup, "Task original", "漏气：更换密封圈；请补齐测试资料。")
    provider = TaskClient(source, missing=True)

    async def actual():
        async with actual_runtime(setup, provider, monkeypatch) as runtime:
            await enable(runtime)
            parent, answer = await parent_answer(runtime, project)
            provider.phase = "action"
            request = payload(
                parent,
                answer,
                project,
                source,
                assignment={
                    "assignee_id": str(setup.peer),
                    "recipient_id": str(setup.human),
                },
            )
            before = totals(setup)
            identity, handle = await start(runtime, request, complete=False)
            event = await question_ready(runtime, identity)
            assert event["questions"][0]["id"] == "outcome"
            assert provider.arguments is None and totals(setup) == before
            response = await runtime.http.get(
                runtime.path + f"/{identity}/candidates", headers=setup.headers
            )
            assert response.json()["items"] == []
            answered = await runtime.http.post(
                runtime.path + f"/{identity}/answers",
                headers=setup.headers,
                json={
                    "answers": {"outcome": "提供经核对的资料包"},
                    "idempotency_key": str(uuid4()),
                },
            )
            assert answered.status_code == 202, answered.text
            result = await asyncio.wait_for(handle.result(), 90)
            assert result["status"] == "completed", result
            pending = await candidate(runtime, identity)
            assert pending["state"] == "pending" and pending["receipt"] is None
            assert pending["command"]["operation"] == "work.task.create"
            assert totals(setup) == before  # Candidate preparation is never T0 execution.
            with tenant_session(
                setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
            ) as session:
                run = session.get(AgentRun, identity)
                sid = run.session_id
                assert run.read_sources[0]["artifact_id"] == source["artifact_id"]
                frozen = session.get(AgentEvent, UUID(pending["event_id"]))
                assert frozen.body["type"] == "domain_candidate"
                assert frozen.body["source"]["skill"]["key"] == "work_management"
                enabled = session.scalar(
                    select(TenantSkillEnablement).where(
                        TenantSkillEnablement.tenant_id == setup.tenant,
                        TenantSkillEnablement.skill_key == "work_management",
                    )
                )
                assert enabled.enabled and not enabled.pilot and not enabled.review_case_refs
            path = f"/v1/categories/{setup.category}/agent-sessions/{sid}/work-state"
            state = await runtime.http.get(path, headers=setup.headers)
            assert state.status_code == 200, state.text
            before_state = state.json()
            assert state_candidate(before_state, pending["event_id"])["state"] == "pending"
            calls = provider.calls
            root = f"/v1/categories/{setup.category}/products/{setup.product}"
            inputs = await runtime.http.post(
                root + "/project-work/inputs", headers=setup.headers, json=pending["command"]
            )
            assert inputs.status_code == 200, inputs.text
            assert totals(setup) == before
            route = f"/v1/categories/{setup.category}/commands"
            saved = await runtime.http.post(route, headers=setup.headers, json=pending["command"])
            assert saved.status_code == 200, saved.text
            receipt = saved.json()
            replay = await runtime.http.post(route, headers=setup.headers, json=pending["command"])
            assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
            assert totals(setup) == (before[0] + 1, before[1])
            adopted = await candidate(runtime, identity)
            assert adopted["state"] == "adopted" and adopted["task"]["id"] == receipt["subject_id"]
            fresh = await runtime.http.get(path, headers=setup.headers)
            assert fresh.status_code == 200, fresh.text
            summary = state_candidate(fresh.json(), pending["event_id"])
            assert summary["state"] == "adopted" and summary["receipt_id"] == receipt["id"]
            assert fresh.json()["revision"] == before_state["revision"]
            assert all(key not in summary for key in ("payload", "command", "source_proof"))
            workspace = await runtime.http.get(
                root + f"/project-work?project_id={project}", headers=setup.headers
            )
            current = workspace.json()
            task = next(row for row in current["tasks"] if row["id"] == receipt["subject_id"])
            assign = {
                "command_id": str(uuid4()),
                "idempotency_key": str(uuid4()),
                "operation": "work.task.assign",
                "category_id": str(setup.category),
                "product_id": str(setup.product),
                "expected_revision": current["product_revision"],
                "source_read_set": pending["command"]["source_read_set"],
                "payload": {
                    "project_id": project,
                    "task": {"id": task["id"], "revision": task["revision"]},
                    "sources": task["sources"],
                    "reason": "本人明确分派资料跟进",
                    **request["work_followup_action"]["assignment"],
                },
            }
            preview = await runtime.http.post(
                route + "/preview", headers=setup.headers, json=assign
            )
            assert preview.status_code == 200, preview.text
            assignment = await runtime.http.post(
                route, headers=setup.headers, json=preview.json()["command"]
            )
            assert assignment.status_code == 200, assignment.text
            assert totals(setup) == (before[0] + 2, before[1])
            assert (await candidate(runtime, identity))["task"]["state"] == "assigned"
            assert provider.calls == calls
            resumed = await runtime.http.post(runtime.path, headers=setup.headers, json=request)
            assert resumed.status_code == 202 and resumed.json()["run_id"] == str(identity)

    asyncio.run(actual())


def test_uncited_private_parent_source_blocks_shared_task_before_new_run(setup, monkeypatch):
    project = create_g0_project(setup, visibility="category").project_id
    public = register(setup, "Public task original", "漏气：更换密封圈；请补齐资料。")
    private = register(setup, "PRIVATE_FOLLOWUP_DISCUSSION", "漏气：更换密封圈。", private=True)
    provider = TaskClient(public)
    provider.parent = ParentClient(public["artifact_id"])

    async def actual():
        async with actual_runtime(setup, provider, monkeypatch) as runtime:
            await enable(runtime)
            parent, answer = await parent_answer(runtime, project)
            assert provider.parent.source_cids[private["artifact_id"]] not in answer["citation_ids"]
            with Session(setup.admin) as session:
                before_runs = session.scalar(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(
                        AgentRun.tenant_id == setup.tenant,
                    )
                )
            before = totals(setup)
            denied = await runtime.http.post(
                runtime.path, headers=setup.headers, json=payload(parent, answer, project, public)
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["detail"]["reason_key"] == "assistant_action_audience_widened"
            assert totals(setup) == before
            with Session(setup.admin) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AgentRun)
                        .where(
                            AgentRun.tenant_id == setup.tenant,
                        )
                    )
                    == before_runs
                )

    asyncio.run(actual())


def test_explicit_child_read_of_new_private_b_cannot_enter_a_shared_task_candidate(
    setup, monkeypatch
):
    project = create_g0_project(setup, visibility="category").project_id
    public = register(setup, "Public task original", "漏气：更换密封圈；请补齐资料。")
    provider = TaskClient(public)

    async def actual():
        async with actual_runtime(setup, provider, monkeypatch) as runtime:
            await enable(runtime)
            parent, answer = await parent_answer(runtime, project)
            private = register(
                setup, "Private child task context", "PRIVATE_FOLLOWUP_ONLY", private=True
            )
            provider.extra = private
            provider.phase = "action"
            before = totals(setup)
            identity, _handle = await start(
                runtime,
                payload(parent, answer, project, public, extra=private),
                accepted_statuses=("completed", "partial"),
            )
            assert "PRIVATE_FOLLOWUP_ONLY" in provider.arguments["goal"]
            with tenant_session(
                setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
            ) as session:
                run = session.get(AgentRun, identity)
                assert {row["artifact_id"] for row in run.read_sources} == {
                    public["artifact_id"],
                    private["artifact_id"],
                }  # B is a genuine explicit Human read, not a forged provider escape.
                assert [ref["id"] for ref in provider.arguments["sources"]] == [
                    public["artifact_id"]
                ]
                assert not list(
                    session.scalars(
                        select(AgentEvent).where(
                            AgentEvent.run_id == identity,
                            AgentEvent.body["type"].astext == "domain_candidate",
                        )
                    )
                )
            response = await runtime.http.get(
                runtime.path + f"/{identity}/candidates", headers=setup.headers
            )
            assert response.status_code == 200 and response.json()["items"] == []
            assert totals(setup) == before

    asyncio.run(actual())


def test_native_original_withdrawal_blocks_the_already_prepared_human_create(
    setup,
    original_security_work,
    monkeypatch,
):
    security = original_security_work
    project = create_g0_project(setup, visibility="private")
    original_id = uploaded(security, content=(SOURCE_LINE + "\n").encode(),
                           visibility="category")
    artifact_id = parsed(security, original_id)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        target = session.get(Project, UUID(project.project_id))
        assert target.visibility == "private" and target.owner_id == setup.human
    work = SimpleNamespace(setup=setup, project_id=UUID(project.project_id),
                           original_id=original_id, security=security,
                           source={"id": str(artifact_id)})
    discussion = register(setup, "Task discussion", "漏气：更换密封圈；请补齐资料。")
    source = {
        "artifact_id": work.source["id"],
        "expected_revision": 1,
        "quote": SOURCE_LINE,
        "line": 1,
    }
    index(setup, UUID(source["artifact_id"]))
    provider = TaskClient(source)
    provider.parent = ParentClient(discussion["artifact_id"])

    async def actual():
        async with actual_runtime(setup, provider, monkeypatch) as runtime:
            await enable(runtime)
            parent, answer = await parent_answer(runtime, work.project_id)
            provider.phase = "action"
            identity, _handle = await start(
                runtime, payload(parent, answer, work.project_id, source)
            )
            pending = await candidate(runtime, identity)
            assert pending["state"] == "pending"
            before = totals(setup)
            prepared = original_preview(
                work.security, withdraw_command(work.security, work.original_id)
            )
            withdrawn = original_execute(work.security, prepared)
            assert withdrawn.status_code == 200, withdrawn.text
            root = f"/v1/categories/{setup.category}/products/{setup.product}"
            for path in (
                root + "/project-work/inputs",
                f"/v1/categories/{setup.category}/commands",
            ):
                denied = await runtime.http.post(
                    path, headers=setup.headers, json=pending["command"]
                )
                assert denied.status_code in {403, 409}, denied.text
            assert (await candidate(runtime, identity))["state"] == "unavailable"
            assert totals(setup) == before

    asyncio.run(actual())
