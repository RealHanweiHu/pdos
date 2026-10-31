"""Actual native T1 grant → admitted Run → no-model Activity; root runs PG only.

Private project/status facts are created by native commands, not inserted or
rewritten. The only fixture mutation is the explicit category-read revocation.
"""
# ruff: noqa: F401 -- actual fixture dependency tree is intentionally re-exported

import os
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from pdos_next import personal_summary_runtime
from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.database import tenant_session
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management.constants import STATUS
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.service import digest
from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work
from tests.work_management_pg.test_workflow import work as work_case


@pytest.fixture
def summary_work(request):
    work = request.getfixturevalue("work_case")
    setup = work.setup
    g0 = create_g0_project(
        setup, visibility="private", name="本人私有摘要项目",
        purpose="Actual ordinary owner-only personal summary source",
    )
    line = "Synthetic private summary evidence, registered for the actual new product."
    original = flow.uploaded(work.security, content=(line + "\n").encode(), visibility="category")
    artifact = flow.parsed(work.security, original)
    source = {"kind": "artifact", "id": str(artifact), "revision": 1,
              "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest()}
    private = SimpleNamespace(**{**vars(work), "project_id": UUID(g0.project_id),
                                 "source": source, "original_id": original})
    _, receipt = flow.execute(private, STATUS, flow.payload(
        private, fact_summary="具名登记：私有项目材料已核对。",
        next_steps="等待原记录中具名办理；不自行判定健康度。", task_refs=[],
    ))
    return SimpleNamespace(work=private, setup=setup, receipt=receipt)


def admit(summary_work):
    setup, work = summary_work.setup, summary_work.work
    wallet = _ready(setup)
    spec = _spec(setup, wallet)
    spec["personal_summary"] = {
        "followed_project_ids": [str(work.project_id)], "groups": ["following"],
        "category_ids": [str(setup.category)], "max_items": 20,
    }
    rule, ref = _activate(setup, spec)
    service_runtime.tick(setup.engine, ref)
    with Session(setup.admin) as session:
        attempt = session.scalar(select(AutomationServiceAttempt).where(
            AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"]),
            AutomationServiceAttempt.state == "admitted",
        ))
        assert attempt is not None
        run = session.get(AgentRun, attempt.run_id)
        assert run.trigger == "automation_service" and run.state == "queued"
        envelope = {"tenant_id": str(run.tenant_id), "category_id": str(run.category_id),
                    "actor_id": str(run.writer_id), "requester_id": str(run.requester_id),
                    "subject_id": str(run.id)}
    return rule, envelope


def kernel(summary_work, monkeypatch):
    setup = summary_work.setup
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    return KernelActivities(
        setup.engine, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
        technical_engine=setup.dispatch,
    )


def saved(summary_work, envelope):
    setup = summary_work.setup
    with Session(setup.admin) as session:
        run = session.get(AgentRun, UUID(envelope["subject_id"]))
        assert run.used_tokens == run.held_tokens == 0
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == run.id,
        )) == 0
        result = run.result
        events = session.scalar(select(func.count()).select_from(AgentEvent).where(
            AgentEvent.run_id == run.id,
        ))
        return result, events


def checked(summary_work, envelope):
    setup = summary_work.setup
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category,
                        read_snapshot=True) as session:
        run = session.get(AgentRun, UUID(envelope["subject_id"]))
        # Match the public endpoint's visible_run precondition: revoked category
        # READ can hide the Run itself before any stored-result hook is entered.
        if run is None or run.requester_id != setup.ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "运行不在当前可读范围。", 403)
        return personal_summary_runtime.checked_result(session, setup.ctx, run)


