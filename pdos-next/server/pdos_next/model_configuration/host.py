"""Server-owned tenant routing metadata; credential material lives only in KMS."""

import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from pdos_next.agent_kernel.mcp_runtime import McpConfiguration
from pdos_next.agent_kernel.pricing import RateCard
from pdos_next.errors import DomainError
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.model_configuration.local_kms import LOCAL_ENDPOINT, LOCAL_REGION
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.providers.types import ProtocolKind
from pdos_next.research.runtime import ResearchConfiguration
from pdos_next.schemas.model_configuration import ModelMetadata
from pdos_next.schemas.model_configuration.dto import ClosedDTO


class KmsLocation(ClosedDTO):
    region: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    endpoint: str

    @model_validator(mode="after")
    def shared_gateway(self):
        # The ("local", "local-keychain") pair selects the macOS Keychain development
        # backend and is never dialed; all other configs require the exact Aliyun gateway.
        if (self.region, self.endpoint) != (LOCAL_REGION, LOCAL_ENDPOINT) and (
            self.endpoint
            not in {
                f"kms.{self.region}.aliyuncs.com",
                f"kms-vpc.{self.region}.aliyuncs.com",
            }
        ):
            raise ValueError("An exact KMS shared gateway endpoint is required")
        return self


class SecretSlot(ClosedDTO):
    tenant_id: UUID
    protocol: ProtocolKind
    reference: UUID
    secret_arn: str = Field(pattern=r"^acs:kms:[a-z0-9-]+:[0-9]+:secret/[^\s]+$")


class Pricing(ClosedDTO):
    source: str = Field(min_length=1, max_length=2000)
    verified_at: datetime
    valid_until: datetime
    input_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cache_read_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cache_creation_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    request_fee: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    currency: Literal["USD"]
    text_tokens_per_utf8_byte: Decimal = Field(ge=1, allow_inf_nan=False)
    text_framing_tokens: int = Field(ge=0)
    text_billing_source: str = Field(min_length=1, max_length=2000)
    output_cap_covers_all_billing: bool
    covers_all_fees: bool


class ModelHost(ClosedDTO):
    tenant_id: UUID
    protocol: ProtocolKind
    base_url: str
    model: str
    model_version: str
    provider: str = Field(min_length=1, max_length=160)
    pricing: Pricing
    max_output_tokens: int = Field(default=2048, strict=True, ge=1, le=524288)
    context_window_tokens: int | None = Field(default=None, strict=True, ge=1024, le=10_000_000)
    development_unlimited_budget: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def valid_route(self):
        from urllib.parse import urlsplit

        from pdos_next.providers.types import output_limit_upper_bound

        ModelMetadata(
            protocol=self.protocol,
            base_url=self.base_url,
            model=self.model,
            model_version=self.model_version,
        )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}", self.provider):
            raise ValueError("A registered public provider identity is required")
        if self.max_output_tokens > output_limit_upper_bound(self.base_url, self.model):
            raise ValueError("Output exceeds the registered provider boundary")
        if self.development_unlimited_budget and (
            self.provider != "minimax"
            or urlsplit(self.base_url).hostname not in {"api.minimax.cn", "api.minimax.io"}
        ):
            raise ValueError("Development budget policy is only available for MiniMax")
        return self

    def key(self):
        return (
            self.tenant_id,
            self.protocol,
            self.base_url.rstrip("/"),
            self.model,
            self.model_version,
        )


class ManagedConnection(ClosedDTO):
    id: UUID
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=120)
    metadata: ModelMetadata
    provider: str
    secret: SecretSlot
    pricing: Pricing | None = None
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_by: UUID
    created_at: datetime

    @model_validator(mode="after")
    def bound_connection(self):
        if (
            self.metadata.connection_id != self.id
            or self.secret.tenant_id != self.tenant_id
            or self.secret.protocol != self.metadata.protocol
        ):
            raise ValueError("Managed connection binding mismatch")
        return self

    @property
    def development_unlimited_budget(self):
        return False


class HostConfiguration(ClosedDTO):
    format_version: Literal[1]
    kms: KmsLocation
    secrets: list[SecretSlot]
    models: list[ModelHost]
    connections: list[ManagedConnection] = Field(default_factory=list)
    research: ResearchConfiguration | None = None
    mcp: McpConfiguration | None = None

    @model_validator(mode="after")
    def unique_bindings(self):
        slots = [(slot.tenant_id, slot.protocol) for slot in self.secrets]
        models = [row.key() for row in self.models]
        connections = [(row.tenant_id, row.id) for row in self.connections]
        if len(set(connections)) != len(connections):
            raise ValueError("Managed connections must be unique")
        if len(set(slots)) != len(slots) or len(set(models)) != len(models):
            raise ValueError("Tenant runtime bindings must be unique")
        if any(slot.secret_arn.split(":")[2] != self.kms.region for slot in self.secrets):
            raise ValueError("KMS secret and endpoint regions must match")
        if any(row.secret.secret_arn.split(":")[2] != self.kms.region for row in self.connections):
            raise ValueError("Managed secret and endpoint regions must match")
        if self.mcp and any(
            slot.secret_arn.split(":")[2] != self.kms.region for slot in self.mcp.secrets
        ):
            raise ValueError("MCP KMS secret and endpoint regions must match")
        return self


