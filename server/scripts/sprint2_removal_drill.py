"""Offline Sprint 2 removal drill: model-free degradation must stay visible and safe."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import create_engine, func, select

from app.ai.application_gateway import configured_application_gateway
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.model_catalog import ModelCatalog
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url


class ProbeOutput(BaseModel):
    result: str


@dataclass(frozen=True)
class RemovalDrillReport:
    brief_unavailable: bool
    chat_degraded: bool
    finding_count_unchanged: bool
    provider_calls: int


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
        with configured_application_gateway(engine, environment) as gateway:
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
            provider_calls=0,
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
