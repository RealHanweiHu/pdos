"""No-model retrieval: OR + tenant IDF/BM25 and codes, joined to current RLS sources."""

from uuid import UUID

from sqlalchemy import Float, Text, and_, case, cast, func, literal, or_, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by, array
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from pdos_next.database import require_context
from pdos_next.domain.preproject.models import Proposal
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Category, Product

from .models import SearchChunk, SearchCorpus, SearchSource, SearchTerm
from .presence import source_families
from .relations import decorate, graph_for, related_page
from .safety import safe_originals
from .schemas import SearchInput as SearchInput
from .sources import dependency_originals, identity_keys, prepare_read, retrieval_catalog
from .tokenizer import CHUNKER, CODE_RULE, RANKING, analyze, or_query, version


def _narrow(session, ctx, data):
    selectors = {
        key: getattr(data, key)
        for key in ("category_id", "product_id", "project_id", "proposal_id")
    }
    if ctx.category_id and selectors["category_id"] not in (None, ctx.category_id):
        raise DomainError("FORBIDDEN_SCOPE", "检索不能越过当前品类范围。")
    queries = []
    for key, model in (
        ("category_id", Category),
        ("product_id", Product),
        ("project_id", Project),
        ("proposal_id", Proposal),
    ):
        if selectors[key] is None:
            continue
        category = model.id if key == "category_id" else model.category_id
        queries.append(
            select(literal(key).label("kind"), model.id, category.label("category_id")).where(
                model.id == selectors[key], func.category_access(model.tenant_id, category)
            )
        )
    if queries:
        rows = session.execute(union_all(*queries)).all()
        if len(rows) != len(queries) or len({row.category_id for row in rows}) != 1:
            raise DomainError("FORBIDDEN_SCOPE", "检索对象不在当前可读的同一品类范围。")
        category = rows[0].category_id
        if ctx.category_id is not None and ctx.category_id != category:
            raise DomainError("FORBIDDEN_SCOPE", "检索对象与当前品类不一致。")
        selectors["category_id"] = category
    else:
        selectors["category_id"] = ctx.category_id
    return selectors


