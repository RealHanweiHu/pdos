from __future__ import annotations

from dataclasses import replace

import pytest

from app.ai.egress import EgressConfigurationError, EgressDeniedError, ProviderEgressPolicy
from app.ai.model_catalog import (
    AgentTier,
    GoldenQualification,
    ModelCatalog,
    ProviderName,
)


def qualification() -> GoldenQualification:
    return GoldenQualification(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        suite_version="s2-v1",
        suite_digest="sha256:trusted-suite",
        status="passed",
    )


def catalog(base_url: str = "http://127.0.0.1:39111/v1") -> ModelCatalog:
    return ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_BASE_URL": base_url,
            "PDOS_LLM_API_KEY": "test-secret",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
        }
    )


def test_egress_policy_only_allows_the_configured_provider_base() -> None:
    model_catalog = catalog()
    policy = ProviderEgressPolicy.from_catalog(model_catalog)
    route = model_catalog.resolve_route(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        agent_tier=AgentTier.DEFAULT,
        qualifications=[qualification()],
    )

    policy.assert_request_allowed(route, "http://127.0.0.1:39111/v1/chat/completions")
    for denied_route, target in (
        (
            replace(route, base_url="https://untrusted.example/v1"),
            "https://untrusted.example/v1/chat/completions",
        ),
        (route, "http://127.0.0.1:39111/admin"),
        (route, "http://localhost:39111/v1/chat/completions"),
    ):
        with pytest.raises(EgressDeniedError):
            policy.assert_request_allowed(denied_route, target)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://provider.example/v1",
        "ftp://api.minimaxi.com/v1",
        "https://user:pass@api.minimaxi.com/v1",
        "https://api.minimaxi.com/v1?redirect=1",
        "https://api.minimaxi.com/v1#fragment",
    ],
)
def test_egress_policy_rejects_unsafe_configured_endpoints(base_url: str) -> None:
    with pytest.raises(EgressConfigurationError):
        ProviderEgressPolicy.from_catalog(catalog(base_url))
