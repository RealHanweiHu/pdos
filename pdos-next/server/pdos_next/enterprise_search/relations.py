"""One hop over registered domain references, with both ends filtered by authority."""

from sqlalchemy import (
    Integer,
    and_,
    cast,
    column,
    func,
    literal,
    or_,
    select,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.supply_execution.models import SupplySnapshot
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import TestResultActionFact

from .indexing import _locator
from .readable_sources import readable

MAX_RELATED = 20
QUALITY = frozenset({"issue", "capa", "change"})
KINDS = QUALITY | {
    "build",
    "test_run",
    "supply",
    "field_feedback",
    "manufacturing_document",
    "verification_handoff",
}
FIELDS = (
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


def edges(kinds, seeds):
    """Only persisted identity/version references, never matching text or inferred graphs."""
    branches = []

    def edge(origin_kind, origin, target_kind, target, relation, query):
        ids = (
            [identity for kind, identity in seeds if kind == origin_kind]
            if isinstance(seeds, set)
            else select(seeds.c.source_id).where(seeds.c.source_type == origin_kind)
        )
        if isinstance(ids, list) and not ids:
            return
        branches.append(
            query.where(origin.in_(ids)).with_only_columns(
                literal(origin_kind).label("origin_kind"),
                origin.label("origin_id"),
                literal(target_kind).label("target_kind"),
                target.label("target_id"),
                literal(relation).label("relation"),
            )
        )

    q = readable(QualityIssueVersion)
    c = readable(ChangeRequestVersion)
    if {"issue", "capa"} <= kinds:
        paired = select(q).where(q.issue_snapshot["capa"]["id"].astext.is_not(None))
        edge("issue", q.id, "capa", q.id, "issue_capa", paired)
        edge("capa", q.id, "issue", q.id, "capa_issue", paired)
    for kind in sorted(kinds & {"issue", "capa"}) if "change" in kinds else ():
        refs = (
            func.jsonb_array_elements(
                func.coalesce(c.request_snapshot["roots"], literal("[]").cast(JSONB)).op("||")(
                    func.coalesce(c.request_snapshot["references"], literal("[]").cast(JSONB))
                )
            )
            .table_valued(column("value", JSONB))
            .render_derived(name="registered_change_refs_" + kind)
        )
        ref = refs.c.value
        fixed = (
            select(c)
            .select_from(c)
            .join(refs, literal(True))
            .join(
                q,
                and_(
                    q.tenant_id == c.tenant_id,
                    q.category_id == c.category_id,
                    q.product_id == c.product_id,
                    q.project_id == c.project_id,
                    q.issue_id == cast(ref["id"].astext, PGUUID),
                    q.revision == cast(ref["revision"].astext, Integer),
                ),
            )
            .where(ref["kind"].astext == kind)
        )
        if kind == "capa":
            fixed = fixed.where(
                or_(
                    ref["key"].astext.is_(None),
                    ref["key"].astext == q.issue_snapshot["capa"]["id"].astext,
                )
            )
        edge("change", c.id, kind, q.id, "change_" + kind, fixed)
        edge(kind, q.id, "change", c.id, kind + "_change", fixed)
    if "issue" in kinds:
        pointer = readable(QualityIssueCurrent)
        merged = (
            select(q)
            .join(
                pointer,
                and_(
                    pointer.tenant_id == q.tenant_id,
                    pointer.product_id == q.product_id,
                    pointer.project_id == q.project_id,
                    pointer.issue_id == cast(q.issue_snapshot["merged_into"].astext, PGUUID),
                ),
            )
            .where(q.issue_snapshot["merged_into"].astext.is_not(None))
        )
        edge("issue", q.id, "issue", pointer.issue_version_id, "merged_into", merged)
        edge("issue", pointer.issue_version_id, "issue", q.id, "merged_from", merged)
    if "build" in kinds:
        from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
        from pdos_next.domain.build_start.models import BuildStart
        from pdos_next.domain.builds.models import Build

        build = readable(Build)
        for kind, models in (
            ("build", (BuildStart, ActualConfiguration, BuildLot)),
            ("supply", (SupplySnapshot,)),
            ("test_run", (VerificationRunVersion, TestResultActionFact)),
        ):
            if kind not in kinds:
                continue
            for model in models:
                row = readable(model)
                fixed = select(row).join(
                    build,
                    and_(
                        build.tenant_id == row.tenant_id,
                        build.product_id == row.product_id,
                        build.project_id == row.project_id,
                        build.id == row.build_id,
                    ),
                )
                edge(kind, row.id, "build", build.id, kind + "_build", fixed)
                edge("build", build.id, kind, row.id, "build_" + kind, fixed)
    from .field_feedback_relations import append_edges

    append_edges(edge, kinds)
    from .role_native_relations import append_edges as append_role_edges

    append_role_edges(edge, kinds)
    return union_all(*branches).cte("registered_enterprise_edges") if branches else None


def graph_for(available, potential):
    kinds = set(available) & KINDS
    return edges(kinds, potential) if kinds else None


def related_page(graph, authority, roots, safe, *, include_history, limit):
    """Both endpoints come from the same final authoritative read snapshot."""
    target = authority.alias("related_target")
    query = (
        select(
            *[target.c[key] for key in FIELDS],
            target.c.original_ids,
            func.length(target.c.body).label("body_chars"),
            graph.c.origin_kind,
            graph.c.origin_id,
            graph.c.relation,
            roots.c.origin_order,
            tuple_(target.c.source_type, target.c.source_id)
            .in_(select(roots.c.source_type, roots.c.source_id))
            .label("direct_target"),
        )
        .select_from(graph)
        .join(
            roots,
            and_(
                roots.c.source_type == graph.c.origin_kind,
                roots.c.source_id == graph.c.origin_id,
            ),
        )
        .join(
            target,
            and_(
                target.c.source_type == graph.c.target_kind,
                target.c.source_id == graph.c.target_id,
                target.c.category_id == roots.c.category_id,
            ),
        )
        .where(target.c.original_ids.bool_op("<@")(array(sorted(safe), type_=PGUUID)))
    )
    if not include_history:
        query = query.where(target.c.source_type.in_(["issue", "capa"]) | target.c.is_current)
    candidates = query.cte("readable_related_candidates")
    eligible = select(
        candidates,
        func.row_number()
        .over(
            partition_by=(candidates.c.source_type, candidates.c.source_id),
            order_by=(candidates.c.origin_order, candidates.c.relation),
        )
        .label("related_rank"),
    ).cte("deduplicated_related_candidates")
    ordering = (
        eligible.c.origin_order,
        eligible.c.is_current.desc(),
        eligible.c.source_revision.desc(),
        eligible.c.source_type,
        eligible.c.source_id,
        eligible.c.relation,
    )
    return union_all(
        select(eligible)
        .where(eligible.c.related_rank == 1, eligible.c.direct_target)
        .order_by(*ordering)
        .limit(limit),
        select(eligible)
        .where(eligible.c.related_rank == 1, ~eligible.c.direct_target)
        .order_by(*ordering)
        .limit(MAX_RELATED + 1),
    ).cte("related_page")


def decorate(result, rows):
    direct = result["items"]
    seeds = {(row["source_type"], row["source_id"]) for row in direct}
    selected = [row for row in rows if not row["direct_target"]]
    origins = {(row["source_type"], row["source_id"]): row for row in direct}
    privacy = {key: (row["private"], row["customer_original"]) for key, row in origins.items()}

    def inherited_flags(row, item):
        private, customer = privacy[(row["origin_kind"], row["origin_id"])]
        item["private"] |= private
        item["customer_original"] |= customer

    def relation(row):
        origin = origins[(row["origin_kind"], row["origin_id"])]
        return {
            "type": row["relation"],
            "source_type": row["origin_kind"],
            "source_id": row["origin_id"],
            "source_revision": origin["source_revision"],
            "content_hash": origin["content_hash"],
        }

    for row in rows:
        if row["direct_target"]:
            item = origins[(row["source_type"], row["source_id"])]
            item["relation"] = relation(row)
            inherited_flags(row, item)
    groups = {key: [] for key in seeds}
    for row in selected[:MAX_RELATED]:
        item = {key: row[key] for key in FIELDS}
        item.update(
            chunk_id=None,
            locator={**_locator(0, row["body_chars"], 1, 1, None), "json_pointer": "/facts"},
            channel="relation",
            rank=0,
            relation=relation(row),
        )
        inherited_flags(row, item)
        groups[(row["origin_kind"], row["origin_id"])].append(item)
    items = []
    for row in direct:
        items.append(row)
        items.extend(groups[(row["source_type"], row["source_id"])])
    for index, row in enumerate(items, 1):
        row["rank"] = index
    return {
        **result,
        "items": items,
        "returned": len(items),
        "direct_returned": len(direct),
        "related_returned": len(items) - len(direct),
        "related_truncated": len(selected) > MAX_RELATED,
    }
