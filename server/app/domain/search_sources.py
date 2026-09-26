"""Permission predicates and bounded source projections for unified search."""

from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    String,
    Uuid,
    and_,
    case,
    cast,
    column,
    false,
    func,
    literal,
    or_,
    select,
    table,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables

KIND_ACTIONS = {
    "project": Action.PROJECT_VIEW,
    "issue": Action.WORK_ITEM_VIEW,
    "task": Action.WORK_ITEM_VIEW,
    "risk": Action.WORK_ITEM_VIEW,
    "requirement": Action.REQUIREMENT_VIEW,
    "specification": Action.PRODUCT_ENGINEERING_VIEW,
    "decision": Action.WORK_ITEM_VIEW,
    "document": Action.DOCUMENT_ANALYZE,
    "attachment": Action.DOCUMENT_ANALYZE,
    "memory": Action.MEMORY_VIEW,
    "sample": Action.QUALITY_VIEW,
}


def contains(value: Any, term: str) -> Any:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.lower(func.coalesce(value, "")).like("%" + escaped + "%", escape="\\")


def relevance(title: Any, body: Any, terms: list[str]) -> Any:
    score: Any = literal(0)
    for term in terms:
        score = score + case((contains(title, term), 3), else_=0)
        score = score + case((contains(body, term), 1), else_=0)
    if terms:
        score = score + case((func.lower(title) == " ".join(terms), 6), else_=0)
    return score


def project_scope(project: Any, tenant: UUID, user: UUID, role: str) -> ColumnElement[bool]:
    if role in {Role.OWNER, Role.ADMIN}:
        return true()
    m, d = tables.project_members, tables.user_delegations
    delegated = select(d.c.principal_user_id).where(
        d.c.tenant_id == tenant,
        d.c.delegate_user_id == user,
        d.c.revoked_at.is_(None),
        d.c.starts_at <= func.clock_timestamp(),
        d.c.ends_at > func.clock_timestamp(),
    )
    return (
        select(m.c.id)
        .where(
            m.c.tenant_id == tenant,
            m.c.project_id == project,
            or_(m.c.user_id == user, m.c.user_id.in_(delegated)),
        )
        .exists()
    )


