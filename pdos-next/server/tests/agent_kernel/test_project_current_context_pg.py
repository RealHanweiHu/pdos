"""Actual native project records→bounded context/readback; root runs isolated PG only."""

# ruff: noqa: F401, F811 -- reuse the native command fixture tree, no fact inserts

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.project_current_context import KEY
from pdos_next.agent_kernel.types import AgentOutput
from pdos_next.database import tenant_session
from pdos_next.domain.work_management.constants import STATUS
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, cmd, post
from tests.agent_kernel.test_run_continuation import scope as api_scope
from tests.agent_kernel.test_run_continuation import start as api_start
from tests.agent_kernel.test_transactions import run as create_read_run
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work
from tests.work_management_pg.test_workflow import work as project_work


def prepare(work):
    setup = work.setup
    _, receipt = flow.execute(work, STATUS, flow.payload(
        work, fact_summary="具名登记：品质结果仍待补录。", next_steps="核对结果后办理阶段评审。",
        task_refs=[],
    ))
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{work.project_id}/governance",
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    adopt = cmd(setup, "work.stage.adopt", {
        "project_id": str(work.project_id), "expected_project_revision": 1,
        "expected_governance_revision": 0, "template": "small-change@1",
        "reason": "具名采用合成项目阶段，未知保留。",
    })
    adopt["source_read_set"] = response.json()["gate"]["required_source_read_set"]
    accepted(setup, adopt)
    return receipt


def start(work):
    return create_read_run(work.setup, product_id=work.setup.product, project_id=work.project_id)


def test_actual_current_project_context_has_named_status_native_unknown_gate_and_no_lookup_claim(
    project_work,
):
    work, setup = project_work, project_work.setup
    receipt = prepare(work)
    store, scope = start(work)
    owner = Bootstrap(setup.engine)
    host = BoundHost(store, owner.adapters())
    result = host.skill_context(scope, "这个项目为什么还没进入DVT？", bindings=())
    current = result["context"]["project"]["current_facts"]
    assert current["named_status"]["reference"]["receipt_id"] == receipt["id"]
    assert current["named_status"]["actor_id"] == str(setup.human)
    assert current["named_status"]["fact_summary"] == "具名登记：品质结果仍待补录。"
    assert current["governance"]["current_stage"]["key"] == "planning"
    assert current["governance"]["gate"]["state"] == "UNKNOWN"
    assert current["governance"]["gate"]["checks"][0]["detail"] == "当前计划尚无适用的批准基线"
    assert current["plan"]["state"] == "not_created"
    assert current["plan"]["latest_finish"] is None and current["as_of"]
    assert all("project=" + str(work.project_id) in ref["url"] for ref in current["references"])
    assert flow.SOURCE_LINE not in str(current)
    output = owner.verify_result(scope, AgentOutput(
        status="completed", summary="当前仍为计划阶段，当前计划尚无适用的批准基线。",
    ).model_dump(mode="json"), [])
    answer = output["result"]["assistant"]
    assert "lookup" not in answer and answer["project_basis"]["as_of"] == current["as_of"]
    assert "sources" not in answer and "citation_ids" not in answer
    with store.transaction(scope) as (_, run):
        assert "customer_original" in run.data_categories
        assert run.read_sources == [] and result["context"]["sources"] == []
        assert any(ref["artifact_id"] == work.source["id"]
                   for ref in run.versions[KEY]["source_proof"])
        assert "fact_summary" not in str(run.versions[KEY])
    owner.check_conversation(scope)


@pytest.mark.parametrize("explicit", [False, True])
def test_native_project_footprint_does_not_expand_d3_explicit_evidence_search(
    project_work, explicit,
):
    """Real Human StartInput and ordinary-RLS adapter; no manufactured tool READ."""
    work, setup = project_work, project_work.setup
    prepare(work)
    selected = [{"artifact_id": work.source["id"], "expected_revision": 1}] if explicit else []
    identity, _ = api_start(setup, product_id=str(setup.product),
                            project_id=str(work.project_id), sources=selected)
    scope = api_scope(setup, identity)
    owner = Bootstrap(setup.engine)
    context = owner.project_context(scope, "按项目当前记录核对，保持本人原件选择。")
    assert context["project"]["current_facts"]["named_status"]["state"] == "available"
    expected = {work.source["id"]} if explicit else set()
    assert {ref["artifact_id"] for ref in context["sources"]} == expected
    # Exercise the registered adapter's actual SQL/RLS contract without forging
    # a model response, ReadSource, ToolCall row or execution receipt.
    evidence = DomainReads(owner.store, owner.commands).call(scope, {"query": ""},
                                                           name="evidence.search")
    assert {item["artifact_id"] for item in evidence["items"]} == expected
    with owner.store.transaction(scope) as (session, run):
        assert "customer_original" in run.data_categories
        assert any(ref["artifact_id"] == work.source["id"]
                   for ref in run.versions[KEY]["source_proof"])
        assert {ref["artifact_id"] for ref in run.read_sources} == expected
        assert list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == identity,
        ))) == []
    owner.check_conversation(scope)


def test_actual_native_update_requires_fresh_current_context_but_history_is_preserved(project_work):
    from pdos_next.agent_kernel.project_current_context import checked_result

    work, setup = project_work, project_work.setup
    prepare(work)
    store, scope = start(work)
    owner = Bootstrap(setup.engine)
    host = BoundHost(store, owner.adapters())
    host.skill_context(scope, "为什么还没进入DVT？", bindings=())
    output = owner.verify_result(scope, {
        "status": "completed", "summary": "原具名记录中的未补录事项。",
        "result": {}, "questions": [], "unfinished": [],
    }, [])
    store.finish(scope, output)
    _, receipt = flow.execute(work, STATUS, flow.payload(
        work, fact_summary="新的具名记录：下一步仍需本人核对。", next_steps="不代替阶段决定。",
        task_refs=[],
    ))
    with pytest.raises(DomainError) as changed:
        owner.check_conversation(scope)
    assert changed.value.code == "SOURCE_STALE"
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        run = session.get(AgentRun, scope.run_id)
        history = checked_result(session, setup.ctx, run, run.result)
        assert history["summary"] == output["summary"]
        assert history["result"]["assistant"]["project_basis"]["currentness"] == "updated"
    next_store, next_scope = start(work)
    current = Bootstrap(setup.engine).project_context(next_scope, "读取最新项目记录")
    assert current["project"]["current_facts"]["named_status"]["reference"]["receipt_id"] == (
        receipt["id"]
    )
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.category_id == setup.category, Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as denied:
        Bootstrap(setup.engine).project_context(next_scope, "不应再暴露原项目")
    assert denied.value.code == "FORBIDDEN_SCOPE"
    response = setup.client.get(f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}",
                                headers=setup.headers)
    assert response.status_code == 403 and output["summary"] not in response.text
