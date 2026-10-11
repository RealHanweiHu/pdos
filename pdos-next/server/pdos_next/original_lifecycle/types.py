"""Server-consumed lifecycle facts. These types are not HTTP permission payloads."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from re import fullmatch
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef


class LifecycleFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Lifecycle times require a timezone")


def token(value: str, name: str, *, maximum: int = 160) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Invalid {name}")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"Invalid {name}")


def positive(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"Invalid {name}")


def exact_reference(value: ObjectRef) -> None:
    if not isinstance(value, ObjectRef) or not isinstance(value.id, UUID):
        raise ValueError("An exact server ObjectRef is required")
    if type(value.version) is not int or type(value.size_bytes) is not int:
        raise ValueError("Object version and size must be integers")
    # The shared ObjectRef constructor checks the immutable key/hash/version.
    value.__post_init__()
    token(value.media_type, "media type", maximum=100)


class LifecycleAction(StrEnum):
    PREVIEW = "preview"
    QUARANTINE = "quarantine"
    RESTORE = "restore"
    RECONCILE = "reconcile"


class ActorKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    AGENT = "agent"


class UploadState(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class ParseState(StrEnum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    RUNNING = "running"
    PARSED = "parsed"
    FAILED = "failed"
    NEEDS_OCR = "needs_ocr"
    UNKNOWN = "unknown"


class Disposition(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    PURGED = "purged"
    UNKNOWN = "unknown"


class IntentState(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    UNKNOWN = "unknown"
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    CANCELLED = "cancelled"


class EffectOutcome(StrEnum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


class DecisionReason(StrEnum):
    REFERENCE_UNKNOWN = "reference_unknown"
    REFERENCED = "referenced"
    FORMAL_HISTORY = "formal_history"
    HOLD_UNKNOWN = "hold_unknown"
    MANUAL_HOLD = "manual_hold"
    REGISTRATION_UNKNOWN = "registration_unknown"
    REGISTERED_ORIGINAL = "registered_original"
    UPLOAD_NOT_TERMINAL = "upload_not_terminal"
    UPLOAD_TIME_UNKNOWN = "upload_time_unknown"
    PARSE_UNKNOWN = "parse_unknown"
    PARSE_IN_PROGRESS = "parse_in_progress"
    DERIVATION_PRESENT = "derivation_present"
    RETENTION_UNKNOWN = "retention_unknown"
    RETENTION_NOT_ELAPSED = "retention_not_elapsed"
    STATE_UNKNOWN = "state_unknown"
    WRONG_DISPOSITION = "wrong_disposition"
    EFFECT_PENDING = "effect_pending"
    QUARANTINE_TIME_UNKNOWN = "quarantine_time_unknown"
    FACT_TIME_INVALID = "fact_time_invalid"


@dataclass(frozen=True, slots=True)
class LifecycleScope:
    tenant_id: UUID
    product_id: UUID | None
    category_id: UUID | None = None

    def __post_init__(self):
        if (
            not isinstance(self.tenant_id, UUID)
            or (self.product_id is not None and not isinstance(self.product_id, UUID))
            or (self.category_id is not None and not isinstance(self.category_id, UUID))
            or (self.product_id is None and self.category_id is None)
        ):
            raise ValueError("Scope must be server-bound UUIDs")


@dataclass(frozen=True, slots=True)
class CurrentAuthorization:
    reference: ObjectRef
    scope: LifecycleScope
    actor_id: UUID
    actor_kind: ActorKind
    action: LifecycleAction
    access_revision: str
    expires_at: datetime | None
    named_decider_id: UUID | None = None
    decision_intent_id: UUID | None = None

    def __post_init__(self):
        exact_reference(self.reference)
        if not isinstance(self.scope, LifecycleScope) or not isinstance(self.actor_id, UUID):
            raise ValueError("Authorization requires server-bound scope and actor")
        if not isinstance(self.action, LifecycleAction) or not isinstance(
            self.actor_kind, ActorKind
        ):
            raise ValueError("Authorization requires typed action and actor kind")
        for value in (self.named_decider_id, self.decision_intent_id):
            if value is not None and not isinstance(value, UUID):
                raise ValueError("Invalid named decision binding")
        token(self.access_revision, "authorization revision")
        if self.expires_at is not None:
            aware(self.expires_at)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Required server configuration, never taken from a candidate or request."""

    version: str
    failed_upload_grace: timedelta
    quarantine_grace: timedelta
    effect_timeout: timedelta

    def __post_init__(self):
        token(self.version, "policy version")
        for name in (
            "failed_upload_grace",
            "quarantine_grace",
            "effect_timeout",
        ):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise ValueError("Retention and time budgets must be positive durations")
        if self.effect_timeout > timedelta(minutes=10):
            raise ValueError("Effect execution budget must be bounded")