def statement(
    kind: str,
    *,
    tenant: UUID,
    user: UUID,
    role: str,
    terms: list[str],
    project_id: UUID | None = None,
    fragment: int | None = None,
) -> Select[Any]:
    """One row per object; documents match all fragments but return one bounded fragment."""
    source = {
        "project": tables.projects,
        "issue": tables.issues,
        "task": tables.tasks,
        "risk": tables.risks,
        "requirement": tables.requirements,
        "specification": tables.specifications,
        "decision": tables.decisions,
        "document": tables.documents,
        "attachment": tables.conversation_attachments,
        "memory": tables.memories,
        "sample": tables.samples,
    }[kind]
    scoped = kind != "requirement"
    project = (
        source.c.id
        if kind == "project"
        else source.c.project_id
        if scoped
        else cast(literal(None), Uuid)
    )
    title: Any = (
        source.c.filename
        if kind in {"document", "attachment"}
        else source.c.serial_number
        if kind == "sample"
        else source.c.name
        if kind == "project"
        else source.c.title
    )
    if "code" in source.c:
        title = func.concat_ws(" · ", source.c.code, title)
    body: Any = literal("")
    at: Any = source.c.updated_at if "updated_at" in source.c else source.c.created_at
    locator: Any = cast(literal(None), String)
    ordinal: Any = cast(literal(None), Integer)
    count: Any = literal(0)
    conversation: Any = cast(literal(None), Uuid)
    status: Any = source.c.status if "status" in source.c else literal(None, String)
    where: list[Any] = [source.c.tenant_id == tenant]
    where.append(true() if is_allowed(Role(role), KIND_ACTIONS[kind]) else false())
    if scoped:
        where.append(project_scope(project, tenant, user, role))
        if project_id is not None:
            where.append(project == project_id)
    elif project_id is not None:
        where.append(false())
    joined: Any = source
    if kind in {"document", "attachment"}:
        if kind == "document":
            f = tables.document_fragments
            fragments = (
                select(
                    f.c.text.label("text"),
                    f.c.locator.label("locator"),
                    f.c.ordinal.label("ordinal"),
                )
                .where(
                    f.c.tenant_id == tenant,
                    f.c.project_id == project,
                    f.c.document_id == source.c.id,
                )
                .correlate(source)
            )
            status = source.c.extraction_status
            count = source.c.fragment_count
        else:
            conversation = source.c.conversation_id
            c = tables.conversations
            where.extend(
                [
                    source.c.revoked_at.is_(None),
                    select(c.c.id)
                    .where(
                        c.c.tenant_id == tenant,
                        c.c.id == source.c.conversation_id,
                        c.c.project_id == project,
                        c.c.created_by_user_id == user,
                    )
                    .exists(),
                ]
            )
            elements = (
                func.jsonb_array_elements(source.c.fragments).table_valued("value").alias("parts")
            )
            value = cast(elements.c.value, JSONB)
            fragments = (
                select(
                    value["text"].astext.label("text"),
                    value["locator"].astext.label("locator"),
                    cast(value["ordinal"].astext, Integer).label("ordinal"),
                )
                .select_from(elements)
                .correlate(source)
            )
            count = func.jsonb_array_length(source.c.fragments)
        parts = fragments.subquery("source_parts")
        for term in terms:
            where.append(
                or_(
                    contains(title, term),
                    select(parts.c.ordinal).where(contains(parts.c.text, term)).exists(),
                )
            )
        selected = select(parts)
        if fragment is not None:
            selected = selected.where(parts.c.ordinal == fragment)
        chosen = (
            selected.order_by(relevance(literal(""), parts.c.text, terms).desc(), parts.c.ordinal)
            .limit(1)
            .lateral("selected_fragment")
        )
        joined = source.outerjoin(chosen, true())
        body, locator, ordinal = chosen.c.text, chosen.c.locator, chosen.c.ordinal
        if fragment is not None:
            where.append(or_(chosen.c.ordinal.is_not(None), count == 0))
    else:
        if kind == "specification":
            body = cast(source.c.content, String)
        elif kind == "decision":
            body = func.concat_ws("\n", source.c.rationale, source.c.context, source.c.outcome)
        elif kind == "memory":
            body = func.concat_ws(
                "\n", source.c.content, source.c.applicability, cast(source.c.tags, String)
            )
            assessment = table(
                "memory_source_assessments",
                column("tenant_id", Uuid),
                column("memory_id", Uuid),
                column("state", String),
                schema="cehub_memory",
            )
            where.extend(
                [
                    source.c.status == "verified",
                    select(assessment.c.memory_id)
                    .where(
                        assessment.c.tenant_id == tenant,
                        assessment.c.memory_id == source.c.id,
                        assessment.c.state.in_(("current", "manual")),
                    )
                    .exists(),
                ]
            )
        elif kind == "sample":
            body = func.concat_ws(
                "\n",
                source.c.serial_number,
                source.c.notes,
            )
        else:
            fields = {
                "project": ("description",),
                "requirement": ("description", "acceptance_criteria"),
                "task": ("description", "expected_output", "completion_evidence_ref"),
                "issue": ("description", "root_cause", "resolution", "closure_criteria"),
                "risk": ("description", "mitigation_plan", "contingency_plan"),
            }[kind]
            body = func.concat_ws(
                "\n", *(cast(source.c[name], String) for name in fields if name in source.c)
            )
        for term in terms:
            where.append(or_(contains(title, term), contains(body, term)))
    project_name: Any = cast(literal(None), String)
    if scoped:
        p = tables.projects.alias("source_project")
        joined = joined.join(p, (p.c.tenant_id == tenant) & (p.c.id == project))
        project_name = p.c.name
    return (
        select(
            literal(kind).label("kind"),
            source.c.id.label("id"),
            project.label("project_id"),
            project_name.label("project_name"),
            title.label("title"),
            func.coalesce(body, "").label("body"),
            relevance(title, body, terms).label("score"),
            at.label("occurred_at"),
            status.label("status"),
            locator.label("locator"),
            ordinal.label("fragment_ordinal"),
            count.label("fragment_count"),
            conversation.label("conversation_id"),
        )
        .select_from(joined)
        .where(and_(*where))
    )


def excerpt(body: Any, terms: list[str], width: int = 180) -> Any:
    positions = [func.nullif(func.strpos(func.lower(body), term), 0) for term in terms]
    start = (
        func.greatest(1, func.coalesce(func.least(*positions), 1) - 45) if positions else literal(1)
    )
    return func.substring(body, start, width)
