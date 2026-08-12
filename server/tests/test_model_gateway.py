from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, select, text

from app.ai.gateway import (
    GatewayInvocation,
    ProviderRateCard,
    StructuredModelGateway,
)
from app.ai.model_catalog import (
    AgentTier,
    GoldenQualification,
    ModelCatalog,
    ProtocolKind,
    ProviderName,
    ResolvedModelRoute,
)
from app.ai.provider_adapters import (
    ChatMessage,
    ProviderRequestError,
    ProviderResponse,
)
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService

SERVER_ROOT = Path(__file__).resolve().parents[1]


class RiskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    risk: Literal["low", "high"]


class FakeAdapter:
    def __init__(self, responses: list[ProviderResponse | ProviderRequestError]) -> None:
        self.responses = responses
        self.calls: list[tuple[ResolvedModelRoute, Sequence[ChatMessage]]] = []

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        self.calls.append((route, messages))
        response = self.responses.pop(0)
        if isinstance(response, ProviderRequestError):
            raise response
        return response


@pytest.fixture(autouse=True)
def model_gateway_database() -> Iterator[str]:
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


def qualification() -> GoldenQualification:
    return GoldenQualification(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        suite_version="s2-v1",
        suite_digest="sha256:trusted-suite",
        status="passed",
    )


def catalog() -> ModelCatalog:
    return ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
            "PDOS_LLM_API_KEY": "test-secret",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
        }
    )


def invocation(tenant_id: UUID, **overrides: object) -> GatewayInvocation:
    values: dict[str, object] = {
        "tenant_id": tenant_id,
        "project_id": None,
        "run_id": None,
        "agent_key": "project_intelligence",
        "agent_tier": AgentTier.REASONING,
        "prompt_version": "project-intelligence-v1",
        "system_prompt": "Frozen system prompt.",
        "instruction": "Assess the project risk and return structured JSON.",
        "context": {
            "project": {
                "id": "project-1",
                "code": "PRJ-001",
                "name": "Motor Controller",
                "status": "active",
                "confidential_notes": "do not send",
            },
            "object_storage_key": "private/original.pdf",
        },
    }
    values.update(overrides)
    return GatewayInvocation.model_validate(values)


def gateway(
    database_url: str,
    adapter: FakeAdapter,
    *,
    budget: int = 1000,
) -> StructuredModelGateway:
    engine = create_engine(psycopg_database_url(database_url))
    model_catalog = catalog()
    qualifications = [qualification()]
    governance = ModelGovernanceService(
        engine,
        catalog=model_catalog,
        qualifications=qualifications,
        default_daily_token_budget=budget,
    )
    return StructuredModelGateway(
        engine,
        catalog=model_catalog,
        qualifications=qualifications,
        governance=governance,
        adapters={ProtocolKind.OPENAI_COMPATIBLE: adapter},
        rate_cards={
            ProviderName.MINIMAX: ProviderRateCard(
                input_microusd_per_million_tokens=1_000_000,
                output_microusd_per_million_tokens=2_000_000,
            )
        },
        max_structured_attempts=2,
    )


def provider_response(
    content: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> ProviderResponse:
    return ProviderResponse(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_id="provider-request",
        model_version="MiniMax-M2.7-20260811",
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )


def seed_tenant(database_url: str) -> UUID:
    tenant_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"tenant-{tenant_id}", "name": "AI Tenant"},
            )
    finally:
        engine.dispose()
    return tenant_id


def invocation_rows(database_url: str, tenant_id: UUID) -> list[dict[str, object]]:
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.tenant_id == tenant_id
                    )
                ).mappings()
            ]
    finally:
        engine.dispose()