def summary_feed(setup):
    response = setup.client.get(
        "/v1/personal/inbox/summaries?page_size=1", headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["version"] == "personal-summary-feed/v1"
    assert page["principal_id"] == str(setup.human)
    return page


def mark_summary_read(setup, item):
    payload = {
        "kind": "run", "target_id": item["run_id"], "expected_revision": 0,
        "observed_token": item["reading_token"], "mark_read": True,
        "archived": False, "followed": False, "request_key": str(uuid4()),
    }
    response = setup.client.post(
        "/v1/personal/inbox/states", headers=setup.headers, json=payload,
    )
    assert response.status_code == 200, response.text
    stored = response.json()
    assert stored["kind"] == "run" and stored["target_id"] == item["run_id"]
    assert stored["read_through"] == item["reading_token"] and stored["revision"] == 1
    # A lost acknowledgement is retried with the original native request key.
    retry = setup.client.post(
        "/v1/personal/inbox/states", headers=setup.headers, json=payload,
    )
    assert retry.status_code == 200 and retry.json() == stored
    states = setup.client.get("/v1/personal/inbox/states", headers=setup.headers)
    assert states.status_code == 200, states.text
    assert stored in states.json()["items"]


def test_actual_no_model_activity_reads_owner_private_source_and_keeps_repeat_result(
    summary_work, monkeypatch,
):
    setup, work = summary_work.setup, summary_work.work
    _rule, envelope = admit(summary_work)
    before = flow.snapshots(work)
    # Native private audience is requester-bound; the admitted writer/owner pair
    # can read what that owner can read while both category grants remain live.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                        requester_id=setup.human, category_id=setup.category) as session:
        assert session.scalar(select(Project.id).where(
            Project.id == work.project_id,
        )) == work.project_id
    # The same background identity alone has no private-owner audience.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                        requester_id=setup.agent, category_id=setup.category) as session:
        assert session.scalar(select(Project.id).where(Project.id == work.project_id)) is None
    worker = kernel(summary_work, monkeypatch)
    monkeypatch.setattr("pdos_next.agent_kernel.activities.activity.heartbeat", lambda *_a: None)
    first = worker.advance(envelope)
    assert first == {"run_id": envelope["subject_id"], "status": "completed"}
    result, events = saved(summary_work, envelope)
    summary = result["result"]["personal_summary"]
    assert summary["principal_id"] == str(setup.human) and summary["model_used"] is False
    assert summary["groups"][0]["id"] == "following"
    item, = summary["groups"][0]["items"]
    assert item["object"]["project_id"] == str(work.project_id) and item["health"] is None
    assert item["object"]["version_id"] == summary_work.receipt["subject_id"]
    assert item["next_step"]["responsible"] is None
    assert item["next_step"]["recorded_by"]["id"] == str(setup.human)
    assert result["result"]["delivery"]["state"] == "available_in_inbox"
    assert checked(summary_work, envelope) == result
    public = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{envelope['subject_id']}",
        headers=setup.headers,
    )
    assert public.status_code == 200, public.text
    assert public.json()["result"] == result
    page = summary_feed(setup)
    item, = page["items"]
    assert item["run_id"] == envelope["subject_id"]
    assert item["category_id"] == str(setup.category)
    assert item["status"] == "completed" and item["reading_token"] == "completed:0"
    assert "result" not in item and "summary" not in item and "facts" not in item
    assert "私有项目材料已核对" not in str(page)
    mark_summary_read(setup, item)
    assert worker.advance(envelope) == first
    assert saved(summary_work, envelope) == (result, events)
    assert flow.snapshots(work) == before
    # The original version remains authorized after a new named record. History
    # must retain its original body rather than replace it with the current one.
    flow.execute(work, STATUS, flow.payload(
        work, fact_summary="另一具名更新：请新查询核对。",
        next_steps="新记录的下一步。", task_refs=[],
    ))
    assert checked(summary_work, envelope) == result
    assert digest(saved(summary_work, envelope)[0]) == digest(result)


def test_actual_owner_revocation_hides_persisted_summary(summary_work, monkeypatch):
    _rule, envelope = admit(summary_work)
    worker = kernel(summary_work, monkeypatch)
    monkeypatch.setattr("pdos_next.agent_kernel.activities.activity.heartbeat", lambda *_a: None)
    assert worker.advance(envelope)["status"] == "completed"
    result, _events = saved(summary_work, envelope)
    setup = summary_work.setup
    item, = summary_feed(setup)["items"]
    assert item["run_id"] == envelope["subject_id"]
    with Session(setup.admin) as session, session.begin():
        session.execute(update(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.category_id == setup.category,
            Grant.principal_id == setup.human,
        ).values(expires_at=now() - timedelta(seconds=1)))
    with pytest.raises(DomainError) as error:
        checked(summary_work, envelope)
    assert error.value.code == "FORBIDDEN_SCOPE"
    public = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{envelope['subject_id']}",
        headers=setup.headers,
    )
    assert public.status_code == 403 and "私有项目材料已核对" not in public.text
    assert summary_feed(setup)["items"] == []
    assert saved(summary_work, envelope)[0] == result  # hiding never edits history


def test_actual_cancelled_summary_run_cannot_append_result(summary_work, monkeypatch):
    _rule, envelope = admit(summary_work)
    setup = summary_work.setup
    worker = kernel(summary_work, monkeypatch)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        cancelled = cancel_run(session, setup.ctx, UUID(envelope["subject_id"]))
    assert cancelled["status"] == "cancelled"
    assert worker.advance(envelope)["status"] == "cancelled"
    assert saved(summary_work, envelope)[0] is None
