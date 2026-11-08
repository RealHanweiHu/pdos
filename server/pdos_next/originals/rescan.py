"""Scheduled rescan of citable originals whose clean scan receipt aged out (D215).

The 24-hour validity of a clean receipt is unchanged; this only renews it. Once an
hour, per tenant:

1. The dispatch role lists references (no content) of parsed, active originals
   whose current receipt is clean but older than its own policy's validity, or was
   made under a scanner configuration the worker no longer runs (after a virus
   database update, for example).
2. For each one, in the original scan requester's own scope, the real parsing gate
   is evaluated again. Only a clean receipt that is now stale for one of those two
   reasons gets a new scan request, through the same ``request_scan`` and the same
   scan workflow as a person's click. The idempotency key makes a retried pass
   reuse the request it already made.

What people see: while the rescan runs the original shows "scanning"; a failed or
infected rescan is stored as an ordinary scan result with its reason; an original
that cannot be rescanned automatically says why (``rescan_reason``). No model is
called on any path.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from temporalio import activity

from pdos_next.core.database import tenant_session
from pdos_next.core.models import Grant, Principal, UploadedOriginal, now
from pdos_next.errors import DomainError

RENEWABLE = frozenset({"SCAN_EXPIRED", "SCANNER_CONFIGURATION_CHANGED"})
PAGE = 200
MAX_PAGES = 25


def renewable(gate, stored):
    """A once-clean receipt that is stale only because it aged out or the scanner changed."""
    return (
        gate is not None
        and gate.state.value == "stale"
        and stored is not None
        and stored.status == "clean"
        and bool(RENEWABLE & set(gate.reasons))
    )


def rescan_reason(s, original, record):
    """Why an aged-out clean original can or cannot be rescanned automatically."""
    from pdos_next.originals.security import runtime_for

    if runtime_for(s) is None:
        return "SCANNER_UNAVAILABLE"
    if original.status != "parsed":
        return "RESCAN_NOT_AUTOMATIC"
    principal = s.get(Principal, record.requester_id)
    grant = s.scalar(
        select(Grant).where(
            Grant.tenant_id == original.tenant_id,
            Grant.category_id == original.category_id,
            Grant.principal_id == record.requester_id,
        )
    )
    if (
        principal is None
        or not principal.active
        or principal.kind != "human"
        or grant is None
        or not grant.can_write
        or (grant.expires_at is not None and grant.expires_at <= now())
    ):
        return "RESCAN_REQUESTER_UNAVAILABLE"
    return "RESCAN_SCHEDULED"


def candidates(dispatch_engine, tenant_id, configuration, *, at: datetime, after=None):
    from pdos_next.originals.security import encoded

    after_at, after_id = after or (None, None)
    with tenant_session(dispatch_engine, tenant_id) as session:
        rows = session.execute(
            text(
                "SELECT category_id,product_id,original_id,requester_id,completed_at FROM "
                "original_rescan_candidates(:tenant,:at,CAST(:scanner AS jsonb),"
                "CAST(:policy AS jsonb),:after_at,:after_id,:limit)"
            ),
            {
                "tenant": tenant_id,
                "at": at,
                "scanner": _json(encoded(configuration.scanner)),
                "policy": _json(encoded(configuration.policy)),
                "after_at": after_at,
                "after_id": after_id,
                "limit": PAGE,
            },
        ).all()
    return [tuple(row) for row in rows]


def _json(value):
    import json

    return json.dumps(value, sort_keys=True)


def rescan_one(engine, tenant_id, category_id, product_id, original_id, requester_id):
    from pdos_next.core.service import Context
    from pdos_next.originals.security import decision, request_scan, security_row

    # The renewal acts in the scope of the person whose scan it renews, as the
    # upload-time scan acts in the uploader's scope (queue_uploaded).
    ctx = Context(tenant_id, requester_id, requester_id, category_id=category_id)
    try:
        with tenant_session(
            engine, tenant_id, actor_id=requester_id, requester_id=requester_id,
            category_id=category_id,
        ) as s:
            original = s.get(UploadedOriginal, original_id)
            if original is None or original.product_id != product_id:
                return "failed", "SOURCE_UNAVAILABLE"
            state = security_row(s, original)
            gate, _, stored = decision(s, original, state, lock=True)
            if not renewable(gate, stored):
                return "current", None
            request_scan(
                s, ctx, product_id, original_id,
                expected_epoch=state.epoch,
                idempotency_key=f"rescan:{original_id}:{state.epoch}",
            )
            return "requested", None
    except DomainError as error:
        return "failed", error.code


def rescan_expired(engine, dispatch_engine, tenant_id, *, heartbeat=lambda: None):
    # Installed on the business engine by the worker entry point (security.configure).
    runtime = getattr(engine, "_pdos_security_runtime", None)
    counts = {"requested": 0, "current": 0, "failed": 0, "failures": {}}
    if runtime is None:
        return {**counts, "skipped": "SCANNER_UNAVAILABLE"}
    tenant_id = UUID(str(tenant_id))
    at, after = now(), None
    for _ in range(MAX_PAGES):
        page = candidates(dispatch_engine, tenant_id, runtime.configuration, at=at, after=after)
        for category_id, product_id, original_id, requester_id, completed_at in page:
            outcome, code = rescan_one(
                engine, tenant_id, category_id, product_id, original_id, requester_id
            )
            counts[outcome] += 1
            if code:
                counts["failures"][code] = counts["failures"].get(code, 0) + 1
            after = (completed_at, original_id)
        heartbeat()
        if len(page) < PAGE:
            break
    return counts


class OriginalRescan:
    def __init__(self, engine, dispatch_engine):
        self.engine, self.dispatch_engine = engine, dispatch_engine

    @activity.defn(name="rescan_expired_originals")
    def rescan(self, reference: dict) -> dict:
        return rescan_expired(
            self.engine, self.dispatch_engine, UUID(reference["tenant_id"]),
            heartbeat=activity.heartbeat,
        )