def test_gateway_retries_invalid_structure_records_aggregate_usage_and_projects_context(
    model_gateway_database: str,
) -> None:
    tenant_id = seed_tenant(model_gateway_database)
    adapter = FakeAdapter(
        [
            provider_response(
                "not-json", input_tokens=10, output_tokens=5, cache_creation_tokens=4
            ),
            provider_response(
                '```json\n{"risk":"high"}\n```',
                input_tokens=12,
                output_tokens=8,
                cache_read_tokens=6,
            ),
        ]
    )

    result = gateway(model_gateway_database, adapter).invoke_structured(
        invocation(tenant_id),
        RiskOutput,
    )

    assert result.status == "succeeded"
    assert result.output == RiskOutput(risk="high")
    assert result.error_code is None
    assert result.structured_attempts == 2
    assert set(result.removed_context_paths) == {
        "object_storage_key",
        "project.confidential_notes",
    }
    assert len(adapter.calls) == 2
    serialized_messages = " ".join(
        message.content for _, messages in adapter.calls for message in messages
    )
    assert "do not send" not in serialized_messages
    assert "private/original.pdf" not in serialized_messages
    assert "test-secret" not in serialized_messages

    rows = invocation_rows(model_gateway_database, tenant_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["input_tokens"] == 22
    assert rows[0]["output_tokens"] == 13
    assert rows[0]["total_tokens"] == 35
    assert rows[0]["cache_read_tokens"] == 6
    assert rows[0]["cache_creation_tokens"] == 4
    assert rows[0]["normalized_cost_microusd"] == 48
    assert rows[0]["structured_attempts"] == 2
    assert rows[0]["error_code"] is None


def test_gateway_budget_circuit_records_degradation_without_provider_call(
    model_gateway_database: str,
) -> None:
    tenant_id = seed_tenant(model_gateway_database)
    engine = create_engine(psycopg_database_url(model_gateway_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "agent_key": "seed",
                    "prompt_version": "seed-v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "input_tokens": 15,
                    "output_tokens": 5,
                    "total_tokens": 20,
                    "structured_attempts": 1,
                },
            )
    finally:
        engine.dispose()
    adapter = FakeAdapter([])

    result = gateway(model_gateway_database, adapter, budget=20).invoke_structured(
        invocation(tenant_id),
        RiskOutput,
    )

    assert result.status == "degraded"
    assert result.output is None
    assert result.error_code == "DAILY_BUDGET_EXCEEDED"
    assert adapter.calls == []
    rows = invocation_rows(model_gateway_database, tenant_id)
    assert {row["status"] for row in rows} == {"succeeded", "budget_exceeded"}
    budget_row = next(row for row in rows if row["status"] == "budget_exceeded")
    assert budget_row["total_tokens"] == 0
    assert budget_row["structured_attempts"] == 0


def test_gateway_provider_failure_is_not_retried_and_is_recorded(
    model_gateway_database: str,
) -> None:
    tenant_id = seed_tenant(model_gateway_database)
    adapter = FakeAdapter([ProviderRequestError("provider_http_429", "provider failed")])

    result = gateway(model_gateway_database, adapter).invoke_structured(
        invocation(tenant_id),
        RiskOutput,
    )

    assert result.status == "degraded"
    assert result.error_code == "PROVIDER_HTTP_429"
    assert len(adapter.calls) == 1
    row = invocation_rows(model_gateway_database, tenant_id)[0]
    assert row["status"] == "provider_error"
    assert row["error_code"] == "PROVIDER_HTTP_429"
    assert row["structured_attempts"] == 1


def test_gateway_schema_exhaustion_stops_at_fixed_attempt_budget(
    model_gateway_database: str,
) -> None:
    tenant_id = seed_tenant(model_gateway_database)
    adapter = FakeAdapter(
        [
            provider_response("{}", input_tokens=4, output_tokens=1),
            provider_response('{"risk":"unknown"}', input_tokens=5, output_tokens=2),
        ]
    )

    result = gateway(model_gateway_database, adapter).invoke_structured(
        invocation(tenant_id),
        RiskOutput,
    )

    assert result.status == "degraded"
    assert result.error_code == "STRUCTURED_OUTPUT_INVALID"
    assert len(adapter.calls) == 2
    row = invocation_rows(model_gateway_database, tenant_id)[0]
    assert row["status"] == "schema_error"
    assert row["input_tokens"] == 9
    assert row["output_tokens"] == 3
    assert row["structured_attempts"] == 2
