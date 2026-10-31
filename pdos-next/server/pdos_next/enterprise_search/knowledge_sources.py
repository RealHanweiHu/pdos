"""Current knowledge dependency authority inside the retrieval SQL, before paging."""

from sqlalchemy import Text, and_, case, cast, column, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB, UUID, array

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.models import Claim


def retrieval_sources(sources, artifacts):
    # Ordinary caller RLS applies to all joins. JSON identities are checked before
    # casting, so malformed persisted metadata cannot fail open or abort a read.
    refs = func.jsonb_array_elements(case(
        (and_(sources.c.source_type == "knowledge",
              func.jsonb_typeof(sources.c.structured["source_refs"]) == "array"),
         sources.c.structured["source_refs"]),
        else_=literal("[]").cast(JSONB),
    )).table_valued(column("value", JSONB)).render_derived(name="knowledge_dependency_refs")
    ref = refs.c.value
    kind, version = ref["type"].astext, ref["version"].astext
    identity = cast(case(
        (ref["id"].astext.op("~*")(
            "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
         ref["id"].astext),
        else_=None,
    ), UUID)
    claim = Claim.__table__.alias("knowledge_dependency_claims")
    snapshot = PublicWebSnapshot.__table__.alias("knowledge_dependency_snapshots")
    root_kind = case((kind == "claim", claim.c.source_kind),
                     (kind == "original", "artifact"), else_=kind)
    root_id = case((kind == "claim", case(
        (claim.c.source_kind == "artifact", claim.c.artifact_id), else_=claim.c.snapshot_id)),
        else_=identity)
    root_version = case((kind == "claim", cast(claim.c.source_revision, Text)), else_=version)
    root = artifacts.c
    correct_version = and_(func.jsonb_typeof(ref["version"]) == "number",
                           version.op("~")("^[1-9][0-9]*$"))
    readable_root = or_(
        and_(root_kind == "artifact", root.source_id.is_not(None)),
        and_(root_kind == "snapshot", snapshot.c.id.is_not(None), root_version == "1"),
    )
    readable = case(
        (kind.in_(["human", "parameter"]), True),
        (kind == "claim", and_(correct_version, claim.c.id.is_not(None), readable_root)),
        (kind.in_(["artifact", "original", "snapshot"]), and_(correct_version, readable_root)),
        else_=False,
    )
    facts = (
        select(
            func.coalesce(func.bool_and(func.coalesce(readable, False)), True).label("readable"),
            func.coalesce(func.bool_or(and_(
                root_kind == "artifact", cast(root.source_revision, Text) != root_version,
            )), False).label("changed"),
            func.coalesce(func.bool_or(or_(
                root.private, snapshot.c.visibility != "category",
                claim.c.privacy == "private", claim.c.visibility != "category",
            )), False).label("private"),
            func.coalesce(func.bool_or(root.customer_original), False).label("customer_original"),
            func.coalesce(func.array_agg(root.original_id.distinct()).filter(
                root.original_id.is_not(None)), array([], type_=UUID)).label("original_ids"),
        )
        .select_from(refs)
        .outerjoin(claim, and_(
            kind == "claim", claim.c.id == identity,
            claim.c.tenant_id == sources.c.tenant_id,
            claim.c.category_id == sources.c.category_id,
            claim.c.status == "active", cast(claim.c.revision, Text) == version,
        ))
        .outerjoin(artifacts, and_(
            root_kind == "artifact", root.source_id == root_id,
            root.tenant_id == sources.c.tenant_id, root.category_id == sources.c.category_id,
        ))
        .outerjoin(snapshot, and_(
            root_kind == "snapshot", snapshot.c.id == root_id,
            snapshot.c.tenant_id == sources.c.tenant_id,
            snapshot.c.category_id == sources.c.category_id,
            snapshot.c.status.in_(["ok", "partial"]),
        ))
        .correlate(sources)
        .lateral("knowledge_current_dependency_authority")
    )
    replacement = {
        "private": sources.c.private | facts.c.private,
        "customer_original": sources.c.customer_original | facts.c.customer_original,
        "original_ids": sources.c.original_ids.op("||")(facts.c.original_ids),
    }
    return (
        select(*(replacement.get(field.key, field).label(field.key) for field in sources.c))
        .select_from(sources)
        .join(facts, literal(True))
        .where(or_(sources.c.source_type != "knowledge", and_(
            func.jsonb_typeof(sources.c.structured["source_refs"]) == "array",
            facts.c.readable, ~facts.c.changed,
        )))
        .cte("retrieval_authoritative_enterprise_sources")
    )
