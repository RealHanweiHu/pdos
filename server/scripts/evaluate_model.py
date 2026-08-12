"""Run the immutable golden suite; never publishes or modifies model qualification."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx2
from dotenv import load_dotenv

from app.ai.golden_runner import evaluate_candidate
from app.ai.golden_suite import load_golden_suite
from app.ai.model_catalog import AgentTier, ModelCatalog, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import configured_provider_adapters

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_ROOT.parent
DEFAULT_SUITE_PATH = SERVER_ROOT / "golden" / "model-gateway-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate one configured model against the trusted PDOS golden suite."
    )
    parser.add_argument(
        "--provider",
        choices=[provider.value for provider in ProviderName],
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    load_dotenv(REPOSITORY_ROOT / ".env")
    provider = ProviderName(arguments.provider)
    catalog = ModelCatalog.from_environment(os.environ)
    configuration = catalog.configuration_for(provider)
    if configuration is None:
        raise SystemExit("selected provider has no configured credential")
    route = ResolvedModelRoute(
        provider=configuration.provider,
        protocol=configuration.protocol,
        base_url=configuration.base_url,
        model=configuration.model,
        api_key=configuration.api_key,
        agent_tier=AgentTier.DEFAULT,
    )
    with httpx2.Client(follow_redirects=False, trust_env=False) as client:
        adapter = configured_provider_adapters(catalog, client)[route.protocol]
        report = evaluate_candidate(route, adapter, load_golden_suite(DEFAULT_SUITE_PATH))
    print(report.model_dump_json(indent=2))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
