"""Frozen provider catalog and model qualification boundary for the LLM gateway."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr


class ProviderName(StrEnum):
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ProtocolKind(StrEnum):
    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC_NATIVE = "anthropic-native"


class AgentTier(StrEnum):
    DEFAULT = "default"
    EXTRACTION = "extraction"
    REASONING = "reasoning"


DEFAULT_PROVIDER = ProviderName.MINIMAX


@dataclass(frozen=True)
class ProviderSpec:
    name: ProviderName
    protocol: ProtocolKind
    default_base_url: str
    default_model: str
    api_key_environment: str


PROVIDER_SPECS = (
    ProviderSpec(
        name=ProviderName.MINIMAX,
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-M3",
        api_key_environment="PDOS_LLM_MINIMAX_API_KEY",
    ),
    ProviderSpec(
        name=ProviderName.DEEPSEEK,
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        api_key_environment="PDOS_LLM_DEEPSEEK_API_KEY",
    ),
    ProviderSpec(
        name=ProviderName.GLM,
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.2",
        api_key_environment="PDOS_LLM_GLM_API_KEY",
    ),
    ProviderSpec(
        name=ProviderName.OPENAI,
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.1",
        api_key_environment="PDOS_LLM_OPENAI_API_KEY",
    ),
    ProviderSpec(
        name=ProviderName.ANTHROPIC,
        protocol=ProtocolKind.ANTHROPIC_NATIVE,
        default_base_url="https://api.anthropic.com",
        default_model="claude-sonnet-5",
        api_key_environment="ANTHROPIC_API_KEY",
    ),
)


class GoldenQualification(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    suite_version: str
    suite_digest: str
    status: Literal["passed", "failed"]


class EligibleModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    protocol: ProtocolKind


@dataclass(frozen=True)
class ProviderConfiguration:
    provider: ProviderName
    protocol: ProtocolKind
    base_url: str
    model: str
    api_key: SecretStr


@dataclass(frozen=True)
class ResolvedModelRoute:
    provider: ProviderName
    protocol: ProtocolKind
    base_url: str
    model: str
    api_key: SecretStr
    agent_tier: AgentTier


@dataclass(frozen=True)
class ModelCatalog:
    providers: tuple[ProviderSpec, ...]
    configurations: tuple[ProviderConfiguration, ...]

    @property
    def protocols(self) -> set[ProtocolKind]:
        return {provider.protocol for provider in self.providers}

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ModelCatalog:
        selected_raw = environment.get("PDOS_LLM_PROVIDER", DEFAULT_PROVIDER.value).strip()
        try:
            selected_provider = ProviderName(selected_raw)
        except ValueError as error:
            raise ValueError("PDOS_LLM_PROVIDER is not supported") from error

        configurations: list[ProviderConfiguration] = []
        for spec in PROVIDER_SPECS:
            prefix = f"PDOS_LLM_{spec.name.value.upper()}"
            specific_key = environment.get(spec.api_key_environment, "").strip()
            if spec.name is ProviderName.ANTHROPIC and not specific_key:
                specific_key = environment.get("PDOS_LLM_ANTHROPIC_API_KEY", "").strip()
            primary_key = (
                environment.get("PDOS_LLM_API_KEY", "").strip()
                if spec.name is selected_provider
                else ""
            )
            api_key = specific_key or primary_key
            if not api_key:
                continue

            primary_base_url = (
                environment.get("PDOS_LLM_BASE_URL", "").strip()
                if spec.name is selected_provider
                else ""
            )
            primary_model = (
                environment.get("PDOS_LLM_MODEL", "").strip()
                if spec.name is selected_provider
                else ""
            )
            base_url = (
                environment.get(f"{prefix}_BASE_URL", "").strip()
                or primary_base_url
                or spec.default_base_url
            )
            model = (
                environment.get(f"{prefix}_MODEL", "").strip()
                or primary_model
                or spec.default_model
            )
            configurations.append(
                ProviderConfiguration(
                    provider=spec.name,
                    protocol=spec.protocol,
                    base_url=base_url.rstrip("/"),
                    model=model,
                    api_key=SecretStr(api_key),
                )
            )
        return cls(providers=PROVIDER_SPECS, configurations=tuple(configurations))

    def configuration_for(self, provider: ProviderName) -> ProviderConfiguration | None:
        return next(
            (
                configuration
                for configuration in self.configurations
                if configuration.provider is provider
            ),
            None,
        )

    def eligible_models(
        self,
        qualifications: list[GoldenQualification],
    ) -> list[EligibleModel]:
        passed_models = {
            (qualification.provider, qualification.model)
            for qualification in qualifications
            if qualification.status == "passed"
        }
        eligible: list[EligibleModel] = []
        for spec in self.providers:
            configuration = self.configuration_for(spec.name)
            if configuration is None:
                continue
            if (configuration.provider, configuration.model) not in passed_models:
                continue
            eligible.append(
                EligibleModel(
                    provider=configuration.provider,
                    model=configuration.model,
                    protocol=configuration.protocol,
                )
            )
        return eligible

    def resolve_route(
        self,
        *,
        provider: ProviderName,
        model: str,
        agent_tier: AgentTier,
        qualifications: list[GoldenQualification],
    ) -> ResolvedModelRoute:
        allowed = {
            (candidate.provider, candidate.model)
            for candidate in self.eligible_models(qualifications)
        }
        configuration = self.configuration_for(provider)
        if configuration is None or (provider, model) not in allowed:
            raise ValueError("model is not configured and golden-qualified")
        return ResolvedModelRoute(
            provider=configuration.provider,
            protocol=configuration.protocol,
            base_url=configuration.base_url,
            model=configuration.model,
            api_key=configuration.api_key,
            agent_tier=agent_tier,
        )
