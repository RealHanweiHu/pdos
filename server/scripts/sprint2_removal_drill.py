"""Offline Sprint 2 removal drill: model-free degradation must stay visible and safe."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import create_engine, func, select

from app.ai.gateway import (
    GatewayInvocation,
    GatewayResult,
    ProviderRateCard,
    StructuredModelGateway,
)
from app.ai.model_catalog import ModelCatalog, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import ChatMessage, ProviderResponse
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService


class ProbeOutput(BaseModel):
    result: str


@dataclass(frozen=True)
class RemovalDrillReport:
    brief_unavailable: bool
    chat_degraded: bool
    finding_count_unchanged: bool
    provider_calls: int


class RejectingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        del route, messages
        self.calls += 1
        raise AssertionError("removal drill reached a model provider")


def run() -> RemovalDrillReport:
    test_url = configured_test_database_url()
    engine = create_engine(psycopg_database_url(test_url))
    tenant_id = uuid4()
    project_id = uuid4()
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PDOS_LLM_")
    }
    try:
        with engine.connect() as connection:
            finding_count_before = int(
                connection.execute(select(func.count()).select_from(tables.findings)).scalar_one()
            )
        catalog = ModelCatalog.from_environment(environment)
        brief_unavailable = not catalog.eligible_models([])
        adapter = RejectingAdapter()
        gateway = StructuredModelGateway(
            engine,
            catalog=catalog,
            qualifications=[],
            governance=ModelGovernanceService(
                engine,
                catalog=catalog,
                qualifications=[],
                default_daily_token_budget=2_000_000,
            ),
            adapters={protocol: adapter for protocol in ProtocolKind},
            rate_cards={provider: ProviderRateCard(0, 0) for provider in ProviderName},
        )
        chat_result: GatewayResult[ProbeOutput] = gateway.invoke_structured(
            GatewayInvocation(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=None,
                agent_key="removal_drill",
                prompt_version="removal-drill-v1",
                system_prompt="Return only the requested schema.",
                instruction="Return a result.",
                context={},
            ),
            ProbeOutput,
        )
        with engine.connect() as connection:
            finding_count_after = int(
                connection.execute(select(func.count()).select_from(tables.findings)).scalar_one()
            )
        return RemovalDrillReport(
            brief_unavailable=brief_unavailable,
            chat_degraded=chat_result.status == "degraded" and chat_result.output is None,
            finding_count_unchanged=finding_count_after == finding_count_before,
            provider_calls=adapter.calls,
        )
    finally:
        engine.dispose()


def main() -> int:
    report = run()
    print(report)
    passed = (
        report.brief_unavailable
        and report.chat_degraded
        and report.finding_count_unchanged
        and report.provider_calls == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
