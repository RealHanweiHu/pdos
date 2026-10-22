"""Material proof regressions against real PostgreSQL and the ordinary application role."""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from contextlib import contextmanager
from copy import deepcopy
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.preproject import category_creation as creation
from pdos_next.domain.preproject.category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ParameterCurrent,
    ParameterVersion,
)
from pdos_next.domain.preproject.provenance import prepare_candidate
from pdos_next.models import Confirmation, Receipt
from pdos_next.service import Context, digest, execute
from tests.preproject import test_review_fixes as fixtures
from tests.preproject.test_g0 import post, request
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_commands_pg import knowledge, parameter

OPERATIONS = ("category.knowledge.add", "category.parameter.publish")


def human_session(work, category_id=None):
    return tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        category_id=category_id or work.category,
    )


def material_command(work, monkeypatch, operation):
    """Create a real trusted synthetic model ledger, then use the real candidate port."""
    arguments = knowledge() if operation == OPERATIONS[0] else parameter()
    original_ledger = fixtures.ledger

    def material_ledger():
        ledger = original_ledger()
        skill_key = "public_research" if operation == OPERATIONS[0] else "competitor_comparison"
        skill = ledger.catalog._skills[skill_key]
        binding = ledger.source.skill.model_copy(
            update={"key": skill.key, "version": skill.version, "digest": skill.digest}
        )
        ledger.source = ledger.source.model_copy(update={"skill": binding})
        ledger.model.execution_binding = {
            **ledger.model.execution_binding,
            "loaded_skills": [binding.model_dump(mode="json")],
        }
        ledger.event.body = {
            **ledger.event.body,
            "key": skill.key,
            "version": skill.version,
            "digest": skill.digest,
        }
        ledger.qualification.skill_key = skill.key
        ledger.qualification.qualified_skill_version = skill.version
        ledger.qualification.qualified_skill_digest = skill.digest
        ledger.qualification.qualified_tool_digest = tool_identity(skill, ledger.registry)
        ledger.qualification.qualified_model_digest = model_identity(ledger.route)
        return ledger

    # Administrative access is confined to the existing synthetic ledger bootstrap.
    # Candidate preparation, preview, material writes and attacks all use application roles.
    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "ledger", material_ledger)
        fixture = fixtures.agent_fixture(work, operation, arguments)
    with fixtures.agent_session(work, fixture) as session:
        prepared = prepare_candidate(
            session,
            fixture.scope,
            operation,
            arguments,
            fixture.source,
            catalog=fixture.catalog,
            registry=fixture.registry,
            route=fixture.route,
        )
    checked = post(work, request(work, operation, prepared), preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    with human_session(work) as session:
        proof = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert proof is not None and not proof.consumed
        assert proof.snapshot["payload"]["prepared_by_run_id"] == str(fixture.scope.run_id)
        proof_id = proof.id
    return command, proof_id


def commit_command(work, command):
    with human_session(work) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        return execute(
            session,
            Context(work.tenant, work.human, work.human, category_id=work.category),
            Command.model_validate(command),
        )


@contextmanager
def insert_hooks(*hooks):
    """Inject a buggy writer at INSERT time without disabling any database guard."""
    for model, hook in hooks:
        event.listen(model, "before_insert", hook)
    try:
        yield
    finally:
        for model, hook in reversed(hooks):
            event.remove(model, "before_insert", hook)


def assert_check_violation(error, message):
    assert error.value.orig.sqlstate == "23514"
    assert message in str(error.value.orig)


def assert_retry_preserves_ai(work, command, proof_id):
    # The failed transaction must leave the actual preview reusable; the exact same
    # command succeeding afterwards proves all non-target requirements are satisfied.
    with human_session(work) as session:
        assert session.get(Confirmation, proof_id).consumed is False
    result = commit_command(work, command)
    with human_session(work) as session:
        receipt = session.get(Receipt, UUID(result["id"]))
        model = KnowledgeEntry if command["operation"] == OPERATIONS[0] else ParameterVersion
        row = session.scalar(select(model).where(model.receipt_id == receipt.id))
        assert row is not None and row.origin == "ai_draft"
        assert row.writer_id == work.agent and row.confirmed_by == work.human
        assert str(row.run_id) == command["payload"]["prepared_by_run_id"]
        assert row.prepared_candidate_id is not None
        assert receipt.agent_run_id == row.run_id and receipt.confirmation_id == proof_id
        assert session.get(Confirmation, proof_id).consumed is True


@pytest.mark.parametrize("operation", OPERATIONS)
def test_material_actual_content_must_equal_its_ai_confirmation(work, monkeypatch, operation):
    command, proof_id = material_command(work, monkeypatch, operation)
    model = KnowledgeEntry if operation == OPERATIONS[0] else ParameterVersion
    touched = []

    def change_actual_content(_mapper, _connection, row):
        touched.append(row.id)
        if isinstance(row, KnowledgeEntry):
            row.content = {"definition": "未经确认的不同实际内容"}
        else:
            row.unit = "Pa"

    reason = (
        "knowledge content differs from confirmation"
        if model is KnowledgeEntry
        else "published parameter differs from confirmation"
    )
    with insert_hooks((model, change_actual_content)), pytest.raises(DBAPIError) as error:
        commit_command(work, command)
    assert touched
    assert_check_violation(error, reason)
    assert_retry_preserves_ai(work, command, proof_id)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_same_content_confirmation_from_another_ai_run_cannot_supply_provenance(
    work, monkeypatch, operation
):
    command, proof_id = material_command(work, monkeypatch, operation)
    other_command, other_proof_id = material_command(work, monkeypatch, operation)
    assert (
        command["payload"]["prepared_by_run_id"] != other_command["payload"]["prepared_by_run_id"]
    )
    assert command["payload"]["candidate_digest"] != other_command["payload"]["candidate_digest"]
    excluded = {"prepared_by_run_id", "candidate_digest", "confirmation_token"}
    assert {k: v for k, v in command["payload"].items() if k not in excluded} == {
        k: v for k, v in other_command["payload"].items() if k not in excluded
    }
    touched = []

    def borrow_other_confirmation(_mapper, connection, receipt):
        assert receipt.confirmation_id == proof_id
        # A legitimate false->true consumption in the SAME transaction removes
        # deadline, actor, operation, consumed and xmin mismatches as explanations.
        assert (
            connection.execute(
                text("UPDATE confirmations SET consumed=true WHERE id=:id AND NOT consumed"),
                {"id": other_proof_id},
            ).rowcount
            == 1
        )
        receipt.confirmation_id = other_proof_id
        touched.append(receipt.id)

    with insert_hooks((Receipt, borrow_other_confirmation)), pytest.raises(DBAPIError) as error:
        commit_command(work, command)
    assert touched
    assert_check_violation(error, "material candidate confirmation mismatch")
    with human_session(work) as session:
        assert session.get(Confirmation, other_proof_id).consumed is False
    assert_retry_preserves_ai(work, command, proof_id)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_same_content_ai_confirmation_cannot_be_laundered_as_human(work, monkeypatch, operation):
    command, proof_id = material_command(work, monkeypatch, operation)
    model = KnowledgeEntry if operation == OPERATIONS[0] else ParameterVersion
    touched = []

    def launder_material(_mapper, _connection, row):
        # Leave content, subject and all material/current relationships unchanged.
        row.origin, row.writer_id = "human", work.human
        row.run_id = row.confirmed_by = row.prepared_candidate_id = None
        touched.append(row.id)

    def launder_receipt(_mapper, _connection, receipt):
        receipt.agent_run_id = None

    def launder_current(_mapper, _connection, current):
        current.origin = "human"

    reason = (
        "unconfirmed material cannot borrow a confirmation"
        if model is KnowledgeEntry
        else "material human provenance mismatch"
    )
    hooks = [(model, launder_material), (Receipt, launder_receipt)]
    if model is KnowledgeEntry:
        hooks.append((KnowledgeCurrent, launder_current))
    with insert_hooks(*hooks), pytest.raises(DBAPIError) as error:
        commit_command(work, command)
    assert touched
    assert_check_violation(error, reason)
    assert_retry_preserves_ai(work, command, proof_id)


@pytest.mark.parametrize("kind", ["knowledge", "parameter"])
def test_old_category_creation_receipt_cannot_append_unselected_material(work, kind):
    body = creation.CategoryCreate(
        key=f"synthetic-proof-{uuid4().hex}",
        name="合成空白品类",
        purpose="检验未勾选资料不能借用建品类回执",
        deidentified_confirmed=True,
        idempotency_key=str(uuid4()),
        groups={"knowledge": [], "parameters": []},
    )
    ctx = Context(work.tenant, work.human, work.human)
    with tenant_session(work.engine, work.tenant, actor_id=work.human) as session:
        view = creation.preview(session, ctx, body)
    body.confirmation_token = view["confirmation_token"]
    with tenant_session(work.engine, work.tenant, actor_id=work.human) as session:
        receipt = creation.create(session, ctx, body)
    category_id, receipt_id = UUID(receipt["category_id"]), UUID(receipt["id"])
    row_id, identity = uuid4(), uuid4()
    with pytest.raises(DBAPIError) as error, human_session(work, category_id) as session:
        original = session.get(Receipt, receipt_id)
        assert original.operation == "category.create"
        assert original.result["knowledge"] == original.result["parameters"] == []
        original_result = deepcopy(original.result)
        provenance = dict(
            id=row_id,
            tenant_id=work.tenant,
            category_id=category_id,
            version=1,
            origin="human",
            writer_id=work.human,
            receipt_id=receipt_id,
            run_id=None,
            confirmed_by=None,
            prepared_candidate_id=None,
        )
        if kind == "knowledge":
            row = KnowledgeEntry(
                **provenance,
                lineage_id=identity,
                action="add",
                **knowledge(),
                regions=[],
                source_refs=[],
                withdraw_reason=None,
            )
            current = KnowledgeCurrent(
                tenant_id=work.tenant,
                category_id=category_id,
                lineage_id=identity,
                kind=row.kind,
                current_entry_id=row_id,
                current_version=1,
                status="active",
                origin="human",
            )
        else:
            fields = parameter()
            fields.pop("parameter_id")
            fields.pop("expected_current_version")
            row = ParameterVersion(
                **provenance,
                parameter_id=identity,
                replaces_version=None,
                enum_values=None,
                **fields,
            )
            current = ParameterCurrent(
                tenant_id=work.tenant,
                category_id=category_id,
                parameter_id=identity,
                key=row.key,
                current_version=1,
            )
        session.add(row)
        session.flush([row])
        session.add(current)
        session.flush()
    assert_check_violation(error, "material and receipt must commit together")
    with human_session(work, category_id) as session:
        assert session.get(type(row), row_id) is None
        assert session.get(Receipt, receipt_id).result == original_result


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("change", ["noop", "reopen", "snapshot"])
def test_consumed_material_confirmation_cannot_be_touched_or_reopened(
    work, monkeypatch, operation, change
):
    command, proof_id = material_command(work, monkeypatch, operation)
    assert_retry_preserves_ai(work, command, proof_id)
    with human_session(work) as session:
        original = deepcopy(session.get(Confirmation, proof_id).snapshot)
    statements = {
        "noop": "UPDATE confirmations SET consumed=consumed WHERE id=:id",
        "reopen": "UPDATE confirmations SET consumed=false WHERE id=:id",
        "snapshot": (
            "UPDATE confirmations SET snapshot=jsonb_set(snapshot,'{payload,candidate_digest}',"
            "'\"forged-candidate\"'::jsonb) WHERE id=:id"
        ),
    }
    with pytest.raises(DBAPIError) as error, human_session(work) as session:
        session.execute(text(statements[change]), {"id": proof_id})
    assert_check_violation(error, "material confirmation can only be consumed once")
    with human_session(work) as session:
        proof = session.get(Confirmation, proof_id)
        assert proof.consumed is True and proof.snapshot == original


@pytest.mark.parametrize("operation", OPERATIONS)
def test_material_confirmation_cannot_be_inserted_already_consumed(work, monkeypatch, operation):
    command, proof_id = material_command(work, monkeypatch, operation)
    with human_session(work) as session:
        proof = session.get(Confirmation, proof_id)
        fields = {
            column.name: deepcopy(getattr(proof, column.name))
            for column in Confirmation.__table__.columns
        }
    fields.update(id=uuid4(), token_hash=digest(str(uuid4())), consumed=True)
    with pytest.raises(DBAPIError) as error, human_session(work) as session:
        session.add(Confirmation(**fields))
        session.flush()
    assert_check_violation(error, "material confirmation starts unconsumed")
    assert_retry_preserves_ai(work, command, proof_id)


def t0_material_fixture(work, monkeypatch, arguments, *, private_context=False):
    """Synthetic qualification/model facts only; no provider is contacted."""
    from dataclasses import replace

    original_ledger = fixtures.ledger

    def public_research_ledger():
        ledger = original_ledger()
        skill = ledger.catalog._skills["public_research"]
        binding = ledger.source.skill.model_copy(
            update={"key": skill.key, "version": skill.version, "digest": skill.digest}
        )
        ledger.source = ledger.source.model_copy(update={"skill": binding})
        ledger.model.execution_binding = {
            **ledger.model.execution_binding,
            "loaded_skills": [binding.model_dump(mode="json")],
        }
        ledger.event.body = {
            **ledger.event.body,
            "key": skill.key,
            "version": skill.version,
            "digest": skill.digest,
        }
        ledger.qualification.skill_key = skill.key
        ledger.qualification.qualified_skill_version = skill.version
        ledger.qualification.qualified_skill_digest = skill.digest
        ledger.qualification.qualified_tool_digest = tool_identity(skill, ledger.registry)
        ledger.qualification.qualified_model_digest = model_identity(ledger.route)
        ledger.scope = replace(ledger.scope, private_context=private_context)
        ledger.run.private_context = private_context
        return ledger

    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "ledger", public_research_ledger)
        return fixtures.agent_fixture(work, OPERATIONS[0], arguments)


