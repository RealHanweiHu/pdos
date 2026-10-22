"""Actual T0/T1 receipts extend one proposal Run; synthetic models and qualifications only."""
# ruff: noqa: F811 -- explicitly imported marked PG fixtures

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import WriteSource, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.proposal_context import KEY
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.research_read_ledger import page_result
from pdos_next.errors import DomainError
from pdos_next.models import Claim, Confirmation, Receipt, now
from pdos_next.research.types import ReadPage, Snapshot
from pdos_next.service import digest
from tests.agent_kernel import test_domain_adapter_transactions as domain_fixture
from tests.agent_kernel.test_domain_adapter_transactions import counts
from tests.agent_kernel.test_proposal_context_pg import read
from tests.agent_kernel.test_snapshot_proof_transactions import model_for
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_evidence_commands_pg import evidence_request
from tests.preproject.test_g0 import create, post, request, save
from tests.preproject.test_g0 import work as work


def bound(work, monkeypatch):
    proposal_id, _ = create(work)
    setup = SimpleNamespace(**vars(work))
    setup.product = None
    original = domain_fixture.ledger

    def ledger():
        f = original()
        f.scope = replace(f.scope, private_context=True, data_categories=frozenset({"internal"}))
        f.run.private_context, f.run.data_categories = True, ["internal"]
        return f

    with monkeypatch.context() as patch:
        patch.setattr(domain_fixture, "ledger", ledger)
        f = domain_fixture.fixture(setup, proposal_id=UUID(proposal_id))
    f.store = KernelStore(work.engine)
    f.owner = Bootstrap(work.engine)
    f.owner.route = lambda *_: f.route
    from pdos_next.agent_kernel.api import StartInput

    with human_session(work) as session:
        facts = f.owner.binding_for(
            session,
            work.ctx,
            StartInput(
                goal="Synthetic continuing proposal",
                idempotency_key=str(uuid4()),
                proposal_id=UUID(proposal_id),
                sources=[{"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}],
            ),
        )
    assert facts.private_context and set(facts.data_categories) == f.scope.data_categories
    with f.store.transaction(f.scope, lock=True) as (_, run):
        assert run.read_sources == facts.read_sources
        run.versions = {**run.versions, KEY: facts.outbound_context}
    f.host = BoundHost(
        f.store, replace(f.owner.adapters(), route_for=lambda _: f.route, tool_registry=f.registry)
    )
    return f


def source_for(f, tool, arguments):
    actual = model_for(f, tool, arguments)
    return WriteSource(skill=f.source.skill, model_call_id=actual.model_call_id, response_index=0)


def execute(f, tool, arguments, *, human=False):
    source = source_for(f, tool, arguments)
    intent = execution_key(f.scope.run_id, source.model_call_id, 0)
    if human:
        candidate = f.owner.prepare_candidate(f.scope, f.registry.get(tool), arguments, intent)
        path = f"/v1/categories/{f.scope.category_id}/commands"
        response = f.client.post(path + "/preview", headers=f.headers, json=candidate["command"])
        assert response.status_code == 200, response.text
        command = response.json()["command"]
        response = f.client.post(path, headers=f.headers, json=command)
        assert response.status_code == 200, response.text

        def replay():
            return f.client.post(path, headers=f.headers, json=command).json()

        return response.json(), replay
    result = f.adapter.execute(f.scope, tool, arguments, intent, source=source)
    return result, lambda: f.adapter.execute(f.scope, tool, arguments, intent, source=source)


def current(f):
    with f.store.transaction(f.scope) as (_, run):
        return digest(run.versions), list(run.versions[KEY]["references"])


def claim_args(f):
    return {**f.arguments, "visibility": "audience"}


def attach(work, f, kind, identity):
    response = post(
        work,
        request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": str(f.scope.proposal_id),
                "ops": [
                    {
                        "kind": "section",
                        "content": {"key": "summary", "text": "Synthetic newly adopted evidence"},
                        "source_refs": [
                            {
                                "type": kind,
                                "id": str(identity),
                                "version": 1,
                                **(
                                    {"line": 1, "quote": "Synthetic public snapshot"}
                                    if kind == "snapshot"
                                    else {}
                                ),
                            }
                        ],
                    }
                ],
            },
        ),
    )
    assert response.status_code == 200, response.text
    assert read(f.owner, f.scope, "proposal.items.read")["items"]
    assert f.owner.project_context(f.scope, "Continue original proposal")["proposal"]["id"] == str(
        f.scope.proposal_id
    )


