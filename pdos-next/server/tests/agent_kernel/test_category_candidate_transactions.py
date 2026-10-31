"""Personal category T1 in the marked PostgreSQL fixture; synthetic model ledger only."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.disclosure import disclosure, skill_operations
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentSession,
    PublicWebSnapshot,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.research_read_ledger import page_result
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_creation_models import CategoryCreationConfirmation
from pdos_next.domain.preproject.category_models import KnowledgeEntry, ParameterVersion
from pdos_next.models import Audit, Category, Grant, Outbox, Receipt, RequestKey
from pdos_next.research.types import ReadPage, Snapshot
from pdos_next.service import digest
from tests.agent_kernel.test_execution_binding import ledger


def personal_fixture(setup, tmp_path, *, sources=True):
    f = ledger()
    f.scope = replace(
        f.scope,
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=None,
        product_id=None,
        proposal_id=None,
    )
    for name in (
        "tenant_id",
        "requester_id",
        "writer_id",
        "category_id",
        "product_id",
        "proposal_id",
    ):
        setattr(f.run, name, getattr(f.scope, name))
    f.run.trigger, f.run.goal = f.scope.trigger, "合成个人新品类研究"
    f.run.intent_key, f.run.intent_digest = str(uuid4()), digest(str(uuid4()))
    f.run.read_sources = []
    skill = f.catalog._skills["category_framing"]
    bound = SkillBinding(
        key=skill.key, version=skill.version, digest=skill.digest, load_event_id=uuid4()
    )
    binding = ModelBinding(
        model_version=f.route.version,
        model_route_digest=f.route.digest,
        tool_definitions_digest=digest(disclosure(f.registry, "main", skill_operations([skill]))),
        prompt_digest=digest("prefix"),
        isolation="main",
        cancel_epoch=0,
        loaded_skills=(bound,),
    )
    f.run.versions = {
        "model_version": f.route.version,
        "model_route_digest": f.route.digest,
        "tool_definitions": {
            "main": binding.tool_definitions_digest,
            "research": digest(f.registry.definitions("research")),
        },
        "prompt_prefixes": {"main": binding.prompt_digest, "research": digest("research prefix")},
    }
    with tenant_session(setup.admin, setup.tenant, actor_id=setup.human) as session:
        session.expire_on_commit = False
        session.add(
            AgentSession(
                id=f.scope.session_id,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                category_id=None,
            )
        )
        session.flush()
        session.add(f.run)
        session.flush()
        session.add_all(
            [
                TenantSkillEnablement(
                    tenant_id=setup.tenant,
                    skill_key=skill.key,
                    enabled=True,
                    pilot=False,
                    qualification_revoked=True,
                ),
                AgentEvent(
                    id=bound.load_event_id,
                    tenant_id=setup.tenant,
                    run_id=f.run.id,
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
    f.store = KernelStore(setup.engine)

    def current(scope):
        with f.store.transaction(scope) as (session, _):
            f.store.authority(session, scope)

    f.artifacts = ResearchArtifacts(tmp_path / "research", current=current)
    f.bootstrap = Bootstrap(setup.engine, ports=RuntimePorts(research_artifacts=f.artifacts))
    f.bootstrap.route = lambda *_: f.route
    f.spec = f.bootstrap.registry.get("category.create")
    f.arguments = {
        "key": "synthetic-" + uuid4().hex,
        "name": "合成品类",
        "purpose": "明确范围",
        "groups": {
            "knowledge": [{"kind": "boundary", "content": {"definition": "范围"}}],
            "parameters": [
                {
                    "key": "pressure",
                    "name": "压力",
                    "value_type": "number",
                    "direction": "higher",
                    "change_note": "合成初始参数",
                }
            ],
        },
    }
    if sources:
        body = "Header\r\n公共证据 💡 repeat repeat\r\nUnread tail"
        f.snapshot = Snapshot(
            uuid4(),
            "https://example.test/article",
            "https://example.test/article",
            "Synthetic",
            "",
            datetime(2026, 10, 11, tzinfo=UTC),
            body,
            sha256(body.encode()).hexdigest(),
            "synthetic",
            "public_web",
        )
        research = replace(f.scope, isolation="research")
        f.artifacts.save_snapshot(research, f.snapshot)
        read_args = {"url": f.snapshot.url, "cursor": 8}
        read_binding = ModelBinding(
            model_version=f.route.version,
            model_route_digest=f.route.digest,
            tool_definitions_digest=f.run.versions["tool_definitions"]["research"],
            prompt_digest=f.run.versions["prompt_prefixes"]["research"],
            isolation="research",
            cancel_epoch=0,
        )
        model, _ = f.store.claim(
            research,
            "synthetic-read-model:" + str(uuid4()),
            "model",
            {},
            execution_binding=read_binding.model_dump(mode="json"),
        )
        f.store.settle(
            research, model, result={"calls": [{"name": "research.read", "arguments": read_args}]}
        )
        end = body.index("\r\n", 8)
        page = page_result(ReadPage(f.snapshot, f"chars:8:{end}", body[8:end], end))
        host = BoundHost(
            f.store,
            KernelAdapters(
                route_for=lambda *_: f.route,
                project_context=lambda *_: {},
                verify_result=lambda *a: a[1],
                prepare_candidate=lambda *_: None,
                execute_command=lambda *_: None,
                tool_registry=f.registry,
                read_tools={"research.read": lambda *_: page},
            ),
        )
        actual = host.read(
            research,
            f.registry.get("research.read"),
            read_args,
            execution_key(f.run.id, model, 0),
            source=ReadSource(model_call_id=model, response_index=0),
        )
        f.read_id = UUID(actual["execution_ref"]["call_id"])
        f.arguments["groups"]["snapshot_refs"] = [
            {"call_id": str(f.read_id), "content_hash": f.snapshot.content_hash}
        ]
        f.arguments["groups"]["knowledge"][0]["source_refs"] = [
            {
                "type": "snapshot",
                "id": str(f.snapshot.id),
                "version": 1,
                "line": 2,
                "quote": "公共证据 💡",
            }
        ]
    f.model_id, _ = f.store.claim(
        f.scope,
        "synthetic-category-model:" + str(uuid4()),
        "model",
        {},
        execution_binding=binding.model_dump(mode="json"),
    )
    f.store.settle(
        f.scope, f.model_id, result={"calls": [{"name": f.spec.name, "arguments": f.arguments}]}
    )
    f.key = execution_key(f.run.id, f.model_id, 0)
    f.candidate = f.bootstrap.prepare_candidate(f.scope, f.spec, f.arguments, f.key)
    return f


def adopted(setup, f, *, omit=()):
    payload = deepcopy(f.candidate["payload"])
    payload["deidentified_confirmed"] = True
    for group in omit:
        payload["groups"][group] = []
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=payload)
    assert preview.status_code == 200, preview.json()
    payload["confirmation_token"] = preview.json()["confirmation_token"]
    diagnostics = []

    def record_error(context):
        diagnostics.append(str(context.original_exception))

    event.listen(setup.engine, "handle_error", record_error)
    try:
        response = setup.client.post("/v1/categories", headers=setup.headers, json=payload)
    finally:
        event.remove(setup.engine, "handle_error", record_error)
    assert response.status_code == 201, (response.json(), diagnostics)
    return response.json(), payload


def counts(setup):
    with Session(setup.admin) as session:
        return tuple(
            session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (
                Category,
                KnowledgeEntry,
                ParameterVersion,
                PublicWebSnapshot,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        )


def test_personal_candidate_actual_t1_sources_signature_and_replay(setup, tmp_path):
    f = personal_fixture(setup, tmp_path)
    assert f.bootstrap.prepare_candidate(f.scope, f.spec, f.arguments, f.key) == f.candidate
    before = counts(setup)
    receipt, payload = adopted(setup, f)
    assert tuple(b - a for a, b in zip(before, counts(setup), strict=True)) == (1,) * 8
    category_id = UUID(receipt["subject_id"])
    with Session(setup.admin) as session:
        category = session.get(Category, category_id)
        assert category.created_by_run_id == f.run.id and category.owner_id == setup.human
        for cls in (KnowledgeEntry, ParameterVersion):
            row = session.scalar(select(cls).where(cls.category_id == category_id))
            assert row.origin == "ai_draft" and row.run_id == f.run.id
            assert row.writer_id == setup.agent and row.confirmed_by == setup.human
        snapshot = session.get(PublicWebSnapshot, f.snapshot.id)
        assert snapshot.category_id == category_id and snapshot.markdown == f.snapshot.markdown
        assert snapshot.registered_by_run_id == f.run.id
        assert (
            session.scalar(
                select(Grant.id).where(
                    Grant.category_id == category_id, Grant.principal_id == setup.agent
                )
            )
            is None
        )
        persisted = session.get(Receipt, UUID(receipt["id"]))
        assert persisted.agent_run_id is None and persisted.result["proof_version"] == 1
        assert persisted.result["groups_digest"] == digest(payload["groups"])
    replay = setup.client.post("/v1/categories", headers=setup.headers, json=payload)
    assert replay.status_code == 201 and replay.json() == receipt
    assert counts(setup) == tuple(a + 1 for a in before)


@pytest.mark.parametrize(
    "omit", [("knowledge",), ("parameters",), ("knowledge", "parameters", "snapshot_refs")]
)
def test_personal_candidate_whole_groups_may_be_omitted(setup, tmp_path, omit):
    f = personal_fixture(setup, tmp_path)
    receipt, payload = adopted(setup, f, omit=omit)
    assert receipt["result"]["groups"] == payload["groups"]


@pytest.mark.parametrize(
    "change", ["wrong_person", "name", "partial_group", "unread_quote", "cancelled"]
)
def test_actual_candidate_rejects_changed_identity_content_or_sources(setup, tmp_path, change):
    f = personal_fixture(setup, tmp_path)
    payload, headers = deepcopy(f.candidate["payload"]), setup.headers
    payload["deidentified_confirmed"] = True
    if change == "wrong_person":
        headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    elif change == "name":
        payload["name"] += "changed"
    elif change == "partial_group":
        payload["groups"]["parameters"][0]["name"] += "changed"
    elif change == "unread_quote":
        payload["groups"]["knowledge"][0]["source_refs"][0]["quote"] = "Unread tail"
    else:
        with f.store.transaction(f.scope, lock=True) as (_, run):
            run.state = "cancelled"
            run.cancel_epoch += 1
    before = counts(setup)
    response = setup.client.post("/v1/categories/preview", headers=headers, json=payload)
    assert response.status_code != 200
    assert counts(setup) == before


def test_category_transaction_failure_rolls_back_every_fact_and_confirmation(setup, tmp_path):
    f = personal_fixture(setup, tmp_path)
    payload = deepcopy(f.candidate["payload"])
    payload["deidentified_confirmed"] = True
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=payload)
    assert preview.status_code == 200
    payload["confirmation_token"] = preview.json()["confirmation_token"]
    before = counts(setup)

    def fail(session, *_):
        if any(isinstance(row, Outbox) and row.tenant_id == setup.tenant for row in session.new):
            raise RuntimeError("synthetic category outbox failure")

    event.listen(Session, "before_flush", fail)
    try:
        with pytest.raises(RuntimeError, match="category outbox"):
            setup.client.post("/v1/categories", headers=setup.headers, json=payload)
    finally:
        event.remove(Session, "before_flush", fail)
    assert counts(setup) == before
    with Session(setup.admin) as session:
        confirmation = session.scalar(
            select(CategoryCreationConfirmation).where(
                CategoryCreationConfirmation.token_hash == digest(payload["confirmation_token"])
            )
        )
        assert not confirmation.consumed
    assert (
        setup.client.post("/v1/categories", headers=setup.headers, json=payload).status_code == 201
    )


def test_sql_cannot_insert_ai_category_without_actual_receipt_or_change_run_identity(
    setup, tmp_path
):
    f = personal_fixture(setup, tmp_path, sources=False)
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as session:
            session.add(
                Category(
                    tenant_id=setup.tenant,
                    owner_id=setup.human,
                    key="forged-" + uuid4().hex,
                    name="forged",
                    purpose="forged",
                    created_by_run_id=f.run.id,
                )
            )
    receipt, _ = adopted(setup, f)
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            category_id=UUID(receipt["subject_id"]),
        ) as session:
            row = session.get(Category, UUID(receipt["subject_id"]))
            row.created_by_run_id = None
            session.flush()
