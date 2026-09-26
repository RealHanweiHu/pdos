"""Environment-backed construction of the isolated Agent execution plane."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.ai.agent_budget import RestrictedBudgetLedger
from app.ai.budget_adoption import agent_budget_configuration
from app.ai.egress import ProviderEgressPolicy
from app.ai.embeddings import EmbeddingError, configured_embedding_gateway
from app.ai.executor import AgentExecutor, GatewayAgentModelInvoker
from app.ai.finding_writer import RestrictedAgentFindingWriter
from app.ai.gateway import StructuredModelGateway
from app.ai.golden_suite import load_golden_suite
from app.ai.loop_policy import configured_loop_binding
from app.ai.model_budget import ModelBudgetController
from app.ai.model_catalog import ModelCatalog
from app.ai.provider_adapters import configured_provider_adapters
from app.ai.qualifications import load_golden_qualifications
from app.ai.run_store import RestrictedAgentRunStore
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_SUITE_PATH = SERVER_ROOT / "golden" / "model-gateway-v1.json"
DEFAULT_QUALIFICATIONS_PATH = SERVER_ROOT / "golden" / "model-qualifications.json"


class RuntimeConfigurationError(ValueError):
    """Raised before a process can start with mixed or missing credentials."""


@dataclass(frozen=True)
class AgentRuntime:
    engine: Engine
    executor: AgentExecutor


def required_database_url(environment: Mapping[str, str], *, key: str) -> str:
    value = environment.get(key, "").strip()
    if not value:
        raise RuntimeConfigurationError(f"{key} must be set")
    shared_runtime_allowed = (
        environment.get("PDOS_ALLOW_SHARED_RUNTIME_DATABASE_URL", "").strip().lower() == "true"
    )
    if environment.get("DATABASE_URL", "").strip() == value and not shared_runtime_allowed:
        raise RuntimeConfigurationError(f"{key} must not reuse DATABASE_URL")
    expected_usernames = {
        "PDOS_WORKER_DATABASE_URL": "pdos_worker",
        "PDOS_AGENT_DATABASE_URL": "pdos_agent",
    }
    try:
        username = make_url(value).username
    except ArgumentError as error:
        raise RuntimeConfigurationError(f"{key} must be a valid database URL") from error
    expected_username = expected_usernames.get(key)
    if not shared_runtime_allowed and username != expected_username:
        raise RuntimeConfigurationError(f"{key} must use the {expected_username} database role")
    return value


@contextmanager
def configured_agent_runtime(
    environment: Mapping[str, str] | None = None,
) -> Iterator[AgentRuntime]:
    values = os.environ if environment is None else environment
    budget_configuration = agent_budget_configuration(values)
    loop_binding = configured_loop_binding(values)
    if loop_binding is not None and budget_configuration is None:
        raise RuntimeConfigurationError("bounded tool loop requires budgeted Agent execution")
    database_url = required_database_url(values, key="PDOS_AGENT_DATABASE_URL")
    engine = create_engine(psycopg_database_url(database_url), pool_pre_ping=True)
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
    default_budget = int(values.get("PDOS_AI_DAILY_TOKEN_BUDGET", "2000000"))
    run_store = RestrictedAgentRunStore(engine)
    governance = ModelGovernanceService(
        engine,
        catalog=catalog,
        qualifications=qualifications,
        default_daily_token_budget=default_budget,
        run_store=run_store,
    )
    try:
        with ExitStack() as stack:
            client = stack.enter_context(httpx2.Client(follow_redirects=False, trust_env=False))
            try:
                embedding_gateway = stack.enter_context(configured_embedding_gateway(values))
            except EmbeddingError as error:
                if error.code != "EMBEDDING_NOT_CONFIGURED":
                    raise
                embedding_gateway = None
            budget_controller = (
                ModelBudgetController.from_publication(
                    RestrictedBudgetLedger(engine, run_store),
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
            gateway = StructuredModelGateway(
                engine,
                catalog=catalog,
                qualifications=qualifications,
                governance=governance,
                adapters=configured_provider_adapters(catalog, client),
                rate_cards={},
                run_store=run_store,
                budget_controller=budget_controller,
            )
            yield AgentRuntime(
                engine=engine,
                executor=AgentExecutor(
                    engine,
                    model_invoker=GatewayAgentModelInvoker(gateway),
                    run_store=run_store,
                    finding_writer=RestrictedAgentFindingWriter(
                        engine,
                        run_store=run_store,
                    ),
                    embedding_gateway=embedding_gateway,
                    loop_binding=loop_binding,
                    loop_step_limit=budget_configuration.profile.model_call_limit
                    if budget_configuration is not None
                    else 0,
                ),
            )
    finally:
        engine.dispose()
