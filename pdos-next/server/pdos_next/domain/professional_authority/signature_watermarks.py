"""Applicability watermarks of an already sealed professional signature.

The caller must first resolve a real, immutable, DB-verified signature snapshot.
This helper cannot validate a client DTO or grant a qualification. False means
that a new dependent action needs review; it never erases the original signature.
"""

from datetime import datetime
from uuid import UUID

from pdos_next.database import require_context
from pdos_next.models import now

from . import service


def _identity(value):
    return value if isinstance(value, UUID) else UUID(value)


def _positive(value):
    return type(value) is int and value > 0


def _time_current(reference, snapshot, at):
    # Only the fixed positive role's applicable facts constrain its next use.
    # Older/minimal snapshots still retain their explicitly stated time facts;
    # absence or None does not invent an expiry or a whole-chain TTL.
    applicability = ("kind", "state", "role", "operations", "purposes")
    if all(key in reference for key in applicability):
        if (
            reference["kind"] not in {"duty", "qualification"}
            or reference["state"] != "active"
            or reference["role"] not in snapshot.get("roles", ())
            or snapshot.get("operation") not in reference["operations"]
            or snapshot.get("purpose") not in reference["purposes"]
        ):
            return True
    for name in ("valid_from", "valid_until"):
        value = reference.get(name)
        if value is None:
            continue
        boundary = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if boundary.tzinfo is None or boundary.utcoffset() is None:
            return False
        if (name == "valid_from" and at < boundary) or (name == "valid_until" and at >= boundary):
            return False
    return True


def signature_current(s, ctx, pid, project_id, snapshot) -> bool:
    """Compare a sealed signature's exact dependencies under the current caller.

    Only ProfessionalCurrent is read. Historical facts, role matrices, sources
    and the old signer's present qualification are not reassessed here. The
    caller independently checks its own ACL and any new operation's authority.
    """
    require_context(s, ctx)
    try:
        if not isinstance(snapshot, dict) or snapshot.get("scope") != {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(pid),
            "project_id": str(project_id),
        }:
            return False
        subject = _identity(snapshot["subject_id"])
        references = snapshot["fact_refs"]
        if not isinstance(references, list) or not references:
            return False
        expected = {}
        identities = set()
        at = now()
        if at.tzinfo is None or at.utcoffset() is None:
            return False
        registry = getattr(s.get_bind(), "_pdos_professional_issuers", {})
        for reference in references:
            identity = _identity(reference["id"])
            series = _identity(reference["series_id"])
            revision, epoch = reference["revision"], reference["epoch"]
            if (
                identity in identities
                or series in expected
                or not _positive(revision)
                or not _positive(epoch)
                or not _positive(reference["issuer_epoch"])
            ):
                return False
            issuer = registry.get(reference["issuer_key"])
            if (
                not isinstance(issuer, service.IssuerContext)
                or issuer.key != reference["issuer_key"]
                or issuer.version != reference["issuer_version"]
                or issuer.epoch != reference["issuer_epoch"]
                or (issuer.tenant_id, issuer.product_id) != (ctx.tenant_id, pid)
                or issuer.project_id not in (None, project_id)
                or not _time_current(reference, snapshot, at)
            ):
                return False
            identities.add(identity)
            expected[series] = (identity, revision, epoch)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

    pointers = service._signature_currents(s, ctx, pid, project_id, subject)
    actual = {}
    for pointer in pointers:
        if pointer.series_id not in expected:
            continue
        if (
            (pointer.tenant_id, pointer.product_id, pointer.project_id, pointer.subject_id)
            != (ctx.tenant_id, pid, project_id, subject)
            or (ctx.category_id is not None and pointer.category_id != ctx.category_id)
            or pointer.series_id in actual
            or not _positive(pointer.fact_revision)
            or not _positive(pointer.epoch)
        ):
            return False
        actual[pointer.series_id] = (pointer.fact_id, pointer.fact_revision, pointer.epoch)
    return actual == expected
