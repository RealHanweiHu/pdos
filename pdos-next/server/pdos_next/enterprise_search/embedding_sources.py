"""Same native RLS/source/hash/scan joins for batch input and semantic recall."""

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import array

from pdos_next.database import require_context
from pdos_next.errors import DomainError

from .models import SearchChunk, SearchSource
from .query import _narrow
from .retrieval_filters import scoped_authority
from .safety import safe_originals
from .sources import dependency_originals, prepare_read, retrieval_catalog
from .tokenizer import CHUNKER, CODE_RULE, version


def readable_chunks(
    session,
    ctx,
    data,
    *,
    ids=None,
    include_text=False,
    materialize_authority=False,
    **filters,
):
    require_context(session, ctx)
    scope = _narrow(session, ctx, data)
    families = tuple(sorted(data.source_types))
    prepare_read(session, families)
    c, state = SearchChunk, SearchSource
    potential = select(c.source_type, c.source_id).where(
        c.tenant_id == ctx.tenant_id,
        c.source_type.in_(families),
    )
    if scope["category_id"]:
        potential = potential.where(c.category_id == scope["category_id"])
    if ids is not None:
        potential = potential.where(c.id.in_(ids))
    potential = potential.distinct()
    safe = safe_originals(session, dependency_originals(session, families, potential))
    authority = retrieval_catalog(families)
    metadata_fields = (
        "source_type",
        "source_id",
        "object_id",
        "source_revision",
        "content_hash",
        "title",
        "category_id",
        "product_id",
        "project_id",
        "proposal_id",
        "nature",
        "private",
        "customer_original",
        "is_current",
        "read_basis_status",
    )
    scoped = scoped_authority(
        authority, ctx.tenant_id, scope, include_history=data.include_history, **filters
    )
    if materialize_authority:
        # Evaluate source RLS once per source, before joining its many chunks.
        # Keep fixed batch reads inline and omit unneeded bodies from the spool.
        scoped = scoped.with_only_columns(
            *[
                authority.c[key]
                for key in (*metadata_fields, "tenant_id", "original_ids", "created_at")
            ],
            maintain_column_froms=True,
        )
    source = scoped.cte("embedding_scoped_authority")
    if materialize_authority:
        source = source.prefix_with("MATERIALIZED")
    fields = [
        c.id.label("chunk_id"),
        c.chunk_hash,
        c.work_key,
        c.ordinal,
        *[source.c[key] for key in metadata_fields],
        c.locator,
    ]
    if include_text:
        fields.append(c.text)
    query = (
        select(*fields)
        .join(
            source,
            and_(
                c.tenant_id == source.c.tenant_id,
                c.category_id == source.c.category_id,
                c.source_type == source.c.source_type,
                c.source_id == source.c.source_id,
                c.source_revision == source.c.source_revision,
                c.content_hash == source.c.content_hash,
            ),
        )
        .join(
            state,
            and_(
                state.tenant_id == c.tenant_id,
                state.source_type == c.source_type,
                state.source_id == c.source_id,
                state.category_id == source.c.category_id,
                state.work_key == c.work_key,
                state.source_revision == c.source_revision,
                state.content_hash == c.content_hash,
                state.status == "ready",
                state.last_error.is_(None),
            ),
        )
        .where(
            c.tenant_id == ctx.tenant_id,
            c.source_type.in_(families),
            c.tokenizer_version == version(),
            c.code_rule_version == CODE_RULE,
            c.chunker_version == CHUNKER,
            source.c.original_ids.bool_op("<@")(array(sorted(safe), type_=PGUUID)),
        )
    )
    if data.after:
        query = query.where(source.c.created_at >= data.after)
    if data.before:
        query = query.where(source.c.created_at < data.before)
    if ids is not None:
        query = query.where(c.id.in_(ids))
    return query


def fixed_rows(session, ctx, manifest):
    from .schemas import SearchInput

    ids = [UUID(row["chunk_id"]) for row in manifest["chunks"]]
    kinds = sorted({row["source_type"] for row in manifest["chunks"]})
    query = readable_chunks(
        session,
        ctx,
        SearchInput(query="embedding fixed batch", source_types=kinds),
        ids=ids,
        include_text=True,
    )
    found = {str(row["chunk_id"]): dict(row) for row in session.execute(query).mappings()}
    expected = {row["chunk_id"]: row for row in manifest["chunks"]}
    if set(found) != set(expected) or any(
        any(
            str(found[key][field]) != str(expected[key][field])
            for field in (
                "source_type",
                "source_id",
                "source_revision",
                "content_hash",
                "chunk_hash",
                "work_key",
            )
        )
        for key in expected
    ):
        raise DomainError("SOURCE_STALE", "固定 Embedding 批次来源已变化或无权读取。")
    return [found[row["chunk_id"]] for row in manifest["chunks"]]


def categories(row):
    # These facts come from the authoritative source relation, not profile/model arguments.
    return {"internal", "customer_original"} if row["customer_original"] else {"internal"}


def manifest_chunk(row):
    return {
        key: str(row[key]) if isinstance(row[key], UUID) else row[key]
        for key in (
            "chunk_id",
            "source_type",
            "source_id",
            "source_revision",
            "content_hash",
            "chunk_hash",
            "work_key",
        )
    }
