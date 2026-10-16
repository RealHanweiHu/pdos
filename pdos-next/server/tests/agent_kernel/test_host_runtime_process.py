"""Default tenant host ports, real API/Worker/PG pricing, offline KMS/model transport."""

import json
import os
import subprocess
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    TenantAdministrator,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.models import Receipt, now
from tests.agent_kernel.test_cost_budget import wallet
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_worker_process_recovery import wait_for
from tests.model_configuration.test_host_runtime import KmsSdk, document, write_config

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_WORKER_PROCESS_CHECK") != "verified-local-synthetic",
    reason="Explicit verified local Temporal/PG host process profile required",
)


class OfflineHostClient:
    def __init__(self):
        self.calls = 0

    def turn(self, route, **_kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        from pdos_next.agent_kernel.types import ModelTurn, ToolCall
        from pdos_next.providers.types import ProviderUsage

        assert in_registered_agent_graph()
        assert route.api_key.get_secret_value() == "synthetic-only-key"
        self.calls += 1
        print(json.dumps({"event": "offline_host_model", "call": self.calls}), flush=True)
        if self.calls == 1:
            return ModelTurn(
                usage=ProviderUsage(20, 10),
                calls=(
                    ToolCall(
                        id="host-proposal",
                        name="proposal.create",
                        arguments={
                            "title": "合成宿主接线提案",
                            "entry_kind": "new_product",
                            "brief": "仅验证宿主配置与实际草稿采用，不代表真实研究或资格。",
                        },
                    ),
                ),
            )
        results = [
            json.loads(row["content"]) for row in _kwargs["messages"] if row["role"] == "tool"
        ]
        assert len(results) == 1 and "error" not in results[0], results
        assert results[0]["state"] == "candidate" and results[0]["requires_human"] is True
        return ModelTurn(
            usage=ProviderUsage(20, 10),
            structured={
                "status": "completed",
                "summary": "Synthetic host candidate ready",
                "result": {},
            },
        )

    def close(self):
        pass


def test_default_host_process_prepares_actual_proposal_and_settles_declared_costs(
    setup, monkeypatch, tmp_path
):
    f = fixture(setup, skill_key="proposal_drafting")
    sdk = KmsSdk()
    monkeypatch.setattr(AliyunKms, "sdk", lambda _self: sdk)
    path = write_config(tmp_path / "runtime.json", document(setup.tenant))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        session.get(TenantSkillEnablement, f.qualification.id).qualified_model_version = None
    budget_id = wallet(setup)
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
                provider="synthetic@1",
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
    process = None
    with (tmp_path / "host-worker.log").open("wb") as log:
        try:
            with TestClient(create_app(setup.engine, setup.auth, workflow_enabled=True)) as api:
                command_path = f"/v1/categories/{setup.category}/commands"
                command = {
                    "command_id": str(uuid4()),
                    "idempotency_key": str(uuid4()),
                    "category_id": str(setup.category),
                    "product_id": None,
                    "operation": "model.configuration.save",
                    "expected_revision": 1,
                    "source_read_set": [],
                    "payload": {
                        "expected_revision": 0,
                        "enabled": True,
                        "metadata": {
                            "protocol": "openai-compatible",
                            "base_url": "https://synthetic.invalid/v1",
                            "model": "synthetic-model",
                            "model_version": "synthetic@1",
                        },
                    },
                }
                preview = api.post(command_path + "/preview", headers=setup.headers, json=command)
                assert preview.status_code == 200, preview.text
                saved = api.post(
                    command_path, headers=setup.headers, json=preview.json()["command"]
                )
                assert saved.status_code == 200, saved.text
                reading = api.get(
                    f"/v1/categories/{setup.category}/model-configuration", headers=setup.headers
                )
                assert reading.json()["configuration"]["credential_status"] == "bound"
                assert "synthetic-only-key" not in reading.text
                assert "secret/" not in reading.text
                agent_path = f"/v1/categories/{setup.category}/agent-runs"
                accepted = api.post(
                    agent_path,
                    headers=setup.headers,
                    json={
                        "goal": "Synthetic host-backed proposal draft",
                        "idempotency_key": str(uuid4()),
                        "sources": [
                            {"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}
                        ],
                    },
                )
                assert accepted.status_code == 202, accepted.text
                identity = UUID(accepted.json()["run_id"])
                env = dict(
                    os.environ,
                    PDOS_WORKFLOW_TENANTS=str(setup.tenant),
                    PDOS_CHECKPOINT_DATABASE_URL=os.environ["M2_TEST_CHECKPOINT_URL"].replace(
                        "postgresql://", "postgresql+psycopg://", 1
                    ),
                    PDOS_OBJECT_ROOT=str(tmp_path / "objects"),
                    PDOS_OBJECT_LIFECYCLE_PROFILE="local-synthetic-v1",
                )
                process = subprocess.Popen(
                    [sys.executable, "-m", "tests.agent_kernel.test_host_runtime_process"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )

                def terminal():
                    value = api.get(agent_path + f"/{identity}", headers=setup.headers).json()
                    return (
                        value
                        if value["status"] in {"completed", "partial", "failed", "cancelled"}
                        else None
                    )

                result = wait_for(terminal, process, seconds=60)
                assert result["status"] == "completed", result
                events = api.get(agent_path + f"/{identity}/events", headers=setup.headers).json()
                candidate = next(
                    row["event"]
                    for row in events["items"]
                    if row["event"]["type"] == "domain_candidate"
                )
                checked = api.post(
                    command_path + "/preview", headers=setup.headers, json=candidate["command"]
                )
                assert checked.status_code == 200, checked.text
                adopted = api.post(
                    command_path, headers=setup.headers, json=checked.json()["command"]
                )
                assert adopted.status_code == 200, adopted.text
                assert adopted.json()["subject_type"] == "proposal"
                with Session(setup.admin) as session:
                    row = session.get(AgentRun, identity)
                    assert row.validation_budget_id == budget_id and row.held_tokens == 0
                    assert row.versions["provider_key"] == "synthetic@1"
                    budget = session.get(ValidationBudget, budget_id)
                    assert row.token_limit == min(
                        2_147_483_647, budget.input_token_limit + budget.output_token_limit
                    )
                    assert budget.calls == 2 and budget.spent_micro_usd == 240
                    assert budget.held_micro_usd == 0
                    calls = list(
                        session.scalars(
                            select(AgentToolCall).where(
                                AgentToolCall.run_id == identity, AgentToolCall.tool == "model"
                            )
                        )
                    )
                    assert len(calls) == 2 and all(call.cost_state == "actual" for call in calls)
                    receipt = session.get(Receipt, UUID(adopted.json()["id"]))
                    assert receipt.agent_run_id == identity
                sdk.version = "rotated-current-version"
                reading = api.get(
                    f"/v1/categories/{setup.category}/model-configuration", headers=setup.headers
                )
                assert reading.json()["configuration"]["credential_status"] == "changed"
                print(
                    json.dumps(
                        {
                            "run_id": str(identity),
                            "actual_proposal": True,
                            "cost_micro_usd": 240,
                            "default_host_ports": True,
                            "external_model_calls": 0,
                            "external_kms_calls": 0,
                        }
                    )
                )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    import asyncio

    from pdos_next.agent_kernel import gateway
    from pdos_next.workflows.worker import main

    offline_sdk = KmsSdk()
    AliyunKms.sdk = lambda _self: offline_sdk
    gateway.AgentProviderClient = OfflineHostClient
    asyncio.run(main())
