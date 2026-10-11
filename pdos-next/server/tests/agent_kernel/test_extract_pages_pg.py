"""Actual isolated read provenance for registered bytes; no real provider calls."""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked database fixtures

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentToolCall, TenantAdministrator
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_m3_original_binding_pg import actual_run, proposal, uploaded
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


def fixture(work, security_work, *, locator=None, cursor=0):
    from pdos_next.agent_kernel.bootstrap import Bootstrap

    _, version_id = uploaded(work, security_work)
    proposal_id = proposal(work, version_id)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, proposal_id)
    child = scope.child("extract", artifact_ids={version_id})
    provider = "synthetic-extract-fixture-no-real-egress"
    with Session(work.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=work.tenant, principal_id=work.human))
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        register_agreement(
            session,
            work.ctx,
            AgreementInput(
                provider=provider,
                expected_revision=0,
                data_categories=list(scope.data_categories),
                decision="批准",
                idempotency_key=str(uuid4()),
                retention_terms="synthetic fixture only",
                training_terms="synthetic fixture only",
                signed_on=now() - timedelta(minutes=1),
                expires_at=now() + timedelta(hours=1),
            ),
        )
    args = {
        "artifact_version_id": str(version_id),
        "locator": locator,
        "cursor": cursor,
        "page_size": 1,
    }
    client = Client(
        lambda _: ModelTurn(
            calls=(ToolCall(id="synthetic-read", name="evidence.artifact.read", arguments=args),),
            usage=ProviderUsage(20, 5),
        )
    )
    route = configured_route()
    reads = DomainReads(owner.store, owner.commands)
    host = BoundHost(
        owner.store,
        KernelAdapters(
            route_for=lambda _: route,
            project_context=lambda *_: {},
            verify_result=lambda *values: values[1],
            prepare_candidate=lambda *_: None,
            execute_command=lambda *_: None,
            provider_for=lambda *_: provider,
            provider_client=client,
            cost_required=False,
            tool_registry=owner.registry,
            read_tools=reads.handlers(),
        ),
    )
    with registered_graph_context("xiaopai"):
        turn = host.model(
            child,
            system="frozen synthetic extract prefix",
            messages=[{"role": "user", "content": "Read actual synthetic source"}],
            tools=owner.registry.definitions("extract"),
            output_schema={"type": "object"},
        )
    assert turn.ledger_call_id is not None and client.calls == 1
    return (
        owner,
        child,
        args,
        host,
        client,
        ReadSource(
            model_call_id=turn.ledger_call_id,
            response_index=0,
        ),
    )


def read(owner, scope, args, host, source):
    return host.read(
        scope,
        owner.registry.get("evidence.artifact.read"),
        args,
        execution_key(scope.run_id, source.model_call_id, source.response_index),
        source=source,
    )


def test_new_located_page_has_actual_completed_read_and_replays_exactly(work, security_work):
    owner, scope, args, host, client, source = fixture(work, security_work, locator="line:1")
    value = read(owner, scope, args, host, source)
    assert value["blocks"][0]["locator"] == "line:1" and value["parse_status"] == "parsed"
    assert (
        value["artifact_version_id"] == args["artifact_version_id"] and "artifact_id" not in value
    )
    assert read(owner, scope, args, host, source) == value and client.calls == 1
    with owner.store.transaction(scope) as (session, _):
        call = session.get(AgentToolCall, UUID(value["execution_ref"]["call_id"]))
        assert call.state == "completed" and call.execution_binding["isolation"] == "extract"
        assert call.execution_binding["tool"] == "evidence.artifact.read"
        assert call.execution_binding["model_call_id"] == str(source.model_call_id)
        assert call.result == {k: v for k, v in value.items() if k != "execution_ref"}
    with pytest.raises(DomainError):
        read(owner, scope, {**args, "artifact_version_id": str(uuid4())}, host, source)
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        cancel_run(session, work.ctx, scope.run_id)
    with pytest.raises(DomainError) as cancelled:
        read(owner, scope, args, host, source)
    assert cancelled.value.code == "CANCELLED_RUN" and client.calls == 1


def test_read_at_eof_keeps_an_empty_page_and_does_not_claim_body_coverage(work, security_work):
    owner, scope, args, host, client, source = fixture(work, security_work, cursor=999)
    # An explicit locator denotes an actual start; a later cursor is still only a read request.
    from pdos_next.agent_kernel.extract_schemas import ArtifactReadInput

    with pytest.raises(ValidationError):
        ArtifactReadInput.model_validate({"artifact_id": args["artifact_version_id"]})
    current = read(owner, scope, args, host, source)
    assert current["blocks"] == [] and current["next_cursor"] is None and client.calls == 1