class TenantRuntime:
    def __init__(self, path, *, kms_factory=AliyunKms):
        self.path, self.kms_factory = Path(path), kms_factory
        self._kms_instance = None

    def kms(self, config):
        key = config.kms.region, config.kms.endpoint
        current = self._kms_instance
        if current is None or current[0] != key:
            current = key, self.kms_factory(*key)
            self._kms_instance = current
        return current[1]

    def configuration(self):
        try:
            if not self.path.is_absolute():
                raise ValueError("API and Worker require the same absolute metadata path")
            if self.path.stat().st_size > 2_097_152:
                raise ValueError("Runtime metadata exceeds its transport bound")
            return HostConfiguration.model_validate_json(self.path.read_bytes())
        except Exception:
            raise DomainError("SOURCE_UNAVAILABLE", "租户模型宿主配置暂不可用。") from None

    @staticmethod
    def slot(config, tenant, protocol):
        return next(
            (row for row in config.secrets if row.tenant_id == tenant and row.protocol == protocol),
            None,
        )

    @staticmethod
    def binding(config, slot, version):
        value = (
            f"{slot.tenant_id}:{slot.protocol}:{config.kms.endpoint}:{slot.secret_arn}:{version}"
        )
        return SecretBinding(
            slot.tenant_id, slot.reference, uuid5(slot.reference, value), slot.protocol, True
        )

    def current(self, tenant, protocol):
        config = self.configuration()
        slot = self.slot(config, tenant, protocol)
        if slot is None:
            return None
        kms = self.kms(config)
        version = kms.current_version(slot.secret_arn)
        return self.binding(config, slot, version) if version else None

    def resolve(self, binding):
        config = self.configuration()
        slot = next((row for row in [*config.secrets, *(c.secret for c in config.connections)]
            if (row.tenant_id, row.protocol, row.reference) == (
                binding.tenant_id, binding.protocol, binding.reference)), None)
        if slot is None:
            return None
        kms = self.kms(config)
        version = kms.current_version(slot.secret_arn)
        if not version or self.binding(config, slot, version) != binding:
            return None
        return SecretMaterial(binding, kms.value(slot.secret_arn, version))

    def model(self, scope, route):
        if getattr(route, "connection_id", None) is not None:
            return self.connection(scope.tenant_id, route)
        key = (
            scope.tenant_id,
            route.protocol,
            route.base_url.rstrip("/"),
            route.model,
            route.version,
        )
        selected = next((row for row in self.configuration().models if row.key() == key), None)
        if selected is None:
            raise DomainError("SOURCE_UNAVAILABLE", "当前模型未绑定租户服务商与价格卡。")
        return selected

    def connection(self, tenant_id, route, *, config=None):
        config = config or self.configuration()
        selected = next((row for row in config.connections
            if row.tenant_id == tenant_id and row.id == route.connection_id), None)
        version = getattr(route, "model_version", None) or route.version
        if selected is None or (
            selected.metadata.protocol, selected.metadata.base_url.rstrip("/"),
            selected.metadata.model, selected.metadata.model_version
        ) != (route.protocol, route.base_url.rstrip("/"), route.model, version):
            raise DomainError("SOURCE_UNAVAILABLE", "当前模型连接不属于本租户或配置已变化。")
        return selected

    def current_for(self, tenant_id, metadata):
        config = self.configuration()
        selected = self.connection(tenant_id, metadata, config=config)
        version = self.kms(config).current_version(selected.secret.secret_arn)
        return self.binding(config, selected.secret, version) if version else None

    def mcp_secret(self, tenant_id, reference):
        config = self.configuration()
        slot = next((
            item for item in config.mcp.secrets
            if item.tenant_id == tenant_id and item.reference == reference
        ), None) if config.mcp else None
        if slot is None:
            return None
        kms = self.kms(config)
        version = kms.current_version(slot.secret_arn)
        return kms.value(slot.secret_arn, version) if version else None

    def provider_for(self, scope, route):
        return self.model(scope, route).provider

    def output_limit_for(self, scope, route):
        if getattr(route, "connection_id", None) is not None:
            self.connection(scope.tenant_id, route)
            return route.max_output_tokens
        return self.model(scope, route).max_output_tokens

    def development_budget_for(self, scope, route):
        return self.model(scope, route).development_unlimited_budget

    def rate_card_for(self, scope, route):
        model = self.model(scope, route)
        if model.pricing is None:
            raise DomainError("SOURCE_UNAVAILABLE", "此服务商尚未填写已核对的价格与计费资料。")
        card = RateCard(
            provider=model.provider,
            model=route.model,
            configuration_version=route.version,
            **model.pricing.model_dump(),
        )
        card.validate(model.provider, route)
        return card


def runtime_ports(engine=None):
    from pdos_next.agent_kernel.bootstrap import RuntimePorts

    path = os.environ.get("PDOS_TENANT_RUNTIME_CONFIG")
    if not path:
        return RuntimePorts()
    from pdos_next.model_configuration.local_kms import factory_for

    host = TenantRuntime(path, kms_factory=factory_for)
    research = {}
    mcp = {}
    if engine is not None:
        try:
            config = host.configuration().research
        except DomainError:
            config = None  # Other business features stay available; model status reports the error.
        if config is not None:
            from pdos_next.research.runtime import configured_ports

            try:
                research = configured_ports(engine, config)
            except OSError:
                research = {}  # A missing research volume must not disable ordinary business APIs.
        try:
            config = host.configuration().mcp
        except DomainError:
            config = None
        if config is not None:
            from pdos_next.agent_kernel.mcp_runtime import configured_ports as mcp_ports
            try:
                mcp = mcp_ports(engine, config, host)
            except OSError:
                mcp = {}  # Missing MCP storage only disables the corresponding read path.
    return RuntimePorts(
        secrets=host,
        provider_for=host.provider_for,
        rate_card_for=host.rate_card_for,
        output_limit_for=host.output_limit_for,
        development_budget_for=host.development_budget_for,
        **research,
        **mcp,
    )
