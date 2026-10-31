"""Published native rules and fixed answer dependencies under ordinary caller RLS."""

from sqlalchemy import (
    Integer,
    Text,
    and_,
    case,
    cast,
    column,
    func,
    literal,
    null,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, array

from pdos_next.domain.knowledge.assistant_models import KnowledgeAnswerReview
from pdos_next.domain.knowledge.models import DesignRuleCurrent, DesignRuleVersion
from pdos_next.domain.projects.models import Project
from pdos_next.models import Product


def published_rules(artifacts):
    from .sources import bound_tenant

    row, pointer = DesignRuleVersion, DesignRuleCurrent
    body = cast(row.body, Text)
    refs = (
        func.jsonb_array_elements(row.source_basis["artifacts"])
        .table_valued(column("value", JSONB))
        .render_derived(name="published_rule_dependencies")
    )
    fixed = refs.c.value
    matched = and_(
        artifacts.c.tenant_id == row.tenant_id,
        artifacts.c.category_id == row.category_id,
        cast(artifacts.c.source_id, Text) == fixed["id"].astext,
        cast(artifacts.c.source_revision, Text) == fixed["revision"].astext,
        artifacts.c.content_hash == fixed["hash"].astext,
    )
    facts = (
        select(
            func.coalesce(func.bool_and(artifacts.c.source_id.is_not(None)), True).label(
                "readable"
            ),
            func.coalesce(func.bool_or(artifacts.c.private), False).label("private"),
            func.coalesce(func.bool_or(artifacts.c.customer_original), False).label(
                "customer_original"
            ),
            func.coalesce(
                func.array_agg(artifacts.c.original_id.distinct()).filter(
                    artifacts.c.original_id.is_not(None)
                ),
                array([], type_=UUID),
            ).label("original_ids"),
            func.coalesce(
                func.jsonb_agg(
                    func.jsonb_build_object(
                        "type", "artifact", "id", fixed["id"], "version", fixed["revision"]
                    )
                ),
                func.jsonb_build_array(),
            ).label("source_refs"),
        )
        .select_from(refs)
        .outerjoin(artifacts, matched)
        .correlate(row)
        .lateral("published_rule_authority")
    )
    return (
        select(
            literal("knowledge").label("source_type"),
            row.id.label("source_id"),
            row.tenant_id,
            row.category_id,
            row.product_id,
            row.project_id,
            null().cast(UUID).label("proposal_id"),
            row.owner_id,
            row.revision.label("source_revision"),
            row.body["title"].astext.label("title"),
            func.encode(func.sha256(func.convert_to(body, "UTF8")), "hex").label("content_hash"),
            body.label("body"),
            func.jsonb_build_object(
                "kind",
                "published_rule",
                "content",
                row.body,
                "source_refs",
                facts.c.source_refs,
                "valid_from",
                row.valid_from,
                "valid_until",
                row.valid_until,
            )
            .cast(JSONB)
            .label("structured"),
            literal("structured").label("nature"),
            (
                (row.visibility != "category")
                | (Product.visibility != "category")
                | (Project.visibility != "category")
                | facts.c.private
            ).label("private"),
            facts.c.customer_original.label("customer_original"),
            (pointer.version_id == row.id).label("is_current"),
            row.created_at,
            null().cast(UUID).label("original_id"),
            row.rule_id.label("object_id"),
            facts.c.original_ids.label("original_ids"),
            literal("current").label("read_basis_status"),
        )
        .join(pointer, and_(pointer.tenant_id == row.tenant_id, pointer.rule_id == row.rule_id))
        .join(Product, and_(Product.tenant_id == row.tenant_id, Product.id == row.product_id))
        .join(Project, and_(Project.tenant_id == row.tenant_id, Project.id == row.project_id))
        .join(facts, literal(True))
        .where(row.tenant_id == bound_tenant(), facts.c.readable)
    )


def annotated_sources(sources, roots):
    """All fixed source checks run before query counts, paging and relation expansion.

    Proofs are flattened when saving. Native deidentification retains its private
    PromotionProof; its shared projection deliberately carries no private IDs.
    """
    review = KnowledgeAnswerReview.__table__.alias("enterprise_knowledge_review")
    refs = (
        func.jsonb_array_elements(func.coalesce(review.c.source_proof, literal("[]").cast(JSONB)))
        .table_valued(column("value", JSONB))
        .render_derived(name="verified_answer_refs")
    )
    value = refs.c.value
    identity = cast(
        case(
            (
                value["source_id"].astext.op("~*")(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                ),
                value["source_id"].astext,
            ),
            else_=None,
        ),
        UUID,
    )
    revision = cast(
        case(
            (
                value["source_revision"].astext.op("~")("^[1-9][0-9]*$"),
                value["source_revision"].astext,
            ),
            else_=None,
        ),
        Integer,
    )
    matched = and_(
        roots.c.tenant_id == sources.c.tenant_id,
        roots.c.category_id == sources.c.category_id,
        roots.c.source_type == value["source_type"].astext,
        roots.c.source_id == identity,
        roots.c.source_revision == revision,
        roots.c.content_hash == value["content_hash"].astext,
    )
    facts = (
        select(
            func.coalesce(func.bool_and(roots.c.source_id.is_not(None)), True).label("readable"),
            func.coalesce(func.bool_or(roots.c.private), False).label("private"),
            func.coalesce(func.bool_or(roots.c.customer_original), False).label(
                "customer_original"
            ),
        )
        .select_from(refs)
        .outerjoin(roots, matched)
        .correlate(sources, review)
        .lateral("verified_answer_authority")
    )
    original = (
        func.unnest(roots.c.original_ids)
        .table_valued("original_id")
        .render_derived(name="verified_answer_originals")
    )
    originals = (
        select(
            func.coalesce(func.array_agg(original.c.original_id.distinct()), array([], type_=UUID))
        )
        .select_from(refs)
        .join(roots, matched)
        .join(original, literal(True))
        .correlate(sources, review)
        .scalar_subquery()
    )
    overdue = review.c.review_due_at <= func.transaction_timestamp()
    state = case(
        (overdue, "needs_review"), (review.c.verified_by.is_not(None), "verified"), else_="draft"
    )
    metadata = func.jsonb_build_object(
        "state",
        state,
        "label",
        case((overdue, "待复核"), (review.c.verified_by.is_not(None), "已核实"), else_="AI 草稿"),
        "review_due_at",
        review.c.review_due_at,
        "applicability_scope",
        review.c.applicability_scope,
        "responsible_id",
        review.c.responsible_id,
    )
    replacement = {
        "structured": case(
            (
                review.c.id.is_not(None),
                sources.c.structured.op("||")(
                    func.jsonb_build_object("knowledge_review", metadata)
                ),
            ),
            else_=sources.c.structured,
        ),
        "private": sources.c.private | facts.c.private,
        "customer_original": sources.c.customer_original | facts.c.customer_original,
        "original_ids": sources.c.original_ids.op("||")(originals),
    }
    return (
        select(*(replacement.get(field.key, field).label(field.key) for field in sources.c))
        .select_from(sources)
        .outerjoin(
            review,
            and_(
                sources.c.source_type == "knowledge",
                review.c.tenant_id == sources.c.tenant_id,
                review.c.subject_kind.in_(["category", "rule"]),
                review.c.subject_id == sources.c.source_id,
            ),
        )
        .join(facts, literal(True))
        .where(or_(review.c.id.is_(None), facts.c.readable))
        .cte("reviewed_enterprise_sources")
    )


def priority(structured, source_type=None):
    """Current business facts precede reviewed knowledge, then ordinary originals.

    This orders retrieval evidence. It does not establish applicability to a
    new task or replace the native rule's fixed applicability assessment.
    """
    state = structured["knowledge_review"]["state"].astext
    return case(
        (source_type.not_in(["artifact", "knowledge"]), 2)
        if source_type is not None
        else (literal(False), 2),
        (state == "needs_review", -1),
        (state == "verified", 1),
        else_=0,
    )
