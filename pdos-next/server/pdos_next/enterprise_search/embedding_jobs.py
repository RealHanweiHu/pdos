"""Fixed, bounded, replayable derived-work manifests; no text in Temporal history."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from pdos_next.service import digest

from .embedding_identity import canonical_provider
from .embedding_models import ChunkEmbedding, EmbeddingBatch
from .embedding_profiles import active
from .embedding_runtime import context_value
from .embedding_schemas import MAX_BATCH, MAX_CHARACTERS
from .embedding_sources import categories, manifest_chunk, readable_chunks
from .schemas import SearchInput


def pack(rows):
    """Deterministic chunk grouping; never use a provider to summarize or classify."""
    batch, characters = [], 0
    for row in rows:
        size = len(row["text"])
        if batch and (len(batch) == MAX_BATCH or characters + size > MAX_CHARACTERS):
            yield batch
            batch, characters = [], 0
        batch.append(row)
        characters += size
    if batch:
        yield batch


def plan(session, ctx, version_id, *, generation, secrets):
    from pdos_next.agent_kernel import policy

    profile, metadata = active(session, ctx.tenant_id, version_id)
    provider = canonical_provider(secrets, ctx.tenant_id, metadata)
    chunks = readable_chunks(
        session, ctx, SearchInput(query="embedding fixed manifest"), include_text=True
    ).cte("embedding_current_inputs")
    present = ChunkEmbedding
    missing = (
        select(chunks)
        .outerjoin(
            present,
            and_(
                present.tenant_id == ctx.tenant_id,
                present.chunk_id == chunks.c.chunk_id,
                present.chunk_hash == chunks.c.chunk_hash,
                present.profile_version_id == profile.id,
            ),
        )
        .where(present.chunk_id.is_(None))
    )
    # Profile selection and current P26 rules narrow before LIMIT. Otherwise a
    # page of intentionally excluded originals could starve later allowed rows.
    allowed, denied = [], []
    for customer, actual in ((False, {"internal"}), (True, {"internal", "customer_original"})):
        if not actual <= set(metadata.data_categories):
            continue
        predicate = chunks.c.customer_original if customer else ~chunks.c.customer_original
        from pdos_next.errors import DomainError

        try:
            policy.egress(session, ctx, provider, data_categories=actual)
            allowed.append(predicate)
        except DomainError:
            denied.append(predicate)
    skipped = session.scalar(
        select(func.count()).select_from(
            missing.where(or_(*denied) if denied else false()).subquery(),
        )
    )
    query = (
        missing.where(or_(*allowed) if allowed else false())
        .order_by(
            chunks.c.source_type,
            chunks.c.source_id,
            chunks.c.source_revision,
            chunks.c.ordinal,
            chunks.c.chunk_id,
        )
        .limit(5001)
    )
    rows = list(session.execute(query).mappings())
    truncated, accepted = len(rows) > 5000, []
    for row in rows[:5000]:
        actual = categories(row)
        if not actual <= set(metadata.data_categories):
            skipped += 1
            continue
        accepted.append(row)
    batches = []
    for group in pack(accepted):
        manifest = {
            "version": 1,
            "context": context_value(ctx),
            "chunks": [manifest_chunk(row) for row in group],
        }
        key = digest([str(profile.id), profile.binding_digest, manifest])
        identity = uuid5(NAMESPACE_URL, f"embedding-batch:{ctx.tenant_id}:{key}")
        previous = session.get(EmbeddingBatch, identity)
        if previous is not None and (
            previous.state == "ready" or previous.last_error == "DERIVED_INDEX_MISSING"
        ):
            # A new real Outbox/rebuild request may repair deleted derived data.
            # It keeps prior charges, and its same generation is idempotent.
            manifest["repair_generation"] = str(generation)
            key = digest([str(profile.id), profile.binding_digest, manifest])
            identity = uuid5(NAMESPACE_URL, f"embedding-batch:{ctx.tenant_id}:{key}")
        session.execute(
            insert(EmbeddingBatch)
            .values(
                id=identity,
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                profile_version_id=profile.id,
                manifest=manifest,
                work_key=key,
                state="queued",
                attempts=0,
            )
            .on_conflict_do_nothing()
        )
        batches.append(str(identity))
    return {
        "batches": batches,
        "uncovered_chunks": skipped,
        "truncated": truncated,
        "scope": "current_requester_readable",
        "profile_version_id": str(profile.id),
    }
