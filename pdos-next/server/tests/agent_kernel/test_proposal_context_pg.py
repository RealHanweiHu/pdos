"""Bound private proposals through the actual host, read ports and egress; synthetic only."""
# ruff: noqa: F811 -- explicitly imported marked PG fixtures

import json
import re
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from time import perf_counter
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.m3_object_reads import M3ObjectReads
from pdos_next.agent_kernel.management import register_agreement
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    TenantAdministrator,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.proposal_context import KEY
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, now
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route, turn
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE, actual_run, uploaded
from tests.agent_kernel.test_transactions import agreement, human_session
from tests.preproject.test_derivation_transactions import derivative_payload, synthetic_parent
from tests.preproject.test_evidence_commands_pg import record_claim
from tests.preproject.test_g0 import create, payload, post, request
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


def start(work, security_work, entry="new_product"):
    args = payload(work)
    if entry == "customer_request":
        _, source = uploaded(work, security_work)
        args.update(
            entry_kind=entry,
            customer_identities=["Synthetic customer"],
            source_refs=[
                {"type": "original", "id": str(source), "version": 1, "line": 1, "quote": QUOTE}
            ],
        )
    elif entry == "derivative":
        args = derivative_payload(work, synthetic_parent(work), "new_variant")
    proposal_id, _ = create(work, args)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, UUID(proposal_id))
    return owner, scope


def read(owner, scope, name="proposal.read", **extra):
    return M3ObjectReads(owner.store, owner.commands).call(
        scope, {"proposal_id": str(scope.proposal_id), **extra}, name=name
    )


def agree(work, scope, categories, *, revision=0):
    with Session(work.admin) as session, session.begin():
        if not session.scalar(
            select(TenantAdministrator).where(
                TenantAdministrator.tenant_id == scope.tenant_id,
                TenantAdministrator.principal_id == work.human,
            )
        ):
            session.add(TenantAdministrator(tenant_id=scope.tenant_id, principal_id=work.human))
    with human_session(work) as session:
        return register_agreement(
            session,
            work.ctx,
            agreement(work).model_copy(
                update={"data_categories": list(categories), "expected_revision": revision}
            ),
        )


def gateway(owner, client):
    return AgentGateway(
        owner.store,
        cost_required=False,
        route_for=lambda _: configured_route(),
        provider_for=lambda *_: "synthetic-provider",
        client=client,
    )


@pytest.mark.parametrize("entry", ["customer_request", "new_product", "derivative"])
def test_three_private_entries_have_actual_bound_context_and_readable_items(
    work, security_work, entry
):
    owner, scope = start(work, security_work, entry)
    context = owner.project_context(scope, "Synthetic proposal work")
    assert context["proposal"]["id"] == str(scope.proposal_id)
    assert context["proposal"]["visibility"] == "private"
    summary = read(owner, scope)
    items = read(owner, scope, "proposal.items.read")
    assert summary["id"] == str(scope.proposal_id) and summary["item_counts"]["spec"] >= 2
    assert items["proposal_id"] == str(scope.proposal_id) and items["questions"]
    assert scope.private_context
    with owner.store.transaction(scope) as (_, row):
        assert row.versions[KEY]["proposal_id"] == str(scope.proposal_id)
        if entry == "customer_request":
            assert "customer_original" in row.data_categories and row.read_sources
            assert tuple(row.customer_identities) == ("Synthetic customer",)


def test_unsigned_provider_allowed_and_registered_agreement_restricts_categories(
    work, security_work
):
    # P26: without a registered agreement the provider is allowed; a registered
    # current agreement then restricts categories; a covering revision passes.
    owner, scope = start(work, security_work, "customer_request")
    client = Client(lambda _: ModelTurn("synthetic", usage=ProviderUsage(1, 1)))
    assert turn(gateway(owner, client), scope).text == "synthetic" and client.calls == 1
    with owner.store.transaction(scope) as (session, row):
        assert row.held_tokens == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.run_id == row.id)
            )
            == 1
        )
    agree(work, scope, ["internal"])
    with pytest.raises(DomainError) as wrong:
        turn(gateway(owner, client), scope)
    assert wrong.value.detail["reason_key"] == "provider_agreement_category" and client.calls == 1
    agree(work, scope, scope.data_categories, revision=1)
    assert turn(gateway(owner, client), scope).text == "synthetic" and client.calls == 1


