"""Owned Sessions with readable Run heads and separately recorded owner-only goals.

This reader records no title, lifecycle, permission, conversation-wide outcome or
memory promise. A selected Run keeps its existing read/continuation endpoints.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import and_, case, exists, func, literal, or_, select

from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access

from .models import AgentRun, AgentSession, AgentSessionBinding

HEAD = ("run_id", "goal", "status", "error_code", "created_at", "continued_from_id", "reverted_at")


class SessionPage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=50)
    proposal_id: UUID | None = None
    project_id: UUID | None = None
    q: str = Field(default="", max_length=160)


class RunPage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=50)
    proposal_id: UUID | None = None
    project_id: UUID | None = None


def _scope(ctx, proposal_id, project_id=None):
    return {
        "category_id": str(ctx.category_id) if ctx.category_id else None,
        "proposal_id": str(proposal_id) if proposal_id else None,
        **({"project_id": str(project_id)} if project_id is not None else {}),
    }


def _human(session, ctx, proposal_id, project_id=None):
    require_context(session, ctx)
    actor = session.get(Principal, ctx.actor_id)
    if (
        ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or actor is None
        or actor.tenant_id != ctx.tenant_id
        or not actor.active
        or actor.kind != "human"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "会话只向当前具名本人显示。", 403)
    if ctx.category_id is None:
        if proposal_id is not None or project_id is not None:
            raise DomainError("FORBIDDEN_SCOPE", "个人会话入口不能选择业务提案。", 403)
    else:
        require_access(session, ctx, None)
        if proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal

            proposal(session, ctx, proposal_id)
        if project_id is not None:
            from pdos_next.domain.projects.models import Project

            from .project_scope import require_project

            project = session.get(Project, project_id)
            if project is None or project.category_id != ctx.category_id:
                raise DomainError("FORBIDDEN_SCOPE", "项目不存在或当前不可读。", 403)
            require_project(session, ctx, project_id, project.product_id)


def _sessions(ctx, proposal_id, project_id=None):
    """Apply ordinary parent RLS before goals, counts, search or cursor reads."""
    from pdos_next.domain.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project

    current_proposal = func.coalesce(AgentSessionBinding.proposal_id, AgentSession.proposal_id)
    query = select(
        AgentSession.id.label("session_id"),
        AgentSession.tenant_id,
        AgentSession.owner_id,
        AgentSession.revision,
        AgentSession.created_at,
        AgentSession.category_id,
        AgentSession.product_id,
        AgentSession.project_id,
        current_proposal.label("proposal_id"),
    ).outerjoin(
        AgentSessionBinding,
        and_(
            AgentSessionBinding.tenant_id == AgentSession.tenant_id,
            AgentSessionBinding.session_id == AgentSession.id,
        ),
    ).where(
        AgentSession.tenant_id == ctx.tenant_id,
        AgentSession.owner_id == ctx.requester_id,
        AgentSession.category_id == ctx.category_id,
        or_(
            AgentSession.product_id.is_(None),
            exists(
                select(Product.id).where(
                    Product.tenant_id == AgentSession.tenant_id,
                    Product.category_id == AgentSession.category_id,
                    Product.id == AgentSession.product_id,
                )
            ),
        ),
        or_(
            current_proposal.is_(None),
            exists(
                select(Proposal.id).where(
                    Proposal.tenant_id == AgentSession.tenant_id,
                    Proposal.category_id == AgentSession.category_id,
                    Proposal.id == current_proposal,
                )
            ),
        ),
        or_(
            AgentSession.project_id.is_(None),
            exists(select(Project.id).where(
                Project.tenant_id == AgentSession.tenant_id,
                Project.category_id == AgentSession.category_id,
                Project.product_id == AgentSession.product_id,
                Project.id == AgentSession.project_id,
            )),
        ),
    )
    if ctx.category_id is None:
        query = query.where(
            AgentSession.product_id.is_(None), current_proposal.is_(None),
            AgentSession.project_id.is_(None),
        )
    if proposal_id is not None:
        query = query.where(current_proposal == proposal_id)
    if project_id is not None:
        query = query.where(AgentSession.project_id == project_id)
    return query.cte("readable_sessions")


def _runs(sessions):
    from .owner_history import goal_rows

    visible = (
        select(
            AgentRun.id.label("run_id"),
            AgentRun.session_id,
            AgentRun.goal,
            AgentRun.state.label("status"),
            AgentRun.error_code,
            AgentRun.created_at,
            AgentRun.continued_from_id,
            AgentRun.reverted_at,
            AgentRun.product_id,
            AgentRun.proposal_id,
            AgentRun.project_id,
        )
        .join(
            sessions,
            and_(
                AgentRun.tenant_id == sessions.c.tenant_id,
                AgentRun.session_id == sessions.c.session_id,
                AgentRun.requester_id == sessions.c.owner_id,
                AgentRun.category_id.is_not_distinct_from(sessions.c.category_id),
                AgentRun.product_id.is_not_distinct_from(sessions.c.product_id),
                AgentRun.project_id.is_not_distinct_from(sessions.c.project_id),
                or_(
                    AgentRun.proposal_id.is_not_distinct_from(sessions.c.proposal_id),
                    and_(sessions.c.proposal_id.is_not(None), AgentRun.proposal_id.is_(None)),
                ),
            ),
        )
    )
    recorded = goal_rows(sessions).cte("recorded_owner_goals")
    hidden = select(
        recorded.c.run_id, recorded.c.session_id, recorded.c.goal,
        literal("hidden").label("status"), literal(None).label("error_code"),
        # Sorting uses the original work-state record clock. The public hidden
        # head labels it recorded_at and leaves the unknown Run clock empty.
        recorded.c.recorded_at.label("created_at"),
        literal(None).label("continued_from_id"), literal(None).label("reverted_at"),
        recorded.c.session_product_id.label("product_id"),
        literal(None).label("proposal_id"), recorded.c.session_project_id.label("project_id"),
    ).where(~exists(select(AgentRun.id).where(
        AgentRun.id == recorded.c.run_id,
    )))
    return visible.union_all(hidden).cte("readable_run_heads")


def _pattern(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _matched(runs, q):
    conditions = [runs.c.goal.ilike(_pattern(q), escape="\\")]
    try:
        identity = UUID(q)
    except ValueError:
        identity = None
    if identity is not None:
        conditions.extend((runs.c.run_id == identity, runs.c.session_id == identity))
        kind = case(
            (runs.c.run_id == identity, "run_id"),
            (runs.c.session_id == identity, "session_id"),
            else_="goal",
        )
    else:
        kind = literal("goal")
    return (
        select(
            *runs.c,
            kind.label("match_kind"),
            func.row_number()
            .over(
                partition_by=runs.c.session_id,
                order_by=(runs.c.created_at.desc(), runs.c.run_id.desc()),
            )
            .label("match_rank"),
        )
        .where(or_(*conditions))
        .cte("matching_run_heads")
    )


def _head(row, prefix=""):
    if row[f"{prefix}status"] == "hidden":
        return {
            "run_id": str(row[f"{prefix}run_id"]), "goal": row[f"{prefix}goal"],
            "status": "hidden", "error_code": None, "created_at": None,
            "recorded_at": row[f"{prefix}created_at"].isoformat(),
            "continued_from_id": None, "reverted": None, "history_hidden": True,
            "hidden_message": "原回答所依据的资料已不可读，保留你的原话。",
        }
    return {
        "run_id": str(row[f"{prefix}run_id"]),
        "goal": row[f"{prefix}goal"],
        "status": row[f"{prefix}status"],
        "error_code": row[f"{prefix}error_code"],
        "created_at": row[f"{prefix}created_at"].isoformat(),
        "continued_from_id": str(row[f"{prefix}continued_from_id"])
        if row[f"{prefix}continued_from_id"]
        else None,
        "reverted": row[f"{prefix}reverted_at"] is not None,
    }


def _metadata(row, run_count, *, include_project=False):
    return {
        "session_id": str(row["session_id"]),
        "revision": row["revision"],
        "created_at": row["created_at"].isoformat(),
        "scope": {
            key: str(row[key]) if row[key] else None
            for key in ("category_id", "product_id", "proposal_id")
            + (("project_id",) if include_project else ())
        },
        "run_count": run_count,
    }


def _after(query, created_at, identity, anchor):
    return query.where(
        or_(
            created_at < anchor.created_at,
            and_(created_at == anchor.created_at, identity < anchor.identity),
        )
    )


def _anchor(session, query):
    row = session.execute(query).one_or_none()
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "分页位置已不在当前可读会话或搜索中，请刷新。", 403)
    return row


def read_list(session, ctx, page):
    _human(session, ctx, page.proposal_id, page.project_id)
    sessions = _sessions(ctx, page.proposal_id, page.project_id)
    runs = _runs(sessions)
    ranked = select(
        *runs.c,
        func.count().over(partition_by=runs.c.session_id).label("run_count"),
        func.row_number()
        .over(
            partition_by=runs.c.session_id,
            order_by=(runs.c.created_at.desc(), runs.c.run_id.desc()),
        )
        .label("run_rank"),
    ).cte("ranked_run_heads")
    query = select(
        *sessions.c,
        ranked.c.run_count,
        *(ranked.c[key].label(f"latest_{key}") for key in HEAD),
    ).join(
        ranked,
        and_(
            ranked.c.session_id == sessions.c.session_id,
            ranked.c.run_rank == 1,
        ),
    )
    q = page.q.strip()
    if q:
        matched = _matched(runs, q)
        query = query.add_columns(
            *(matched.c[key].label(f"matched_{key}") for key in HEAD),
            matched.c.match_kind,
        ).join(
            matched,
            and_(
                matched.c.session_id == sessions.c.session_id,
                matched.c.match_rank == 1,
            ),
        )
    eligible = query.cte("eligible_session_summaries")
    query = select(eligible)
    if page.cursor is not None:
        anchor = _anchor(
            session,
            select(
                eligible.c.created_at,
                eligible.c.session_id.label("identity"),
            ).where(eligible.c.session_id == page.cursor),
        )
        query = _after(query, eligible.c.created_at, eligible.c.session_id, anchor)
    rows = (
        session.execute(
            query.order_by(eligible.c.created_at.desc(), eligible.c.session_id.desc()).limit(
                page.page_size + 1
            )
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows[: page.page_size]:
        item = _metadata(row, row["run_count"], include_project=page.project_id is not None)
        item.update(
            latest_run=_head(row, "latest_"),
            matched_run={**_head(row, "matched_"), "match_kind": row["match_kind"]} if q else None,
        )
        items.append(item)
    return {
        "version": "agent-session-list/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.proposal_id, page.project_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "items": items,
        "next_cursor": items[-1]["session_id"] if len(rows) > page.page_size else None,
    }


def read_runs(session, ctx, session_id, page):
    _human(session, ctx, page.proposal_id, page.project_id)
    sessions = _sessions(ctx, page.proposal_id, page.project_id)
    selected = (
        session.execute(select(sessions).where(sessions.c.session_id == session_id))
        .mappings()
        .one_or_none()
    )
    if selected is None:
        raise DomainError("NOT_FOUND", "会话不存在或不在当前本人范围。", 404)
    runs = _runs(sessions)
    count = session.scalar(
        select(func.count()).select_from(runs).where(runs.c.session_id == session_id)
    )
    if not count:
        raise DomainError("INTEGRITY_MISMATCH", "会话内没有可完整核对的运行。", 409)
    query = select(runs).where(runs.c.session_id == session_id)
    if page.cursor is not None:
        anchor = _anchor(
            session,
            select(runs.c.created_at, runs.c.run_id.label("identity")).where(
                runs.c.session_id == session_id, runs.c.run_id == page.cursor
            ),
        )
        query = _after(query, runs.c.created_at, runs.c.run_id, anchor)
    neighbors = runs.alias("readable_neighbor")
    query = query.add_columns(
        exists(
            select(neighbors.c.run_id).where(
                neighbors.c.session_id == runs.c.session_id,
                neighbors.c.run_id == runs.c.continued_from_id,
            )
        ).label("previous_visible"),
        select(neighbors.c.run_id)
        .where(
            neighbors.c.session_id == runs.c.session_id,
            neighbors.c.continued_from_id == runs.c.run_id,
        )
        .scalar_subquery()
        .label("next_run_id"),
    )
    rows = (
        session.execute(
            query.order_by(runs.c.created_at.desc(), runs.c.run_id.desc()).limit(page.page_size + 1)
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows[: page.page_size]:
        if row["continued_from_id"] is not None and not row["previous_visible"]:
            raise DomainError("INTEGRITY_MISMATCH", "会话内原运行关系无法完整核对。", 409)
        item = _head(row)
        item["conversation"] = {
            "previous_run_id": item["continued_from_id"],
            "next_run_id": str(row["next_run_id"])
            if row["next_run_id"] and not item.get("history_hidden") else None,
            **({"links_unavailable": True} if item.get("history_hidden") else {}),
        }
        items.append(item)
    return {
        "version": "agent-session-runs/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.proposal_id, page.project_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "session": _metadata(selected, count, include_project=page.project_id is not None),
        "items": items,
        "next_cursor": items[-1]["run_id"] if len(rows) > page.page_size else None,
    }


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/personal/agent-sessions")
    @result.get("/v1/categories/{category_id}/agent-sessions")
    def listing(page: Annotated[SessionPage, Query()], ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return read_list(session, ctx, page)

    @result.get("/v1/personal/agent-sessions/{session_id}/runs")
    @result.get("/v1/categories/{category_id}/agent-sessions/{session_id}/runs")
    def details(session_id: UUID, page: Annotated[RunPage, Query()], ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return read_runs(session, ctx, session_id, page)

    return result
