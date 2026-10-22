"""Claim reads and source roots under the caller's actual tenant/category audience."""

from sqlalchemy import select, text

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.models import Artifact, Claim, ObjectAudience, Product, UploadedOriginal

from .access import fail, proposal
from .schemas import Reference


def source_reference(row):
    """Return the underlying pinned source, never a claim-as-source shortcut."""
    snapshot = getattr(row, "source_kind", "artifact") == "snapshot"
    return Reference(
        type="snapshot" if snapshot else "artifact",
        id=row.snapshot_id if snapshot else row.artifact_id,
        version=row.source_revision,
        line=row.line,
        quote=row.quote,
    ).model_copy(update={"quote": row.quote})


def _in_scope(ctx, row):
    return bool(row and row.tenant_id == ctx.tenant_id and row.category_id == ctx.category_id)


def source_privacy(s, ctx, row):
    """Return source-root privacy; private run context is a separate Claim fact."""
    snapshot = getattr(row, "source_kind", "artifact") == "snapshot"
    model, identity = (
        (PublicWebSnapshot, row.snapshot_id) if snapshot else (Artifact, row.artifact_id)
    )
    source = s.get(model, identity)
    if not _in_scope(ctx, source):
        fail("SOURCE_UNAVAILABLE", "source_unreadable", "Claim 来源不在当前可读范围。", 403)
    private = source.visibility != "category"
    if not snapshot:
        if source.product_id:
            parent = s.get(Product, source.product_id)
            if not _in_scope(ctx, parent):
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "来源型号不在当前可读范围。", 403)
            private |= parent.visibility != "category"
        if source.original_id:
            original = s.get(UploadedOriginal, source.original_id)
            if not _in_scope(ctx, original):
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "来源原件不在当前可读范围。", 403)
            private |= original.visibility != "category"
            if original.product_id and original.product_id != source.product_id:
                parent = s.get(Product, original.product_id)
                if not _in_scope(ctx, parent):
                    fail("SOURCE_UNAVAILABLE", "source_unreadable", "原件型号不可读。", 403)
                private |= parent.visibility != "category"
    return "private" if private else "shared"


def load_source(s, ctx, reference, *, product_id=None, lock=False):
    """Resolve one active, exact source version through the existing artifact safeguards."""
    if reference.type == "artifact":
        from pdos_next.service import source_for

        source = source_for(s, ctx, product_id, reference.id, reference.version)
        body = source.content
    else:
        query = select(PublicWebSnapshot).where(
            PublicWebSnapshot.id == reference.id,
            PublicWebSnapshot.tenant_id == ctx.tenant_id,
            PublicWebSnapshot.category_id == ctx.category_id,
        )
        source = s.scalar(
            (query.with_for_update(read=True) if lock else query).execution_options(
                populate_existing=True
            )
        )
        if not _in_scope(ctx, source):
            fail("SOURCE_UNAVAILABLE", "snapshot_unreadable", "快照不在当前可读范围。", 403)
        if reference.version != 1 or source.status not in {"ok", "partial"}:
            fail("SOURCE_STALE", "snapshot_unavailable", "快照版本已失效或尚不可用。")
        body = source.markdown
    lines = body.splitlines()
    if (
        not reference.line
        or reference.line > len(lines)
        or not reference.quote
        or reference.quote not in lines[reference.line - 1]
    ):
        fail("VALIDATION_FAILED", "quote_not_in_source", "逐字片段不在指定来源定位处。")
    return source


def _historical_reader(s, ctx, row):
    if row.human_owner_id == ctx.requester_id:
        return True
    # Withdrawal freezes explicit Claim readers; a later proposal.share must
    # never grant historical bodies to its newly expanded audience.
    return (
        s.scalar(
            select(ObjectAudience.id).where(
                ObjectAudience.tenant_id == ctx.tenant_id,
                ObjectAudience.category_id == ctx.category_id,
                ObjectAudience.principal_id == ctx.requester_id,
                ObjectAudience.object_type == "claims",
                ObjectAudience.subject_id == row.id,
            )
        )
        is not None
    )


def lock_references(s, ctx, identities):
    """Lock readable facts without granting the caller Claim UPDATE permission."""
    if not identities:
        return
    list(
        s.execute(
            text(
                "SELECT id,revision,status FROM "
                "m3_lock_claim_references(:tenant,:category,CAST(:ids AS uuid[]))"
            ),
            {
                "tenant": ctx.tenant_id,
                "category": ctx.category_id,
                "ids": sorted(set(identities), key=str),
            },
        )
    )


def resolve(
    s, ctx, id, version, approved=False, lock=False, allow_withdrawn=False, source_lock=False
):
    """Read a pinned Claim; withdrawn bodies never become usable approval evidence."""
    query = select(Claim).where(
        Claim.id == id, Claim.tenant_id == ctx.tenant_id, Claim.category_id == ctx.category_id
    )
    if lock:
        lock_references(s, ctx, [id])
    row = s.scalar(query.execution_options(populate_existing=True))
    if not _in_scope(ctx, row):
        if row is None:
            from .root_sources import claim_states

            state = claim_states(s, ctx, [{"type": "claim", "id": str(id), "version": version}])
            if state.get(str(id), (None, None))[1] in {"withdrawn", "reverted"}:
                fail("SOURCE_STALE", "claim_withdrawn", "Claim 已撤回，不能作为当前证据。")
        fail("NOT_FOUND", "claim_not_found", "Claim 不存在或不在当前受众内。", 404)
    if row.status != "active":
        if not allow_withdrawn or approved:
            fail("SOURCE_STALE", "claim_withdrawn", "Claim 已撤回，不能作为当前证据。")
        if not _historical_reader(s, ctx, row):
            fail("NOT_FOUND", "claim_not_found", "Claim 不存在或不在当前受众内。", 404)
    historical_version = False
    if allow_withdrawn and not approved and row.status != "active" and row.revision == version + 1:
        from .evidence_models import ClaimWithdrawal

        if row.status == "withdrawn":
            historical_version = (
                s.scalar(
                    select(ClaimWithdrawal.id).where(
                        ClaimWithdrawal.tenant_id == ctx.tenant_id,
                        ClaimWithdrawal.category_id == ctx.category_id,
                        ClaimWithdrawal.claim_id == row.id,
                        ClaimWithdrawal.expected_version == version,
                    )
                )
                is not None
            )
        elif row.status == "reverted":
            from pdos_next.models import Receipt

            historical_version = (
                s.scalar(
                    select(Receipt.id).where(
                        Receipt.tenant_id == ctx.tenant_id,
                        Receipt.category_id == ctx.category_id,
                        Receipt.operation == "ai.run.revert",
                        (
                            (
                                (Receipt.subject_type == "claim")
                                & (Receipt.subject_id == row.id)
                                & (Receipt.subject_revision == row.revision)
                            )
                            | (
                                (Receipt.subject_type == "agent_run")
                                & (Receipt.subject_id == row.run_id)
                                & Receipt.result["receipt_ids"].contains([str(row.receipt_id)])
                            )
                        ),
                    )
                )
                is not None
            )
    if row.revision != version and not historical_version:
        fail("SOURCE_STALE", "claim_version_moved", "Claim 版本已变化。")
    if row.status != "active":
        return row
    if getattr(row, "privacy", None) == "private" and row.proposal_id:
        proposal(s, ctx, row.proposal_id, lock=lock)
    if approved:
        load_source(
            s, ctx, source_reference(row), product_id=row.product_id, lock=lock or source_lock
        )
    return row
