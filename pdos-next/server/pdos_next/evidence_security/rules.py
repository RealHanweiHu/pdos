"""Fail-closed scan validity and parsing gate; persistence belongs to the main command service."""

from datetime import datetime
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef

from .types import (
    ScanConfiguration,
    ScanGuardPort,
    ScannerIdentity,
    ScanPolicy,
    ScanReceipt,
    ScanRequest,
    ScanStatus,
    SecurityDecision,
    SecurityFailure,
    SecurityState,
    aware,
)


def bind_request(
    guard: ScanGuardPort,
    object_ref: ObjectRef,
    *,
    request_id: UUID,
    scanner: ScannerIdentity,
    policy: ScanPolicy,
    now: datetime,
) -> ScanRequest:
    configuration = guard.current_configuration()
    if not isinstance(configuration, ScanConfiguration) or (
        configuration.scanner != scanner or configuration.policy != policy
    ):
        raise SecurityFailure("SCANNER_CONFIGURATION_CHANGED")
    binding = guard.bind_for_scan(object_ref)
    if (
        binding.object_ref != object_ref
        or not binding.source_active
        or guard.is_current(binding) is not True
    ):
        raise SecurityFailure("SOURCE_UNAVAILABLE")
    return ScanRequest(request_id, binding, scanner, policy, now)


def parsing_gate(
    request: ScanRequest,
    receipt: ScanReceipt | None,
    guard: ScanGuardPort,
    *,
    now: datetime,
) -> SecurityDecision:
    """Use only receipts retrieved from the trusted worker receipt store.

    Call under the mainline source/ACL lock before staging a parse intent and again before
    writing a derived Artifact. A True result is permission to consider parsing, not a grant.
    """
    aware(now)
    try:
        current = request.binding.source_active and guard.is_current(request.binding) is True
        configuration = guard.current_configuration()
    except Exception:
        current = False
        configuration = None
    if not current:
        return SecurityDecision(SecurityState.STALE, False, True, ("SOURCE_OR_ACCESS_CHANGED",))
    if not isinstance(configuration, ScanConfiguration) or (
        configuration.scanner != request.scanner or configuration.policy != request.policy
    ):
        return SecurityDecision(
            SecurityState.STALE, False, True, ("SCANNER_CONFIGURATION_CHANGED",)
        )
    if receipt is None:
        return SecurityDecision(SecurityState.NOT_SCANNED, False, True, ("SCAN_REQUIRED",))
    reasons = []
    if (
        receipt.request_id != request.request_id
        or receipt.binding != request.binding
        or receipt.scanner != request.scanner
        or receipt.policy_digest != request.policy.digest
    ):
        reasons.append("SCAN_BASIS_CHANGED")
    if receipt.started_at < request.requested_at or receipt.completed_at > now:
        reasons.append("SCAN_TIME_INVALID")
    if (
        receipt.completed_at - receipt.started_at
    ).total_seconds() > request.policy.limits.timeout_seconds:
        reasons.append("SCAN_BUDGET_EXPIRED")
    if (now - receipt.completed_at).total_seconds() > request.policy.clean_max_age_seconds:
        reasons.append("SCAN_EXPIRED")
    if reasons:
        return SecurityDecision(SecurityState.STALE, False, True, tuple(reasons))
    if receipt.status == ScanStatus.CLEAN and receipt.error_code is None:
        return SecurityDecision(SecurityState.CLEAN, True, False, ())
    state = (
        SecurityState.QUARANTINED
        if receipt.status in {ScanStatus.INFECTED, ScanStatus.REJECTED}
        else SecurityState.SCAN_FAILED
    )
    return SecurityDecision(state, False, True, (receipt.error_code or receipt.status.value,))