@pytest.mark.parametrize("change", ["withdraw_source", "new_source", "audience", "manifest"])
def test_changed_source_scope_cannot_reach_model_or_read_port(work, security_work, change):
    owner, scope = start(work, security_work, "customer_request")
    agree(work, scope, scope.data_categories)
    client = Client(lambda _: pytest.fail("Changed private context must not reach a model"))
    if change == "new_source":
        _, source = uploaded(work, security_work, label="A newly mounted original")
        response = post(
            work,
            request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": str(scope.proposal_id),
                    "ops": [
                        {
                            "kind": "section",
                            "content": {
                                "key": "summary",
                                "text": "New synthetic mounted source",
                            },
                            "source_refs": [
                                {
                                    "type": "original",
                                    "id": str(source),
                                    "version": 1,
                                    "line": 1,
                                    "quote": QUOTE,
                                }
                            ],
                        }
                    ],
                },
            ),
        )
        assert response.status_code == 200, response.text
    with Session(work.admin) as session, session.begin():
        run = session.get(AgentRun, scope.run_id)
        if change == "withdraw_source":
            session.get(Artifact, UUID(run.read_sources[0]["artifact_id"])).status = "withdrawn"
        elif change == "audience":
            grant = session.scalar(
                select(Grant).where(
                    Grant.category_id == scope.category_id, Grant.principal_id == scope.writer_id
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)
        elif change == "manifest":
            versions = deepcopy(run.versions)
            versions[KEY]["proposal_id"] = str(work.product)
            run.versions = versions

    for action in (
        lambda: owner.project_context(scope, "Synthetic work"),
        lambda: read(owner, scope),
        lambda: turn(gateway(owner, client), scope),
    ):
        with pytest.raises(DomainError):
            action()
    assert client.calls == 0


def test_private_run_without_original_manifest_needs_new_bound_run(work, security_work):
    owner, scope = start(work, security_work)
    with Session(work.admin) as session, session.begin():
        session.get(AgentRun, scope.run_id).versions = {}
    with pytest.raises(DomainError) as error:
        read(owner, scope)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_registered_graph_reads_private_proposal_and_continues_with_actual_tool_result(
    work, security_work
):
    owner, scope = start(work, security_work, "customer_request")
    agree(work, scope, scope.data_categories)
    # The intentionally unmetered transport reserves bytes, rather than real model tokens.
    with Session(work.admin) as session, session.begin():
        session.get(AgentRun, scope.run_id).token_limit = 1_000_000
        if session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == work.tenant,
            TenantSkillEnablement.skill_key == "gap_check",
        )) is None:
            session.add(TenantSkillEnablement(tenant_id=work.tenant, skill_key="gap_check",
                                             enabled=True))
    seen = []

    def response(kwargs):
        context = json.loads(kwargs["messages"][0]["content"])["context"]
        assert context["proposal"]["id"] == str(scope.proposal_id)
        assert QUOTE in kwargs["messages"][0]["content"]
        seen.append(kwargs["messages"])
        if len(seen) == 1:
            return ModelTurn(
                calls=(
                    ToolCall(
                        id="synthetic-private-read",
                        name="proposal.items.read",
                        arguments={"proposal_id": str(scope.proposal_id)},
                    ),
                ),
                usage=ProviderUsage(2, 1),
            )
        assert any(message.get("role") == "tool" for message in kwargs["messages"])
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": "Synthetic private gap check",
                "result": {},
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(2, 1),
        )

    client = Client(response)
    adapters = replace(
        owner.adapters(),
        route_for=lambda _: configured_route(),
        provider_for=lambda *_: "synthetic-provider",
        provider_client=client,
        cost_required=False,
    )
    result = AgentKernel(BoundHost(owner.store, adapters), owner.registry).execute(
        scope, goal="Synthetic private proposal gap check", preload=("gap_check",),
    )
    assert result["output"]["status"] == "completed" and client.calls == 2, result["output"]
    with owner.store.transaction(scope) as (session, run):
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id, AgentToolCall.tool == "proposal.items.read"
            )
        )
        assert call.state == "completed" and call.result["proposal_id"] == str(scope.proposal_id)
        assert call.execution_binding["read_kind"] == "ordinary/v1"
        assert "engine_version" not in call.execution_binding
        assert owner.registry.get("proposal.items.read").version == "2"


