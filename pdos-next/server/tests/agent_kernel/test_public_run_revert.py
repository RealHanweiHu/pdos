"""Real common HTTP owner with explicitly synthetic AI history; no model is called."""

from dataclasses import replace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import persistence
from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentSession
from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.models import Artifact, Audit, Claim, Confirmation, Consumption, Outbox, Receipt
from pdos_next.service import digest
from tests.agent_kernel.test_execution_binding import ledger
from tests.agent_kernel.test_transactions import run


def claim_ledger(setup, artifact):
    """Synthetic provider output; the real adapter writes the Claim and its receipt."""
    f = ledger()
    f.scope = replace(
        f.scope, tenant_id=setup.tenant, category_id=setup.category,
        requester_id=setup.human, writer_id=setup.agent, product_id=setup.product,
    )
    skill = f.catalog._skills["public_research"]
    bound = SkillBinding(
        key=skill.key, version=skill.version, digest=skill.digest, load_event_id=uuid4(),
    )
    binding = ModelBinding(
        model_version=f.route.version, model_route_digest=f.route.digest,
        tool_definitions_digest=digest(f.registry.definitions()), prompt_digest=digest("prefix"),
        isolation="main", cancel_epoch=0, loaded_skills=(bound,),
    )
    for name in ("tenant_id", "category_id", "requester_id", "writer_id", "product_id"):
        setattr(f.run, name, getattr(f.scope, name))
    f.run.trigger, f.run.goal = "page", "Synthetic whole-run revert history"
    f.run.intent_key, f.run.intent_digest = str(uuid4()), digest(str(uuid4()))
    f.run.read_sources = [{
        "artifact_id": str(artifact), "expected_revision": 1, "product_id": str(setup.product),
    }]
    f.run.versions = {
        "model_version": f.route.version, "model_route_digest": f.route.digest,
        "tool_definitions": {"main": binding.tool_definitions_digest},
        "prompt_prefixes": {"main": binding.prompt_digest},
    }
    f.spec = f.registry.get("evidence.claim.record")
    f.arguments = {
        "artifact_id": str(artifact), "line": 1, "quote": "150 PSI",
        "statement": "Synthetic supported output", "visibility": "private",
    }
    f.model.tenant_id, f.model.call_key = setup.tenant, str(uuid4())
    f.model.input_digest = digest("synthetic provider request")
    f.model.execution_binding = binding.model_dump(mode="json")
    f.model.result = {"calls": [{"id": "synthetic-native", "name": f.spec.name,
                                  "arguments": f.arguments}]}
    f.source = WriteSource(skill=bound, model_call_id=f.model.id, response_index=0)
    f.qualification.tenant_id, f.qualification.skill_key = setup.tenant, skill.key
    f.qualification.qualified_skill_version = skill.version
    f.qualification.qualified_skill_digest = skill.digest
    f.qualification.qualified_tool_digest = tool_identity(skill, f.registry)
    f.qualification.qualified_model_digest = model_identity(f.route)
    f.qualification.reviewed_by = setup.human
    with tenant_session(
        setup.admin, setup.tenant, actor_id=setup.human, requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        session.expire_on_commit = False
        session.add(AgentSession(
            id=f.scope.session_id, tenant_id=setup.tenant, category_id=setup.category,
            product_id=setup.product, owner_id=setup.human,
        ))
        session.flush()
        session.add(f.run)
        session.flush()
        session.add_all([f.model, f.qualification, AgentEvent(
            id=bound.load_event_id, tenant_id=setup.tenant, run_id=f.scope.run_id, sequence=1,
            body={"type": "skill_loaded", "key": bound.key, "version": bound.version,
                  "digest": bound.digest, "isolation": "main"},
        )])
    f.adapter = DomainCommands(
        setup.engine, catalog=f.catalog, registry=f.registry, route=lambda *_: f.route,
    )
    return f


def history(setup, *, category_only=False):
    artifact, artifacts_receipt = uuid4(), uuid4()
    product = None if category_only else setup.product
    # Product Claims use a shared source, with the AI output kept private. Under
    # M3 a private AI source would require a real proposal-bound Run instead.
    visibility = "private" if category_only else "category"
    with tenant_session(
        setup.admin, setup.tenant, actor_id=setup.agent, requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        s.add(Artifact(
            id=artifact, tenant_id=setup.tenant, category_id=setup.category, product_id=product,
            owner_id=setup.human, title="Synthetic AI output",
            source_label="M3 public owner fixture", content="Synthetic pressure: 150 PSI",
            content_hash=digest("Synthetic pressure: 150 PSI"), visibility=visibility,
        ))
    # The Run source gate resolves actual rows at INSERT time. Commit the source
    # before creating the Run that pins it, then bind its synthetic history receipt.
    f = None if category_only else claim_ledger(setup, artifact)
    if category_only:
        store, scope = run(setup, product_id=None)
    else:
        store, scope = persistence.KernelStore(setup.engine), f.scope
    with tenant_session(
        setup.admin, setup.tenant, actor_id=setup.agent, requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        s.add(Receipt(
            id=artifacts_receipt, tenant_id=setup.tenant, category_id=setup.category,
            product_id=product, command_id=uuid4(), actor_id=setup.agent,
            requester_id=setup.human, operation="evidence.artifact.register",
            subject_type="artifact", subject_id=artifact, subject_revision=1,
            visibility=visibility, request_digest=digest(str(uuid4())),
            intent_digest=digest(str(uuid4())), agent_run_id=scope.run_id,
            result={"id": str(artifact), "revision": 1, "status": "active"},
        ))
    claim = None
    if f:
        receipt = f.adapter.execute(
            scope, f.spec.name, f.arguments,
            execution_key(scope.run_id, f.model.id, 0), source=f.source,
        )
        claim = UUID(receipt["subject_id"])
        with Session(setup.admin) as s:
            actual = s.get(Claim, claim)
            assert actual.artifact_id == artifact and actual.source_locator == "line:1"
            assert actual.origin == "ai_draft" and actual.run_id == scope.run_id
            assert actual.writer_id == setup.agent and actual.receipt_id == UUID(receipt["id"])
    with store.transaction(scope, lock=True) as (_, row):
        row.state, row.result = "completed", {"synthetic_history": True}
    return scope, artifact, claim


def preview(setup, scope):
    return setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/revert-preview",
        headers=setup.headers,
    )


def test_actual_whole_run_preview_and_human_t1_command_revert_all_drafts_once(setup):
    scope, artifact, claim = history(setup)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    command = candidate.json()["command"]
    assert command["payload"]["run_id"] == str(scope.run_id)
    assert len(candidate.json()["review"]["receipts"]) == 2
    path = f"/v1/categories/{setup.category}/commands"
    done = setup.client.post(path, headers=setup.headers, json=command)
    assert done.status_code == 200
    repeated = setup.client.post(path, headers=setup.headers, json=command)
    assert repeated.json() == done.json()
    with Session(setup.admin) as s:
        actual = s.get(AgentRun, scope.run_id)
        assert actual.state == "completed" and actual.result == {"synthetic_history": True}
        assert actual.reverted_at and actual.cancel_epoch == 1
        assert s.get(Artifact, artifact).status == "withdrawn"
        assert s.get(Claim, claim).status == "reverted"
        receipt = s.get(Receipt, actual.revert_receipt_id)
        assert receipt.actor_id == setup.human and receipt.agent_run_id is None
        assert s.scalar(
            select(func.count()).select_from(Audit).where(Audit.receipt_id == receipt.id)
        ) == 1
        assert s.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.receipt_id == receipt.id)
        ) == 1


