"""Source projectors share one authoritative RLS relation for indexing and retrieval."""

from functools import lru_cache
from hashlib import sha256

from sqlalchemy import (
    Boolean,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    null,
    select,
    text,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, array

from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.models import Artifact, OriginalSecurity, Product, UploadedOriginal


def bound_tenant():
    """Indexable narrowing from the server-established session, in addition to RLS."""
    return cast(func.nullif(func.current_setting("pdos.tenant_id", True), ""), UUID)


def prepare_read(session, source_types):
    # Correlated RLS plans exceed PostgreSQL's generic JIT cost threshold even
    # for small interactive reads. Keep this setting local to the transaction;
    # neither authority nor source predicates change, and it is done once/batch.
    transaction = session.get_nested_transaction() or session.get_transaction()
    if set(source_types) - {"artifact"} and (
        transaction is None or session.info.get("enterprise_no_jit") is not transaction
    ):
        session.execute(text("SET LOCAL jit=off"))
        session.info["enterprise_no_jit"] = (
            session.get_nested_transaction() or session.get_transaction()
        )


def _hash(value):
    return func.encode(func.sha256(func.convert_to(value, "UTF8")), "hex")


def catalog(source_types=None):
    from .schemas import SOURCE_TYPES

    return _catalog(tuple(sorted(set(SOURCE_TYPES if source_types is None else source_types))))


def retrieval_catalog(source_types):
    """New retrieval excludes unavailable/changed knowledge before all counts.

    Fixed citation history keeps its separate signed dependency recheck; a new
    retrieval must not silently reinterpret an old knowledge dependency version.
    """
    if "knowledge" not in source_types:
        return catalog(source_types)
    from .knowledge_sources import retrieval_sources

    return retrieval_sources(
        catalog(source_types).element.cte("enterprise_retrieval_basis"),
        catalog(["artifact"]).element.cte("knowledge_retrieval_artifacts"),
    )


@lru_cache(maxsize=512)
def _catalog(source_types):
    # Cache only immutable SQL syntax. Context, scopes, principals, source rows
    # and RLS results are resolved anew inside each caller's transaction.
    """No SECURITY DEFINER view: all branches execute under the caller's actual RLS."""
    a, o, security = Artifact, UploadedOriginal, OriginalSecurity
    artifact = (
        select(
            literal("artifact").label("source_type"),
            a.id.label("source_id"),
            a.tenant_id,
            a.category_id,
            a.product_id,
            null().cast(UUID).label("project_id"),
            null().cast(UUID).label("proposal_id"),
            a.owner_id,
            a.revision.label("source_revision"),
            a.title,
            a.content_hash,
            a.content.label("body"),
            null().cast(JSONB).label("structured"),
            literal("untrusted").label("nature"),
            (
                (a.visibility != "category")
                | func.coalesce(Product.visibility != "category", False)
                | func.coalesce(o.visibility != "category", False)
            ).label("private"),
            a.original_id.is_not(None).label("customer_original"),
            literal(True, Boolean).label("is_current"),
            a.created_at,
            a.original_id,
            a.id.label("object_id"),
            case(
                (a.original_id.is_not(None), array([a.original_id])), else_=array([], type_=UUID)
            ).label("original_ids"),
            literal("current").label("read_basis_status"),
        )
        .outerjoin(Product, and_(Product.tenant_id == a.tenant_id, Product.id == a.product_id))
        .outerjoin(
            o,
            and_(
                o.tenant_id == a.tenant_id,
                o.id == a.original_id,
                o.category_id == a.category_id,
                o.product_id.is_not_distinct_from(a.product_id),
            ),
        )
        .outerjoin(
            security,
            and_(security.tenant_id == o.tenant_id, security.original_id == o.id),
        )
        .where(
            a.tenant_id == bound_tenant(),
            a.status == "active",
            a.category_id.is_not(None),
            a.product_id.is_(None) | Product.id.is_not(None),
            a.original_id.is_(None)
            | and_(
                o.id.is_not(None),
                o.status == "parsed",
                o.scan_status == "clean",
                security.source_state == "active",
                security.disposition == "active",
                security.current_request_id.is_not(None),
            ),
        )
    )
    k, c = KnowledgeEntry, KnowledgeCurrent
    body = cast(k.content, Text)
    knowledge = (
        select(
            literal("knowledge").label("source_type"),
            k.id.label("source_id"),
            k.tenant_id,
            k.category_id,
            null().cast(UUID).label("product_id"),
            null().cast(UUID).label("project_id"),
            null().cast(UUID).label("proposal_id"),
            k.writer_id.label("owner_id"),
            k.version.label("source_revision"),
            func.coalesce(
                k.content["title"].astext, k.content["name"].astext, literal("品类知识 · ") + k.kind
            ).label("title"),
            _hash(body).label("content_hash"),
            body.label("body"),
            func.jsonb_build_object(
                "kind",
                k.kind,
                "origin",
                k.origin,
                "content",
                k.content,
                "source_refs",
                k.source_refs,
            )
            .cast(JSONB)
            .label("structured"),
            case((k.origin == "imported", "untrusted"), else_="structured").label("nature"),
            literal(False, Boolean).label("private"),
            literal(False, Boolean).label("customer_original"),
            (c.current_entry_id == k.id).label("is_current"),
            k.created_at,
            null().cast(UUID).label("original_id"),
            k.lineage_id.label("object_id"),
            array([], type_=UUID).label("original_ids"),
            literal("current").label("read_basis_status"),
        )
        .join(
            c,
            and_(
                c.tenant_id == k.tenant_id,
                c.category_id == k.category_id,
                c.lineage_id == k.lineage_id,
            ),
        )
        .where(k.tenant_id == bound_tenant(), c.status == "active", k.action != "withdraw")
    )
    from .business_sources import projectors

    selected = set(source_types)
    # Full-family and non-knowledge dependency roots share a long prefix.
    # PostgreSQL truncates identifiers at 63 bytes, so keep each distinct CTE
    # name short even when both relations occur in the same statement.
    suffix = "_" + sha256("|".join(source_types).encode()).hexdigest()[:16]
    branches = []
    if "knowledge" in selected:
        from .schemas import SOURCE_TYPES
        from .verified_knowledge import published_rules

        roots = _catalog(tuple(sorted(set(SOURCE_TYPES) - {"knowledge"})))
        branches.extend(
            (knowledge, published_rules(artifact.cte("published_rule_artifacts" + suffix)))
        )
        if selected - {"knowledge"}:
            branches.append(select(roots).where(roots.c.source_type.in_(selected - {"knowledge"})))
    else:
        if "artifact" in selected:
            branches.append(artifact)
        branches.extend(
            projectors(artifact.cte("enterprise_authoritative_artifacts" + suffix), selected)
        )
    combined = union_all(*branches).cte("authoritative_enterprise_sources" + suffix)
    if "knowledge" not in selected:
        return combined
    from .knowledge_sources import retrieval_sources

    # Fixed proof roots need all actual families, even a knowledge-only query.
    from .schemas import SOURCE_TYPES
    from .verified_knowledge import annotated_sources

    roots = _catalog(tuple(sorted(set(SOURCE_TYPES) - {"knowledge"})))
    legacy = retrieval_sources(
        combined, artifact.cte("verified_legacy_artifacts" + suffix)
    ).element.cte("verified_native_dependency_roots" + suffix)
    # Unannotated legacy knowledge is itself resolved through its actual native refs.
    proof_roots = union_all(
        select(roots), select(legacy).where(legacy.c.source_type == "knowledge")
    ).cte("verified_fixed_roots")
    return annotated_sources(combined, proof_roots)


def select_sources(*, source_type=None, source_id=None, include_body=False, source_types=None):
    sources = catalog([source_type] if source_type else source_types)
    fields = [
        column for column in sources.c if include_body or column.key not in {"body", "structured"}
    ]
    query = select(*fields)
    if source_type is not None:
        query = query.where(sources.c.source_type == source_type)
    if source_id is not None:
        query = query.where(sources.c.source_id == source_id)
    return query


def identity_keys(source_types, identity):
    """Cheap index selectors, never a substitute for the final authority join."""
    from .business_sources import projectors

    selected = set(source_types)
    branches = projectors(None, selected, identity=identity)
    if "knowledge" in selected:
        from pdos_next.domain.knowledge.models import DesignRuleVersion

        branches.append(
            select(
                literal("knowledge").label("source_type"), DesignRuleVersion.id.label("source_id")
            ).where(
                DesignRuleVersion.tenant_id == bound_tenant(),
                DesignRuleVersion.rule_id == identity,
            )
        )
        branches.append(
            select(
                literal("knowledge").label("source_type"), KnowledgeEntry.id.label("source_id")
            ).where(
                KnowledgeEntry.tenant_id == bound_tenant(), KnowledgeEntry.lineage_id == identity
            )
        )
    return union_all(*branches) if branches else None


def dependency_originals(session, source_types, candidates):
    """Possible scan targets, never authority: the final source query stays current."""
    from .models import SearchSource

    keys = candidates.cte("potential_source_keys")
    rows = session.execute(
        select(keys.c.source_type, keys.c.source_id, SearchSource.original_ids)
        .select_from(keys)
        .outerjoin(SearchSource, and_(
            SearchSource.tenant_id == bound_tenant(),
            SearchSource.source_type == keys.c.source_type,
            SearchSource.source_id == keys.c.source_id,
        ))
    ).all()
    possible = {identity for row in rows if row.original_ids is not None
                for identity in row.original_ids}
    missing = [(row.source_type, row.source_id) for row in rows if row.original_ids is None]
    if missing:
        # Old/unindexed metadata uses the existing ordinary-authority discovery.
        # Cached IDs can only widen the scan check, never make a source readable:
        # safe_originals and the final current catalog validate the real root set.
        uncached = select(keys).where(
            tuple_(keys.c.source_type, keys.c.source_id).in_(missing)
        ).cte("uncached_original_source_keys")
        possible.update(_authoritative_originals(session, source_types, uncached))
    return possible


def _authoritative_originals(session, source_types, keys):
    """Original discovery for rows without the derived scan-target hint."""
    from .business_sources import projectors

    artifact = catalog(["artifact"])
    branches = projectors(artifact, set(source_types), dependencies=keys)
    if "artifact" in source_types:
        branches.append(
            select(artifact.c.original_ids).join(
                keys,
                and_(keys.c.source_type == "artifact", keys.c.source_id == artifact.c.source_id),
            )
        )
    if "knowledge" in source_types:
        knowledge = retrieval_catalog(["knowledge"])
        branches.append(
            select(knowledge.c.original_ids).join(
                keys,
                and_(keys.c.source_type == "knowledge", keys.c.source_id == knowledge.c.source_id),
            )
        )
    if not branches:
        return set()
    return {identity for values in session.scalars(union_all(*branches)) for identity in values}