@pytest.mark.parametrize("location", ["item", "claim"])
def test_original_mounted_only_below_item_or_claim_has_same_run_and_egress_binding(
    work, security_work, location
):
    _, source = uploaded(work, security_work)
    args = payload(work)
    if location == "item":
        args["groups"]["items"][0]["source_refs"] = [
            {"type": "original", "id": str(source), "version": 1, "line": 1, "quote": QUOTE}
        ]
    proposal_id, _ = create(work, args)
    if location == "claim":
        receipt = record_claim(work, source, quote=QUOTE, proposal_id=proposal_id)
        response = post(
            work,
            request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": proposal_id,
                    "ops": [
                        {
                            "kind": "section",
                            "content": {"key": "summary", "text": "Synthetic claim summary"},
                            "source_refs": [
                                {"type": "claim", "id": receipt["subject_id"], "version": 1}
                            ],
                        }
                    ],
                },
            ),
        )
        assert response.status_code == 200, response.text
    owner = Bootstrap(work.engine)
    scope, sources = actual_run(work, owner, UUID(proposal_id))
    assert sources == [{"artifact_id": str(source), "expected_revision": 1, "product_id": None}]
    assert "customer_original" in scope.data_categories and scope.private_context
    assert read(owner, scope, "proposal.items.read")["items"]


def test_source_revocation_while_model_runs_does_not_release_result_and_frees_reservation(
    work, security_work
):
    owner, scope = start(work, security_work, "customer_request")
    agree(work, scope, scope.data_categories)

    def response(_):
        with Session(work.admin) as session, session.begin():
            run = session.get(AgentRun, scope.run_id)
            session.get(Artifact, UUID(run.read_sources[0]["artifact_id"])).status = "withdrawn"
        return ModelTurn("Unexposed synthetic answer", usage=ProviderUsage(2, 1))

    client = Client(response)
    with pytest.raises(DomainError):
        turn(gateway(owner, client), scope)
    assert client.calls == 1
    with owner.store.transaction(scope) as (session, row):
        assert row.held_tokens == 0
        call = session.scalar(select(AgentToolCall).where(AgentToolCall.run_id == row.id))
        assert call.state == "unknown" and call.result is None


def test_bound_egress_check_compares_metadata_without_reopening_upstream_body(
    work, security_work, monkeypatch
):
    from pdos_next.agent_kernel import proposal_context
    from pdos_next.domain.preproject import views

    owner, scope = start(work, security_work, "customer_request")
    monkeypatch.setattr(
        proposal_context, "collect", lambda *a, **k: pytest.fail("Source tree recollected")
    )
    monkeypatch.setattr(
        proposal_context.baseline,
        "validate_sources",
        lambda *a, **k: pytest.fail("Source tree revalidated"),
    )
    monkeypatch.setattr(
        views, "read", lambda *a, **k: pytest.fail("Proposal body reread")
    )
    statements = []

    def observe(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.engine, "before_cursor_execute", observe)
    started = perf_counter()
    try:
        proposal_context.check(owner.store, scope)
    finally:
        elapsed = (perf_counter() - started) * 1000
        event.remove(work.engine, "before_cursor_execute", observe)
    body_reads = sum(
        bool(re.search(r"\bartifact_versions\.content(?:\s|,)", sql)) for sql in statements
    )
    assert body_reads == 0
    print(
        json.dumps(
            {
                "scope": "one synthetic original, outbound watermark read",
                "elapsed_ms": round(elapsed, 2),
                "sql_count": len(statements),
                "artifact_body_selects": body_reads,
            }
        )
    )
