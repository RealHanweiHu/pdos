"""Native project facts remain fixed history roots without a Tool READ.

Root runs these only on its verified isolated pdos_test. Business writes use the
existing Human APIs; summaries are synthetic, with no provider or quality score.
"""

# ruff: noqa: F401, F811 -- explicit pytest fixture imports are intentional

import os
from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_original_security import execute as original_post
from test_original_security import preview as original_preview
from test_original_security import withdraw_command

from pdos_next.agent_kernel import conversation_acl as acl
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.project_current_context import KEY
from pdos_next.agent_kernel.types import AgentOutput
from pdos_next.domain.projects.models import Project
from pdos_next.models import OriginalSecurity
from tests.agent_kernel.test_project_work_task_context_pg import (
    create_task,
    original_security_work,
    project_facts,
    project_work,
    tasks,
)
from tests.agent_kernel.test_run_continuation import scope as api_scope
from tests.agent_kernel.test_run_continuation import start as api_start
from tests.work_management_pg import test_workflow as flow

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                               reason="root-owned verified isolated pdos_test required")


def completed_project_context(work):
    # project_facts calls actual BoundHost.skill_context and persists its typed
    # context snapshot. No provider or registered Tool READ participates.
    scope, bootstrap, facts = project_facts(work)
    output = bootstrap.verify_result(scope, AgentOutput(
        status="completed", summary="合成历史：两项复验；日期为预测，湿热负责人和日期未登记。",
    ).model_dump(mode="json"), [])
    bootstrap.store.finish(scope, output)
    with flow.scoped(work) as session:
        row = session.get(AgentRun, scope.run_id)
        assert row is not None and row.state == "completed" and row.read_sources == []
        assert list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == row.id,
        ))) == []
        assert any("project" in snapshot["fields"] for snapshot in
                   row.versions["context_snapshots"].values())
        assert output["result"]["assistant"]["project_basis"]["references"] == facts["references"]
        original = {"goal": row.goal, "summary": row.result["summary"],
                    "project_revision": session.get(Project, work.project_id).revision,
                    "project_binding": deepcopy(row.versions[KEY])}
        access = acl.manifests(session, [row])
        assert acl.classify(session, access) == {str(row.id): "current"}
    return scope, bootstrap, facts, access, original


def classify(work, access):
    with flow.scoped(work) as session:
        return acl.classify(session, access)


def unchanged_original(work, identity, original):
    # Revocation may hide the Run under ordinary RLS. This test-only, read-only
    # inspection verifies retention; it grants no product access or execution.
    with Session(work.setup.admin) as session:
        row = session.get(AgentRun, identity)
        assert row.goal == original["goal"] and row.result["summary"] == original["summary"]
        assert row.versions[KEY] == original["project_binding"]


def test_carried_project_facts_supply_fixed_source_task_and_plan_roots_without_tool_reads(tasks):
    work = tasks
    scope, _, facts, access, original = completed_project_context(work)
    manifest = access[str(scope.run_id)]
    deps = manifest["dependencies"]
    assert manifest["unverified"] == [] and manifest["citations"] == []
    assert len(manifest["projects"]) == 1
    assert manifest["projects"][0]["project_id"] == str(work.project_id)
    assert manifest["projects"][0]["metadata_snapshot"] == (
        original["project_binding"]["metadata_snapshot"])
    proof = original["project_binding"]["source_proof"]
    assert work.source["id"] in {ref["artifact_id"] for ref in proof}
    for ref in proof:
        assert {"kind": "artifact", "id": ref["artifact_id"],
                "version": ref["expected_revision"], "content_hash": ref["content_hash"]} in deps
    assert {task["task_id"] for task in facts["tasks"]} == {
        str(work.pressure_id), str(work.humidity_id)}
    for task in facts["tasks"]:
        reference = task["reference"]
        assert acl.dependency("work_task", reference["id"], reference["revision"]) in deps
        assert acl.dependency("receipt", reference["receipt_id"]) in deps
        plan = task["plan"]
        assert plan["state"] == "available" and plan["date_nature"] == "forecast"
        assert acl.dependency("plan_task", plan["task_reference"]["id"]) in deps
        assert acl.dependency("plan", plan["plan_reference"]["id"],
                              plan["plan_reference"]["revision"]) in deps
    assert classify(work, access) == {str(scope.run_id): "current"}
    unchanged_original(work, scope.run_id, original)


