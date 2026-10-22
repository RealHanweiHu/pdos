"""Fail-closed rules for orphan detection, reversible recovery and purge eligibility."""

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID

from .types import (
    DecisionReason,
    Disposition,
    LifecycleFailure,
    OriginalState,
    ParseState,
    ReferenceState,
    RetentionDecision,
    RetentionPolicy,
    UploadState,
    aware,
)


def _canonical(value):
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        aware(value)
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, timedelta):
        return value // timedelta(microseconds=1)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def digest(value) -> str:
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def facts_digest(original: OriginalState, references: ReferenceState) -> str:
    original_data, reference_data = asdict(original), asdict(references)
    # Observation time changes on an otherwise identical authoritative reread.
    # All source facts and the authority's read versions remain bound.
    original_data.pop("observed_at")
    reference_data.pop("observed_at")
    return digest([original_data, reference_data])


def _common(original, references, policy, now, *, allowed_pending=None):
    aware(now)
    if original.reference != references.reference or original.scope != references.scope:
        raise LifecycleFailure(
            "BINDING_MISMATCH", "Authoritative object and reference scopes differ"
        )
    reasons = []
    if references.reference_count is None or references.formal_history is None:
        reasons.append(DecisionReason.REFERENCE_UNKNOWN)
    if original.pending_intent_id is not None and original.pending_intent_id != allowed_pending:
        reasons.append(DecisionReason.EFFECT_PENDING)
    if original.disposition in (Disposition.UNKNOWN, Disposition.PURGED):
        reasons.append(DecisionReason.STATE_UNKNOWN)
    if (
        original.created_at > now
        or original.observed_at > now
        or references.observed_at > now
        or (
            original.upload_terminal_at is not None
            and (
                original.upload_terminal_at < original.created_at
                or original.upload_terminal_at > now
            )
        )
        or (original.quarantined_at is not None and original.quarantined_at > now)
    ):
        reasons.append(DecisionReason.FACT_TIME_INVALID)
    return reasons


def _recycle_protection(original, references, reasons):
    if references.reference_count:
        reasons.append(DecisionReason.REFERENCED)
    if references.formal_history is True:
        reasons.append(DecisionReason.FORMAL_HISTORY)
    if original.manual_hold is None:
        reasons.append(DecisionReason.HOLD_UNKNOWN)
    elif original.manual_hold:
        reasons.append(DecisionReason.MANUAL_HOLD)
    if original.registered is None:
        reasons.append(DecisionReason.REGISTRATION_UNKNOWN)
    elif original.registered:
        reasons.append(DecisionReason.REGISTERED_ORIGINAL)
    if original.upload_state not in (UploadState.FAILED, UploadState.ABANDONED):
        reasons.append(DecisionReason.UPLOAD_NOT_TERMINAL)
    if original.parse_state == ParseState.UNKNOWN:
        reasons.append(DecisionReason.PARSE_UNKNOWN)
    elif original.parse_state in (ParseState.QUEUED, ParseState.RUNNING):
        reasons.append(DecisionReason.PARSE_IN_PROGRESS)
    elif original.parse_state in (ParseState.PARSED, ParseState.NEEDS_OCR):
        reasons.append(DecisionReason.DERIVATION_PRESENT)


def _decision(reasons, not_before, policy):
    distinct = tuple(dict.fromkeys(reasons))
    return RetentionDecision(not distinct, distinct, not_before, policy.version)


def evaluate_quarantine(
    original: OriginalState,
    references: ReferenceState,
    policy: RetentionPolicy,
    now: datetime,
    *,
    allowed_pending: UUID | None = None,
) -> RetentionDecision:
    reasons = _common(original, references, policy, now, allowed_pending=allowed_pending)
    _recycle_protection(original, references, reasons)
    if original.disposition != Disposition.ACTIVE:
        reasons.append(DecisionReason.WRONG_DISPOSITION)
    if original.upload_terminal_at is None:
        reasons.append(DecisionReason.UPLOAD_TIME_UNKNOWN)
    if original.retention_until is None:
        reasons.append(DecisionReason.RETENTION_UNKNOWN)
    not_before = None
    if original.upload_terminal_at is not None and original.retention_until is not None:
        not_before = max(
            original.retention_until, original.upload_terminal_at + policy.failed_upload_grace
        )
        if now < not_before:
            reasons.append(DecisionReason.RETENTION_NOT_ELAPSED)
    return _decision(reasons, not_before, policy)


def evaluate_restore(
    original: OriginalState,
    references: ReferenceState,
    policy: RetentionPolicy,
    now: datetime,
    *,
    allowed_pending: UUID | None = None,
) -> RetentionDecision:
    reasons = _common(original, references, policy, now, allowed_pending=allowed_pending)
    if original.disposition != Disposition.QUARANTINED:
        reasons.append(DecisionReason.WRONG_DISPOSITION)
    if original.quarantined_at is None:
        reasons.append(DecisionReason.QUARANTINE_TIME_UNKNOWN)
    # Referenced/history/held bytes can be recovered. No retention/scan policy is
    # weakened by restoring physical accessibility; parser/read gates remain separate.
    return _decision(reasons, None, policy)


def evaluate_purge(
    original: OriginalState,
    references: ReferenceState,
    policy: RetentionPolicy,
    now: datetime,
) -> RetentionDecision:
    """Eligibility only. This module issues no purge authorization or physical delete."""
    reasons = _common(original, references, policy, now)
    _recycle_protection(original, references, reasons)
    if original.disposition != Disposition.QUARANTINED:
        reasons.append(DecisionReason.WRONG_DISPOSITION)
    if original.quarantined_at is None:
        reasons.append(DecisionReason.QUARANTINE_TIME_UNKNOWN)
    if original.retention_until is None:
        reasons.append(DecisionReason.RETENTION_UNKNOWN)
    if original.upload_terminal_at is None:
        reasons.append(DecisionReason.UPLOAD_TIME_UNKNOWN)
    not_before = None
    if all(
        value is not None
        for value in (
            original.quarantined_at,
            original.retention_until,
            original.upload_terminal_at,
        )
    ):
        not_before = max(
            original.retention_until,
            original.quarantined_at + policy.quarantine_grace,
            original.upload_terminal_at + policy.failed_upload_grace,
        )
        if now < not_before:
            reasons.append(DecisionReason.RETENTION_NOT_ELAPSED)
    return _decision(reasons, not_before, policy)
