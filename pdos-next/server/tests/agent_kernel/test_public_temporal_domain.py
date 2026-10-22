"""Offline synthetic provider, real authenticated API/Temporal/graph/PG domain owner."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from pdos_next.agent_kernel.qualification_binding import model_identity

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.models import Claim, Receipt, now
from pdos_next.providers.types import ProviderUsage
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_model_configuration_transactions import configured, submit


@pytest.mark.parametrize("qualified", [True, False])
def test_actual_authenticated_run_uses_temporal_graph_and_common_claim_owner(
    setup, monkeypatch, qualified
):
    f = fixture(setup)
    management_client, runtime_ports, configuration = configured(setup)
    saved_configuration, _ = submit(setup, management_client, configuration)
    assert saved_configuration.status_code == 200, saved_configuration.text
    bootstrap = Bootstrap(setup.engine, ports=runtime_ports)
    f.route = bootstrap.route_for(f.scope)
    with Session(setup.admin) as session, session.begin():
        from pdos_next.agent_kernel.models import TenantSkillEnablement

        qualification = session.get(TenantSkillEnablement, f.qualification.id)
        qualification.qualified_model_version = f.route.version if qualified else None
        qualification.qualified_model_digest = model_identity(f.route) if qualified else None

    class SyntheticClient:
        def __init__(self):
            self.calls = 0

        def turn(self, route, **kwargs):
            from pdos_agent_runtime.graph import in_registered_agent_graph

            assert in_registered_agent_graph() and route == f.route
            self.calls += 1
            if self.calls == 1:
                return ModelTurn(
                    calls=(
                        ToolCall(id="native", name="evidence.claim.record", arguments=f.arguments),
                    ),
                    usage=ProviderUsage(20, 10),
                )
            return ModelTurn(
                usage=ProviderUsage(20, 10),
                structured={
                    "status": "completed",
                    "summary": "Synthetic verified actual fact",
                    "result": {},
                    "questions": [],
                    "unfinished": [],
                },
            )

        def close(self):
            pass

    client = SyntheticClient()
    adapters = replace(
        bootstrap.adapters(),
        provider_for=lambda *_: "synthetic-offline-provider",
        provider_client=client,
        cost_required=False,
        preload=lambda _: ("public_research",),
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        register_agreement(
            session,
            setup.ctx,
            AgreementInput(
                provider="synthetic-offline-provider",
                expected_revision=0,
                data_categories=["internal"],
                decision="批准",
                idempotency_key=str(uuid4()),
                retention_terms="fixture-only:no-contract-or-egress",
                training_terms="synthetic only",
                signed_on=now() - timedelta(minutes=1),
                expires_at=now() + timedelta(hours=1),
            ),
        )

    async def actual():
        binary = Path(__file__).resolve().parents[3] / ".local/tools/temporal"
        # Reuse the inspected local binary; this test never downloads or calls a public service.
        assert binary.is_file()
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(binary))
        try:
            port = TemporalPort(environment.client, task_queue="s0-fixture-" + str(uuid4()))
            ports = bootstrap.api_ports(port)

            def synthetic_binding(*args):
                value = bootstrap.binding_for(*args)
                # Unmetered synthetic byte-as-token accounting is deliberately conservative.
                value.token_limit = 500000
                return value

            app = create_app(
                setup.engine,
                setup.auth,
                agent_runtime_ports=runtime_ports,
                agent_api_ports=replace(ports, binding_for=synthetic_binding),
            )
            activities = KernelActivities(
                setup.engine,
                checkpoint_url=os.environ["M2_TEST_CHECKPOINT_URL"].replace(
                    "postgresql://", "postgresql+psycopg://", 1
                ),
                technical_engine=setup.dispatch,
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(
                    environment.client,
                    task_queue=port.task_queue,
                    workflows=[XiaopaiWork],
                    activities=[activities.advance],
                    activity_executor=executor,
                ):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local"
                    ) as http:
                        path = f"/v1/categories/{setup.category}/agent-runs"
                        payload = {
                            "goal": "Synthetic actual source claim",
                            "idempotency_key": str(uuid4()),
                            "product_id": str(setup.product),
                            "sources": [
                                {"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}
                            ],
                        }
                        started = await http.post(path, headers=setup.headers, json=payload)
                        assert started.status_code == 202, started.text
                        identity = UUID(started.json()["run_id"])
                        result = await asyncio.wait_for(
                            environment.client.get_workflow_handle(
                                workflow_id(setup.tenant, identity)
                            ).result(),
                            50,
                        )
                        assert result["status"] == "completed", result
                        saved = await http.get(path + "/" + str(identity), headers=setup.headers)
                        assert saved.json()["status"] == "completed"
                        await http.post(path, headers=setup.headers, json=payload)
                        assert client.calls == 2
                        if not qualified:
                            events = await http.get(
                                path + "/" + str(identity) + "/events", headers=setup.headers
                            )
                            candidate = next(
                                item["event"]
                                for item in events.json()["items"]
                                if item["event"]["type"] == "claim_candidate"
                            )
                            command_path = f"/v1/categories/{setup.category}/commands"
                            preview = await http.post(
                                command_path + "/preview",
                                headers=setup.headers,
                                json=candidate["command"],
                            )
                            assert preview.status_code == 200, preview.text
                            confirmed = await http.post(
                                command_path, headers=setup.headers, json=preview.json()["command"]
                            )
                            assert confirmed.status_code == 200, confirmed.text
                            assert confirmed.json()["result"]["origin"] == "ai_draft"
                            assert confirmed.json()["result"]["confirmed_by"] == str(setup.human)
                            replay = await http.post(
                                command_path, headers=setup.headers, json=preview.json()["command"]
                            )
                            assert replay.json() == confirmed.json()
                        with Session(setup.admin) as session:
                            receipt = session.scalar(
                                select(Receipt).where(
                                    Receipt.agent_run_id == identity,
                                    Receipt.operation == "evidence.claim.record",
                                )
                            )
                            assert receipt is not None
                            claim = session.get(Claim, receipt.subject_id)
                            assert claim.writer_id == setup.agent
                            assert claim.human_owner_id == setup.human
                            if qualified:
                                call = session.scalar(
                                    select(AgentToolCall).where(
                                        AgentToolCall.run_id == identity,
                                        AgentToolCall.tool == "evidence.claim.record",
                                    )
                                )
                                assert call.state == "completed" and call.receipt_id == receipt.id
                            assert session.get(AgentRun, identity).held_tokens == 0
        finally:
            await environment.shutdown()

    asyncio.run(actual())
