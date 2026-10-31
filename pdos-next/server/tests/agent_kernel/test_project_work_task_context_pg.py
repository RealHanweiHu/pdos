"""Native task/plan facts and ordinary-RLS metadata; root alone runs isolated PG.

No provider, embeddings, Temporal or direct business-fact inserts. Domain writes
use the actual inputs/preview/command path; tampering checks roll back rejection.
"""

# ruff: noqa: F401, F811 -- pytest's explicit native fixture tree

import os
from copy import copy, deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import event, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_original_security import execute as original_post
from test_original_security import preview as original_preview
from test_original_security import withdraw_command
from test_project_first_plan import accepted, cmd, post

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.project_current_context import KEY, KIND, _link, checked_result
from pdos_next.agent_kernel.project_work_task_context import collect
from pdos_next.agent_kernel.types import AgentOutput
from pdos_next.domain.projects.models import ProjectTask
from pdos_next.domain.work_management import owner
from pdos_next.domain.work_management.models import WorkTaskVersion
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from tests.agent_kernel.test_run_continuation import scope as api_scope
from tests.agent_kernel.test_run_continuation import start as api_start
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work
from tests.work_management_pg.test_workflow import work as project_work

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                               reason="root-owned verified isolated pdos_test required")


def create_task(work, title, *, plan=None):
    _, receipt = flow.execute(work, flow.CREATE, flow.payload(
        work, title=title, goal="仅登记实际合成复验工作，预测与承诺分开。",
        outcomes=[{"key": "review", "text": "复验原记录", "required": True}], plan_task=plan,
    ))
    return UUID(receipt["result"]["task_id"]), receipt


@pytest.fixture
def tasks(project_work):
    work, setup = project_work, project_work.setup
    proposed = post(setup, cmd(setup, "work.plan.propose", {
        "project_id": str(work.project_id), "expected_project_revision": 1,
        "reason": "具名登记两个合成计划任务，未知工时保留。",
        "schedule": {"start": "2026-11-08T01:00:00Z", "calendar": {
            "version": "project-work-context@1", "timezone": "Asia/Shanghai",
            "working_weekdays": list(range(7)),
            "intervals": [{"start_minute": 540, "end_minute": 1020}],
        }, "tasks": [
            {"key": "pressure", "title": "接头耐压复验", "discipline": "engineering",
             "duration_min_minutes": 60, "duration_max_minutes": 60,
             "estimate_source": "合成项目负责人登记的一小时预测，不是日期承诺。"},
            {"key": "humidity", "title": "密封圈湿热复验", "discipline": "npi"},
        ]},
    }, work.source["id"]))
    assert proposed.status_code == 200, proposed.text
    applied, _ = accepted(setup, cmd(setup, "work.plan.apply", {
        "project_id": str(work.project_id), "proposal_id": proposed.json()["subject_id"],
        "expected_project_revision": 1,
    }, work.source["id"]))
    with flow.scoped(work) as session:
        actual = {row.key: row for row in session.scalars(select(ProjectTask).where(
            ProjectTask.project_id == work.project_id,
            ProjectTask.plan_id == UUID(applied["subject_id"]),
        ))}
        refs = {key: {"id": str(row.id), "revision": applied["subject_revision"]}
                for key, row in actual.items()}
    work.pressure_id, _ = create_task(work, "接头耐压复验", plan=refs["pressure"])
    work.humidity_id, _ = create_task(work, "密封圈湿热复验", plan=refs["humidity"])
    work.task_id = work.pressure_id
    flow.execute(work, flow.ASSIGN, flow.payload(
        work, task=flow.task(work, "proposed"), assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    ))
    work.plan_id = applied["subject_id"]
    return work


def project_facts(work):
    setup = work.setup
    identity, _ = api_start(setup, product_id=str(setup.product), project_id=str(work.project_id),
                            goal="按当前项目权威任务核对负责人、预测与承诺。")
    scope = api_scope(setup, identity)
    bootstrap = Bootstrap(setup.engine)
    host = BoundHost(bootstrap.store, bootstrap.adapters())
    context = host.skill_context(scope, "核对当前项目任务", bindings=())["context"]
    return scope, bootstrap, context["project"]["current_facts"]


