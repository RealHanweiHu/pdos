"""Deterministic RRF over current RLS-filtered keyword and semantic candidates.

No embedding provider is called by this module, including page requests. A vector
must be supplied by an already-accounted server Run or an explicit offline shadow.
Without it the original keyword response is returned unchanged.
"""

from uuid import UUID

from sqlalchemy import (
    Integer,
    Text,
    and_,
    bindparam,
    cast,
    column,
    func,
    select,
    text,
    tuple_,
    values,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from pdos_next.errors import DomainError

from .embedding_models import ChunkEmbedding, Vector
from .embedding_profiles import active
from .embedding_runtime import unit_vector
from .embedding_schemas import EmbeddingResponse, validate_response
from .embedding_sources import readable_chunks
from .query import _narrow, search
from .relations import decorate, graph_for, related_page
from .retrieval_filters import scoped_authority
from .safety import safe_originals
from .sources import dependency_originals, retrieval_catalog

RANKING = "enterprise-rrf/v1;k=60;exact-id-code-family-first"
EXACT_CHUNK_THRESHOLD = 1000
MAX_SEMANTIC_POOL = 1000


def pool_limits(limit):
    size = min(MAX_SEMANTIC_POOL, max(100, limit * 20))
    while True:
        yield size
        if size == MAX_SEMANTIC_POOL:
            return
        size = min(MAX_SEMANTIC_POOL, size * 2)


def _embedding_match(authorized, tenant, profile, dimensions):
    v = ChunkEmbedding
    return and_(
        v.tenant_id == tenant,
        v.chunk_id == authorized.c.chunk_id,
        v.chunk_hash == authorized.c.chunk_hash,
        v.category_id == authorized.c.category_id,
        v.profile_version_id == profile,
        v.dimensions == dimensions,
    )


def eligible_chunks_statement(authorized, tenant, profile, dimensions):
    return (
        select(ChunkEmbedding.chunk_id.label("semantic_eligible_chunk"))
        .select_from(authorized)
        .join(ChunkEmbedding, _embedding_match(authorized, tenant, profile, dimensions))
        .limit(EXACT_CHUNK_THRESHOLD + 1)
        .execution_options(pdos_semantic_custom_plan=True)
    )


def public_rows(rows, *, omit=()):
    # Native keyword jsonb_agg already serializes these UUIDs. The semantic SQL
    # path uses mappings, so normalize before the same relation decorator.
    return [
        {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in row.items()
            if key not in omit
        }
        for row in rows
    ]


def rrf(keyword, semantic, *, limit, k=60):
    """Exact identifiers keep native priority; scores never confer validity."""
    weights, found = {}, {}
    for channel in (keyword, semantic):
        seen = set()
        for index, row in enumerate(channel, 1):
            identity = (row["source_type"], row["source_id"])
            if identity in seen:
                continue
            seen.add(identity)
            weights[identity] = weights.get(identity, 0) + 1 / (k + index)
            found.setdefault(identity, dict(row))
    priority = {"exact_id": 4, "exact_code": 3, "code_family": 2}
    ordered = sorted(
        found,
        key=lambda identity: (
            -priority.get(found[identity].get("channel"), 0),
            -weights[identity],
            identity[0],
            str(identity[1]),
            str(found[identity].get("chunk_id") or ""),
        ),
    )
    return [
        {**found[identity], "rank": number} for number, identity in enumerate(ordered[:limit], 1)
    ]


def nearest_statement(
    authorized,
    tenant_id,
    profile_version,
    dimensions,
    vector,
    *,
    limit,
    strategy="exact",
    pool_limit=None,
):
    if strategy not in {"exact", "iterative"}:
        raise ValueError("Explicit registered scan strategy required")
    if strategy == "iterative":
        if pool_limit is not None and (
            type(pool_limit) is not int or not 1 <= pool_limit <= MAX_SEMANTIC_POOL
        ):
            raise ValueError("Bounded server pool limit required")
        authorized = (
            select(authorized).cte("iterative_semantic_authority").prefix_with("MATERIALIZED")
        )
    v = ChunkEmbedding
    operand = cast(
        bindparam("embedding_query_vector", value=tuple(vector), type_=Vector(dimensions)),
        Vector(dimensions),
    )
    distance = cast(v.vector, Vector(dimensions)).op("<=>")(operand)
    if strategy == "iterative":
        # Filtered ANN may yield fewer distinct sources than exact; compare on the
        # same allowed set and report it. Iterative HNSW is set by the owner below.
        # PG16 requires every inner ordering key to match the HNSW operator;
        # stable source/chunk ties are resolved after this distance-only pool.
        # Keep current authority as a membership predicate on the vector scan,
        # before LIMIT. IS TRUE retains SQL NULL rejection and prevents PG16
        # from pulling the membership back into an authority-driven semijoin.
        membership = (
            tuple_(v.chunk_id, v.chunk_hash, v.category_id)
            .in_(select(authorized.c.chunk_id, authorized.c.chunk_hash, authorized.c.category_id))
            .is_(True)
        )
        neighbors = (
            select(v.chunk_id, v.chunk_hash, v.category_id, distance.label("distance"))
            .where(
                v.tenant_id == tenant_id,
                v.profile_version_id == profile_version,
                v.dimensions == dimensions,
                membership,
            )
            .order_by(distance)
            .limit(pool_limit if pool_limit is not None else next(pool_limits(limit)))
            .cte("iterative_semantic_neighbors")
        )
        pool = (
            select(
                authorized,
                neighbors.c.distance,
                func.count().over().label("_candidate_chunk_count"),
            )
            .select_from(neighbors)
            .join(
                authorized,
                and_(
                    neighbors.c.chunk_id == authorized.c.chunk_id,
                    neighbors.c.chunk_hash == authorized.c.chunk_hash,
                    neighbors.c.category_id == authorized.c.category_id,
                ),
            )
            .cte("iterative_semantic_pool")
        )
    else:
        candidates = (
            select(authorized, distance.label("distance"))
            .select_from(authorized)
            .join(
                v,
                _embedding_match(authorized, tenant_id, profile_version, dimensions),
            )
        )
        pool = candidates.cte("exact_semantic_pool").prefix_with("MATERIALIZED")
    ranked = select(
        pool,
        func.row_number()
        .over(
            partition_by=(pool.c.source_type, pool.c.source_id),
            order_by=(pool.c.distance, pool.c.chunk_id),
        )
        .label("source_rank"),
    ).cte("semantic_source_ranks")
    return (
        select(ranked)
        .where(ranked.c.source_rank == 1)
        .order_by(
            ranked.c.distance,
            ranked.c.source_id,
            ranked.c.chunk_id,
        )
        .limit(limit + 1)
        .execution_options(pdos_semantic_custom_plan=True)
    )


def public_scan_evidence(evidence):
    """Stage identities are test/internal observations, never additional tool sources."""
    return {
        key: evidence[key]
        for key in (
            "requested_strategy",
            "executed_strategy",
            "selection_reason",
            "exact_chunk_threshold",
            "target_sources",
            "max_pool_limit",
            "eligible_probe",
            "shortfall",
            "shortfall_reason",
            "exhausted",
        )
        if key in evidence
    } | {
        "attempts": [
            {
                key: attempt[key]
                for key in (
                    "strategy",
                    "pool_limit",
                    "candidate_chunks",
                    "returned_sources",
                )
            }
            for attempt in evidence.get("attempts", [])
        ],
    }


def semantic_rows(
    session, ctx, data, version_id, vector, *, strategy="exact", scan_evidence=None, **filters
):
    if strategy not in {"exact", "iterative"}:
        raise ValueError("Explicit registered scan strategy required")
    _profile, metadata = active(session, ctx.tenant_id, version_id)
    validate_response(EmbeddingResponse((tuple(vector),)), count=1, dimensions=metadata.dimensions)
    authorized = readable_chunks(
        session, ctx, data, materialize_authority=True, **filters
    ).cte("semantic_authorized_chunks")
    evidence = scan_evidence if scan_evidence is not None else {}
    evidence.clear()
    evidence.update(
        {
            "requested_strategy": strategy,
            "executed_strategy": strategy,
            "selection_reason": "requested_exact"
            if strategy == "exact"
            else "large_authorized_set",
            "exact_chunk_threshold": EXACT_CHUNK_THRESHOLD,
            "target_sources": data.limit + 1,
            "max_pool_limit": MAX_SEMANTIC_POOL,
            "eligible_probe": None,
            "attempts": [],
            "shortfall": False,
        }
    )
    executed = strategy
    if strategy == "iterative":
        observed = len(
            session.execute(
                eligible_chunks_statement(
                    authorized,
                    ctx.tenant_id,
                    version_id,
                    metadata.dimensions,
                )
            ).all()
        )
        complete = observed <= EXACT_CHUNK_THRESHOLD
        evidence["eligible_probe"] = {
            "returned_chunks": observed,
            "limit": EXACT_CHUNK_THRESHOLD + 1,
            "complete": complete,
        }
        if complete:
            executed = "exact"
            evidence.update(executed_strategy=executed, selection_reason="small_authorized_set")
    if executed == "iterative":
        session.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
    normalized = unit_vector(vector)
    for size in pool_limits(data.limit) if executed == "iterative" else (None,):
        rows = list(
            session.execute(
                nearest_statement(
                    authorized,
                    ctx.tenant_id,
                    version_id,
                    metadata.dimensions,
                    normalized,
                    limit=data.limit,
                    strategy=executed,
                    pool_limit=size,
                )
            ).mappings()
        )
        chunk_count = (
            (int(rows[0]["_candidate_chunk_count"]) if rows else 0)
            if executed == "iterative"
            else (
                evidence["eligible_probe"]["returned_chunks"]
                if evidence["eligible_probe"]
                else None
            )
        )
        evidence["attempts"].append(
            {
                "strategy": executed,
                "pool_limit": size,
                "candidate_chunks": chunk_count,
                "returned_sources": len(rows),
                "source_ids": [str(row["source_id"]) for row in rows],
            }
        )
        if executed == "exact" or len(rows) >= data.limit + 1:
            break
    evidence["shortfall"] = executed == "iterative" and len(rows) < data.limit + 1
    evidence["exhausted"] = len(rows) < data.limit + 1 if executed == "exact" else None
    if evidence["shortfall"]:
        evidence["shortfall_reason"] = "distinct_source_target_unmet_within_pool_cap"
    private_columns = {
        "distance",
        "chunk_hash",
        "work_key",
        "ordinal",
        "source_rank",
        "_candidate_chunk_count",
    }
    return [{**row, "channel": "semantic"} for row in public_rows(rows, omit=private_columns)]


def expand(session, ctx, data, result, **filters):
    if not result["items"]:
        return result
    roots = (
        values(
            column("source_type", Text),
            column("source_id", PGUUID),
            column("category_id", PGUUID),
            column("origin_order", Integer),
        )
        .data(
            [
                (
                    row["source_type"],
                    UUID(str(row["source_id"])),
                    UUID(str(row["category_id"])),
                    number,
                )
                for number, row in enumerate(result["items"], 1)
            ]
        )
        .cte("hybrid_relation_roots")
    )
    graph = graph_for(data.source_types, roots)
    if graph is None:
        return result
    dependencies = select(roots.c.source_type, roots.c.source_id).union(
        select(graph.c.target_kind, graph.c.target_id),
    )
    safe = safe_originals(session, dependency_originals(session, data.source_types, dependencies))
    authority = (
        scoped_authority(
            retrieval_catalog(data.source_types),
            ctx.tenant_id,
            _narrow(session, ctx, data),
            include_history=data.include_history,
            graph=graph,
            **filters,
        )
        .cte("hybrid_relation_authority")
        .prefix_with("MATERIALIZED")
    )
    rows = session.execute(
        select(
            related_page(
                graph,
                authority,
                roots,
                safe,
                include_history=data.include_history,
                limit=data.limit,
            )
        )
    ).mappings()
    return decorate(result, public_rows(rows))


def hybrid_search(
    session, ctx, data, *, profile_version_id=None, vector=None, strategy="exact", **filters
):
    keyword = search(session, ctx, data, **filters)
    if profile_version_id is None or vector is None:
        return keyword  # Default remains the exact existing keyword contract.
    try:
        scan_evidence = {}
        semantic = semantic_rows(
            session,
            ctx,
            data,
            profile_version_id,
            vector,
            strategy=strategy,
            scan_evidence=scan_evidence,
            **filters,
        )
    except DomainError as error:
        if error.code != "SOURCE_UNAVAILABLE":
            raise
        return {
            **keyword,
            "semantic": {"status": "unavailable", "reason": "profile_disabled_or_unavailable"},
        }
    direct = [row for row in keyword["items"] if row.get("channel") != "relation"]
    items = rrf(direct, semantic, limit=data.limit)
    merged = {
        **keyword,
        "items": items,
        "returned": len(items),
        "direct_returned": len(items),
        "related_returned": 0,
        "related_truncated": False,
        "truncated": keyword["truncated"] or len(semantic) > data.limit,
        "ranking_version": RANKING,
        "semantic": {
            "status": "queried",
            "profile_version_id": str(profile_version_id),
            "scan_strategy": scan_evidence.get("executed_strategy", strategy),
            "requested_scan_strategy": strategy,
            "scan_evidence": public_scan_evidence(scan_evidence),
            "candidate_count": len(semantic),
        },
    }
    return expand(session, ctx, data, merged, **filters)