@dataclass(frozen=True, slots=True)
class OriginalState:
    reference: ObjectRef
    scope: LifecycleScope
    revision: int
    inventory_revision: str
    created_at: datetime
    observed_at: datetime
    upload_state: UploadState
    registered: bool | None
    upload_terminal_at: datetime | None
    parse_state: ParseState
    retention_until: datetime | None
    manual_hold: bool | None
    disposition: Disposition = Disposition.ACTIVE
    quarantined_at: datetime | None = None
    pending_intent_id: UUID | None = None

    def __post_init__(self):
        exact_reference(self.reference)
        if not isinstance(self.scope, LifecycleScope):
            raise ValueError("Original scope must be server-bound")
        positive(self.revision, "original lifecycle revision")
        token(self.inventory_revision, "inventory revision")
        for value in (self.created_at, self.observed_at):
            aware(value)
        for value in (self.upload_terminal_at, self.retention_until, self.quarantined_at):
            if value is not None:
                aware(value)
        for value in (self.registered, self.manual_hold):
            if value is not None and type(value) is not bool:
                raise ValueError("Facts must be boolean or explicitly unknown")
        if not isinstance(self.upload_state, UploadState) or not isinstance(
            self.parse_state, ParseState
        ):
            raise ValueError("Typed upload and parse states are required")
        if not isinstance(self.disposition, Disposition):
            raise ValueError("Typed disposition is required")
        if self.pending_intent_id is not None and not isinstance(self.pending_intent_id, UUID):
            raise ValueError("Invalid pending intent")


@dataclass(frozen=True, slots=True)
class ReferenceState:
    reference: ObjectRef
    scope: LifecycleScope
    read_version: str
    observed_at: datetime
    reference_count: int | None
    formal_history: bool | None

    def __post_init__(self):
        exact_reference(self.reference)
        if not isinstance(self.scope, LifecycleScope):
            raise ValueError("Reference scope must be server-bound")
        token(self.read_version, "reference read version")
        aware(self.observed_at)
        if self.reference_count is not None and (
            type(self.reference_count) is not int or self.reference_count < 0
        ):
            raise ValueError("Reference count must be nonnegative or explicitly unknown")
        if self.formal_history is not None and type(self.formal_history) is not bool:
            raise ValueError("History must be boolean or explicitly unknown")


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    eligible: bool
    reasons: tuple[DecisionReason, ...]
    not_before: datetime | None
    policy_version: str

    def __post_init__(self):
        if type(self.eligible) is not bool or self.eligible != (not self.reasons):
            raise ValueError("An eligible decision cannot contain blocking reasons")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, DecisionReason) for reason in self.reasons
        ):
            raise ValueError("Typed immutable decision reasons are required")
        token(self.policy_version, "policy version")
        if self.not_before is not None:
            aware(self.not_before)