def measured(work):
    statements = []

    def counted(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", counted)
    try:
        with flow.scoped(work) as session:
            project = owner.project(session, work.setup.ctx, work.setup.product, work.project_id)
            value = collect(session, work.setup.ctx, project, link=lambda *args: _link(
                project, *args, tab="work",
            ).model_dump())
        return value, statements
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", counted)


def test_actual_current_task_plan_unknown_and_peer_receipt_match_owner_guards(tasks):
    work, setup = tasks, tasks.setup
    flow.execute(work, flow.ACCEPT, flow.payload(work, task=flow.task(work, "assigned")),
                 actor=setup.peer)
    _, commitment = flow.execute(work, flow.COMMIT, flow.payload(
        work, task=flow.task(work, "accepted"), recipient_id=str(setup.human),
        outcome_keys=["review"], promised_at="2026-11-10T02:00:00Z",
        original_timezone="Asia/Shanghai", calendar_id=None, replaces=None,
    ), actor=setup.peer)
    current, statements = measured(work)
    tasks_by_id = {task.task_id: task for task in current[0]}
    pressure, humidity = tasks_by_id[str(work.pressure_id)], tasks_by_id[str(work.humidity_id)]
    assert pressure.record_status == "accepted" and pressure.assignee_id == str(setup.peer)
    assert pressure.plan.latest_finish == "2026-11-08T02:00:00Z"
    assert pressure.plan.date_nature == "forecast" and pressure.plan.state == "available"
    assert pressure.commitments[0].reference.receipt_id == commitment["id"]
    assert pressure.commitments[0].promised_at.startswith("2026-11-10")
    assert humidity.assignee_id is None and humidity.plan.latest_finish is None
    assert humidity.plan.unknown_reasons and humidity.commitments == []
    assert not current[6] and {row["artifact_id"] for row in current[3]} == {work.source["id"]}
    assert all(sum(marker in sql for sql in statements) == 1 for marker in (
        "project_work_task_heads", "project_work_commitment_heads", "project_work_receipt_groups"))
    with flow.scoped(work) as session:
        for ref in current[2]:
            if ref["kind"] == "work_task":
                row = session.get(WorkTaskVersion, UUID(ref["id"]))
                owner.retained(session, setup.ctx, setup.product, row)
                owner.sources_current(session, setup.ctx, setup.product, row.source_basis)
    _, _, actual = project_facts(work)
    assert actual["version"] == KIND and len(actual["tasks"]) == 2
    assert work.source["position"] not in str(actual)
    assert flow.SOURCE_LINE not in str(actual)


def test_actual_metadata_query_count_does_not_grow_with_task_count(tasks):
    work = tasks
    before, first = measured(work)
    create_task(work, "第三条独立待办，不更改已登记两条")
    after, second = measured(work)
    assert len(before[0]) == 2 and len(after[0]) == 3
    assert len(first) == len(second)
    assert before[-1]["tasks"]["items"] != after[-1]["tasks"]["items"]


def test_native_task_version_update_preserves_old_answer_and_refreshes_current_facts(tasks):
    work, setup = tasks, tasks.setup
    scope, bootstrap, current = project_facts(work)
    output = bootstrap.verify_result(scope, AgentOutput(
        status="completed", summary="当时耐压任务已分派；计划日期为预测，尚无承诺。",
    ).model_dump(mode="json"), [])
    bootstrap.store.finish(scope, output)
    with flow.scoped(work) as session:
        old_run = session.get(AgentRun, scope.run_id)
        before = deepcopy(old_run.versions[KEY]["metadata_snapshot"])
    flow.execute(work, flow.ACCEPT, flow.payload(work, task=flow.task(work, "assigned")),
                 actor=setup.peer)
    with pytest.raises(DomainError) as changed:
        bootstrap.project_context(scope, "不能静默把已冻结任务换成新版本。")
    assert changed.value.code == "SOURCE_STALE"
    with flow.scoped(work) as session:
        row = session.get(AgentRun, scope.run_id)
        restored = checked_result(session, setup.ctx, row, row.result)
        assert restored["summary"] == output["summary"]
        assert restored["result"]["assistant"]["project_basis"]["currentness"] == "updated"
    new_scope, _, newer = project_facts(work)
    actual = next(task for task in newer["tasks"] if task["task_id"] == str(work.pressure_id))
    assert actual["record_status"] == "accepted"
    assert actual["reference"]["revision"] == 3
    with flow.scoped(work) as session:
        new = session.get(AgentRun, new_scope.run_id).versions[KEY]["metadata_snapshot"]
        assert before["project_revision"] == new["project_revision"]
        assert before["tasks"] != new["tasks"]


def test_actual_source_withdrawal_blocks_frozen_context_and_canonical_source_guard(tasks):
    work, setup = tasks, tasks.setup
    scope, bootstrap, _ = project_facts(work)
    with flow.scoped(work) as session:
        fixed = deepcopy(session.scalar(select(WorkTaskVersion).where(
            WorkTaskVersion.task_id == work.pressure_id,
            WorkTaskVersion.revision == 2,
        )).source_basis)
    prepared = original_preview(work.security, withdraw_command(work.security, work.original_id))
    withdrawn = original_post(work.security, prepared)
    assert withdrawn.status_code == 200, withdrawn.text
    with flow.scoped(work) as session, pytest.raises(DomainError) as canonical:
        owner.sources_current(session, setup.ctx, setup.product, fixed)
    assert canonical.value.code == "SOURCE_UNAVAILABLE"
    with pytest.raises(DomainError) as actual:
        bootstrap.project_context(scope, "已撤回原件不应再出站。")
    assert actual.value.code == "SOURCE_UNAVAILABLE"


def test_actual_ordinary_work_fact_tampering_is_rejected_without_changing_projection(tasks):
    work = tasks
    before = measured(work)[0]
    identity = UUID(before[0][0].reference.id)
    with pytest.raises(DBAPIError), flow.scoped(work) as session:
        session.execute(update(WorkTaskVersion).where(WorkTaskVersion.id == identity).values(
            body={"forged": "not a native fact"},
        ))
        session.flush()
    after = measured(work)[0]
    assert [task.model_dump() for task in before[0]] == [task.model_dump() for task in after[0]]


def test_scope_grant_loss_cannot_reveal_task_context(tasks):
    work, setup = tasks, tasks.setup
    scope, bootstrap, _ = project_facts(work)
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.category_id == setup.category,
            Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as denied:
        bootstrap.project_context(scope, "本人权限已撤，不应返回实际任务。")
    assert denied.value.code == "FORBIDDEN_SCOPE"


def test_neighbor_project_native_task_does_not_enter_selected_project(tasks):
    from hashlib import sha256
    from types import SimpleNamespace

    work = tasks
    neighbor_setup = copy(work.setup)
    neighbor = create_g0_project(neighbor_setup, visibility="category", name="相邻P9合成项目")
    text = "相邻项目独有记录，不作为所选P8的事实。"
    registered = post(neighbor_setup, cmd(neighbor_setup, "evidence.artifact.register", {
        "title": "NEIGHBOR_SOURCE_ONLY", "content": text, "source_label": "Synthetic fixture",
        "visibility": "category",
    }))
    assert registered.status_code == 200, registered.text
    other = SimpleNamespace(setup=neighbor_setup, project_id=UUID(neighbor.project_id), source={
        "kind": "artifact", "id": registered.json()["subject_id"], "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(text.encode()).hexdigest(),
    })
    neighbor_task, _ = create_task(other, "NEIGHBOR_TASK_ONLY")
    _, _, actual = project_facts(work)
    assert len(actual["tasks"]) == 2
    assert str(neighbor_task) not in str(actual) and "NEIGHBOR_" not in str(actual)


def test_native_twenty_task_bound_reports_actual_missing_without_silent_drop(tasks):
    work = tasks
    for index in range(19):
        create_task(work, f"合成追加待办{index + 1:02d}")
    current, statements = measured(work)
    assert len(current[0]) == 20 and current[1] is True
    assert "tasks_truncated" in current[6]
    assert len(current[-1]["tasks"]["items"]) == 20
    assert current[-1]["tasks"]["has_more"] is True
    assert [task.task_id for task in current[0]] == sorted(task.task_id for task in current[0])
    assert sum("project_work_task_heads" in sql for sql in statements) == 1
    _, _, actual = project_facts(work)
    assert len(actual["tasks"]) == 20 and actual["tasks_has_more"] is True
    assert actual["complete"] is False and "tasks_truncated" in actual["missing"]
