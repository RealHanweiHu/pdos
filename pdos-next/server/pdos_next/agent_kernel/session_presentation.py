"""Human-owned Session presentation, independent of Run and business facts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import and_, exists, func, or_, select, text

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .models import AgentRun, AgentSession
from .project_scope import require_project
from .session_presentation_models import AgentSessionPresentation
from .session_views import (
    HEAD,
    _anchor,
    _head,
    _human,
    _matched,
    _pattern,
    _runs,
    _scope,
    _sessions,
)


class ConversationPage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=50)
    proposal_id: UUID | None = None
    q: str = Field(default="", max_length=160)
    view: Literal["active", "archived"] = "active"


class PresentationScope(StrictModel):
    proposal_id: UUID | None = None


class PresentationInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    action: Literal["rename", "pin", "unpin", "archive", "restore"]
    title: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def title_for_rename(self):
        if (self.action == "rename") != ("title" in self.model_fields_set):
            raise ValueError("重命名须提供 title（可为空）；其他操作不能携带 title。")
        return self


def _visible_sessions(ctx, proposal_id):
    from pdos_next.domain.projects.models import Project

    readable = _sessions(ctx, proposal_id)
    return (
        select(*readable.c, AgentSession.project_id)
        .join(
            AgentSession,
            and_(
                AgentSession.tenant_id == readable.c.tenant_id,
                AgentSession.id == readable.c.session_id,
            ),
        )
        .where(
            or_(
                AgentSession.project_id.is_(None),
                exists(
                    select(Project.id).where(
                        Project.tenant_id == AgentSession.tenant_id,
                        Project.category_id == AgentSession.category_id,
                        Project.product_id == AgentSession.product_id,
                        Project.id == AgentSession.project_id,
                    )
                ),
            )
        )
        .cte("presentation_readable_sessions")
    )


def _visible_runs(sessions):
    readable = _runs(sessions)
    return (
        select(*readable.c)
        .join(AgentRun, AgentRun.id == readable.c.run_id)
        .join(sessions, sessions.c.session_id == readable.c.session_id)
        .where(
            AgentRun.tenant_id == sessions.c.tenant_id,
            AgentRun.project_id.is_not_distinct_from(sessions.c.project_id),
        )
        .cte("presentation_readable_runs")
    )


def _eligible(ctx, page):
    sessions = _visible_sessions(ctx, page.proposal_id)
    runs = _visible_runs(sessions)
    ranked = select(
        *runs.c,
        func.count().over(partition_by=runs.c.session_id).label("run_count"),
        func.row_number()
        .over(
            partition_by=runs.c.session_id,
            order_by=(runs.c.created_at.desc(), runs.c.run_id.desc()),
        )
        .label("run_rank"),
    ).cte("presentation_ranked_runs")
    presentation = AgentSessionPresentation
    latest = (
        select(presentation)
        .join(
            sessions,
            and_(
                presentation.tenant_id == sessions.c.tenant_id,
                presentation.session_id == sessions.c.session_id,
                presentation.owner_id == sessions.c.owner_id,
            ),
        )
        .distinct(presentation.session_id)
        .order_by(presentation.session_id, presentation.revision.desc())
        .cte("latest_session_presentation")
    )
    query = (
        select(
            *sessions.c,
            ranked.c.run_count,
            *(ranked.c[key].label(f"latest_{key}") for key in HEAD),
            latest.c.id.label("presentation_id"),
            func.coalesce(latest.c.revision, 0).label("presentation_revision"),
            latest.c.title.label("presentation_title"),
            func.coalesce(latest.c.pinned, False).label("presentation_pinned"),
            func.coalesce(latest.c.archived, False).label("presentation_archived"),
            latest.c.created_at.label("presentation_created_at"),
        )
        .join(
            ranked,
            and_(ranked.c.session_id == sessions.c.session_id, ranked.c.run_rank == 1),
        )
        .outerjoin(latest, latest.c.session_id == sessions.c.session_id)
        .where(func.coalesce(latest.c.archived, False) == (page.view == "archived"))
    )
    if page.q:
        matched = _matched(runs, page.q)
        query = (
            query.add_columns(
                *(matched.c[key].label(f"matched_{key}") for key in HEAD),
                matched.c.match_kind,
            )
            .outerjoin(
                matched,
                and_(matched.c.session_id == sessions.c.session_id, matched.c.match_rank == 1),
            )
            .where(
                or_(
                    latest.c.title.ilike(_pattern(page.q), escape="\\"),
                    matched.c.run_id.is_not(None),
                )
            )
        )
    return query.cte("eligible_conversations")


def _list_presentation(row):
    return {
        "id": str(row["presentation_id"]) if row["presentation_id"] else None,
        "revision": row["presentation_revision"],
        "title": row["presentation_title"],
        "pinned": row["presentation_pinned"],
        "archived": row["presentation_archived"],
        "created_at": row["presentation_created_at"].isoformat()
        if row["presentation_created_at"] else None,
    }


def read_list(session, ctx, page):
    _human(session, ctx, page.proposal_id)
    eligible = _eligible(ctx, page)
    query = select(eligible)
    if page.cursor is not None:
        anchor = _anchor(
            session,
            select(
                eligible.c.presentation_pinned,
                eligible.c.created_at,
                eligible.c.session_id.label("identity"),
            ).where(eligible.c.session_id == page.cursor),
        )
        query = query.where(
            or_(
                and_(
                    eligible.c.presentation_pinned.is_(False),
                    anchor.presentation_pinned is True,
                ),
                and_(
                    eligible.c.presentation_pinned == anchor.presentation_pinned,
                    or_(
                        eligible.c.created_at < anchor.created_at,
                        and_(
                            eligible.c.created_at == anchor.created_at,
                            eligible.c.session_id < anchor.identity,
                        ),
                    ),
                ),
            )
        )
    rows = session.execute(
        query.order_by(
            eligible.c.presentation_pinned.desc(),
            eligible.c.created_at.desc(),
            eligible.c.session_id.desc(),
        ).limit(page.page_size + 1)
    ).mappings().all()
    items = []
    for row in rows[:page.page_size]:
        items.append({
            "session_id": str(row["session_id"]),
            "revision": row["revision"],
            "created_at": row["created_at"].isoformat(),
            "scope": {
                key: str(row[key]) if row[key] else None
                for key in ("category_id", "product_id", "proposal_id", "project_id")
            },
            "run_count": row["run_count"],
            "latest_run": _head(row, "latest_"),
            "matched_run": {**_head(row, "matched_"), "match_kind": row["match_kind"]}
            if page.q and row["matched_run_id"] is not None else None,
            "presentation": _list_presentation(row),
        })
    return {
        "version": "agent-conversation-list/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.proposal_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "items": items,
        "next_cursor": items[-1]["session_id"] if len(rows) > page.page_size else None,
    }


def _target(session, ctx, session_id, proposal_id, *, lock=False):
    query = select(AgentSession).where(
        AgentSession.tenant_id == ctx.tenant_id,
        AgentSession.owner_id == ctx.requester_id,
        AgentSession.category_id == ctx.category_id,
        AgentSession.id == session_id,
    )
    if proposal_id is not None:
        query = query.where(AgentSession.proposal_id == proposal_id)
    row = session.scalar(query.with_for_update(read=True) if lock else query)
    if row is None:
        raise DomainError("NOT_FOUND", "会话不存在或不在当前本人范围。", 404)
    if ctx.category_id is None:
        if any((row.product_id, row.proposal_id, row.project_id)):
            raise DomainError("FORBIDDEN_SCOPE", "个人入口不能管理业务范围会话。", 403)
    else:
        require_access(session, ctx, row.product_id, lock=lock)
        if row.proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal

            proposal(session, ctx, row.proposal_id)
        require_project(session, ctx, row.project_id, row.product_id, lock=lock)
    return row


def _request(session, ctx, key):
    return session.scalar(select(AgentSessionPresentation).where(
        AgentSessionPresentation.tenant_id == ctx.tenant_id,
        AgentSessionPresentation.owner_id == ctx.requester_id,
        AgentSessionPresentation.request_key == key,
    ))


def _response(ctx, row, target, proposal_id):
    return {
        "version": "agent-session-presentation/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, proposal_id),
        "session": {
            "session_id": str(target.id),
            **{
                key: str(getattr(target, key)) if getattr(target, key) else None
                for key in ("category_id", "product_id", "proposal_id", "project_id")
            },
        },
        "presentation": {
            "id": str(row.id),
            "revision": row.revision,
            "title": row.title,
            "pinned": row.pinned,
            "archived": row.archived,
            "created_at": row.created_at.isoformat(),
            "action": row.action,
            "request_key": str(row.request_key),
        },
    }


def change(session, ctx, session_id, data, proposal_id=None):
    _human(session, ctx, proposal_id)
    # Same-user request serialization precedes Session serialization everywhere.
    for key in (
        f"session-presentation-request:{ctx.tenant_id}:{ctx.requester_id}:{data.request_key}",
        f"session-presentation-session:{ctx.tenant_id}:{session_id}",
    ):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )
    target = _target(session, ctx, session_id, proposal_id, lock=True)
    request_sha256 = digest({
        "category_id": ctx.category_id,
        "proposal_id": proposal_id,
        "session_id": session_id,
        "request": data.model_dump(exclude={"request_key"}, exclude_unset=True),
    })
    previous_request = _request(session, ctx, data.request_key)
    if previous_request is not None:
        if (
            previous_request.session_id != target.id
            or previous_request.request_sha256 != request_sha256
        ):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的会话操作。", 409)
        return _response(ctx, previous_request, target, proposal_id)
    previous = session.scalar(
        select(AgentSessionPresentation)
        .where(
            AgentSessionPresentation.tenant_id == ctx.tenant_id,
            AgentSessionPresentation.session_id == target.id,
            AgentSessionPresentation.owner_id == ctx.requester_id,
        )
        .order_by(AgentSessionPresentation.revision.desc())
        .limit(1)
    )
    revision = previous.revision if previous else 0
    if data.expected_revision != revision:
        raise DomainError("VERSION_CONFLICT", "会话显示设置已变化，请刷新后重新操作。", 409)
    row = AgentSessionPresentation(
        tenant_id=ctx.tenant_id,
        session_id=target.id,
        owner_id=ctx.requester_id,
        revision=revision + 1,
        previous_id=previous.id if previous else None,
        request_key=data.request_key,
        request_sha256=request_sha256,
        action=data.action,
        title=data.title if data.action == "rename" else previous.title if previous else None,
        pinned=(data.action == "pin") if data.action in {"pin", "unpin"}
        else previous.pinned if previous else False,
        archived=(data.action == "archive") if data.action in {"archive", "restore"}
        else previous.archived if previous else False,
    )
    session.add(row)
    session.flush()
    return _response(ctx, row, target, proposal_id)


def read_request(session, ctx, session_id, key, proposal_id=None):
    _human(session, ctx, proposal_id)
    target = _target(session, ctx, session_id, proposal_id)
    row = _request(session, ctx, key)
    if row is None or row.session_id != target.id:
        raise DomainError("NOT_FOUND", "当前会话中没有该操作请求。", 404)
    return _response(ctx, row, target, proposal_id)
