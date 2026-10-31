"""Root shared PostgreSQL: actual common Claim owner, synthetic model ledger only."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.disclosure import binding_operations, disclosure_digest
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentSession,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.qualification_binding import tool_identity
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Claim, Grant, Outbox, Receipt, RequestKey
from pdos_next.safety import verify_test_target
from pdos_next.service import digest, execute
from tests.agent_kernel.test_execution_binding import ledger


def fixture(setup, *, artifact_id=None, proposal_id=None, skill_key="public_research"):
    verify_test_target(setup.admin)
    f = ledger()
    f.scope = replace(
        f.scope,
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        product_id=setup.product,
        proposal_id=proposal_id,
    )
    skill = f.catalog._skills[skill_key]
    bound = SkillBinding(
        key=skill.key, version=skill.version, digest=skill.digest, load_event_id=uuid4()
    )
    if artifact_id is None:
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            receipt = execute(
                session,
                setup.ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key=str(uuid4()),
                    category_id=setup.category,
                    operation="evidence.artifact.register",
                    expected_revision=1,
                    payload={
                        "title": "合成品类资料",
                        "source_label": "本地合成",
                        "content": "Synthetic exact source",
                        "visibility": "category",
                    },
                ),
            )
            artifact_id = UUID(receipt["subject_id"])
    f.arguments = {
        "artifact_id": str(artifact_id),
        "line": 1,
        "quote": "Synthetic exact source",
        "statement": "Synthetic supported fact",
        "visibility": "category",
    }
    f.spec = f.registry.get("evidence.claim.record")
    run = f.run
    for name in (
        "tenant_id", "requester_id", "writer_id", "category_id", "product_id", "proposal_id",
    ):
        setattr(run, name, getattr(f.scope, name))
    run.trigger, run.goal = f.scope.trigger, "Synthetic actual common domain adapter"
    run.intent_key, run.intent_digest = str(uuid4()), digest(str(uuid4()))
    run.read_sources = [
        {"artifact_id": str(artifact_id), "expected_revision": 1, "product_id": None}
    ]
    binding = ModelBinding(
        model_version=f.route.version,
        model_route_digest=f.route.digest,
        tool_definitions_digest=disclosure_digest(
            f.registry, "main", binding_operations(f.catalog, (bound,))
        ),
        prompt_digest=digest("prefix"),
        isolation="main",
        cancel_epoch=0,
        loaded_skills=(bound,),
    )
    run.versions = {
        "model_version": f.route.version,
        "model_route_digest": f.route.digest,
        "tool_definitions": {"main": binding.tool_definitions_digest},
        "prompt_prefixes": {"main": binding.prompt_digest},
    }
    model = f.model
    model.tenant_id, model.call_key = setup.tenant, str(uuid4())
    model.input_digest, model.execution_binding = (
        digest("synthetic request"),
        binding.model_dump(mode="json"),
    )
    model.result = {
        "calls": [{"id": "untrusted-native", "name": f.spec.name, "arguments": f.arguments}]
    }
    f.source = WriteSource(skill=bound, model_call_id=model.id, response_index=0)
    f.qualification.tenant_id, f.qualification.skill_key = setup.tenant, skill.key
    f.qualification.qualified_skill_version = skill.version
    f.qualification.qualified_skill_digest = skill.digest
    f.qualification.qualified_tool_digest = tool_identity(skill, f.registry)
    f.qualification.reviewed_by = setup.human
    with tenant_session(
        setup.admin,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        session.expire_on_commit = False
        session.add(
            AgentSession(
                id=run.session_id,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                proposal_id=proposal_id,
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(run)
        session.flush()
        existing_qualification = session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == setup.tenant,
            TenantSkillEnablement.skill_key == skill.key,
        ))
        if existing_qualification is None:
            session.add(f.qualification)
        session.add_all(
            [
                model,
                AgentEvent(
                    id=bound.load_event_id,
                    tenant_id=setup.tenant,
                    run_id=run.id,
                    sequence=1,
                    body={
                        "type": "skill_loaded",
                        "key": bound.key,
                        "version": bound.version,
                        "digest": bound.digest,
                        "isolation": "main",
                    },
                ),
            ]
        )
    f.adapter = DomainCommands(
        setup.engine, catalog=f.catalog, registry=f.registry, route=lambda *_: f.route
    )
    return f


def counts(setup):
    verify_test_target(setup.admin)
    with Session(setup.admin) as session:
        return tuple(
            session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (Claim, Receipt, Audit, Outbox, RequestKey, AgentToolCall)
        )


def save(f):
    return f.adapter.execute(
        f.scope,
        f.spec.name,
        f.arguments,
        execution_key(f.scope.run_id, f.model.id, 0),
        source=f.source,
    )


def test_actual_common_claim_and_completed_recovery_need_only_current_read_access(setup):
    f = fixture(setup)
    before = counts(setup)
    result = save(f)
    after = counts(setup)
    assert tuple(b - a for a, b in zip(before, after, strict=True)) == (1, 1, 1, 1, 1, 1)
    with Session(setup.admin) as session, session.begin():
        receipt = session.get(Receipt, UUID(result["id"]))
        call = session.get(AgentToolCall, UUID(result["agent_call_id"]))
        claim = session.get(Claim, receipt.subject_id)
        assert receipt.agent_run_id == f.scope.run_id and receipt.run_id is None
        assert call.receipt_id == receipt.id and call.state == "completed"
        assert (
            claim.artifact_id == UUID(f.arguments["artifact_id"])
            and claim.product_id == setup.product
        )
        assert claim.writer_id == setup.agent and claim.human_owner_id == setup.human
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.agent
            )
        )
        grant.can_write = False
        qualification = session.get(TenantSkillEnablement, f.qualification.id)
        qualification.enabled, qualification.qualification_revoked = False, True
        artifact = session.get(Artifact, UUID(f.arguments["artifact_id"]))
        artifact.status = "withdrawn"
    key = execution_key(f.scope.run_id, f.model.id, 0)
    assert f.adapter.recover(f.scope, f.spec, f.arguments, key, source=f.source) == result
    assert counts(setup) == after


def test_actual_common_domain_failure_rolls_back_call_fact_and_receipt_group(setup):
    f = fixture(setup)
    before = counts(setup)

    def fail(session, *_):
        if any(isinstance(row, Outbox) and row.tenant_id == setup.tenant for row in session.new):
            raise RuntimeError("synthetic terminal outbox failure")

    event.listen(Session, "before_flush", fail)
    try:
        with pytest.raises(RuntimeError, match="terminal outbox"):
            save(f)
    finally:
        event.remove(Session, "before_flush", fail)
    assert counts(setup) == before
    assert save(f)["id"]


def test_actual_model_arguments_and_current_route_cannot_be_substituted(setup):
    f = fixture(setup)
    before = counts(setup)
    with pytest.raises(DomainError):
        f.adapter.execute(
            f.scope,
            f.spec.name,
            {**f.arguments, "statement": "substituted"},
            execution_key(f.scope.run_id, f.model.id, 0),
            source=f.source,
        )
    f.route = SimpleNamespace(version=f.route.version, digest=digest("rotated synthetic route"))
    with pytest.raises(DomainError):
        save(f)
    assert counts(setup) == before


def test_cross_run_existing_result_keeps_original_ownership_and_has_no_new_call(setup):
    first = fixture(setup)
    original = save(first)
    second = fixture(setup, artifact_id=UUID(first.arguments["artifact_id"]))
    before = counts(setup)
    existing = save(second)
    assert existing["existing_result"] is True
    assert existing["id"] == original["id"]
    assert existing["agent_run_id"] == str(first.scope.run_id)
    assert counts(setup) == before
    with Session(setup.admin) as session:
        assert session.get(Receipt, UUID(existing["id"])).agent_run_id == first.scope.run_id
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == second.scope.run_id,
            AgentToolCall.tool == first.spec.name)) == 0


def test_actual_read_tools_keep_root_metadata_and_exact_isolated_source_scope(setup):
    from pdos_next.agent_kernel.domain_reads import DomainReads
    from pdos_next.agent_kernel.persistence import KernelStore

    f = fixture(setup)
    reads = DomainReads(KernelStore(setup.engine), f.adapter)
    category = reads.call(f.scope, {}, name="category.read")
    assert category["id"] == str(setup.category)
    metadata = reads.call(f.scope, {}, name="evidence.search")["items"]
    assert [row["artifact_id"] for row in metadata] == [f.arguments["artifact_id"]]
    assert all("content" not in row and "lines" not in row for row in metadata)
    identity = UUID(f.arguments["artifact_id"])
    args = {"artifact_version_id": str(identity)}
    with pytest.raises(DomainError) as denied:
        reads.call(f.scope, args, name="evidence.artifact.read")
    assert denied.value.code == "FORBIDDEN_SCOPE"
    child = f.scope.child("extract", artifact_ids={identity})
    actual = reads.call(child, args, name="evidence.artifact.read")
    assert actual["blocks"] == [{"locator": "line:1", "text": f.arguments["quote"],
                                 "derived_line_start": 1, "derived_line_end": 1}]
    assert actual["next_cursor"] is None and actual["revision"] == 1
    with pytest.raises(DomainError):
        reads.call(child, {"artifact_version_id": str(uuid4())}, name="evidence.artifact.read")
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    with pytest.raises(DomainError) as stale:
        reads.call(child, args, name="evidence.artifact.read")
    assert stale.value.code == "SOURCE_UNAVAILABLE"