@pytest.mark.parametrize("human", [False, True])
def test_new_claim_can_be_adopted_read_and_replayed_in_original_run(work, monkeypatch, human):
    f = bound(work, monkeypatch)
    f.client, f.headers = work.client, work.headers
    before = current(f)[1]
    receipt, replay = execute(f, "evidence.claim.record", claim_args(f), human=human)
    identity = UUID(receipt["subject_id"])
    after = current(f)
    assert {ref["type"] for ref in after[1]} >= {"claim", "artifact"}
    assert not any(ref["id"] == str(identity) for ref in before)
    attach(work, f, "claim", identity)
    assert replay()["id"] == receipt["id"] and current(f) == after
    with Session(work.admin) as session:
        row = session.get(Claim, identity)
        assert row.run_id == f.scope.run_id and row.writer_id == f.scope.writer_id
        assert row.confirmed_by == (work.human if human else None)
    from pdos_next.agent_kernel.proposal_context import check

    check(f.store, f.scope)


def retained_snapshot(f, tmp_path):
    artifacts = ResearchArtifacts(tmp_path, current=f.store.current)
    body = "Synthetic public snapshot\nRegistered without a network request.\n"
    snapshot = Snapshot(
        uuid4(),
        "https://synthetic.test/admission",
        "https://synthetic.test/admission",
        "Synthetic snapshot",
        "Fixture",
        now(),
        body,
        hashlib.sha256(body.encode()).hexdigest(),
        "synthetic",
        "public_web",
    )
    artifacts.save_snapshot(f.scope, snapshot)
    args = {"url": snapshot.url, "cursor": 0}
    source = model_for(f, "research.read", args, isolation="research")
    child = f.scope.child("research")
    f.host.read_callback(
        child,
        f.registry.get("research.read"),
        args,
        execution_key(child.run_id, source.model_call_id, 0),
        source=source,
        callback=lambda *_: page_result(ReadPage(snapshot, f"chars:0:{len(body)}", body, None)),
    )
    f.adapter.artifacts, f.owner.commands.artifacts = artifacts, artifacts
    f.owner.engine._pdos_research_artifacts = artifacts
    return snapshot


@pytest.mark.parametrize("human", [False, True])
def test_new_snapshot_then_claim_continue_in_same_run(work, monkeypatch, tmp_path, human):
    f = bound(work, monkeypatch)
    f.client, f.headers = work.client, work.headers
    snapshot = retained_snapshot(f, tmp_path)
    registered, replay = execute(
        f, "research.snapshot.register", {"snapshot_id": str(snapshot.id)}, human=human
    )
    assert any(ref["type"] == "snapshot" and ref["id"] == str(snapshot.id) for ref in current(f)[1])
    attach(work, f, "snapshot", snapshot.id)
    before = current(f)
    assert replay()["id"] == registered["id"] and current(f) == before
    arguments = {
        "source": {
            "kind": "snapshot",
            "id": str(snapshot.id),
            "version": 1,
            "line": 1,
            "quote": "Synthetic public snapshot",
        },
        "nature": "extracted",
        "content": {"text": "Synthetic public snapshot"},
    }
    receipt, _ = execute(f, "evidence.claim.record", arguments, human=human)
    assert any(
        ref["type"] == "claim" and ref["id"] == receipt["subject_id"] for ref in current(f)[1]
    )
    with Session(work.admin) as session:
        assert session.get(PublicWebSnapshot, snapshot.id).visibility == "private"
        assert session.get(Receipt, UUID(registered["id"])).agent_run_id == f.scope.run_id
    assert read(f.owner, f.scope)["id"] == str(f.scope.proposal_id)


