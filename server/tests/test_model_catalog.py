from __future__ import annotations

from app.ai.model_catalog import (
    DEFAULT_PROVIDER,
    AgentTier,
    GoldenQualification,
    ModelCatalog,
    ProtocolKind,
    ProviderName,
)


def passed(provider: ProviderName, model: str) -> GoldenQualification:
    return GoldenQualification(
        provider=provider,
        model=model,
        suite_version="s2-v1",
        suite_digest="sha256:test-suite",
        status="passed",
    )


def test_catalog_defaults_to_minimax_and_freezes_two_protocol_shapes() -> None:
    catalog = ModelCatalog.from_environment({})

    assert DEFAULT_PROVIDER is ProviderName.MINIMAX
    assert catalog.protocols == {
        ProtocolKind.OPENAI_COMPATIBLE,
        ProtocolKind.ANTHROPIC_NATIVE,
    }
    assert [provider.name for provider in catalog.providers] == [
        ProviderName.MINIMAX,
        ProviderName.DEEPSEEK,
        ProviderName.GLM,
        ProviderName.OPENAI,
        ProviderName.ANTHROPIC,
    ]


def test_catalog_requires_both_credentials_and_passed_golden_qualification() -> None:
    catalog = ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_API_KEY": "minimax-secret",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
            "PDOS_LLM_DEEPSEEK_API_KEY": "deepseek-secret",
            "PDOS_LLM_DEEPSEEK_MODEL": "deepseek-v4-flash",
            "PDOS_LLM_OPENAI_API_KEY": "openai-secret",
            "PDOS_LLM_OPENAI_MODEL": "gpt-5.1",
        }
    )

    eligible = catalog.eligible_models(
        [
            passed(ProviderName.MINIMAX, "MiniMax-M2.7"),
            passed(ProviderName.OPENAI, "gpt-5.1"),
            GoldenQualification(
                provider=ProviderName.DEEPSEEK,
                model="deepseek-v4-flash",
                suite_version="s2-v1",
                suite_digest="sha256:test-suite",
                status="failed",
            ),
            passed(ProviderName.GLM, "glm-5.2"),
        ]
    )

    assert [(item.provider, item.model) for item in eligible] == [
        (ProviderName.MINIMAX, "MiniMax-M2.7"),
        (ProviderName.OPENAI, "gpt-5.1"),
    ]
    assert all("key" not in item.model_dump(mode="json") for item in eligible)
    assert all("base_url" not in item.model_dump(mode="json") for item in eligible)


def test_primary_credentials_only_apply_to_the_selected_primary_provider() -> None:
    catalog = ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "deepseek",
            "PDOS_LLM_BASE_URL": "https://api.deepseek.com",
            "PDOS_LLM_API_KEY": "primary-secret",
            "PDOS_LLM_MODEL": "deepseek-v4-flash",
        }
    )

    assert catalog.configuration_for(ProviderName.DEEPSEEK) is not None
    assert catalog.configuration_for(ProviderName.MINIMAX) is None
    assert "primary-secret" not in repr(catalog)


def test_agent_tier_is_preserved_without_overriding_the_tenant_model() -> None:
    catalog = ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_API_KEY": "minimax-secret",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
        }
    )
    qualifications = [passed(ProviderName.MINIMAX, "MiniMax-M2.7")]

    extraction = catalog.resolve_route(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        agent_tier=AgentTier.EXTRACTION,
        qualifications=qualifications,
    )
    reasoning = catalog.resolve_route(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        agent_tier=AgentTier.REASONING,
        qualifications=qualifications,
    )

    assert extraction.provider == reasoning.provider == ProviderName.MINIMAX
    assert extraction.model == reasoning.model == "MiniMax-M2.7"
    assert extraction.agent_tier is AgentTier.EXTRACTION
    assert reasoning.agent_tier is AgentTier.REASONING


def test_unqualified_or_mismatched_models_fail_closed() -> None:
    catalog = ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_API_KEY": "minimax-secret",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
        }
    )

    for model, qualifications in (
        ("MiniMax-M2.7", []),
        ("unconfigured-model", [passed(ProviderName.MINIMAX, "unconfigured-model")]),
    ):
        try:
            catalog.resolve_route(
                provider=ProviderName.MINIMAX,
                model=model,
                agent_tier=AgentTier.DEFAULT,
                qualifications=qualifications,
            )
        except ValueError as error:
            assert str(error) == "model is not configured and golden-qualified"
        else:
            raise AssertionError("unqualified model route must fail closed")