def test_category_only_run_reverts_category_artifact_through_public_human_owner(setup):
    scope, artifact, _ = history(setup, category_only=True)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    done = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers,
        json=candidate.json()["command"],
    )
    assert done.status_code == 200
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "withdrawn"
        assert s.get(AgentRun, scope.run_id).reverted_at


def test_public_revert_refuses_external_consumption_and_changes_nothing(setup):
    scope, artifact, claim = history(setup)
    with Session(setup.admin) as s, s.begin():
        s.add(Consumption(
            tenant_id=setup.tenant, category_id=setup.category, product_id=setup.product,
            claim_id=claim, consumer_type="synthetic_next_step", consumer_id=uuid4(),
        ))
    denied = preview(setup, scope)
    assert denied.status_code == 409
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        assert s.get(AgentRun, scope.run_id).reverted_at is None


@pytest.mark.parametrize("stage", ["finish", "outbox"])
def test_public_revert_tail_failure_rolls_back_every_business_and_technical_effect(
    setup, monkeypatch, stage
):
    scope, artifact, claim = history(setup)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    command = candidate.json()["command"]
    with Session(setup.admin) as s:
        before = {model: s.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
        ) for model in (Receipt, Audit, Outbox)}
    original = persistence.finish_run_revert

    def failed_finish(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic finish tail failure")

    def failed_outbox(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("synthetic outbox tail failure")

    if stage == "finish":
        monkeypatch.setattr(persistence, "finish_run_revert", failed_finish)
    else:
        event.listen(setup.engine, "before_cursor_execute", failed_outbox)
    try:
        with pytest.raises(RuntimeError, match=f"synthetic {stage} tail failure"):
            setup.client.post(
                f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=command
            )
    finally:
        if stage == "outbox":
            event.remove(setup.engine, "before_cursor_execute", failed_outbox)
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        actual = s.get(AgentRun, scope.run_id)
        assert actual.reverted_at is None and actual.cancel_epoch == 0
        confirmation = s.scalar(
            select(Confirmation).where(Confirmation.subject_id == scope.run_id)
        )
        assert confirmation.consumed is False
        for model, count in before.items():
            assert s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            ) == count


def test_private_external_definition_consumption_is_opaque_but_blocks_whole_run(setup):
    scope, artifact, claim = history(setup)
    reference = {
        "artifact_id": str(artifact), "expected_revision": 1, "line": 1, "quote": "150 PSI"
    }
    saved = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json={
            "command_id": str(uuid4()), "idempotency_key": "private-consumer:" + str(uuid4()),
            "operation": "product.definition.draft", "category_id": str(setup.category),
            "product_id": str(setup.product), "expected_revision": 1,
            "source_read_set": [{"artifact_id": str(artifact), "expected_revision": 1}],
            "payload": {
                "title": "Synthetic private consumer", "purpose": "M2 private downstream fixture",
                "visibility": "private", "use_cases": ["Synthetic verification"],
                "sources": [reference], "specs": [], "change_reason": "Explicit synthetic consumer",
            },
        },
    )
    assert saved.status_code == 200
    from tests.agent_kernel.test_transactions import human_session

    with human_session(setup) as s:
        assert s.get(DefinitionRevision, saved.json()["subject_id"]) is None
    denied = preview(setup, scope)
    assert denied.status_code == 409
    assert "Synthetic private consumer" not in denied.text
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        assert s.get(AgentRun, scope.run_id).reverted_at is None