def search(
    session, ctx, data: SearchInput, *, exclude_project=None, exclude_proposal=None,
    exclude_sources=(), allow_customer_private=True,
):
    require_context(session, ctx)
    scope = _narrow(session, ctx, data)
    parsed = analyze(data.query)
    try:
        identity = UUID(data.query.strip())
    except ValueError:
        identity = None
    if not parsed["terms"] and not parsed["codes"] and identity is None:
        raise DomainError("INVALID_PAYLOAD", "请输入可检索的词语或对象编号。", 422)
    prepare_read(session, data.source_types)
    families, as_of = source_families(session, ctx, data.source_types, scope)
    if not families:
        return _response(session, data, scope, parsed, [], as_of=as_of)
    c, state, corpus = SearchChunk, SearchSource, SearchCorpus
    channels = []
    if parsed["terms"]:
        channels.append(c.terms.op("@@")(func.to_tsquery("simple", or_query(parsed["terms"]))))
    if parsed["codes"]:
        channels += [c.codes.overlap(parsed["codes"]), c.code_families.overlap(parsed["codes"])]
    potential_channels = list(channels)
    if identity is not None:
        ids = identity_keys(families, identity)
        potential_channels.append(c.source_id == identity)
        if ids is not None:
            potential_channels.append(tuple_(c.source_type, c.source_id).in_(ids))
    potential = (
        select(c.source_type, c.source_id)
        .where(
            c.tenant_id == ctx.tenant_id,
            c.source_type.in_(families),
            or_(*potential_channels),
        )
        .distinct()
    )
    if scope["category_id"] is not None:
        potential = potential.where(c.category_id == scope["category_id"])
    potential = potential.cte("indexed_potential_sources")
    graph = graph_for(families, potential)
    dependencies = select(potential)
    if graph is not None:
        dependencies = dependencies.union(
            select(
                graph.c.target_kind.label("source_type"),
                graph.c.target_id.label("source_id"),
            )
        )
    originals = dependency_originals(session, families, dependencies)
    safe = safe_originals(session, originals)

    authority = retrieval_catalog(families)
    scoped = select(authority).where(authority.c.tenant_id == ctx.tenant_id)
    for key, value in scope.items():
        if value is not None:
            scoped = scoped.where(getattr(authority.c, key) == value)
    # These filters come only from the host's one-shot same-category policy.
    # Apply them to both direct and relation authority before counts or paging.
    if exclude_project is not None:
        scoped = scoped.where(authority.c.project_id.is_distinct_from(exclude_project))
    if exclude_proposal is not None:
        scoped = scoped.where(authority.c.proposal_id.is_distinct_from(exclude_proposal))
    if exclude_sources:
        scoped = scoped.where(~tuple_(authority.c.source_type, authority.c.source_id).in_(
            [(kind, UUID(str(identity))) for kind, identity in exclude_sources]
        ))
    if not allow_customer_private:
        scoped = scoped.where(~and_(authority.c.private, authority.c.customer_original))
    if not data.include_history:
        current = authority.c.is_current
        if graph is not None:
            current = or_(
                current,
                and_(
                    authority.c.source_type.in_(["issue", "capa"]),
                    tuple_(authority.c.source_type, authority.c.source_id).in_(
                        select(graph.c.target_kind, graph.c.target_id)
                    ),
                ),
            )
        scoped = scoped.where(current)
    # Materialize current authoritative facts once for direct and related results.
    # Exact registered quality references may retain their fixed older revision.
    authorized = scoped.cte("scoped_authoritative_sources").prefix_with("MATERIALIZED")
    direct = select(authorized)
    if not data.include_history:
        direct = direct.where(authorized.c.is_current)
    if data.after:
        direct = direct.where(authorized.c.created_at >= data.after)
    if data.before:
        direct = direct.where(authorized.c.created_at < data.before)
    s = direct.cte("scoped_enterprise_sources")
    condition = and_(
        c.tenant_id == s.c.tenant_id,
        c.category_id == s.c.category_id,
        c.source_type == s.c.source_type,
        c.source_id == s.c.source_id,
        c.source_revision == s.c.source_revision,
        c.content_hash == s.c.content_hash,
    )
    matched = (
        select(c.id, s.c.original_id, s.c.original_ids)
        .join(s, condition)
        .join(
            state,
            and_(
                state.tenant_id == c.tenant_id,
                state.source_type == c.source_type,
                state.source_id == c.source_id,
                state.work_key == c.work_key,
                state.category_id == s.c.category_id,
                state.status == "ready",
            ),
        )
        .where(
            c.tenant_id == ctx.tenant_id,
            c.source_type.in_(data.source_types),
            c.tokenizer_version == version(),
            c.code_rule_version == CODE_RULE,
            c.chunker_version == CHUNKER,
        )
    )
    if identity is not None:
        channels.append(or_(c.source_id == identity, s.c.object_id == identity))
    matched = matched.where(or_(*channels)).cte("readable_keyword_matches")
    unsafe = select(
        func.coalesce(
            func.bool_or(~matched.c.original_ids.bool_op("<@")(array(sorted(safe), type_=PGUUID))),
            False,
        ).label("unsafe_match")
    ).cte("unsafe_matches")
    count = (
        select(func.count())
        .select_from(c)
        .where(
            c.tenant_id == s.c.tenant_id,
            c.category_id == s.c.category_id,
            c.source_type == s.c.source_type,
            c.source_id == s.c.source_id,
            c.source_revision == s.c.source_revision,
            c.content_hash == s.c.content_hash,
            c.tokenizer_version == version(),
            c.code_rule_version == CODE_RULE,
            c.chunker_version == CHUNKER,
            c.work_key == state.work_key,
        )
        .correlate(s, state)
        .scalar_subquery()
    )
    missing = (
        select(
            func.bool_or(
                or_(
                    state.id.is_(None),
                    state.status != "ready",
                    state.last_error.is_not(None),
                    state.source_revision != s.c.source_revision,
                    state.content_hash != s.c.content_hash,
                    state.chunk_count != count,
                )
            ).label("incomplete"),
            func.min(state.checked_at).label("indexed_as_of"),
        )
        .select_from(s)
        .outerjoin(
            state,
            and_(
                state.tenant_id == s.c.tenant_id,
                state.category_id == s.c.category_id,
                state.source_type == s.c.source_type,
                state.source_id == s.c.source_id,
            ),
        )
        .where(
            s.c.tenant_id == ctx.tenant_id,
            s.c.source_type.in_(data.source_types),
        )
    )
    health = missing.cte("enterprise_index_health")
    eligible = select(matched.c.id).where(
        matched.c.original_ids.bool_op("<@")(array(sorted(safe), type_=PGUUID)),
    )
    terms = func.unnest(array(parsed["terms"], type_=Text)).table_valued("term").render_derived()
    tf = func.coalesce(cast(c.term_counts.op("->>")(terms.c.term), Float), 0) + 2.5 * func.coalesce(
        cast(c.title_counts.op("->>")(terms.c.term), Float), 0
    )
    avg = func.greatest(cast(corpus.token_count, Float) / func.greatest(corpus.chunk_count, 1), 1)
    df = func.least(func.coalesce(SearchTerm.document_count, 1), corpus.chunk_count)
    score = (
        select(
            func.coalesce(
                func.sum(
                    func.ln(1 + (corpus.chunk_count - df + 0.5) / (df + 0.5))
                    * (tf * 2.2)
                    / (tf + 1.2 * (0.25 + 0.75 * c.token_count / avg))
                ),
                0,
            )
        )
        .select_from(terms)
        .outerjoin(
            SearchTerm,
            and_(
                SearchTerm.tenant_id == c.tenant_id,
                SearchTerm.term == terms.c.term,
            ),
        )
        .correlate(c.__table__, corpus.__table__)
        .scalar_subquery()
    )
    code_hit = case(
        (c.codes.overlap(parsed["codes"]), 2),
        (c.code_families.overlap(parsed["codes"]), 1),
        else_=0,
    )
    exact = (
        case((or_(c.source_id == identity, s.c.object_id == identity), 1), else_=0)
        if identity
        else literal(0)
    )
    freshness = (
        1
        if data.include_history
        else (
            1
            + 0.05
            * func.exp(
                -0.693147
                * func.greatest(
                    func.extract("epoch", func.transaction_timestamp() - s.c.created_at),
                    0,
                )
                / (180 * 86400)
            )
        )
    )
    score = score * freshness
    ranked = (
        select(
            c.id.label("chunk_id"),
            c.source_type,
            c.source_id,
            s.c.object_id,
            c.source_revision,
            c.content_hash,
            c.locator,
            s.c.title,
            s.c.category_id,
            s.c.product_id,
            s.c.project_id,
            s.c.proposal_id,
            s.c.nature,
            s.c.private,
            s.c.customer_original,
            s.c.is_current,
            s.c.read_basis_status,
            exact.label("exact_match"),
            code_hit.label("code_hit"),
            score.label("score"),
            func.row_number()
            .over(
                partition_by=(c.source_type, c.source_id),
                order_by=(exact.desc(), code_hit.desc(), score.desc(), c.id),
            )
            .label("source_rank"),
        )
        .join(s, condition)
        .join(corpus, corpus.tenant_id == c.tenant_id)
        .where(c.id.in_(eligible))
        .cte("ranked_enterprise_matches")
    )
    page = (
        select(ranked)
        .where(ranked.c.source_rank == 1)
        .order_by(
            ranked.c.exact_match.desc(),
            ranked.c.code_hit.desc(),
            ranked.c.score.desc(),
            ranked.c.source_id,
            ranked.c.chunk_id,
        )
        .limit(data.limit + 1)
        .cte("enterprise_page")
    )
    ordering = (
        page.c.exact_match.desc(),
        page.c.code_hit.desc(),
        page.c.score.desc(),
        page.c.source_id,
        page.c.chunk_id,
    )
    roots = (
        select(
            page,
            func.row_number().over(order_by=ordering).label("origin_order"),
        )
        .order_by(*ordering)
        .limit(data.limit)
        .cte("direct_relation_roots")
    )

    def json_rows(rows, order):
        return (
            select(
                func.coalesce(
                    func.jsonb_agg(aggregate_order_by(func.to_jsonb(rows.table_valued()), *order)),
                    literal("[]").cast(JSONB),
                )
            )
            .select_from(rows)
            .scalar_subquery()
        )

    related = literal("[]").cast(JSONB)
    if graph is not None:
        relations = related_page(
            graph,
            authorized,
            roots,
            safe,
            include_history=data.include_history,
            limit=data.limit,
        )
        related = json_rows(
            relations,
            (
                relations.c.origin_order,
                relations.c.is_current.desc(),
                relations.c.source_revision.desc(),
                relations.c.source_type,
                relations.c.source_id,
                relations.c.relation,
            ),
        )
    # Independent aggregate subqueries keep a single header even for no matches
    # without multiplying the bounded direct and related result sets.
    metadata = (
        session.execute(
            select(
                health.c.incomplete,
                health.c.indexed_as_of,
                unsafe.c.unsafe_match,
                func.transaction_timestamp().label("as_of"),
                json_rows(page, ordering).label("primary_rows"),
                related.label("related_rows"),
            )
            .select_from(health)
            .join(unsafe, literal(True))
        )
        .mappings()
        .one()
    )
    result = _response(
        session,
        data,
        scope,
        parsed,
        metadata["primary_rows"],
        incomplete=bool(metadata["incomplete"]) or bool(metadata["unsafe_match"]),
        indexed_as_of=metadata["indexed_as_of"],
        as_of=metadata["as_of"],
    )
    return decorate(result, metadata["related_rows"])


