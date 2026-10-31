"""Atomic snapshot registration and cross-requester Unicode reads, ordinary roles."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, WriteSource, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.disclosure import binding_operations, disclosure_digest
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.m3_calculators import ENGINES
from pdos_next.agent_kernel.models import AgentRun, PublicWebSnapshot, TenantSkillEnablement
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.registered_snapshot_reads import RegisteredSnapshotReads
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.research_read_ledger import page_result as raw_page_result
from pdos_next.agent_kernel.snapshot_read_ledger import validate_snapshot_read
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, now
from pdos_next.research.service import ResearchChild, ResearchService
from pdos_next.research.types import ReadPage, ResearchTask, Snapshot
from pdos_next.research.web import ResourceLimits
from tests.agent_kernel.research.test_research import service as synthetic_service
from tests.agent_kernel.test_read_proof_transactions import read_fixture
from tests.preproject.test_g0 import create
from tests.preproject.test_g0 import read as read_proposal


def model_for(f, tool, arguments, *, isolation="main"):
    scope = f.scope.child(isolation)
    previous = ModelBinding.model_validate(f.model.execution_binding)
    loaded = () if isolation != "main" else previous.loaded_skills
    binding = previous.model_copy(update={
        "isolation": isolation,
        "tool_definitions_digest": disclosure_digest(
            f.registry, isolation, binding_operations(f.catalog, loaded),
        ),
        "loaded_skills": loaded,
    })
    with f.store.transaction(scope, lock=True) as (_, run):
        run.versions = {
            **run.versions,
            "tool_definitions": {**run.versions["tool_definitions"],
                                 isolation: binding.tool_definitions_digest},
            "prompt_prefixes": {**run.versions["prompt_prefixes"],
                                isolation: binding.prompt_digest},
        }
    identity, _ = f.store.claim(
        scope, "snapshot-model:" + str(uuid4()), "model", {"fixture": True},
        execution_binding=binding.model_dump(mode="json"),
    )
    f.store.settle(scope, identity, result={"calls": [{"name": tool, "arguments": arguments}]})
    return ReadSource(model_call_id=identity, response_index=0)


def registration(setup, tmp_path, *, human=False):
    f = read_fixture(setup)
    artifacts = ResearchArtifacts(tmp_path, current=f.store.current)
    body = "合成目录😀\r\n单价 3.125 CNY，数量 2\r\n尚未读取末行"
    snapshot = Snapshot(
        uuid4(), "https://synthetic.test/snapshot", "https://synthetic.test/snapshot",
        "合成快照", "fixture", now(), body, hashlib.sha256(body.encode()).hexdigest(),
        "synthetic", "unknown",
    )
    artifacts.save_snapshot(f.scope, snapshot)
    arguments = {"url": snapshot.url, "cursor": 0}
    source = model_for(f, "research.read", arguments, isolation="research")
    scope = f.scope.child("research")
    page = ReadPage(snapshot, f"chars:0:{len(body)}", body, None)
    f.host.read_callback(
        scope, f.registry.get("research.read"), arguments,
        execution_key(scope.run_id, source.model_call_id, 0), source=source,
        callback=lambda *_: raw_page_result(page),
    )
    source = model_for(f, "research.snapshot.register", {"snapshot_id": str(snapshot.id)})
    spec = f.registry.get("research.snapshot.register")
    key = execution_key(f.scope.run_id, source.model_call_id, 0)
    bootstrap = Bootstrap(setup.engine, ports=RuntimePorts(research_artifacts=artifacts))
    bootstrap.route = lambda *_: f.route
    if human:
        with Session(setup.admin) as session, session.begin():
            session.get(TenantSkillEnablement, f.qualification.id).qualification_revoked = True
        prepared = bootstrap.prepare_candidate(
            f.scope, spec, {"snapshot_id": str(snapshot.id)}, key,
        )
        path = f"/v1/categories/{setup.category}/commands"
        preview = setup.client.post(path + "/preview", headers=setup.headers,
                                    json=prepared["command"])
        assert preview.status_code == 200, preview.text
        saved = setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
        assert saved.status_code == 200, saved.text
        receipt = saved.json()
    else:
        f.adapter.artifacts = artifacts
        receipt = f.adapter.execute(
            f.scope, spec.name, {"snapshot_id": str(snapshot.id)}, key,
            source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                               response_index=0),
        )
    return f, snapshot, receipt


@pytest.mark.parametrize("human", [False, True])
def test_actual_atomic_snapshot_registration_t0_and_t1(setup, tmp_path, human):
    f, snapshot, saved = registration(setup, tmp_path, human=human)
    with Session(setup.admin) as session:
        row = session.get(PublicWebSnapshot, snapshot.id)
        receipt = session.get(Receipt, UUID(saved["id"]))
        assert row.markdown == snapshot.markdown and row.receipt_id == receipt.id
        assert receipt.result["proof_version"] == 1
        assert receipt.result["registered_by_run_id"] == str(f.scope.run_id)
        assert receipt.agent_run_id == f.scope.run_id
        assert receipt.actor_id == (setup.human if human else setup.agent)
        assert (receipt.confirmation_id is not None) == human


def registered_page(f, snapshot, *, cursor, page_chars):
    scope = f.scope.child("research")
    arguments = {"url": snapshot.url, "cursor": cursor}
    source = model_for(f, "research.read", arguments, isolation="research")

    async def no_search(*_):
        raise AssertionError("No actual external search or fetch is permitted in this fixture")

    service = ResearchService(
        SimpleNamespace(provider="synthetic", search=no_search), egress=lambda *_: True,
        limits=ResourceLimits(page_chars=page_chars),
    )
    service.register_user_message(scope, snapshot.url)
    child = ResearchChild(service, scope, ResearchTask("reuse", "Synthetic reuse"))
    port = RegisteredSnapshotReads(f.store)
    key = execution_key(scope.run_id, source.model_call_id, 0)
    return port.read(f.host, child, f.registry.get("research.read"), arguments, key, source=source)


def test_actual_cross_requester_snapshot_read_keeps_original_run_private(setup, tmp_path):
    original, snapshot, _ = registration(setup, tmp_path)
    peer = SimpleNamespace(**vars(setup))
    peer.human = setup.peer
    peer.ctx = replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer)
    f = read_fixture(peer)
    cursor = len(snapshot.markdown.splitlines(keepends=True)[0])
    page = registered_page(f, snapshot, cursor=cursor, page_chars=20)
    with f.store.transaction(f.scope) as (session, _):
        assert session.get(AgentRun, original.scope.run_id) is None
        proven = validate_snapshot_read(
            session, f.scope, snapshot.id, 1, 2, "单价 3.125 CNY",
            call_id=UUID(page["execution_ref"]["call_id"]),
        )
        assert proven.snapshot_id == snapshot.id
        with pytest.raises(DomainError):
            validate_snapshot_read(
                session, f.scope, snapshot.id, 1, 3, "尚未读取末行",
                call_id=proven.call_id,
            )


def test_marked_snapshot_without_actual_call_cannot_be_inserted(setup, tmp_path):
    f, snapshot, _ = registration(setup, tmp_path)
    with pytest.raises(DBAPIError):
        with f.store.transaction(f.scope) as (session, _):
            source = session.get(PublicWebSnapshot, snapshot.id)
            forged = PublicWebSnapshot(**{
                col.name: getattr(source, col.name) for col in PublicWebSnapshot.__table__.columns
                if col.name not in {"id", "created_at"}
            }, id=uuid4())
            session.add(forged)


def test_cross_run_snapshot_claim_needs_actual_current_run_page(setup, tmp_path):
    _, snapshot, _ = registration(setup, tmp_path)
    f = read_fixture(setup)
    cursor = len(snapshot.markdown.splitlines(keepends=True)[0])
    registered_page(f, snapshot, cursor=cursor, page_chars=20)
    spec = f.registry.get("evidence.claim.record")
    arguments = {
        "source": {"kind": "snapshot", "id": str(snapshot.id), "version": 1,
                   "line": 2, "quote": "单价 3.125 CNY"},
        "nature": "extracted", "content": {"text": "单价 3.125 CNY"},
    }
    source = model_for(f, spec.name, arguments)
    saved = f.adapter.execute(
        f.scope, spec.name, arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0),
        source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                           response_index=0),
    )
    from pdos_next.models import Claim

    with Session(setup.admin) as session:
        receipt = session.get(Receipt, UUID(saved["id"]))
        claim = session.get(Claim, receipt.subject_id)
        assert claim.snapshot_id == snapshot.id and claim.run_id == f.scope.run_id
    unread = {**arguments, "source": {**arguments["source"], "line": 3, "quote": "尚未读取末行"}}
    source = model_for(f, spec.name, unread)
    with pytest.raises(DomainError):
        f.adapter.execute(
            f.scope, spec.name, unread, execution_key(f.scope.run_id, source.model_call_id, 0),
            source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                               response_index=0),
        )


def test_cross_run_snapshot_link_requires_whole_locator_in_actual_page(setup, tmp_path):
    _, snapshot, _ = registration(setup, tmp_path)
    proposal_id, _ = create(setup)
    item = read_proposal(setup, proposal_id).json()["items"][0]
    category_scope = SimpleNamespace(**vars(setup))
    category_scope.product = None
    f = read_fixture(
        category_scope, proposal_id=UUID(proposal_id), skill_key="proposal_drafting",
    )
    cursor = len(snapshot.markdown.splitlines(keepends=True)[0])
    registered_page(f, snapshot, cursor=cursor, page_chars=20)
    spec = f.registry.get("evidence.link.create")
    arguments = {
        "evidence": {"type": "snapshot", "id": str(snapshot.id), "version": 1,
                     "locator": "line:2"},
        "target": {"type": "proposal_item", "id": item["item_id"],
                   "version": item["version"]},
        "relation": "supports",
    }
    source = model_for(f, spec.name, arguments)
    saved = f.adapter.execute(
        f.scope, spec.name, arguments, execution_key(f.scope.run_id, source.model_call_id, 0),
        source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                           response_index=0),
    )
    linked = read_proposal(setup, proposal_id).json()["items"][0]["evidence_links"]
    assert linked[0]["id"] == saved["result"]["link_id"]
    unread = {**arguments, "evidence": {**arguments["evidence"], "locator": "line:3"}}
    source = model_for(f, spec.name, unread)
    with pytest.raises(DomainError):
        f.adapter.execute(
            f.scope, spec.name, unread, execution_key(f.scope.run_id, source.model_call_id, 0),
            source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                               response_index=0),
        )


def test_computed_claim_can_consume_proven_cross_run_snapshot(setup, tmp_path):
    _, snapshot, _ = registration(setup, tmp_path)
    f = read_fixture(setup)
    cursor = len(snapshot.markdown.splitlines(keepends=True)[0])
    registered_page(f, snapshot, cursor=cursor, page_chars=20)
    source_ref = {"type": "snapshot", "id": str(snapshot.id), "version": 1,
                  "line": 2, "quote": "单价 3.125 CNY"}
    arguments = {"lines": [{"label": "合成报价", "qty": "2", "unit_cost": "3.125",
                            "currency": "CNY", "as_of": "2026-10-10",
                            "source_ref": source_ref}]}
    source = model_for(f, "calc.cost_subtotal", arguments)
    computed = f.host.read(
        f.scope, f.registry.get("calc.cost_subtotal"), arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0), source=source,
    )
    content = computed["proof_claims"]["single_currency_subtotal"]
    assert content == ENGINES["calc.cost_subtotal"].calculate(arguments)["proof_claims"][
        "single_currency_subtotal"
    ]
    claim = {
        "source": {"kind": "snapshot", "id": str(snapshot.id), "version": 1,
                   "line": 2, "quote": "单价 3.125 CNY"},
        "nature": "computed", "availability": "known", "content": content,
        "extraction_ref": {"call_id": computed["execution_ref"]["call_id"],
                           "result_path": ["proof_claims", "single_currency_subtotal"]},
    }
    source = model_for(f, "evidence.claim.record", claim)
    saved = f.adapter.execute(
        f.scope, "evidence.claim.record", claim,
        execution_key(f.scope.run_id, source.model_call_id, 0),
        source=WriteSource(skill=f.source.skill, model_call_id=source.model_call_id,
                           response_index=0),
    )
    with Session(setup.admin) as session:
        from pdos_next.models import Claim

        receipt = session.get(Receipt, UUID(saved["id"]))
        actual = session.get(Claim, receipt.subject_id)
        assert actual.nature == "computed" and actual.content == content
        assert actual.snapshot_id == snapshot.id and actual.run_id == f.scope.run_id


def test_actual_bootstrap_search_seals_object_and_replays_without_provider(setup, tmp_path):
    f = read_fixture(setup, tool="research.search", arguments={"query": "synthetic pump"})
    artifacts = ResearchArtifacts(tmp_path, current=f.store.current)
    runtime = synthetic_service()
    bootstrap = Bootstrap(setup.engine, ports=RuntimePorts(
        research_service=runtime, research_artifacts=artifacts,
    ))
    bootstrap.route = lambda *_: f.route
    host = BoundHost(bootstrap.store, bootstrap.adapters())
    first = host.read(
        f.scope, f.read_spec, f.read_arguments, f.read_key, source=f.read_source,
    )
    assert first["hits"] and first["provider"] == runtime.search_adapter.provider
    assert runtime.search_adapter.queries == ["synthetic pump"]
    # Fresh process memory still rehydrates the sealed result and original URL grants.
    replacement = synthetic_service()
    recovered = Bootstrap(setup.engine, ports=RuntimePorts(
        research_service=replacement, research_artifacts=artifacts,
    ))
    recovered.route = lambda *_: f.route
    replay = BoundHost(recovered.store, recovered.adapters()).read(
        f.scope, f.read_spec, f.read_arguments, f.read_key, source=f.read_source,
    )
    assert replay == first and replacement.search_adapter.queries == []
    key = f.scope.tenant_id, f.scope.requester_id, f.scope.session_id, f.scope.run_id
    assert replacement._allowlists[key] == {hit["url"] for hit in first["hits"]}
