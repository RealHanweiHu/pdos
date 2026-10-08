"""Authoritative inventory and reference protection for the current reviewed schema."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, text

from pdos_next.domain.original_lifecycle_execution.codec import decode_intent
from pdos_next.domain.original_lifecycle_execution.runtime import BoundFacts
from pdos_next.errors import DomainError
from pdos_next.lifecycle_catalog import COVERED_COLUMNS, GUARDED
from pdos_next.models import (
    Base,
    Grant,
    LifecycleIntentRecord,
    LifecycleObject,
    Principal,
    Product,
    Receipt,
    UploadAttempt,
    UploadedOriginal,
    now,
)
from pdos_next.object_journal import JournalScope
from pdos_next.object_storage import StorageFailure
from pdos_next.original_lifecycle.rules import digest, evaluate_quarantine, evaluate_restore
from pdos_next.original_lifecycle.types import (
    Disposition,
    LifecycleFailure,
    LifecycleScope,
    OriginalState,
    ParseState,
    ReferenceState,
    UploadState,
)
from pdos_next.originals import object_reference
from pdos_next.service import require_access
from pdos_next.upload_lifecycle import exact_reference

# These tables are identity/configuration/transport/lifecycle bookkeeping, not
# consuming business references. Column additions still invalidate coverage.
NON_CONSUMING = frozenset(
    {
        "principals",
        "login_sessions",
        "grants",
        "qualifications",
        "model_invocations",
        "model_budget_reservations",
        "confirmations",
        "inbox_deliveries",
        "products",
        "upload_attempts",
        "lifecycle_objects",
        "lifecycle_candidates",
        "lifecycle_intents",
        "lifecycle_requests",
        # Derived physical identity/capacity mirror only. Immutable scoped fact
        # bundles and committed occupancy proofs retain every original reference.
        "operational_asset_sentinels",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "id",
        "tenant_id",
        "product_id",
        "owner_id",
        "actor_id",
        "requester_id",
        "writer_id",
        "human_owner_id",
        "accountable_owner_id",
        "principal_id",
        "named_decider_id",
    }
)


def product_gate(s, ctx, product_id):
    product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product:
        raise DomainError("FORBIDDEN_SCOPE", "产品范围不可用。", 403)
    require_access(s, ctx, product_id, write=True, lock=True)
    actor = s.get(Principal, ctx.requester_id)
    if actor.kind != "human" or ctx.run_id or ctx.actor_id != ctx.requester_id:
        raise DomainError("NAMED_DECISION_REQUIRED", "原件保留由具名本人核对。", 403)
    return product


def _scope_owner(s, ctx, product_id, object_id, store):
    product_gate(s, ctx, product_id)
    original = s.get(UploadedOriginal, object_id)
    attempt = s.get(UploadAttempt, object_id)
    owner, reference = None, None
    if original and original.product_id == product_id:
        owner, reference = original.owner_id, object_reference(original)
    elif attempt and attempt.product_id == product_id:
        owner, reference = attempt.owner_id, exact_reference(attempt.reference)
    else:
        try:
            item = store.inspect(object_id)
        except StorageFailure:
            raise DomainError("SOURCE_UNAVAILABLE", "当前范围内未能核对这个原件。", 403) from None
        if item.scope == JournalScope(ctx.tenant_id, product_id):
            owner, reference = item.requester_id, item.reference
    if owner != ctx.requester_id or reference is None:
        raise DomainError("SOURCE_UNAVAILABLE", "原件保留不在当前本人范围。", 403)
    return reference, original, attempt


def resolve_reference(s, ctx, product_id, object_id, store):
    return _scope_owner(s, ctx, product_id, object_id, store)[0]


def read_facts(s, ctx, product_id, reference, previous, store):
    resolved, original, attempt = _scope_owner(s, ctx, product_id, reference.id, store)
    if resolved != reference:
        raise LifecycleFailure("BINDING_MISMATCH", "原件字节绑定不一致。")
    item, journal_error = None, None
    try:
        item = store.lookup_original(reference, JournalScope(ctx.tenant_id, product_id))
    except StorageFailure as failure:
        journal_error = failure.code
    grant = s.scalar(
        select(Grant).where(Grant.product_id == product_id, Grant.principal_id == ctx.requester_id)
    )
    principal = s.get(Principal, ctx.requester_id)
    projection = s.get(LifecycleObject, reference.id)
    registered, upload_state, terminal = None, UploadState.UNKNOWN, None
    parsed = ParseState.UNKNOWN
    if original:
        registered, upload_state = True, UploadState.SUCCEEDED
        parsed = {
            "uploaded": ParseState.NOT_REQUESTED,
            "parsed": ParseState.PARSED,
            "failed": ParseState.FAILED,
            "needs_ocr": ParseState.NEEDS_OCR,
        }.get(original.status, ParseState.UNKNOWN)
        terminal = original.created_at
    elif attempt and attempt.status == "abandoned":
        # Positive committed terminal reservation + matching terminal journal.
        if item and item.registration_state == "aborted" and item.byte_status == "intact":
            registered, upload_state = False, UploadState.ABANDONED
            terminal, parsed = attempt.terminal_at, ParseState.NOT_REQUESTED
    elif attempt and attempt.status == "reserved":
        upload_state, parsed = UploadState.PENDING, ParseState.NOT_REQUESTED
    # Never infer registration failure from absence of an UploadedOriginal row.
    if item and item.registration_state == "registered" and not original:
        registered, upload_state, parsed = None, UploadState.UNKNOWN, ParseState.UNKNOWN
    created = (
        attempt.created_at if attempt else original.created_at if original else item.created_at
    )
    observed = now()
    inventory = digest(
        {
            "journal": item.to_dict(include_internal=True) if item else journal_error,
            "registration": [str(original.id), original.revision, original.status]
            if original
            else None,
            "attempt": [attempt.revision, attempt.status, str(attempt.terminal_at)]
            if attempt
            else None,
            "access": [principal.access_epoch, grant.access_epoch],
            "protection": projection.protection_revision if projection else 1,
        }
    )
    state = OriginalState(
        reference=reference,
        scope=LifecycleScope(ctx.tenant_id, product_id),
        revision=previous.revision if previous else 1,
        inventory_revision=inventory,
        created_at=created,
        observed_at=observed,
        upload_state=upload_state,
        registered=registered,
        upload_terminal_at=terminal,
        parse_state=parsed,
        retention_until=projection.retention_until if projection else None,
        manual_hold=projection.manual_hold if projection else None,
        disposition=previous.disposition if previous else Disposition.ACTIVE,
        quarantined_at=previous.quarantined_at if previous else None,
        pending_intent_id=previous.pending_intent_id if previous else None,
    )
    return BoundFacts(ctx.requester_id, state)


def _uuids(value):
    if isinstance(value, UUID):
        return {value}
    if isinstance(value, str):
        try:
            return {UUID(value)}
        except ValueError:
            return set()
    if isinstance(value, dict):
        return set().union(*(_uuids(v) for k, v in value.items() if k not in IDENTITY_KEYS))
    if isinstance(value, (tuple, list)):
        return set().union(*(_uuids(v) for v in value))
    return set()


def schema_covered(s):
    rows = s.execute(
        text(
            "SELECT c.relname,a.attname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') "
            "AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum"
        )
    )
    actual = {}
    for table, column in rows:
        if table not in {"alembic_version", "environment_guard"}:
            actual.setdefault(table, []).append(column)
    # Physical order differs when columns were added. Names/types are separately
    # checked by migrations; unknown table/column never becomes an empty inventory.
    columns_known = set(actual) == set(COVERED_COLUMNS) and all(
        set(actual[name]) == set(columns) for name, columns in COVERED_COLUMNS.items()
    )
    if not columns_known:
        return False
    guards = set(
        s.execute(
            text(
                "SELECT c.relname,t.tgname,p.proname FROM pg_catalog.pg_trigger t "
                "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid "
                "WHERE n.nspname='public' AND NOT t.tgisinternal AND t.tgenabled IN ('O','A')"
            )
        ).all()
    )
    required = {
        (name, "lifecycle_reference", "lifecycle_reference_gate")
        for name in (*GUARDED, "upload_attempts")
        if name != "inbox_deliveries"
    }
    required |= {
        ("products", "lifecycle_epoch", "lifecycle_product_epoch"),
        ("uploaded_originals", "upload_registration", "protect_upload_registration"),
    }
    required |= {
        (name, "retained_record", "protect_lifecycle_record")
        for name in ("upload_attempts", "lifecycle_objects", "lifecycle_intents")
    }
    required |= {
        (name, "retained_record", "protect_next_snapshot")
        for name in ("lifecycle_candidates", "lifecycle_requests")
    }
    return required <= guards


def journal_inventory(store, scope):
    cursor, items = None, {}
    for _ in range(100):
        page = store.inventory(scope, limit=100, cursor=cursor)
        items.update({item.upload_id: item for item in page.items})
        if page.unavailable_count:
            return items, False
        if not page.has_more:
            return items, page.complete
        if not page.next_cursor or page.next_cursor == cursor:
            return items, False
        cursor = page.next_cursor
    return items, False


class References:
    def __init__(self, s, ctx, product_id, store):
        self.s, self.ctx, self.product_id, self.store = s, ctx, product_id, store

    def read_current(self, reference):
        product = product_gate(self.s, self.ctx, self.product_id)
        self.s.refresh(product, attribute_names=["lifecycle_epoch"])
        version = str(product.lifecycle_epoch)
        _, inventory_complete = journal_inventory(
            self.store, JournalScope(self.ctx.tenant_id, self.product_id)
        )
        known = schema_covered(self.s) and inventory_complete
        rows = []
        if known:
            control_receipts = set(
                self.s.scalars(
                    select(Receipt.id).where(
                        Receipt.product_id == self.product_id,
                        Receipt.operation.startswith("evidence.lifecycle."),
                    )
                )
            )
            # Scoped, bounded closure across all reviewed current/history business rows.
            for name, table in Base.metadata.tables.items():
                if name in NON_CONSUMING:
                    continue
                query = select(table).where(table.c.tenant_id == self.ctx.tenant_id)
                if "product_id" in table.c:
                    query = query.where(table.c.product_id == self.product_id)
                batch = self.s.execute(query.limit(2001)).mappings().all()
                if len(batch) > 2000 or len(rows) + len(batch) > 12000:
                    known = False
                    break
                for value in batch:
                    row = dict(value)
                    if row.get("receipt_id") in control_receipts:
                        continue
                    if name == "action_receipts" and row["operation"].startswith(
                        "evidence.lifecycle."
                    ):
                        continue
                    rows.append((name, row.get("id"), _uuids(row)))
        reached, referenced = {reference.id}, set()
        if known:
            changed = True
            while changed:
                changed = False
                for index, (_, identity, links) in enumerate(rows):
                    if index not in referenced and (identity == reference.id or links & reached):
                        referenced.add(index)
                        if identity:
                            reached.add(identity)
                        changed = True
        formal = any(
            rows[i][0]
            not in {
                "uploaded_originals",
                "artifact_versions",
                "original_security",
                "original_scan_requests",
                "original_scan_results",
                "outbox_events",
                "audit_entries",
            }
            for i in referenced
        )
        return ReferenceState(
            reference,
            LifecycleScope(self.ctx.tenant_id, self.product_id),
            version,
            now(),
            len(referenced) if known else None,
            formal if known else None,
        )

    def read_under_fence(self, fence):
        if fence.original.scope != LifecycleScope(self.ctx.tenant_id, self.product_id):
            raise LifecycleFailure("BINDING_MISMATCH", "保护栅栏不在当前范围。")
        return self.read_current(fence.original.reference)


def inventory(s, ctx, product_id, store):
    from pdos_next.domain.original_lifecycle_execution.service import runtime_for

    product_gate(s, ctx, product_id)
    service = runtime_for(s, ctx, product_id)
    scope, cursor, complete, journal_items = (
        JournalScope(ctx.tenant_id, product_id),
        None,
        False,
        {},
    )
    # Full scoped enumeration is bounded; any corrupt page or cap preserves unknown.
    for _ in range(100):
        page = store.inventory(scope, limit=100, cursor=cursor)
        journal_items.update(
            {i.upload_id: i for i in page.items if i.requester_id == ctx.requester_id}
        )
        if page.unavailable_count:
            break
        if not page.has_more:
            complete = page.complete
            break
        if not page.next_cursor or page.next_cursor == cursor:
            break
        cursor = page.next_cursor
    originals = {
        r.id: r
        for r in s.scalars(
            select(UploadedOriginal).where(
                UploadedOriginal.product_id == product_id,
                UploadedOriginal.owner_id == ctx.requester_id,
            )
        )
    }
    attempts = {
        r.id: r
        for r in s.scalars(
            select(UploadAttempt).where(
                UploadAttempt.product_id == product_id, UploadAttempt.owner_id == ctx.requester_id
            )
        )
    }
    objects = {
        r.id: r
        for r in s.scalars(
            select(LifecycleObject).where(
                LifecycleObject.product_id == product_id,
                LifecycleObject.owner_id == ctx.requester_id,
            )
        )
    }
    ids = set(originals) | set(attempts) | set(journal_items) | set(objects)
    if len(ids) > 1000:
        raise DomainError(
            "INVENTORY_INCOMPLETE", "原件范围超出当前完整核对上限，未给出回收资格。", 409
        )
    result = []
    for identity in sorted(ids, key=str):
        reference = resolve_reference(s, ctx, product_id, identity, store)
        original = service.store.read_current(reference)
        refs = service.references.read_current(reference)
        if not complete:
            refs = replace(refs, reference_count=None, formal_history=None)
        quarantine = evaluate_quarantine(original, refs, service.policy, now())
        restore = evaluate_restore(original, refs, service.policy, now())
        item, registered, attempt = (
            journal_items.get(identity),
            originals.get(identity),
            attempts.get(identity),
        )
        histories = []
        for row in s.scalars(
            select(LifecycleIntentRecord)
            .where(LifecycleIntentRecord.object_id == identity)
            .order_by(LifecycleIntentRecord.created_at)
        ):
            intent = decode_intent(row.document)
            histories.append(
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    "action": intent.action.value,
                    "state": intent.state.value,
                    "created_at": intent.created_at.isoformat(),
                    "updated_at": intent.updated_at.isoformat(),
                    "reason": row.reason,
                    "recovery_required": intent.recovery_required,
                    "can_cancel": intent.state.value == "pending" and intent.permit is None,
                    "can_reconcile": intent.state.value in {"in_flight", "unknown"},
                }
            )
        result.append(
            {
                "id": str(identity),
                "title": registered.title
                if registered
                else attempt.title
                if attempt
                else "未完成上传",
                "filename": registered.filename
                if registered
                else attempt.filename
                if attempt
                else "保留的原件",
                "revision": original.revision,
                "registered": original.registered,
                "upload_state": original.upload_state.value,
                "parse_state": original.parse_state.value,
                "retention_until": original.retention_until.isoformat()
                if original.retention_until
                else None,
                "manual_hold": original.manual_hold,
                "disposition": original.disposition.value,
                "pending_intent_id": str(original.pending_intent_id)
                if original.pending_intent_id
                else None,
                "reference_count": refs.reference_count,
                "formal_history": refs.formal_history,
                "coverage_complete": complete and refs.reference_count is not None,
                "registration_state": item.registration_state if item else "unknown",
                "byte_status": item.byte_status if item else "unavailable",
                "reasons": [r.value for r in quarantine.reasons],
                "can_quarantine": complete and quarantine.eligible,
                "can_restore": complete and restore.eligible,
                "can_record_protection": original.pending_intent_id is None,
                "can_abandon_upload": bool(
                    attempt and attempt.status == "reserved" and not registered
                ),
                "upload_attempt_id": str(attempt.id) if attempt else None,
                "upload_attempt_revision": attempt.revision if attempt else None,
                "policy_version": service.policy.version,
                "intents": histories,
            }
        )
    return {
        "items": result,
        "coverage_complete": complete and schema_covered(s),
        "policy": {
            "version": service.policy.version,
            "profile": "local-synthetic"
            if service.policy.version.startswith("local-synthetic")
            else "configured",
            "failed_upload_grace_seconds": service.policy.failed_upload_grace
            // timedelta(seconds=1),
            "quarantine_grace_seconds": service.policy.quarantine_grace // timedelta(seconds=1),
        },
    }
