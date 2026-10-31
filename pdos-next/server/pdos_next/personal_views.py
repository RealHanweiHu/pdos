"""Personal cross-category projections under the caller's ordinary RR/RLS scope."""

from collections import defaultdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Query
from pydantic import Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import load_only

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import require_context, tenant_session
from pdos_next.domain.preproject.models import ProjectOpenItem, Proposal
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource
from pdos_next.domain.projects.models import (
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, Principal, Product
from pdos_next.original_security import source_status
from pdos_next.project_work_summaries import latest as latest_work_updates
from pdos_next.domain.project_governance.projection import summary as governance_summary
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context


def _personal(session, ctx):
    require_context(session, ctx)
    if ctx.category_id is not None or ctx.actor_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "个人视图须使用本人会话。", 403)


def _page(
    session, ctx, model, *, cursor, page_size, extra=(), identity=None, fields=(), anchor_extra=None
):
    query = select(model).where(model.tenant_id == ctx.tenant_id, *extra)
    if fields:
        query = query.options(
            load_only(model.id, model.tenant_id, *(getattr(model, field) for field in fields))
        )
    if identity is not None:
        return list(session.scalars(query.where(model.id == identity))), None
    if cursor:
        anchor = session.scalar(
            select(model)
            .options(load_only(model.id, model.created_at))
            .where(
                model.tenant_id == ctx.tenant_id,
                model.id == cursor,
                *(extra if anchor_extra is None else anchor_extra),
            )
        )
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "分页位置已不可读，请刷新列表。", 403)
        query = query.where(
            or_(
                model.created_at < anchor.created_at,
                and_(model.created_at == anchor.created_at, model.id < anchor.id),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(model.created_at.desc(), model.id.desc()).limit(page_size + 1)
        )
    )
    return rows[:page_size], str(rows[page_size - 1].id) if len(rows) > page_size else None


def _heads(session, ctx, model, identities, fields):
    if not identities:
        return {}
    return {
        row.id: row
        for row in session.scalars(
            select(model)
            .where(
                model.tenant_id == ctx.tenant_id,
                model.id.in_(identities),
            )
            .options(load_only(model.id, model.tenant_id, *(getattr(model, f) for f in fields)))
        )
    }


