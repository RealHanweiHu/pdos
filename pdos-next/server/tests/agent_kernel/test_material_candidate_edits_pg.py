"""Synthetic model ledger → editable material → one real T1 receipt. No model calls."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun, AgentSession, AgentSessionBinding
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.domain.preproject.category_models import KnowledgeEntry, ParameterVersion
from pdos_next.domain.preproject.models import PreparedCandidate
from tests.agent_kernel.test_domain_candidates_pg import read
from tests.preproject.test_material_commands_pg import parameter
from tests.products.test_definition_item_commands_pg import confirmed
from tests.products.test_definition_item_revert_pg import agent_fixture


def candidate(setup, kind, *, goal="Synthetic material candidate editing"):
    operation = "category.parameter.publish" if kind == "parameter" else "category.knowledge.add"
    arguments = (
        parameter()
        if kind == "parameter"
        else {
            "kind": kind,
            "content": {"brand": "合成品牌", "model": "合成型号"}
            if kind == "competitor"
            else {
                "label": "合成用户声音",
                "source_platform": "合成访谈",
                "representative_refs": [],
            },
        }
    )
    fixture = agent_fixture(
        setup,
        arguments,
        operation=operation,
        skill_key="competitor_comparison",
        product_bound=False,
        goal=goal,
    )
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: fixture.route
    prepared = owner.prepare_candidate(
        fixture.scope,
        owner.registry.get(operation),
        arguments,
        execution_key(fixture.scope.run_id, fixture.model.id, 0),
    )
    command = deepcopy(prepared["command"])
    command.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    command["payload"]["human_edits"] = (
        {"name": "人工完善的噪声"}
        if kind == "parameter"
        else {
            "content": {
                **command["payload"]["content"],
                "model" if kind == "competitor" else "label": "人工完善后的资料",
            },
        }
    )
    return fixture, prepared, command


@pytest.mark.parametrize("kind", ["competitor", "voice", "parameter"])
def test_human_edits_keep_original_and_ai_provenance_and_cannot_duplicate(setup, kind):
    fixture, original, command = candidate(setup, kind)
    receipt, replay = confirmed(setup, command)
    assert receipt["result"]["human_edits"] == command["payload"]["human_edits"]
    assert receipt["result"]["edited_by"] == str(setup.human)
    assert receipt["agent_run_id"] == str(fixture.scope.run_id)
    with Session(setup.admin) as s:
        model = ParameterVersion if kind == "parameter" else KnowledgeEntry
        row = s.scalar(select(model).where(model.receipt_id == UUID(receipt["id"])))
        assert row.origin == "ai_draft" and row.confirmed_by == setup.human
        sealed = s.get(PreparedCandidate, row.prepared_candidate_id)
        assert "human_edits" not in sealed.payload
        assert (
            row.name
            if kind == "parameter"
            else row.content["model" if kind == "competitor" else "label"]
        ).startswith("人工完善")
        assert (
            sealed.payload["name"]
            if kind == "parameter"
            else sealed.payload["content"]["model" if kind == "competitor" else "label"]
        ) != "人工完善后的资料"
    listed = read(setup, fixture).json()["items"][0]
    assert listed["state"] == "adopted" and listed["receipt"]["id"] == receipt["id"]
    assert listed["material_binding"]["kind"] == kind
    assert (
        listed["material_binding"]["digest"] == original["command"]["payload"]["candidate_digest"]
    )
    assert listed["command"] is None
    path = f"/v1/categories/{setup.category}/commands"
    assert setup.client.post(path, headers=setup.headers, json=replay).json()["id"] == receipt["id"]
    denied = setup.client.post(path + "/preview", headers=setup.headers, json=original["command"])
    assert denied.status_code == 409, denied.text


@pytest.mark.parametrize(
    "edit",
    [
        {"supersedes": None},
        {"source_refs": []},
        {"kind": "voice"},
        {"prepared_by_run_id": str(uuid4())},
    ],
)
def test_edits_cannot_change_scope_target_or_original_source_manifest(setup, edit):
    _, _, command = candidate(setup, "competitor")
    command["payload"]["human_edits"] = edit
    result = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=command
    )
    assert result.status_code == 403, result.text


def test_original_tampering_cancel_and_permission_change_still_deny(setup):
    fixture, _, command = candidate(setup, "competitor")
    path = f"/v1/categories/{setup.category}/commands"
    tampered = deepcopy(command)
    tampered["payload"]["content"]["brand"] = "覆盖原稿"
    assert (
        setup.client.post(path + "/preview", headers=setup.headers, json=tampered).status_code
        == 403
    )
    preview = setup.client.post(path + "/preview", headers=setup.headers, json=command)
    assert preview.status_code == 200, preview.text
    assert (
        setup.client.post(
            path,
            headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
            json=preview.json()["command"],
        ).status_code
        == 403
    )
    with Session(setup.admin) as s, s.begin():
        s.get(AgentRun, fixture.scope.run_id).state = "cancelled"
    assert (
        setup.client.post(path, headers=setup.headers, json=preview.json()["command"]).status_code
        == 403
    )


def test_downgrade_preserves_named_human_edit_history(setup):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from migrations.versions import s0_0815_material_candidate_edits as migration

    _, _, command = candidate(setup, "parameter")
    confirmed(setup, command)
    with setup.admin.connect() as connection:
        transaction = connection.begin()
        original_head = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="Human-edited material history exists"):
                    migration.downgrade()
        finally:
            transaction.rollback()
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == original_head
        )


def test_proposal_candidate_human_edit_uses_original_seal_and_one_confirmation(setup):
    from tests.preproject.test_g0 import payload

    arguments = payload(setup)
    for item in arguments["groups"]["items"]:
        if item["kind"] == "spec":
            item["content"]["item_status"] = "ai_draft"
    fixture = agent_fixture(
        setup,
        arguments,
        operation="proposal.create",
        skill_key="proposal_drafting",
        product_bound=False,
        goal="Synthetic editable proposal",
    )
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: fixture.route
    prepared = owner.prepare_candidate(
        fixture.scope,
        owner.registry.get("proposal.create"),
        arguments,
        execution_key(fixture.scope.run_id, fixture.model.id, 0),
    )
    command = deepcopy(prepared["command"])
    command.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    command["payload"]["human_edits"] = {"title": "人工完善提案", "brief": "人工完善摘要"}
    receipt, replay = confirmed(setup, command)
    assert receipt["result"]["human_edits"] == command["payload"]["human_edits"]
    from pdos_next.domain.preproject.models import Proposal

    with Session(setup.admin) as session:
        proposal = session.get(Proposal, UUID(receipt["subject_id"]))
        assert proposal.title == "人工完善提案" and proposal.brief == "人工完善摘要"
        assert proposal.created_by_run_id == fixture.scope.run_id
        original = session.get(PreparedCandidate, UUID(receipt["result"]["prepared_candidate_id"]))
        assert (
            original.payload["title"] == arguments["title"]
            and "human_edits" not in original.payload
        )
    assert (
        setup.client.post(
            f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=replay
        ).json()["id"]
        == receipt["id"]
    )
    listed = read(setup, fixture).json()["items"][0]
    assert listed["state"] == "adopted" and listed["receipt"]["id"] == receipt["id"]
    assert (
        setup.client.post(
            f"/v1/categories/{setup.category}/commands/preview",
            headers=setup.headers,
            json=prepared["command"],
        ).status_code
        == 409
    )


def proposal_command(setup, *, parent_id=None):
    from tests.preproject.test_g0 import payload

    arguments = payload(setup)
    for item in arguments["groups"]["items"]:
        if item["kind"] == "spec":
            item["content"]["item_status"] = "ai_draft"
    fixture = agent_fixture(
        setup,
        arguments,
        operation="proposal.create",
        skill_key="proposal_drafting",
        product_bound=False,
        parent_id=parent_id,
        goal="Synthetic proposal session binding",
    )
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: fixture.route
    prepared = owner.prepare_candidate(
        fixture.scope,
        owner.registry.get("proposal.create"),
        arguments,
        execution_key(fixture.scope.run_id, fixture.model.id, 0),
    )
    command = deepcopy(prepared["command"])
    command.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    command["payload"]["human_edits"] = {"title": "会话内保存提案", "brief": "真实回执绑定"}
    return fixture, command


def test_binding_guard_preserves_existing_project_scope_checks():
    from migrations.schema_s0_0823 import DOWNGRADE_GUARD_SQL, RUN_GUARD

    downgrade = next(sql for sql in DOWNGRADE_GUARD_SQL if "kernel_run_guard" in sql)
    for guard in (RUN_GUARD, downgrade):
        assert guard.count("NEW.project_id IS DISTINCT FROM OLD.project_id") == 1
        assert guard.count("s.project_id IS DISTINCT FROM NEW.project_id") == 1


def test_saved_proposal_binds_session_and_continues_with_real_proposal_scope(setup):
    fixture, command = proposal_command(setup)
    receipt, _ = confirmed(setup, command)
    owner = Bootstrap(setup.engine)
    proposal_id = UUID(receipt["subject_id"])
    assert receipt["result"]["title"] == "会话内保存提案"
    original_detail = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{fixture.scope.run_id}",
        headers=setup.headers,
    )
    assert original_detail.status_code == 200, original_detail.text
    assert original_detail.json()["proposal_id"] is None
    assert original_detail.json()["session_proposal_id"] == receipt["subject_id"]
    with Session(setup.admin) as session:
        parent = session.get(AgentRun, fixture.scope.run_id)
        conversation = session.get(AgentSession, parent.session_id)
        assert parent.proposal_id is None
        assert conversation.proposal_id is None and conversation.revision == 1
        binding = session.scalar(
            select(AgentSessionBinding).where(AgentSessionBinding.session_id == parent.session_id)
        )
        assert binding.proposal_id == proposal_id and binding.receipt_id == UUID(receipt["id"])
    with Session(setup.admin) as session, session.begin():
        parent = session.get(AgentRun, fixture.scope.run_id)
        parent.state = "completed"
        parent.result = {"summary": "合成提案候选已保存", "unfinished": [], "result": {}}
    root = f"/v1/categories/{setup.category}/agent-runs"
    response = setup.client.post(root, headers=setup.headers, json={
        "goal": "继续修订刚保存的提案", "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(fixture.scope.run_id),
    })
    assert response.status_code == 202, response.text
    child = response.json()["run_id"]
    detail = setup.client.get(f"{root}/{child}", headers=setup.headers)
    assert detail.status_code == 200 and detail.json()["proposal_id"] == receipt["subject_id"]
    history = setup.client.get(
        f"/v1/categories/{setup.category}/agent-sessions/{response.json()['session_id']}/runs",
        headers=setup.headers,
    )
    assert history.status_code == 200, history.text
    assert {item["run_id"] for item in history.json()["items"]} == {
        str(fixture.scope.run_id),
        child,
    }
    bound = KernelStore(setup.engine).scope(
        tenant_id=setup.tenant, requester_id=setup.human, writer_id=setup.agent,
        category_id=setup.category, run_id=UUID(child),
    )
    context = owner.project_context(bound, "继续修订刚保存的提案")
    assert context["proposal"]["id"] == receipt["subject_id"]
    assert context["conversation"]["turns"][0]["run_id"] == str(fixture.scope.run_id)


def test_prebinding_active_run_keeps_original_history_after_save(setup):
    root = f"/v1/categories/{setup.category}/agent-runs"
    started = setup.client.post(root, headers=setup.headers, json={
        "goal": "保存前的原始讨论", "idempotency_key": str(uuid4()),
    })
    assert started.status_code == 202, started.text
    root_id = UUID(started.json()["run_id"])
    with Session(setup.admin) as session, session.begin():
        parent = session.get(AgentRun, root_id)
        parent.state = "completed"
        parent.result = {"summary": "原始讨论已完成", "unfinished": [], "result": {}}
    fixture, command = proposal_command(setup, parent_id=root_id)
    receipt, _ = confirmed(setup, command)
    assert receipt["subject_id"]
    bound = KernelStore(setup.engine).scope(
        tenant_id=setup.tenant, requester_id=setup.human, writer_id=setup.agent,
        category_id=setup.category, run_id=fixture.scope.run_id,
    )
    context = Bootstrap(setup.engine).project_context(bound, "恢复原续接运行")
    assert context["conversation"]["root_run_id"] == str(root_id)
    assert context["conversation"]["turns"][0]["run_id"] == str(root_id)


def test_active_continuation_blocks_binding_until_finished(setup):
    fixture, command = proposal_command(setup)
    with Session(setup.admin) as session, session.begin():
        parent = session.get(AgentRun, fixture.scope.run_id)
        parent.state = "completed"
        parent.result = {"summary": "合成提案候选待确认", "unfinished": [], "result": {}}
    root = f"/v1/categories/{setup.category}/agent-runs"
    continued = setup.client.post(root, headers=setup.headers, json={
        "goal": "先继续讨论再保存提案", "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(fixture.scope.run_id),
    })
    assert continued.status_code == 202, continued.text
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=command
    )
    assert preview.status_code == 200, preview.text
    denied = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=preview.json()["command"],
    )
    assert denied.status_code == 409 and denied.json()["code"] == "VERSION_CONFLICT", denied.text
    with Session(setup.admin) as session:
        assert session.scalar(
            select(AgentSessionBinding).where(
                AgentSessionBinding.session_id == fixture.scope.session_id
            )
        ) is None
    with Session(setup.admin) as session, session.begin():
        session.get(AgentRun, UUID(continued.json()["run_id"])).state = "cancelled"
    receipt, _ = confirmed(setup, command)
    assert receipt["subject_id"]
    with Session(setup.admin) as session:
        binding = session.scalar(
            select(AgentSessionBinding).where(
                AgentSessionBinding.session_id == fixture.scope.session_id
            )
        )
        assert binding.proposal_id == UUID(receipt["subject_id"])
