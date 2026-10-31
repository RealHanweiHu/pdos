"""Actual source classification reaches the first child provider policy check.

One real direct-parent action carries an uncited uploaded customer original only
as taint/currentness proof. Native T1 original scanning/parsing and a native data
agreement are used; no Run, ledger, artifact, audience or receipt is fabricated.
"""
# ruff: noqa: F401,F811 -- native fixture dependency tree

import asyncio
import os
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from build_operational_facts.fixtures import configuration, definition, operational_work, project
from build_start.test_transactions import ready_work
from pdos_next.agent_kernel import gateway
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import now
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.enterprise_search.test_action_footprint_temporal_pg import (
    ParentClient,
    action_payload,
    materials,
)
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.verification_action_harness import (
    VerificationClient,
    actual_runtime,
    start,
)
from tests.enterprise_search.verification_negative_fixture import private_action_work
from tests.test_original_security import parsed, security_work, uploaded
from verification_handoff.fixtures import known_configuration

pytestmark = [pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit guarded PG, local Temporal and verified checkpoint runtime required",
), pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)]


def test_uncited_parent_customer_original_classifies_private_child_before_real_egress(
    private_action_work, security_work, monkeypatch,
):
    person, selection, public, execution = materials(private_action_work)
    original = uploaded(
        security_work, title="Uncited customer private discussion",
        content="漏气：更换密封圈。CUSTOMER_ONLY_PARENT\n".encode(),
    )
    customer_artifact = parsed(security_work, original)
    index(person, customer_artifact)
    provider = VerificationClient(execution, private_action_work.scope.purpose)
    provider.parent = ParentClient(public["artifact_id"])
    actual_egress, observations = gateway.egress, []

    def observed(session, scope, provider_key, **kwargs):
        try:
            return actual_egress(session, scope, provider_key, **kwargs)
        except DomainError as error:
            observations.append((
                scope.run_id, kwargs.get("data_categories"), deepcopy(error.detail),
            ))
            raise

    monkeypatch.setattr(gateway, "egress", observed)

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, _handle = await start(runtime, {
                "goal": "以前漏气怎么处理？", "idempotency_key": str(uuid4()),
                "product_id": str(person.product), "project_id": selection["project_id"],
                "search_preferences": {"scope": "same_category", "include_customer_private": True},
            }, accepted_statuses=("completed", "partial"))
            response = await runtime.http.get(runtime.path + f"/{parent}", headers=person.headers)
            assert response.status_code == 200, response.text
            answer = response.json()["result"]["result"]["assistant"]
            customer_cid = provider.parent.source_cids[str(customer_artifact)]
            assert customer_cid not in answer["citation_ids"]
            assert answer["citation_ids"] == [provider.parent.source_cids[public["artifact_id"]]]
            # The parent dynamically searched/read the original; initial Run scope
            # has not silently acquired it as a selected business input.
            with Session(person.admin) as session:
                row = session.get(AgentRun, parent)
                # Native project scope can already be private. This original
                # was acquired dynamically and is absent from its initial class.
                assert "customer_original" not in row.data_categories
                assert str(customer_artifact) not in {
                    ref["artifact_id"] for ref in row.read_sources
                }
            # P26: an actual registered agreement may constrain the already
            # classified data. No real provider is invoked by this fixture.
            with tenant_session(
                person.engine, person.tenant, actor_id=person.human,
                requester_id=person.human, category_id=person.category,
            ) as session:
                register_agreement(session, person.ctx, AgreementInput(
                    provider="synthetic-assistant-no-egress", expected_revision=0,
                    data_categories=["internal"], signed_on=now() - timedelta(minutes=1),
                    expires_at=now() + timedelta(hours=1), retention_terms="synthetic-only",
                    training_terms="synthetic-only", decision="批准", idempotency_key=str(uuid4()),
                ))
            provider.phase = "action"
            before_calls = provider.calls
            child, _handle = await start(
                runtime, action_payload(parent, answer, selection, execution),
                accepted_statuses=("failed", "partial"),
            )
            assert provider.calls == before_calls
            rejected = [row for row in observations if row[0] == child]
            assert rejected and all("customer_original" in row[1] for row in rejected)
            assert all(row[2]["reason_key"] == "provider_agreement_category" for row in rejected)
            with Session(person.admin) as session:
                row = session.get(AgentRun, child)
                assert row.private_context and "customer_original" in row.data_categories
                action = row.versions["verification_action"]
                assert action["source_proof"]["taint"] == {
                    "private": True, "customer_original": True,
                }
                assert action["citation_ids"] == answer["citation_ids"]
                assert str(customer_artifact) not in {
                    ref["artifact_id"] for ref in row.read_sources
                }
                assert all(ref["source_id"] != str(customer_artifact) for ref in
                           row.versions["requested_context_selection"]["sources"])
                assert session.scalars(select(AgentToolCall).where(
                    AgentToolCall.run_id == child, AgentToolCall.tool == "model",
                )).all() == []
    asyncio.run(actual())