def projects(session, ctx, *, cursor=None, page_size=50, project_id=None):
    _personal(session, ctx)
    rows, next_cursor = _page(
        session,
        ctx,
        Project,
        cursor=cursor,
        page_size=page_size,
        identity=project_id,
        fields=(
            "category_id",
            "product_id",
            "owner_id",
            "name",
            "purpose",
            "scope",
            "visibility",
            "status",
            "revision",
            "current_plan_id",
            "g0_decision_id",
            "created_at",
        ),
    )
    categories = _heads(
        session, ctx, Category, {row.category_id for row in rows}, ("name", "purpose")
    )
    products = _heads(
        session, ctx, Product, {row.product_id for row in rows}, ("category_id", "name", "purpose")
    )
    project_ids = {row.id for row in rows}
    links = (
        list(
            session.scalars(
                select(ProjectProductLink).where(
                    ProjectProductLink.tenant_id == ctx.tenant_id,
                    ProjectProductLink.project_id.in_(project_ids),
                )
            )
        )
        if project_ids
        else []
    )
    definitions = _heads(
        session,
        ctx,
        DefinitionRevision,
        {link.definition_id for link in links},
        ("category_id", "product_id", "revision", "title", "status", "g0_decision_id"),
    )
    sources = (
        list(
            session.scalars(
                select(DefinitionSource)
                .where(
                    DefinitionSource.tenant_id == ctx.tenant_id,
                    DefinitionSource.definition_id.in_(definitions),
                )
                .options(
                    load_only(
                        DefinitionSource.id,
                        DefinitionSource.definition_id,
                        DefinitionSource.artifact_id,
                        DefinitionSource.source_revision,
                    )
                )
            )
        )
        if definitions
        else []
    )
    artifacts = _heads(
        session,
        ctx,
        Artifact,
        {source.artifact_id for source in sources},
        (
            "category_id",
            "product_id",
            "original_id",
            "revision",
            "status",
            "owner_id",
            "visibility",
        ),
    )
    source_states = {identity: source_status(session, row) for identity, row in artifacts.items()}
    by_definition = defaultdict(list)
    for source in sources:
        by_definition[source.definition_id].append(source)
    by_project = defaultdict(list)
    for link in links:
        by_project[link.project_id].append(link)
    plans = (
        {
            row.id: row
            for row in session.execute(
                select(
                    PlanRevision.id,
                    PlanRevision.project_id,
                    PlanRevision.product_id,
                    PlanRevision.revision,
                    PlanRevision.status,
                    PlanRevision.forecast["earliest_finish"].astext.label("earliest_finish"),
                    PlanRevision.forecast["latest_finish"].astext.label("latest_finish"),
                ).where(
                    PlanRevision.tenant_id == ctx.tenant_id,
                    PlanRevision.id.in_(
                        {row.current_plan_id for row in rows if row.current_plan_id}
                    ),
                )
            )
        }
        if any(row.current_plan_id for row in rows)
        else {}
    )
    packages = defaultdict(list)
    tasks = {}
    if plans:
        for package in session.execute(
            select(
                ProjectWorkPackage.plan_id,
                ProjectWorkPackage.id,
                ProjectWorkPackage.discipline,
            ).where(
                ProjectWorkPackage.tenant_id == ctx.tenant_id, ProjectWorkPackage.plan_id.in_(plans)
            )
        ):
            packages[package.plan_id].append(
                {"id": str(package.id), "discipline": package.discipline}
            )
        tasks = dict(
            session.execute(
                select(ProjectTask.plan_id, func.count(ProjectTask.id))
                .where(ProjectTask.tenant_id == ctx.tenant_id, ProjectTask.plan_id.in_(plans))
                .group_by(ProjectTask.plan_id)
            ).all()
        )
    open_items = defaultdict(list)
    if project_ids:
        for item in session.execute(
            select(
                ProjectOpenItem.id,
                ProjectOpenItem.project_id,
                ProjectOpenItem.kind,
                ProjectOpenItem.title,
                ProjectOpenItem.owner_id,
                ProjectOpenItem.due_date,
                ProjectOpenItem.status,
            )
            .where(
                ProjectOpenItem.tenant_id == ctx.tenant_id,
                ProjectOpenItem.project_id.in_(project_ids),
            )
            .order_by(ProjectOpenItem.due_date, ProjectOpenItem.id)
        ):
            open_items[item.project_id].append(
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "title": item.title,
                    "owner_id": str(item.owner_id),
                    "due_date": item.due_date.isoformat(),
                    "status": item.status,
                }
            )
    people = _heads(
        session,
        ctx,
        Principal,
        {row.owner_id for row in rows}
        | {UUID(item["owner_id"]) for items in open_items.values() for item in items},
        ("name",),
    )
    for items in open_items.values():
        for item in items:
            person = people.get(UUID(item["owner_id"]))
            item["owner_name"] = person.name if person else None
    updates = latest_work_updates(session, ctx, rows)
    entries, unavailable = [], 0
    for row in rows:
        product, category = products.get(row.product_id), categories.get(row.category_id)
        # The G0 root remains the project's fixed definition even if later links
        # associate another model or variant. No proposal body is needed here.
        fixed = [
            (link, definitions[link.definition_id])
            for link in by_project[row.id]
            if link.definition_id in definitions
            and link.product_id == row.product_id
            and definitions[link.definition_id].g0_decision_id == row.g0_decision_id
        ]
        if not product or not category or product.category_id != row.category_id or len(fixed) != 1:
            unavailable += 1
            continue
        link, definition = fixed[0]
        refs = by_definition[definition.id]
        if (
            definition.category_id != row.category_id
            or definition.product_id != row.product_id
            or (definition.revision != link.definition_revision)
            or any(source.artifact_id not in artifacts for source in refs)
        ):
            unavailable += 1
            continue
        current = all(
            source_states[source.artifact_id] == "active"
            and artifacts[source.artifact_id].revision == source.source_revision
            for source in refs
        )
        state = "current" if current else "needs_recheck"
        plan = plans.get(row.current_plan_id)
        if plan and (plan.project_id != row.id or plan.product_id != row.product_id):
            plan = None
        entries.append(
            {
                "category": {
                    "id": str(category.id),
                    "name": category.name,
                    "purpose": category.purpose,
                },
                "product": {
                    "id": str(product.id),
                    "name": product.name,
                    "purpose": product.purpose,
                },
                "project": {
                    "id": str(row.id),
                    "name": row.name,
                    "purpose": row.purpose,
                    "scope": row.scope,
                    "owner_id": str(row.owner_id),
                    "owner_name": people[row.owner_id].name if row.owner_id in people else None,
                    "visibility": row.visibility,
                    "revision": row.revision,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                    "latest_status_update": updates.get(row.id),
                    "governance": governance_summary(session, ctx, row),
                    "source_status": state,
                    "definition": {
                        "id": str(definition.id),
                        "title": definition.title,
                        "revision": definition.revision,
                        "status": definition.status,
                        "source_status": state,
                    },
                    "plan": {
                        "id": str(plan.id),
                        "revision": plan.revision,
                        "status": plan.status,
                        "forecast": {
                            "earliest_finish": plan.earliest_finish,
                            "latest_finish": plan.latest_finish,
                        },
                    }
                    if plan
                    else None,
                    "plan_state": "available"
                    if plan
                    else "unavailable"
                    if row.current_plan_id
                    else "not_created",
                    "work_packages": packages[row.current_plan_id] if plan else [],
                    "task_count": tasks.get(row.current_plan_id, 0) if plan else None,
                },
                "openItems": open_items[row.id],
                "openItemsError": "",
            }
        )
    if project_id is not None and not entries:
        raise DomainError("NOT_FOUND", "此项目当前不可见或来源权限需要重核。", 404)
    return {
        "items": entries,
        "next_cursor": next_cursor,
        "unavailable_count": unavailable,
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
    }