@dataclass(frozen=True, slots=True)
class OrphanCandidate:
    """Stored preview for orphan quarantine or restoration; no permission is conveyed."""

    id: UUID
    action: LifecycleAction
    original: OriginalState
    references: ReferenceState
    decision: RetentionDecision
    captured_at: datetime
    policy_digest: str
    digest: str

    def __post_init__(self):
        if (
            not isinstance(self.original, OriginalState)
            or not isinstance(self.references, ReferenceState)
            or not isinstance(self.decision, RetentionDecision)
        ):
            raise ValueError("Candidate requires frozen typed server facts and decision")
        if (
            not isinstance(self.id, UUID)
            or self.action
            not in (
                LifecycleAction.QUARANTINE,
                LifecycleAction.RESTORE,
            )
            or not isinstance(self.action, LifecycleAction)
        ):
            raise ValueError("Invalid candidate action or identity")
        if self.original.reference != self.references.reference:
            raise ValueError("Candidate must bind the same exact ObjectRef")
        if self.original.scope != self.references.scope:
            raise ValueError("Candidate scopes must match")
        aware(self.captured_at)
        for value in (self.digest, self.policy_digest):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("Invalid candidate or policy digest")

    def as_dict(self) -> dict:
        # ObjectRef.as_dict() includes its old static scan_status. Do not use it here:
        # lifecycle recovery has no authority to make a scan-status assertion.
        ref = self.original.reference
        return {
            "candidate_id": str(self.id),
            "action": self.action.value,
            "object_id": str(ref.id),
            "object_version": ref.version,
            "content_sha256": ref.content_sha256,
            "size_bytes": ref.size_bytes,
            "media_type": ref.media_type,
            "lifecycle_revision": self.original.revision,
            "inventory_revision": self.original.inventory_revision,
            "reference_read_version": self.references.read_version,
            "policy_version": self.decision.policy_version,
            "policy_digest": self.policy_digest,
            "eligible": self.decision.eligible,
            "reasons": [reason.value for reason in self.decision.reasons],
            "not_before": self.decision.not_before.isoformat()
            if self.decision.not_before
            else None,
            "captured_at": self.captured_at.isoformat(),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class EffectPermit:
    operation_id: UUID
    reference: ObjectRef
    scope: LifecycleScope
    action: LifecycleAction
    lease_token: UUID
    attempt: int
    named_decider_id: UUID
    authorization_revision: str
    lifecycle_revision: int
    inventory_revision: str
    reference_read_version: str
    policy_digest: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self):
        exact_reference(self.reference)
        for value in (self.operation_id, self.lease_token, self.named_decider_id):
            if not isinstance(value, UUID):
                raise ValueError("Invalid effect identity")
        if not isinstance(self.scope, LifecycleScope) or not isinstance(
            self.action, LifecycleAction
        ):
            raise ValueError("Invalid effect scope or action")
        if self.action not in (LifecycleAction.QUARANTINE, LifecycleAction.RESTORE):
            raise ValueError("Only reversible effects can be permitted")
        if type(self.attempt) is not int or self.attempt != 1:
            raise ValueError("A lifecycle intent permits only one physical attempt")
        token(self.authorization_revision, "effect authorization revision")
        positive(self.lifecycle_revision, "effect lifecycle revision")
        token(self.inventory_revision, "effect inventory revision")
        token(self.reference_read_version, "effect reference read version")
        if len(self.policy_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.policy_digest
        ):
            raise ValueError("Invalid effect policy digest")
        aware(self.issued_at)
        aware(self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("Effect permit must expire after issue")


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    operation_id: UUID
    reference: ObjectRef
    scope: LifecycleScope
    lease_token: UUID
    outcome: EffectOutcome
    observed_disposition: Disposition | None
    integrity_verified: bool
    observed_at: datetime
    transport_revision: str
    error_code: str | None = None

    def __post_init__(self):
        exact_reference(self.reference)
        if not isinstance(self.scope, LifecycleScope) or not isinstance(
            self.outcome, EffectOutcome
        ):
            raise ValueError("Typed receipt scope and outcome are required")
        for value in (self.operation_id, self.lease_token):
            if not isinstance(value, UUID):
                raise ValueError("Invalid effect receipt identity")
        if type(self.integrity_verified) is not bool:
            raise ValueError("Integrity verification must be explicit")
        if self.outcome != EffectOutcome.UNKNOWN and (
            not self.integrity_verified
            or self.observed_disposition
            not in (
                Disposition.ACTIVE,
                Disposition.QUARANTINED,
            )
        ):
            raise ValueError("Known outcomes require verification of retained exact bytes")
        if self.observed_disposition is not None and not isinstance(
            self.observed_disposition, Disposition
        ):
            raise ValueError("Typed receipt disposition is required")
        aware(self.observed_at)
        token(self.transport_revision, "transport revision")
        if self.error_code is not None:
            if (
                not isinstance(self.error_code, str)
                or fullmatch(r"[A-Z][A-Z0-9_]{0,79}", self.error_code) is None
            ):
                raise ValueError("Effect errors must be bounded machine codes, not diagnostics")


@dataclass(frozen=True, slots=True)
class LifecycleIntent:
    id: UUID
    candidate_id: UUID
    candidate_digest: str
    intent_digest: str
    reference: ObjectRef
    scope: LifecycleScope
    action: LifecycleAction
    named_decider_id: UUID
    authorization_revision: str
    policy_version: str
    revision: int
    state: IntentState
    created_at: datetime
    updated_at: datetime
    permit: EffectPermit | None = None
    receipt: EffectReceipt | None = None
    recovery_required: bool = False
    protection_reasons: tuple[DecisionReason, ...] = ()

    def __post_init__(self):
        exact_reference(self.reference)
        for value in (self.id, self.candidate_id, self.named_decider_id):
            if not isinstance(value, UUID):
                raise ValueError("Invalid lifecycle intent identity")
        if not isinstance(self.scope, LifecycleScope) or not isinstance(self.state, IntentState):
            raise ValueError("Invalid lifecycle intent scope or state")
        if self.action not in (
            LifecycleAction.QUARANTINE,
            LifecycleAction.RESTORE,
        ) or not isinstance(self.action, LifecycleAction):
            raise ValueError("Invalid lifecycle intent action")
        for value in (self.candidate_digest, self.intent_digest):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("Invalid lifecycle intent digest")
        positive(self.revision, "intent revision")
        token(self.authorization_revision, "authorization revision")
        token(self.policy_version, "policy version")
        aware(self.created_at)
        aware(self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("Intent time cannot move backwards")
        if self.state in (IntentState.IN_FLIGHT, IntentState.UNKNOWN, IntentState.APPLIED) and (
            self.permit is None
        ):
            raise ValueError("An attempted intent requires its exact stored effect permit")
        if type(self.recovery_required) is not bool or self.recovery_required != bool(
            self.protection_reasons
        ):
            raise ValueError("Recovery must retain the current protection reasons")
        if not isinstance(self.protection_reasons, tuple) or any(
            not isinstance(reason, DecisionReason) for reason in self.protection_reasons
        ):
            raise ValueError("Typed immutable protection reasons are required")
        if self.permit is not None and (
            self.permit.operation_id != self.id
            or self.permit.reference != self.reference
            or self.permit.scope != self.scope
            or self.permit.action != self.action
            or self.permit.named_decider_id != self.named_decider_id
        ):
            raise ValueError("Intent and effect permit must bind the same exact operation")
        if self.receipt is not None and (
            self.permit is None
            or self.receipt.operation_id != self.id
            or self.receipt.reference != self.reference
            or self.receipt.scope != self.scope
            or self.receipt.lease_token != self.permit.lease_token
        ):
            raise ValueError("Intent and effect receipt must bind the same exact attempt")


@dataclass(frozen=True, slots=True)
class RequestBinding:
    scope: LifecycleScope
    actor_id: UUID
    key: str
    fingerprint: str
    intent_id: UUID

    def __post_init__(self):
        if not isinstance(self.scope, LifecycleScope):
            raise ValueError("Invalid request scope")
        if not isinstance(self.actor_id, UUID) or not isinstance(self.intent_id, UUID):
            raise ValueError("Invalid request binding")
        token(self.key, "idempotency key", maximum=200)
        if len(self.fingerprint) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.fingerprint
        ):
            raise ValueError("Invalid request fingerprint")


@dataclass(frozen=True, slots=True)
class LifecycleFence:
    """A port assertion that the shared object lock is held in the caller transaction."""

    original: OriginalState
    token: UUID

    def __post_init__(self):
        if not isinstance(self.original, OriginalState) or not isinstance(self.token, UUID):
            raise ValueError("Invalid lifecycle fence")