def execute_t0_material(fixture, arguments, source=None):
    from pdos_next.agent_kernel.bindings import execution_key

    source = source or fixture.source
    return fixture.adapter.execute(
        fixture.scope,
        OPERATIONS[0],
        arguments,
        execution_key(fixture.scope.run_id, source.model_call_id, source.response_index),
        source=source,
    )


def assert_no_t0_material_write(work, fixture):
    from pdos_next.agent_kernel.models import AgentToolCall

    with human_session(work) as session:
        assert (
            session.scalar(select(Receipt.id).where(Receipt.agent_run_id == fixture.scope.run_id))
            is None
        )
        assert (
            session.scalar(
                select(KnowledgeEntry.id).where(KnowledgeEntry.run_id == fixture.scope.run_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(AgentToolCall.id).where(
                    AgentToolCall.run_id == fixture.scope.run_id,
                    AgentToolCall.tool == OPERATIONS[0],
                )
            )
            is None
        )


def test_t0_material_actual_controlled_call_adds_replays_and_supersedes_ai_draft(work, monkeypatch):
    from pdos_next.agent_kernel.models import AgentToolCall

    arguments = knowledge()
    fixture = t0_material_fixture(work, monkeypatch, arguments)
    added = execute_t0_material(fixture, arguments)
    replay = execute_t0_material(fixture, arguments)
    assert replay["id"] == added["id"]
    assert replay["agent_call_id"] == added["agent_call_id"]
    identity = UUID(added["result"]["lineage_id"])
    replacement = knowledge(
        content={"definition": "合成公开研究补充的边界"},
        supersedes={"lineage_id": str(identity), "expected_version": 1},
    )
    source = fixtures.new_model_call(work, fixture, OPERATIONS[0], replacement)
    updated = execute_t0_material(fixture, replacement, source)
    assert updated["result"]["version"] == 2
    with human_session(work) as session:
        rows = session.scalars(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.lineage_id == identity)
            .order_by(KnowledgeEntry.version)
        ).all()
        assert [(r.version, r.action) for r in rows] == [(1, "add"), (2, "supersede")]
        assert rows[0].content["definition"] == arguments["content"]["definition"]
        assert rows[1].content["definition"] == replacement["content"]["definition"]
        current = session.get(KnowledgeCurrent, (work.tenant, identity))
        assert current.current_version == 2 and current.current_entry_id == rows[1].id
        assert current.origin == "ai_draft"
        for row, result in zip(rows, (added, updated), strict=True):
            assert row.origin == "ai_draft" and row.writer_id == work.agent
            assert row.run_id == fixture.scope.run_id
            assert row.confirmed_by is None and row.prepared_candidate_id is None
            receipt = session.get(Receipt, row.receipt_id)
            assert receipt.id == UUID(result["id"])
            assert receipt.actor_id == work.agent and receipt.requester_id == work.human
            assert receipt.confirmation_id is None and receipt.agent_run_id == fixture.scope.run_id
            call = session.get(AgentToolCall, UUID(result["agent_call_id"]))
            assert call.state == "completed" and call.receipt_id == receipt.id
            assert call.tool == OPERATIONS[0]
            assert call.execution_binding["operation"] == OPERATIONS[0]


