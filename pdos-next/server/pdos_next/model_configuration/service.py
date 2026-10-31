"""Immutable tenant configuration plans consumed inside the COMMON command transaction.

This module has no confirmation tokens, receipts, commits, model calls or qualification writes.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import (
    AdministratorPort,
    ManagementContext,
    SecretBinding,
    SecretPort,
)
from pdos_next.schemas.model_configuration import (
    ConfigurationReading,
    ModelMetadata,
    SaveConfiguration,
    SavePreview,
)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fail(code: str, status: int = 409):
    raise DomainError(code, "模型配置条件已变化或尚不可用，请重新核对当前配置。", status) from None


def utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


@dataclass(frozen=True)
class ConfigurationVersion:
    tenant_id: UUID
    id: UUID
    revision: int
    metadata: ModelMetadata
    enabled: bool
    created_by: UUID
    created_at: datetime
    secret: SecretBinding | None = field(repr=False)

    @property
    def binding_digest(self) -> str:
        return digest(
            {
                "tenant": str(self.tenant_id),
                "id": str(self.id),
                "revision": self.revision,
                "metadata": self.metadata.binding_metadata(),
                "enabled": self.enabled,
                "secret": secret_digest(self.secret),
            }
        )

    @property
    def provider_version(self) -> str:
        # The existing Qualification.provider_version column has a 160-character bound.
        return f"mc:{self.id}:{self.revision}:{self.binding_digest}"


class ConfigurationStore(Protocol):
    def current(self, tenant_id: UUID) -> ConfigurationVersion | None: ...
    def append(self, version: ConfigurationVersion, *, expected_revision: int) -> None:
        """Atomic CAS append in caller Session; lock head, no commit, no partial writes."""
        ...


def secret_digest(binding: SecretBinding | None) -> str | None:
    if binding is None:
        return None
    return digest(
        {
            "tenant": str(binding.tenant_id),
            "reference": str(binding.reference),
            "version": str(binding.version),
            "protocol": binding.protocol,
        }
    )


def current_secret(
    port: SecretPort | None, tenant: UUID, protocol: str, metadata=None
) -> SecretBinding | None:
    if port is None:
        fail("MODEL_SECRET_INTERFACE_MISSING")
    try:
        if metadata is not None and getattr(metadata, "connection_id", None) is not None:
            selector = getattr(port, "current_for", None)
            if selector is None:
                fail("MODEL_SECRET_SCOPE_MISMATCH", 403)
            value = selector(tenant, metadata)
        else:
            value = port.current(tenant, protocol)
    except Exception:
        fail("MODEL_SECRET_UNAVAILABLE")
    if value is not None and (
        not isinstance(value, SecretBinding)
        or value.tenant_id != tenant
        or value.protocol != protocol
        or not isinstance(value.reference, UUID)
        or not isinstance(value.version, UUID)
        or type(value.available) is not bool
    ):
        fail("MODEL_SECRET_SCOPE_MISMATCH", 403)
    return value


@dataclass(frozen=True)
class SavePlan:
    context: ManagementContext
    expected_revision: int
    previous_digest: str | None
    version: ConfigurationVersion
    expires_at: datetime

    @property
    def digest(self) -> str:
        return digest(
            {
                "tenant": str(self.context.tenant_id),
                "actor": str(self.context.actor_id),
                "expected": self.expected_revision,
                "previous": self.previous_digest,
                "next": self.version.binding_digest,
                "expires": self.expires_at.isoformat(),
            }
        )

    def preview(self) -> SavePreview:
        return SavePreview(
            expected_revision=self.expected_revision,
            next_revision=self.version.revision,
            metadata=self.version.metadata,
            enabled=self.version.enabled,
            credential_status="bound"
            if self.version.secret and self.version.secret.available
            else "missing",
            digest=self.digest,
            expires_at=self.expires_at,
        )


class ConfigurationService:
    def __init__(
        self,
        store: ConfigurationStore,
        administrators: AdministratorPort | None,
        secrets: SecretPort | None,
    ):
        self.store, self.administrators, self.secrets = store, administrators, secrets

    def _admin(self, context: ManagementContext):
        if self.administrators is None:
            fail("MODEL_ADMIN_INTERFACE_MISSING", 403)
        try:
            allowed = self.administrators.is_current_human_admin(context)
        except Exception:
            fail("MODEL_ADMIN_UNAVAILABLE", 403)
        if allowed is not True:
            fail("MODEL_ADMIN_REQUIRED", 403)

    def _head(self, tenant: UUID):
        head = self.store.current(tenant)
        if head is not None and head.tenant_id != tenant:
            fail("MODEL_CONFIGURATION_SCOPE_MISMATCH", 403)
        return head

    def plan(
        self, context: ManagementContext, payload: SaveConfiguration, *, now: datetime
    ) -> SavePlan:
        self._admin(context)
        if not utc(now):
            fail("MODEL_CLOCK_INVALID")
        # Revalidate even when a caller used model_construct; never log ValidationError input.
        try:
            payload = SaveConfiguration.model_validate(payload.model_dump(mode="python"))
        except (ValidationError, ValueError, AttributeError, TypeError):
            fail("MODEL_CONFIGURATION_INPUT_INVALID", 422)
        head = self._head(context.tenant_id)
        if (head.revision if head else 0) != payload.expected_revision:
            fail("MODEL_CONFIGURATION_STALE")
        secret = current_secret(
            self.secrets, context.tenant_id, payload.metadata.protocol, payload.metadata)
        version = ConfigurationVersion(
            tenant_id=context.tenant_id,
            id=uuid5(
                NAMESPACE_URL,
                "pdos-next:model-configuration:"
                + digest(
                    {
                        "tenant": str(context.tenant_id),
                        "expected_revision": payload.expected_revision,
                        "previous": head.binding_digest if head else None,
                        "metadata": payload.metadata.binding_metadata(),
                        "enabled": payload.enabled,
                        "secret": secret_digest(secret),
                    }
                ),
            ),
            revision=payload.expected_revision + 1,
            metadata=payload.metadata,
            enabled=payload.enabled,
            created_by=context.actor_id,
            created_at=now,
            secret=secret,
        )
        return SavePlan(
            context,
            payload.expected_revision,
            head.binding_digest if head else None,
            version,
            now + timedelta(minutes=5),
        )

    def restore_reviewed_plan(
        self,
        context: ManagementContext,
        payload: SaveConfiguration,
        reviewed: SavePreview,
        *,
        now: datetime,
    ) -> SavePlan:
        """Rebuild only from the COMMON persisted preview after its confirmation guard.

        No secret references must be placed in its public review snapshot. The deterministic
        version ID and original expiry let mainline reconstruct this plan without a second
        preview store, while current config/secret/admin facts are re-read and compared.
        Client-supplied reviewed objects are not authorization to call apply_plan.
        """
        if not utc(now) or not utc(reviewed.expires_at) or now >= reviewed.expires_at:
            fail("MODEL_CONFIGURATION_PREVIEW_EXPIRED")
        restored = self.plan(context, payload, now=reviewed.expires_at - timedelta(minutes=5))
        if restored.preview() != reviewed:
            fail("MODEL_CONFIGURATION_PREVIEW_CHANGED")
        return restored

    def apply_plan(
        self, context: ManagementContext, plan: SavePlan, *, now: datetime
    ) -> ConfigurationVersion:
        """Only call AFTER the common preview/confirmation guard, in its transaction.

        The store CAS must serialize same-tenant writers. The secret snapshot and admin
        facts must also remain current to commit (mainline transaction/secret-port contract).
        """
        self._admin(context)
        if (
            context != plan.context
            or plan.version.tenant_id != context.tenant_id
            or plan.version.created_by != context.actor_id
        ):
            fail("MODEL_CONFIGURATION_SCOPE_MISMATCH", 403)
        if not utc(now) or not utc(plan.expires_at) or now >= plan.expires_at:
            fail("MODEL_CONFIGURATION_PREVIEW_EXPIRED")
        head = self._head(context.tenant_id)
        if (
            (head.revision if head else 0) != plan.expected_revision
            or (head.binding_digest if head else None) != plan.previous_digest
            or plan.version.revision != plan.expected_revision + 1
        ):
            fail("MODEL_CONFIGURATION_STALE")
        secret = current_secret(
            self.secrets, context.tenant_id, plan.version.metadata.protocol, plan.version.metadata)
        if secret != plan.version.secret:
            fail("MODEL_SECRET_CHANGED")
        self.store.append(plan.version, expected_revision=plan.expected_revision)
        return plan.version

    def reading(self, context: ManagementContext) -> ConfigurationReading | None:
        self._admin(context)
        head = self._head(context.tenant_id)
        if head is None:
            return None
        try:
            secret = current_secret(
                self.secrets, context.tenant_id, head.metadata.protocol, head.metadata)
            if secret_digest(secret) != secret_digest(head.secret):
                state, display = "changed", "需重新绑定"
            elif secret is None or not secret.available:
                state, display = "missing", "未绑定"
            else:
                state, display = "bound", "已绑定 ••••"
        except DomainError:
            state, display = "unavailable", "暂不可核对"
        return ConfigurationReading(
            revision=head.revision,
            version_id=head.id,
            provider_version=head.provider_version,
            metadata=head.metadata,
            enabled=head.enabled,
            credential_status=state,
            credential_display=display,
            created_at=head.created_at,
        )


def parse_save_payload(payload: object) -> SaveConfiguration:
    """Use at the common command boundary; never echo Pydantic errors()/raw input."""
    try:
        return SaveConfiguration.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        fail("MODEL_CONFIGURATION_INPUT_INVALID", 422)