def run_activity(session, ctx, *, cursor=None, page_size=50, waiting=False):
    _personal(session, ctx)
    filters = [
        AgentRun.requester_id == ctx.requester_id,
        or_(AgentRun.proposal_id.is_(None), AgentRun.proposal_id.in_(select(Proposal.id))),
    ]
    anchor_scope = tuple(filters)
    if waiting:
        filters.append(AgentRun.state == "waiting_input")
    rows, next_cursor = _page(
        session,
        ctx,
        AgentRun,
        cursor=cursor,
        page_size=page_size,
        extra=filters,
        anchor_extra=anchor_scope,
        fields=(
            "requester_id",
            "category_id",
            "product_id",
            "proposal_id",
            "goal",
            "state",
            "cancel_epoch",
            "created_at",
        ),
    )
    categories = _heads(
        session, ctx, Category, {row.category_id for row in rows if row.category_id}, ("name",)
    )
    return {
        "items": [
            {
                "run_id": str(row.id),
                "goal": row.goal,
                "status": row.state,
                "reading_token": f"{row.state}:{row.cancel_epoch}",
                "created_at": row.created_at.isoformat(),
                "product_id": str(row.product_id) if row.product_id else None,
                "scope": "category" if row.category_id else "personal",
                "categoryId": str(row.category_id) if row.category_id else "",
                "categoryName": categories[row.category_id].name if row.category_id else "个人",
            }
            for row in rows
            if row.category_id is None or row.category_id in categories
        ],
        "next_cursor": next_cursor,
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
    }


class ProjectPage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=50, ge=1, le=200)


class ActivityPage(ProjectPage):
    waiting: bool = False


class G0ReviewPage(ProjectPage):
    page_size: int = Field(default=50, ge=1, le=100)


class TestStartPromisePage(ProjectPage):
    page_size: int = Field(default=20, ge=1, le=100)


class PersonalProjectWorkPage(ProjectPage):
    queue: Literal["receive", "verify", "tasks", "commitments"]
    page_size: int = Field(default=20, ge=1, le=100)


class SearchPage(StrictModel):
    q: str = Field(min_length=1, max_length=200)
    kind: Literal["all", "category", "project", "product", "proposal"] = "all"
    cursor: str | None = Field(default=None, pattern=(
        r"^(?:category|project|product|proposal):"
        r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:[a-f0-9]{16}$"
    ))
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入名称或完整 ID。")
        return value.strip()


def register_routes(app, engine, auth_dependency):
    def scope(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        )

    @app.get("/v1/personal/projects")
    def portfolio(page: Annotated[ProjectPage, Query()], ctx: Context = auth_dependency):
        with scope(ctx) as session:
            return projects(session, ctx, cursor=page.cursor, page_size=page.page_size)

    @app.get("/v1/personal/projects/{project_id}")
    def project_detail(project_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as session:
            return projects(session, ctx, project_id=project_id)

    @app.get("/v1/personal/project-work")
    def project_work(
        page: Annotated[PersonalProjectWorkPage, Query()], ctx: Context = auth_dependency
    ):
        from pdos_next.personal_project_work import read

        with scope(ctx) as session:
            return read(
                session, ctx, queue=page.queue, cursor=page.cursor, page_size=page.page_size
            )

    @app.get("/v1/personal/run-activity")
    def activity(page: Annotated[ActivityPage, Query()], ctx: Context = auth_dependency):
        with scope(ctx) as session:
            return run_activity(
                session, ctx, cursor=page.cursor, page_size=page.page_size, waiting=page.waiting
            )

    @app.get("/v1/personal/search")
    def object_search(page: Annotated[SearchPage, Query()], ctx: Context = auth_dependency):
        from pdos_next.personal_search import search

        with scope(ctx) as session:
            _personal(session, ctx)
            return search(
                session, ctx, page.q, kind=page.kind, cursor=page.cursor, page_size=page.page_size,
            )

    @app.get("/v1/personal/g0-reviews")
    def g0_reviews(page: Annotated[G0ReviewPage, Query()], ctx: Context = auth_dependency):
        from pdos_next.personal_g0_reviews import read

        with scope(ctx) as session:
            return read(session, ctx, cursor=page.cursor, page_size=page.page_size)

    @app.get("/v1/personal/test-start-promises")
    def test_start_promises(
        page: Annotated[TestStartPromisePage, Query()], ctx: Context = auth_dependency
    ):
        from pdos_next.personal_test_start_promises import read

        with scope(ctx) as session:
            return read(session, ctx, cursor=page.cursor, page_size=page.page_size)
