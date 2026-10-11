"""Server-bound scan contracts. These DTOs are never authorization-bearing request payloads."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef


def aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware server timestamp is required")


def label(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("A bounded server-owned version label is required")
    if any(ord(c) < 32 for c in value):
        raise ValueError("Version labels cannot contain control characters")


def error_code(value: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 80
        or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in value)
    ):
        raise ValueError("Only bounded machine error codes are accepted")


class ScanStatus(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class SecurityState(StrEnum):
    NOT_SCANNED = "not_scanned"
    CLEAN = "clean"
    QUARANTINED = "quarantined"
    SCAN_FAILED = "scan_failed"
    STALE = "stale"


class SecurityFailure(Exception):
    def __init__(self, code: str):
        # Raw scanner diagnostics / document snippets must not leak to logs or UI.
        error_code(code)
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScanLimits:
    max_input_bytes: int = 8_388_608
    max_zip_entries: int = 1_000
    max_zip_expanded_bytes: int = 50_000_000
    max_zip_entry_bytes: int = 20_000_000
    max_zip_ratio: int = 100
    timeout_seconds: float = 15

    def __post_init__(self):
        caps = {
            "max_input_bytes": 50_000_000,
            "max_zip_entries": 2_000,
            "max_zip_expanded_bytes": 100_000_000,
            "max_zip_entry_bytes": 50_000_000,
            "max_zip_ratio": 200,
        }
        for name, cap in caps.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError(f"Invalid bounded budget: {name}")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 60
        ):
            raise ValueError("Scan timeout must be finite and at most 60 seconds")


@dataclass(frozen=True, slots=True)
class ScannerIdentity:
    scanner: str
    engine_version: str
    rules_version: str

    def __post_init__(self):
        for value in asdict(self).values():
            label(value)


@dataclass(frozen=True, slots=True)
class ScanPolicy:
    version: str = "pdos-evidence-security-v1"
    limits: ScanLimits = ScanLimits()
    clean_max_age_seconds: int = 86_400

    def __post_init__(self):
        label(self.version)
        if not isinstance(self.limits, ScanLimits):
            raise ValueError("Typed scan limits required")
        if type(self.clean_max_age_seconds) is not int or not (
            1 <= self.clean_max_age_seconds <= 604_800
        ):
            raise ValueError("Clean receipt validity must be bounded")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ScanConfiguration:
    scanner: ScannerIdentity
    policy: ScanPolicy

    def __post_init__(self):
        if not isinstance(self.scanner, ScannerIdentity) or not isinstance(self.policy, ScanPolicy):
            raise ValueError("Current server scanner configuration must be typed")


@dataclass(frozen=True, slots=True)
class ScanBinding:
    """Read from server scope/ACL/source ports, never copied from a model or payload."""

    object_ref: ObjectRef
    tenant_id: UUID
    product_id: UUID | None
    requester_id: UUID
    original_revision: int
    access_revision: str
    audience_revision: str
    source_active: bool
    category_id: UUID | None = None

    def __post_init__(self):
        if not isinstance(self.object_ref, ObjectRef) or any(
            not isinstance(value, UUID)
            for value in (self.tenant_id, self.requester_id)
        ):
            raise ValueError("Exact object and server scope UUIDs required")
        if ((self.product_id is not None and not isinstance(self.product_id, UUID))
            or (self.category_id is not None and not isinstance(self.category_id, UUID))
            or (self.product_id is None and self.category_id is None)):
            raise ValueError("A category must bind a pre-model original")
        if type(self.object_ref.version) is not int or type(self.object_ref.size_bytes) is not int:
            raise ValueError("Object versions and byte sizes must be exact integers")
        if type(self.original_revision) is not int or self.original_revision < 1:
            raise ValueError("Positive original read revision required")
        if type(self.source_active) is not bool:
            raise ValueError("Source availability must be authoritative")
        label(self.access_revision)
        label(self.audience_revision)


@dataclass(frozen=True, slots=True)
class ScanRequest:
    request_id: UUID
    binding: ScanBinding
    scanner: ScannerIdentity
    policy: ScanPolicy
    requested_at: datetime

    def __post_init__(self):
        if not isinstance(self.request_id, UUID) or not isinstance(self.binding, ScanBinding):
            raise ValueError("A server-created scan request is required")
        if not isinstance(self.scanner, ScannerIdentity) or not isinstance(self.policy, ScanPolicy):
            raise ValueError("Scanner and policy versions are required")
        aware(self.requested_at)


@dataclass(frozen=True, slots=True)
class ScannerReply:
    """Transport response must echo every identity; no raw diagnostic text is accepted."""

    request_id: UUID
    object_ref: ObjectRef
    scanner: ScannerIdentity
    status: ScanStatus
    error_code: str | None = None

    def __post_init__(self):
        if not isinstance(self.request_id, UUID) or not isinstance(self.object_ref, ObjectRef):
            raise ValueError("Exact response object identity required")
        if not isinstance(self.scanner, ScannerIdentity) or not isinstance(self.status, ScanStatus):
            raise ValueError("Typed scanner identity and result required")
        if self.error_code is not None:
            error_code(self.error_code)
        if self.status == ScanStatus.CLEAN and self.error_code is not None:
            raise ValueError("An error cannot certify clean bytes")


@dataclass(frozen=True, slots=True)
class ScanReceipt:
    request_id: UUID
    binding: ScanBinding
    scanner: ScannerIdentity
    policy_digest: str
    status: ScanStatus
    started_at: datetime
    completed_at: datetime
    error_code: str | None = None

    def __post_init__(self):
        if not isinstance(self.request_id, UUID) or not isinstance(self.binding, ScanBinding):
            raise ValueError("Exact server request and binding required")
        if not isinstance(self.scanner, ScannerIdentity) or not isinstance(self.status, ScanStatus):
            raise ValueError("Typed scan receipt required")
        if len(self.policy_digest) != 64 or any(
            c not in "0123456789abcdef" for c in self.policy_digest
        ):
            raise ValueError("A policy SHA-256 is required")
        aware(self.started_at)
        aware(self.completed_at)
        if self.completed_at < self.started_at:
            raise ValueError("Receipt time order is invalid")
        if self.error_code is not None:
            error_code(self.error_code)
        if self.status == ScanStatus.CLEAN and self.error_code is not None:
            raise ValueError("An error cannot certify clean bytes")


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    state: SecurityState
    allow_parse: bool
    quarantine_required: bool
    reasons: tuple[str, ...]


class ScanGuardPort(Protocol):
    def current_configuration(self) -> ScanConfiguration:
        """Current local scanner/rules and budget policy from server-owned configuration."""
        ...

    def bind_for_scan(self, object_ref: ObjectRef) -> ScanBinding:
        """Bind uploaded readable active object and scope/actor/ACL from server context.

        Must deny pending/failed upload, lifecycle-quarantined/inflight/unknown or withdrawn
        originals. Scanner-driven quarantine may still be read by an authorized rescanner.
        """
        ...

    def is_current(self, binding: ScanBinding) -> bool:
        """Recheck source/scope/ACL/lifecycle fence; failure or unknown must return False."""
        ...


class ScannerPort(Protocol):
    async def scan(self, request: ScanRequest) -> ScanReceipt: ...


class ScanTransportPort(Protocol):
    async def inspect(self, request: ScanRequest, content: bytes) -> ScannerReply:
        """Local server-owned transport; bounded/cancellable, no implicit external egress.

        CLEAN requires actual whole-byte scan with independently observed engine/rule versions,
        not an echo of requested versions. No request/LLM-supplied transport or fake in runtime.
        """
        ...


class ScanReceiptStorePort(Protocol):
    def stage_receipt(self, request: ScanRequest, receipt: ScanReceipt) -> None:
        """Caller-owned command transaction; lock/recheck binding, stage Audit/Outbox, no commit.

        Unique request ID: replay same receipt, reject conflicting receipt. Scanner results are
        worker inputs, never accepted through a public request payload. No receipt means no clean.
        """
        ...
