"""Batch current original-scan proofs before retrieval, using the existing pure gate."""

from dataclasses import dataclass

from sqlalchemy import and_, select

from pdos_next.clock import now
from pdos_next.evidence_security.rules import parsing_gate
from pdos_next.evidence_security.types import ScanBinding
from pdos_next.models import (
    Grant,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    Principal,
    UploadedOriginal,
)
from pdos_next.original_security import decoded_receipt, decoded_request, runtime_for
from pdos_next.originals import object_reference
from pdos_next.service import digest


@dataclass(frozen=True)
class BoundScanGuard:
    configuration: object
    binding: ScanBinding

    def current_configuration(self):
        return self.configuration

    def is_current(self, binding):
        return binding == self.binding and self.binding.source_active


def safe_originals(session, identities):
    if not identities:
        return set()
    runtime = runtime_for(session)
    if runtime is None:
        return set()
    o, security, request, result = (
        UploadedOriginal,
        OriginalSecurity,
        OriginalScanRequest,
        OriginalScanResult,
    )
    rows = session.execute(
        select(o, security, request, result, Principal, Grant)
        .join(
            security,
            and_(security.tenant_id == o.tenant_id, security.original_id == o.id),
        )
        .join(
            request,
            and_(
                request.tenant_id == o.tenant_id,
                request.id == security.current_request_id,
                request.original_id == o.id,
            ),
        )
        .join(result, and_(result.tenant_id == o.tenant_id, result.request_id == request.id))
        .join(
            Principal,
            and_(Principal.tenant_id == o.tenant_id, Principal.id == request.requester_id),
        )
        .join(
            Grant,
            and_(
                Grant.tenant_id == o.tenant_id,
                Grant.principal_id == Principal.id,
                Grant.category_id == o.category_id,
            ),
        )
        .where(o.id.in_(identities))
    ).all()
    allowed, at = set(), now()
    for original, state, requested, recorded, principal, grant in rows:
        try:
            bound = ScanBinding(
                object_reference(original),
                original.tenant_id,
                original.product_id,
                requested.requester_id,
                state.epoch,
                digest(
                    [
                        grant.id,
                        grant.can_write,
                        grant.expires_at,
                        grant.access_epoch,
                        principal.active,
                        principal.access_epoch,
                    ]
                ),
                digest(
                    [original.owner_id, original.visibility, state.source_state, state.disposition]
                ),
                bool(
                    principal.active
                    and (grant.expires_at is None or grant.expires_at > at)
                    and state.source_state == "active"
                    and state.disposition == "active"
                    and original.status == "parsed"
                ),
                category_id=original.category_id,
            )
            scan = decoded_request(requested.binding)
            receipt = decoded_receipt(recorded.result, scan)
            if parsing_gate(
                scan, receipt, BoundScanGuard(runtime.configuration, bound), now=at
            ).allow_parse:
                allowed.add(original.id)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue  # Malformed metadata is never a clean scan.
    return allowed
