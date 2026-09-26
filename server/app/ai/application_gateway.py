"""Application-plane model gateway construction for synchronous AI APIs."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

import httpx2
from pydantic import BaseModel
from sqlalchemy import Engine

from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_adoption import ApplicationBudgetConfiguration
from app.ai.budget_ledger import ExistingRunBudgetLedger
from app.ai.egress import ProviderEgressPolicy
from app.ai.gateway import (
    GatewayInvocation,
    GatewayResult,
    StructuredModelGateway,
)
from app.ai.golden_suite import load_golden_suite
from app.ai.model_budget import ModelBudgetController
from app.ai.model_catalog import ModelCatalog
from app.ai.provider_adapters import configured_provider_adapters
from app.ai.qualifications import load_golden_qualifications
from app.domain.model_governance import ModelGovernanceService

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_SUITE_PATH = SERVER_ROOT / "golden" / "model-gateway-v1.json"
DEFAULT_QUALIFICATIONS_PATH = SERVER_ROOT / "golden" / "model-qualifications.json"


class ApplicationModelGateway(Protocol):
    """Narrow structural type used by API services and test fakes."""

    def invoke_structured[OutputT: BaseModel](
        self,
        invocation: GatewayInvocation,
        output_type: type[OutputT],
    ) -> GatewayResult[OutputT]: ...


@contextmanager
def configured_application_gateway(
    engine: Engine,
    environment: Mapping[str, str] | None = None,
    *,
    request_timeout_seconds: float = 30.0,
    max_structured_attempts: int = 2,
) -> Iterator[StructuredModelGateway]:
    values = os.environ if environment is None else environment
    budget_configuration = ApplicationBudgetConfiguration.from_environment(values)
    catalog = ModelCatalog.from_environment(values)
    trusted_suite = load_golden_suite(DEFAULT_GOLDEN_SUITE_PATH)
    qualification_path = Path(
        values.get(
            "PDOS_LLM_GOLDEN_QUALIFICATIONS_PATH",
            str(DEFAULT_QUALIFICATIONS_PATH),
        )
    )
    qualifications = load_golden_qualifications(
        qualification_path,
        trusted_suite=trusted_suite,
    )
    governance = ModelGovernanceService(
        engine,
        catalog=catalog,
        qualifications=qualifications,
        default_daily_token_budget=int(values.get("PDOS_AI_DAILY_TOKEN_BUDGET", "2000000")),
    )
    with (
        httpx2.Client(follow_redirects=False, trust_env=False) as client,
        ApplicationLeaseKeeper(engine) as lease_keeper,
    ):
        budget_controller = (
            ModelBudgetController.from_publication(
                ExistingRunBudgetLedger(engine),
                profile=budget_configuration.profile,
                path=budget_configuration.meter_path,
                expected_sha256=budget_configuration.meter_sha256,
                qualifications=qualifications,
                client=client,
                egress_policy=ProviderEgressPolicy.from_catalog(catalog),
            )
            if budget_configuration is not None
            else None
        )
        yield StructuredModelGateway(
            engine,
            catalog=catalog,
            qualifications=qualifications,
            governance=governance,
            adapters=configured_provider_adapters(
                catalog, client, request_timeout_seconds=request_timeout_seconds
            ),
            max_structured_attempts=max_structured_attempts,
            rate_cards={},
            budget_controller=budget_controller,
            application_lease_keeper=lease_keeper,
        )
