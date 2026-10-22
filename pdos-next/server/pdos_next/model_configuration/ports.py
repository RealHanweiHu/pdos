"""Server-only ports. Implementations must use authenticated context and durable truth."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from pdos_next.providers.types import ProtocolKind


@dataclass(frozen=True)
class ManagementContext:
    tenant_id: UUID
    actor_id: UUID


class AdministratorPort(Protocol):
    def is_current_human_admin(self, context: ManagementContext) -> bool: ...


@dataclass(frozen=True)
class SecretBinding:
    tenant_id: UUID
    reference: UUID = field(repr=False)
    version: UUID = field(repr=False)
    protocol: ProtocolKind
    available: bool


@dataclass(frozen=True)
class SecretMaterial:
    binding: SecretBinding = field(repr=False)
    credential: SecretStr = field(repr=False)


class SecretPort(Protocol):
    """Current tenant/protocol slot; no fallback, env lookup, network probe or secret logging.

    A replacement/rotation must allocate a new immutable version. resolve returns exactly
    the requested reference/version or None. Implementations redact underlying exceptions.
    """

    def current(self, tenant_id: UUID, protocol: ProtocolKind) -> SecretBinding | None: ...
    def resolve(self, binding: SecretBinding) -> SecretMaterial | None: ...


@dataclass(frozen=True)
class RuntimeQuery:
    """Built by the server from the Run, never deserialized from a model/client payload."""

    tenant_id: UUID
    run_id: UUID
    writer_id: UUID
    operation: str
    purpose: str
    skill_version: str
    tool_version: str
    cancel_epoch: int


@dataclass(frozen=True)
class RuntimeFacts:
    query: RuntimeQuery
    binding_digest: str
    expires_at: datetime
    permitted: bool | None = None
    qualified: bool | None = None
    egress_allowed: bool | None = None
    budget_available: bool | None = None
    cancelled: bool | None = None
    # qualified means REAL, current golden-case eligibility for this exact binding,
    # operation, purpose, skill and tool version; old provider qualifications do not match.


class RuntimePolicyPort(Protocol):
    def current_facts(self, query: RuntimeQuery, binding_digest: str) -> RuntimeFacts | None: ...