def test_native_task_append_marks_old_history_updated_and_continuation_reads_fresh_tasks(tasks):
    work, setup = tasks, tasks.setup
    scope, bootstrap, _, access, original = completed_project_context(work)
    frozen = deepcopy(access)
    third_id, receipt = create_task(work, "第三项原生复验，旧回答不被改写")
    with flow.scoped(work) as session:
        assert session.get(Project, work.project_id).revision == original["project_revision"]
    assert classify(work, access) == {str(scope.run_id): "updated"}
    assert access == frozen
    assert acl.dependency("work_task", receipt["subject_id"], receipt["subject_revision"]) not in (
        access[str(scope.run_id)]["dependencies"])
    child, _ = api_start(setup, continue_from_run_id=str(scope.run_id),
                         goal="继续核对当前三项任务，保留上轮的原始回答。")
    bound = api_scope(setup, child)
    current = BoundHost(bootstrap.store, bootstrap.adapters()).skill_context(
        bound, "继续核对当前三项任务，保留上轮的原始回答。", bindings=(),
    )["context"]
    fresh = current["project"]["current_facts"]
    assert len(fresh["tasks"]) == 3 and str(third_id) in {
        task["task_id"] for task in fresh["tasks"]}
    previous = next(turn for turn in current["conversation"]["turns"]
                    if turn["run_id"] == str(scope.run_id))
    assert previous["goal"] == original["goal"] and previous["outcome_state"] == "updated"
    assert previous["historical_outcome"]["summary"] == original["summary"]
    assert "资料已更新" in str(previous["historical_outcome"]["notes"])
    assert previous["sources"] == []
    bootstrap.check_conversation(bound)
    unchanged_original(work, scope.run_id, original)


def test_native_original_withdrawal_hides_fixed_project_history_but_retains_old_summary(tasks):
    work = tasks
    scope, _, _, access, original = completed_project_context(work)
    frozen = deepcopy(access)
    with flow.scoped(work) as session:
        epoch = session.scalar(select(OriginalSecurity.epoch).where(
            OriginalSecurity.original_id == work.original_id))
    assert type(epoch) is int
    prepared = original_preview(work.security, withdraw_command(
        work.security, work.original_id, expected_epoch=epoch))
    response = original_post(work.security, prepared)
    assert response.status_code == 200, response.text
    assert classify(work, access) == {str(scope.run_id): "hidden"}
    assert access == frozen
    unchanged_original(work, scope.run_id, original)


def test_first_native_named_status_marks_known_empty_project_history_updated(tasks):
    work = tasks
    scope, _, facts, access, original = completed_project_context(work)
    assert facts["named_status"]["state"] == "not_recorded"
    assert facts["named_status"]["reference"] is None
    _, receipt = flow.execute(work, flow.STATUS, flow.payload(
        work, fact_summary="首次具名登记：复验结果仍待补录。",
        next_steps="本人核对原始结果后继续，不把预测变成承诺。", task_refs=[],
    ))
    with flow.scoped(work) as session:
        assert session.get(Project, work.project_id).revision == original["project_revision"]
    assert classify(work, access) == {str(scope.run_id): "updated"}
    _, _, fresh = project_facts(work)
    assert fresh["named_status"]["state"] == "available"
    assert fresh["named_status"]["reference"]["id"] == receipt["subject_id"]
    assert fresh["named_status"]["reference"]["receipt_id"] == receipt["id"]
    assert UUID(fresh["named_status"]["actor_id"]) == work.setup.human
    unchanged_original(work, scope.run_id, original)