def test_t0_material_private_run_cannot_add_shared_knowledge(work, monkeypatch):
    from pdos_next.errors import DomainError

    arguments = knowledge()
    fixture = t0_material_fixture(work, monkeypatch, arguments, private_context=True)
    with pytest.raises(DomainError) as error:
        execute_t0_material(fixture, arguments)
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert error.value.detail["reason"] == "private_context_run"
    assert_no_t0_material_write(work, fixture)


def imported_material_work(work):
    """Use the public seed admission and named member grant, never forged origin rows."""
    from copy import copy

    from pdos_next.category_scope import MemberGrant, grant_member

    seed = creation.load_seed(creation.SEED_KEYS[0])
    boundary_index = next(
        index
        for index, item in enumerate(seed["groups"]["knowledge"])
        if item["kind"] == "boundary"
    )
    body = creation.CategoryCreate(
        **{key: seed[key] for key in ("key", "name", "purpose", "seed_key")},
        groups={"knowledge": seed["groups"]["knowledge"], "parameters": []},
        deidentified_confirmed=True,
        idempotency_key=str(uuid4()),
    )
    ctx = Context(work.tenant, work.human, work.human)
    with tenant_session(work.engine, work.tenant, actor_id=work.human) as session:
        view = creation.preview(session, ctx, body)
    body.confirmation_token = view["confirmation_token"]
    with tenant_session(work.engine, work.tenant, actor_id=work.human) as session:
        created = creation.create(session, ctx, body)
    scoped = copy(work)
    scoped.category = UUID(created["category_id"])
    with human_session(scoped) as session:
        grant_member(
            session,
            Context(scoped.tenant, scoped.human, scoped.human, category_id=scoped.category),
            MemberGrant(
                principal_id=scoped.agent,
                can_write=True,
                expected_revision=1,
                idempotency_key=str(uuid4()),
                decision="批准",
            ),
        )
    return scoped, UUID(created["result"]["knowledge"][boundary_index]["lineage_id"])