@pytest.mark.parametrize("human", [False, True])
def test_admission_rolls_back_with_receipt_and_retries_without_duplicate(work, monkeypatch, human):
    f = bound(work, monkeypatch)
    args = claim_args(f)
    source = source_for(f, "evidence.claim.record", args)
    intent = execution_key(f.scope.run_id, source.model_call_id, 0)
    if human:
        candidate = f.owner.prepare_candidate(
            f.scope, f.registry.get("evidence.claim.record"), args, intent
        )
        checked = post(work, candidate["command"], preview=True)
        assert checked.status_code == 200, checked.text
        command = checked.json()["command"]

        def perform():
            response = post(work, command)
            assert response.status_code == 200, response.text
            return response.json()
    else:

        def perform():
            return f.adapter.execute(f.scope, "evidence.claim.record", args, intent, source=source)

    before, business = current(f), counts(work)

    def fail(_c, _cursor, statement, *_args):
        if statement.startswith("UPDATE agent_runs SET versions"):
            raise RuntimeError("Synthetic context admission tail failure")

    event.listen(work.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="context admission tail failure"):
            perform()
    finally:
        event.remove(work.engine, "before_cursor_execute", fail)
    assert current(f) == before and counts(work) == business
    if human:
        with Session(work.admin) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
                )
            )
            assert not confirmation.consumed
    result = perform()
    assert any(ref["id"] == result["subject_id"] for ref in current(f)[1])


def test_newly_admitted_claim_withdrawal_still_stops_original_run(work, monkeypatch):
    f = bound(work, monkeypatch)
    receipt, _ = execute(f, "evidence.claim.record", claim_args(f))
    save(
        work,
        evidence_request(
            work,
            "evidence.claim.withdraw",
            {
                "claim_id": receipt["subject_id"],
                "expected_version": 1,
                "reason": "Synthetic withdrawal",
            },
        ),
    )
    with pytest.raises(DomainError):
        read(f.owner, f.scope)