def _response(session, data, scope, parsed, rows, *, incomplete=False, indexed_as_of=None, as_of):
    items = []
    for rank, row in enumerate(rows[: data.limit], 1):
        items.append(
            {
                key: str(row[key]) if isinstance(row[key], UUID) else row[key]
                for key in (
                    "chunk_id",
                    "source_type",
                    "source_id",
                    "object_id",
                    "source_revision",
                    "content_hash",
                    "locator",
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
            }
        )
        items[-1]["rank"] = rank
        items[-1]["channel"] = (
            "exact_id"
            if row["exact_match"]
            else "exact_code"
            if row["code_hit"] == 2
            else "code_family"
            if row["code_hit"]
            else "keyword"
        )
    return {
        "coverage": {
            "status": "partial" if incomplete else "current",
            "notice": "部分当前可读来源尚未完成索引或当前扫描复核。" if incomplete else None,
            "indexed_as_of": indexed_as_of.isoformat() if indexed_as_of else None,
        },
        "version": "enterprise-search/v1",
        "items": items,
        "returned": len(items),
        "direct_returned": len(items),
        "related_returned": 0,
        "related_truncated": False,
        "truncated": len(rows) > data.limit,
        "as_of": as_of.isoformat(),
        "scope": {key: str(value) if value else None for key, value in scope.items()},
        "query_trace": {
            key: parsed[key]
            for key in (
                "terms",
                "removed",
                "codes",
                "families",
                "tokenizer_version",
                "code_rule_version",
            )
        },
        "ranking_version": RANKING,
    }