@pytest.mark.parametrize("protected_origin", ["human", "confirmed_ai", "imported"])
def test_t0_material_cannot_supersede_protected_material(work, monkeypatch, protected_origin):
    from pdos_next.errors import DomainError

    if protected_origin == "human":
        response = post(work, request(work, OPERATIONS[0], knowledge()))
        assert response.status_code == 200, response.text
        identity = UUID(response.json()["result"]["lineage_id"])
    elif protected_origin == "confirmed_ai":
        command, _proof_id = material_command(work, monkeypatch, OPERATIONS[0])
        result = commit_command(work, command)
        identity = UUID(result["result"]["lineage_id"])
    else:
        work, identity = imported_material_work(work)
    with human_session(work) as session:
        current = session.get(KnowledgeCurrent, (work.tenant, identity))
        original = session.get(KnowledgeEntry, current.current_entry_id)
        original_id, original_content = original.id, deepcopy(original.content)
        assert (
            original.origin
            == {"human": "human", "confirmed_ai": "ai_draft", "imported": "imported"}[
                protected_origin
            ]
        )
        assert (original.confirmed_by == work.human) is (protected_origin == "confirmed_ai")
    arguments = knowledge(
        content={"definition": "AI 尝试覆盖受保护资料"},
        supersedes={"lineage_id": str(identity), "expected_version": 1},
    )
    fixture = t0_material_fixture(work, monkeypatch, arguments)
    with pytest.raises(DomainError) as error:
        execute_t0_material(fixture, arguments)
    assert error.value.code == "CONFIRMATION_REQUIRED"
    assert error.value.detail["reason"] == "human_value_protected"
    assert_no_t0_material_write(work, fixture)
    with human_session(work) as session:
        current = session.get(KnowledgeCurrent, (work.tenant, identity))
        assert current.current_version == 1 and current.current_entry_id == original_id
        assert session.get(KnowledgeEntry, original_id).content == original_content
        assert (
            len(
                session.scalars(
                    select(KnowledgeEntry).where(KnowledgeEntry.lineage_id == identity)
                ).all()
            )
            == 1
        )