def test_registered_graph_records_new_claim_adopts_it_and_finishes_without_new_run(
    work, monkeypatch
):
    import json

    from pdos_next.agent_kernel.api import StartInput
    from pdos_next.agent_kernel.graph import AgentKernel
    from pdos_next.agent_kernel.models import TenantSkillEnablement
    from pdos_next.agent_kernel.persistence import create_run
    from pdos_next.agent_kernel.types import ModelTurn, ToolCall
    from pdos_next.providers.types import ProviderUsage
    from tests.agent_kernel.test_gateway import Client, configured_route
    from tests.agent_kernel.test_proposal_context_pg import agree

    f = bound(work, monkeypatch)
    route = configured_route()
    f.owner.route = f.owner.commands.route = lambda *_: route
    with human_session(work) as session:
        facts = f.owner.binding_for(
            session,
            work.ctx,
            StartInput(
                goal="Synthetic proposal evidence adoption",
                idempotency_key=str(uuid4()),
                proposal_id=f.scope.proposal_id,
                sources=[{"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}],
            ),
        )
        run_id = create_run(
            session,
            work.ctx,
            goal="Synthetic proposal evidence adoption",
            writer_id=work.agent,
            intent_key=str(uuid4()),
            proposal_id=f.scope.proposal_id,
            private_context=facts.private_context,
            data_categories=facts.data_categories,
            customer_identities=facts.customer_identities,
            read_sources=facts.read_sources,
            outbound_context=facts.outbound_context,
            token_limit=1_000_000,
        ).id
    scope = f.store.scope(
        tenant_id=work.tenant,
        requester_id=work.human,
        writer_id=work.agent,
        category_id=work.category,
        run_id=run_id,
    )
    skill = f.owner.catalog._skills["proposal_drafting"]
    with Session(work.admin) as session, session.begin():
        # The synthetic model route changed above; pin that actual quality identity too.
        prior = session.get(TenantSkillEnablement, f.qualification.id)
        prior.qualified_model_digest = model_identity(route)
        prior.qualified_model_version = route.version
        session.add(
            TenantSkillEnablement(
                tenant_id=work.tenant,
                skill_key=skill.key,
                enabled=True,
                pilot=True,
                qualified_skill_version=skill.version,
                qualified_model_version=route.version,
                qualified_skill_digest=skill.digest,
                qualified_tool_digest=tool_identity(skill, f.owner.registry),
                qualified_model_digest=model_identity(route),
                reviewed_by=work.human,
                reviewed_at=now(),
                review_case_refs=["synthetic-review-" + str(i) for i in range(10)],
            )
        )
    agree(work, scope, scope.data_categories)
    turns, claim_id = [], None

    def answer(kwargs):
        nonlocal claim_id
        turns.append(kwargs["messages"])
        if len(turns) == 1:
            call = ToolCall(
                id="record",
                name="evidence.claim.record",
                arguments={
                    "source": {
                        "kind": "artifact",
                        "id": f.arguments["artifact_id"],
                        "version": 1,
                        "line": 1,
                        "quote": "Synthetic exact source",
                    },
                    "nature": "extracted",
                    "content": {"text": "Synthetic exact source"},
                },
            )
        elif len(turns) == 2:
            receipt = json.loads(kwargs["messages"][-1]["content"])
            assert "error" not in receipt, receipt
            claim_id = receipt["subject_id"]
            call = ToolCall(
                id="adopt",
                name="proposal.item.patch",
                arguments={
                    "proposal_id": str(scope.proposal_id),
                    "ops": [
                        {
                            "kind": "section",
                            "content": {"key": "summary", "text": "Synthetic evidence adopted"},
                            "source_refs": [{"type": "claim", "id": claim_id, "version": 1}],
                        }
                    ],
                },
            )
        elif len(turns) == 3:
            assert "error" not in json.loads(kwargs["messages"][-1]["content"])
            call = ToolCall(
                id="read",
                name="proposal.items.read",
                arguments={"proposal_id": str(scope.proposal_id)},
            )
        else:
            value = json.loads(kwargs["messages"][-1]["content"])
            assert any(
                item["content"].get("text") == "Synthetic evidence adopted"
                for item in value["items"]
            ), value
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "Synthetic evidence adopted",
                    "result": {"claim_id": claim_id},
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(2, 1),
            )
        return ModelTurn(calls=(call,), usage=ProviderUsage(2, 1))

    client = Client(answer)
    adapters = replace(
        f.owner.adapters(),
        route_for=lambda _: route,
        provider_for=lambda *_: "synthetic-provider",
        provider_client=client,
        cost_required=False,
    )
    result = AgentKernel(BoundHost(f.store, adapters), f.registry).execute(
        scope, goal="Synthetic evidence adoption", preload=("public_research", "proposal_drafting")
    )
    assert result["output"]["status"] == "completed" and client.calls == 4, result["output"]
    with f.store.transaction(scope) as (_, run):
        assert run.state == "completed" and run.id == run_id
        assert run.read_sources == facts.read_sources and run.data_categories == list(
            facts.data_categories
        )
        assert any(ref["id"] == claim_id for ref in run.versions[KEY]["references"])
    print(
        json.dumps(
            {
                "registered_graph_run_id": str(run_id),
                "synthetic_model_turns": client.calls,
                "outcome": result["output"]["status"],
                "claim_id": claim_id,
                "original_read_set_unchanged": True,
                "real_provider_calls": 0,
            }
        )
    )


def test_current_run_admits_shared_snapshot_after_actual_registered_page_read(
    work, monkeypatch, tmp_path
):
    from tests.agent_kernel.test_snapshot_proof_transactions import registered_page, registration

    _, snapshot, _ = registration(work, tmp_path / "original")
    f = bound(work, monkeypatch)
    assert not any(ref["id"] == str(snapshot.id) for ref in current(f)[1])
    cursor = len(snapshot.markdown.splitlines(keepends=True)[0])
    registered_page(f, snapshot, cursor=cursor, page_chars=20)
    arguments = {
        "source": {
            "kind": "snapshot",
            "id": str(snapshot.id),
            "version": 1,
            "line": 2,
            "quote": "单价 3.125 CNY",
        },
        "nature": "extracted",
        "content": {"text": "单价 3.125 CNY"},
    }
    receipt, _ = execute(f, "evidence.claim.record", arguments)
    assert any(ref["type"] == "snapshot" and ref["id"] == str(snapshot.id) for ref in current(f)[1])
    assert any(
        ref["type"] == "claim" and ref["id"] == receipt["subject_id"] for ref in current(f)[1]
    )
    attach(work, f, "claim", receipt["subject_id"])
