from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, select, text

from app.ai.executor import AgentExecutor, GatewayAgentModelInvoker
from app.ai.gateway import ProviderRateCard, StructuredModelGateway
from app.ai.model_catalog import (
    GoldenQualification,
    ModelCatalog,
    ProtocolKind,
    ProviderName,
    ResolvedModelRoute,
)
from app.ai.provider_adapters import ChatMessage, ProviderResponse
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService
from app.worker.dispatcher import AgentDispatcher

SERVER_ROOT = Path(__file__).resolve().parents[1]


class FakeProviderAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[ResolvedModelRoute, Sequence[ChatMessage]]] = []

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        self.calls.append((route, messages))
        return ProviderResponse(
            content=(
                '{"disposition":"no_action","candidate_type":null,'
                '"summary":"No evidence-backed action is warranted.",'
                '"proposed_payload":null,"evidence_event_ids":[],"confidence":0.8}'
            ),
            input_tokens=21,
            output_tokens=9,
            request_id="fake-provider-request",
            model_version="fake-minimax-v1",
        )


@pytest.fixture
def event_to_model_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_project(connection: Connection) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": "e2e-agent", "name": "Agent E2E"},
    )
    connection.execute(
        tables.workflows.insert(),
        {"id": workflow_id, "tenant_id": tenant_id, "code": "npd", "name": "NPD"},
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": "PRJ-E2E",
            "name": "Agent E2E",
            "status": "active",
        },
    )
    return tenant_id, project_id


def test_real_event_flows_through_dispatcher_langgraph_fake_provider_and_trace(
    event_to_model_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(event_to_model_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection)
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"issue:{uuid4()}",
                        event_type="ISSUE_CREATED",
                        schema_version=1,
                        source="e2e_test",
                        entity="issue",
                        entity_id=uuid4(),
                        payload={"description": "private raw issue description"},
                        timestamp=now - timedelta(minutes=16),
                    )
                    .returning(tables.events.c.id)
                ).scalar_one()
            )
        catalog = ModelCatalog.from_environment(
            {
                "PDOS_LLM_PROVIDER": "minimax",
                "PDOS_LLM_API_KEY": "fake-provider-secret",
                "PDOS_LLM_MODEL": "MiniMax-M2.7",
                "PDOS_LLM_BASE_URL": "https://fake-model.local/v1",
            }
        )
        qualifications = [
            GoldenQualification(
                provider=ProviderName.MINIMAX,
                model="MiniMax-M2.7",
                suite_version="fake-suite-v1",
                suite_digest="sha256:fake-suite",
                status="passed",
            )
        ]
        provider = FakeProviderAdapter()
        gateway = StructuredModelGateway(
            engine,
            catalog=catalog,
            qualifications=qualifications,
            governance=ModelGovernanceService(
                engine,
                catalog=catalog,
                qualifications=qualifications,
                default_daily_token_budget=2_000_000,
            ),
            adapters={ProtocolKind.OPENAI_COMPATIBLE: provider},
            rate_cards={ProviderName.MINIMAX: ProviderRateCard(0, 0)},
        )

        cycle = AgentDispatcher(engine).dispatch_once(now=now)
        execution = AgentExecutor(
            engine,
            model_invoker=GatewayAgentModelInvoker(gateway),
        ).execute_next(now=now)

        assert cycle.scanned_event_count == 1
        assert cycle.created_run_count == 1
        assert cycle.queued_run_count == 1
        assert execution.status == "succeeded"
        assert execution.run_id is not None
        assert len(provider.calls) == 1
        all_messages = "\n".join(
            message.content for _, messages in provider.calls for message in messages
        )
        assert "private raw issue description" not in all_messages
        assert "fake-provider-secret" not in all_messages
        assert str(project_id) in all_messages

        with engine.connect() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == execution.run_id)
                )
                .mappings()
                .one()
            )
            invocation = (
                connection.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.run_id == execution.run_id
                    )
                )
                .mappings()
                .one()
            )
        assert run["status"] == "succeeded"
        assert run["event_row_ids"] == [event_id]
        assert run["run_context"]["tenant_id"] == str(tenant_id)
        assert invocation["tenant_id"] == tenant_id
        assert invocation["project_id"] == project_id
        assert invocation["run_id"] == execution.run_id
        assert invocation["status"] == "succeeded"
        assert invocation["total_tokens"] == 30
    finally:
        engine.dispose()
