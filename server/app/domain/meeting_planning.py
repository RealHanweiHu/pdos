"""Immutable, project-bound ad-hoc meeting briefs for human and model preparation."""

import json
from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meeting_preparation import (
    SOURCE_TABLES,
    TEMPLATES,
    MeetingPreparationService,
    _source_value,
)
from app.domain.meeting_recurrence_commands import authorize
from app.domain.meeting_recurrence_roster import Participant
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

T = tables.meeting_planning_briefs
Kind = Literal["task", "issue", "risk", "decision"]
FIELDS = (
    "title",
    "description",
    "status",
    "priority",
    "severity",
    "due_date",
    "target_date",
    "assignee_user_id",
    "owner_user_id",
    "expected_output",
    "blocked_reason",
    "root_cause",
    "resolution",
    "closure_criteria",
    "closure_evidence_ref",
    "likelihood",
    "impact",
    "mitigation_plan",
    "contingency_plan",
    "context",
    "options",
    "trade_offs",
    "outcome",
    "rationale",
    "consequence",
    "evidence_refs",
    "completion_evidence_ref",
    "issue_type",
)


class Source(Contract):
    kind: Kind
    id: UUID
    expected_digest: Digest


class Draft(Contract):
    request_id: UUID
    parent_id: UUID | None = None
    title: str = Field(min_length=1, max_length=240, pattern=r"\S")
    meeting_type: str = "special"
    question: str = Field(min_length=1, max_length=10000, pattern=r"\S")
    expected_output: str = Field(min_length=1, max_length=5000, pattern=r"\S")
    timezone: str = Field(max_length=64)
    proposed_start_at: AwareDatetime | None = None
    proposed_end_at: AwareDatetime | None = None
    participants: tuple[Participant, ...] = Field(default=(), max_length=99)
    sources: tuple[Source, ...] = Field(default=(), max_length=30)
    reason: Text

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.meeting_type not in TEMPLATES:
            raise ValueError("请选择现有会议类型")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("请选择有效 IANA 时区") from error
        if (self.proposed_start_at is None) != (self.proposed_end_at is None):
            raise ValueError("拟议时间须同时填写开始和结束，也可均留待核对")
        if self.proposed_start_at is not None and self.proposed_end_at is not None:
            duration = (
                self.proposed_end_at.astimezone(UTC) - self.proposed_start_at.astimezone(UTC)
            ).total_seconds()
            if not 300 <= duration <= 43200:
                raise ValueError("拟议时长须为5分钟至12小时")
        if len({p.user_id for p in self.participants}) != len(self.participants):
            raise ValueError("参会候选不能重复")
        if len({(s.kind, s.id) for s in self.sources}) != len(self.sources):
            raise ValueError("业务依据不能重复")
        return self


class Save(Draft):
    preview_digest: Digest


def authorize_sources(c: Connection, ctx: AuthContext, project: UUID) -> None:
    authorize(c, ctx, project)
    KnowledgeCorrectionService._authorize(
        c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
    )


def source(c: Connection, ctx: AuthContext, project: UUID, kind: Kind, id: UUID) -> dict[str, Any]:
    t = SOURCE_TABLES[kind][0]
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingStateError("所选业务依据不在当前项目")
    return source_value(row, kind, project)


def source_value(row: Any, kind: Kind, project: UUID) -> dict[str, Any]:
    if (kind == "risk" and row["draft_state"] != "confirmed") or row.get("deleted_at") is not None:
        raise MeetingStateError("所选业务依据已删除或风险仍为草稿，请重新核对")
    summary = _source_value(row, kind, project)
    raw = _plain({key: row[key] for key in FIELDS if key in row})
    excerpts, omitted = {}, {}
    remaining = 10000
    for key, value in raw.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            limit = min(remaining, 4000)
            excerpts[key] = value[:limit]
            remaining -= len(excerpts[key])
            if len(value) > limit:
                omitted[key] = len(value) - limit
        else:
            excerpts[key] = value
    return {**summary, "record": excerpts, "omitted_characters": omitted}


def options(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    kind: Kind,
    query: str,
    before: UUID | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize_sources(c, ctx, project)
        t, title, _ = SOURCE_TABLES[kind]
        q = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
        if kind == "risk":
            q = q.where(t.c.draft_state == "confirmed")
        if "deleted_at" in t.c:
            q = q.where(t.c.deleted_at.is_(None))
        if query.strip():
            q = q.where(t.c[title].contains(query.strip(), autoescape=True))
        if before:
            q = q.where(t.c.id < before)
        rows = list(c.execute(q.order_by(t.c.id.desc()).limit(31)).mappings())
        return {
            "items": [source_value(row, kind, project) for row in rows[:30]],
            "next_before": str(rows[29]["id"]) if len(rows) > 30 else None,
            "members": [
                _plain(p) for p in MeetingPreparationService.members(c, ctx.tenant.id, project)
            ],
            "actor_id": str(ctx.user.id),
            "actor_name": ctx.user.display_name,
            "templates": TEMPLATES,
        }


def get(c: Connection, ctx: AuthContext, project: UUID, id: UUID) -> Any:
    row = (
        c.execute(
            select(T).where(
                T.c.tenant_id == ctx.tenant.id,
                T.c.project_id == project,
                T.c.id == id,
                T.c.created_by_user_id == ctx.user.id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingNotFoundError
    return row


def current(c: Connection, row: Any) -> Any:
    return (
        c.execute(
            select(T)
            .where(T.c.tenant_id == row["tenant_id"], T.c.root_id == row["root_id"])
            .order_by(T.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )


def snapshot(c: Connection, ctx: AuthContext, project: UUID, draft: Draft) -> dict[str, Any]:
    authorize(c, ctx, project, write=True)
    authorize_sources(c, ctx, project)
    parent = get(c, ctx, project, draft.parent_id) if draft.parent_id else None
    if parent is not None and current(c, parent)["id"] != parent["id"]:
        raise MeetingStateError("原起草资料已有新版本，请载入最新版本后修订")
    ids = {p.user_id for p in draft.participants} | {ctx.user.id}
    MeetingService._require_project_members(
        c, tenant_id=ctx.tenant.id, project_id=project, user_ids=ids
    )
    people = {
        str(p["id"]): _plain(p)
        for p in MeetingPreparationService.members(c, ctx.tenant.id, project)
    }
    candidates: dict[str, str] = {str(p.user_id): p.participation for p in draft.participants}
    candidates[str(ctx.user.id)] = "organizer"
    references = []
    for selected in draft.sources:
        item = source(c, ctx, project, selected.kind, selected.id)
        if item["digest"] != selected.expected_digest:
            raise MeetingStateError("所选业务资料已变化，请查看当前内容并重新选择")
        references.append(item)
    return {
        "version": "meeting-planning-source-v1",
        "project_id": str(project),
        "author_id": str(ctx.user.id),
        "author_name": ctx.user.display_name,
        "parent_id": str(parent["id"]) if parent else None,
        "parent_digest": parent["source_digest"] if parent else None,
        "title": draft.title,
        "meeting_type": draft.meeting_type,
        "question": draft.question,
        "expected_output": draft.expected_output,
        "timezone": draft.timezone,
        "proposed_start_at": draft.proposed_start_at.astimezone(UTC).isoformat()
        if draft.proposed_start_at
        else None,
        "proposed_end_at": draft.proposed_end_at.astimezone(UTC).isoformat()
        if draft.proposed_end_at
        else None,
        "participants": [
            {**people[id], "participation": participation}
            for id, participation in sorted(candidates.items())
        ],
        "sources": references,
        "reason": draft.reason,
        "missing": ([] if draft.proposed_start_at else ["尚未指定拟议时间"])
        + ([] if references else ["仅有本次填写要求，尚未选择业务记录依据"]),
        "template": TEMPLATES[draft.meeting_type],
    }


def preview(engine: Engine, ctx: AuthContext, project: UUID, draft: Draft) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        value = snapshot(c, ctx, project, draft)
        return {"snapshot": value, "preview_digest": digest(value)}


def save(engine: Engine, ctx: AuthContext, project: UUID, command: Save) -> dict[str, Any]:
    signature = digest(command.model_dump(mode="json"))
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        authorize_sources(c, ctx, project)
        prior = c.execute(select(T).where(T.c.id == command.request_id)).mappings().one_or_none()
        if prior is not None:
            if (
                prior["tenant_id"],
                prior["project_id"],
                prior["created_by_user_id"],
                prior["request_digest"],
            ) != (ctx.tenant.id, project, ctx.user.id, signature):
                raise MeetingStateError("原请求编号已用于其他起草资料")
            return _plain(prior)
        value = snapshot(c, ctx, project, command)
        if digest(value) != command.preview_digest:
            raise MeetingStateError("起草资料或候选人员已变化，请重新预览")
        parent = get(c, ctx, project, command.parent_id) if command.parent_id else None
        row = (
            c.execute(
                T.insert()
                .values(
                    id=command.request_id,
                    tenant_id=ctx.tenant.id,
                    project_id=project,
                    created_by_user_id=ctx.user.id,
                    root_id=parent["root_id"] if parent else command.request_id,
                    parent_id=command.parent_id,
                    version=parent["version"] + 1 if parent else 1,
                    request_digest=signature,
                    source_digest=digest(value),
                    source_snapshot=value,
                    created_at=datetime.now(UTC),
                )
                .returning(T)
            )
            .mappings()
            .one()
        )
        EventAuditWriter(
            c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
        ).record(
            EventDraft(
                event_id=f"meeting-planning:{row['id']}",
                event_type="MEETING_PLANNING_CHANGED",
                source="meeting_service",
                entity_id=row["root_id"],
                payload={"brief_id": str(row["id"]), "version": row["version"], "action": "saved"},
            ),
            AuditDraft(
                action="meeting_planning.saved",
                before_snapshot={"parent_id": str(parent["id"])} if parent else None,
                after_snapshot=_plain(row),
                context={"actor_name": ctx.user.display_name},
            ),
        )
        return _plain(row)


def read(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    id: UUID | None = None,
    before: int | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize_sources(c, ctx, project)
        status = authorize(c, ctx, project)
        row = get(c, ctx, project, id) if id else None
        q = select(T).where(
            T.c.tenant_id == ctx.tenant.id,
            T.c.project_id == project,
            T.c.created_by_user_id == ctx.user.id,
        )
        if row is not None:
            q = q.where(T.c.root_id == row["root_id"])
        if before is not None:
            q = q.where(T.c.sequence < before)
        rows = list(c.execute(q.order_by(T.c.sequence.desc()).limit(21)).mappings())
        differences = []
        if row is not None:
            for old in row["source_snapshot"]["sources"]:
                try:
                    now = source(c, ctx, project, old["kind"], UUID(old["id"]))
                    if now["digest"] != old["digest"]:
                        differences.append(
                            {
                                "kind": old["kind"],
                                "id": old["id"],
                                "title": old["title"],
                                "status": "changed",
                                "current": now,
                            }
                        )
                except MeetingStateError:
                    differences.append(
                        {
                            "kind": old["kind"],
                            "id": old["id"],
                            "title": old["title"],
                            "status": "unavailable",
                            "current": None,
                        }
                    )
        from app.ai.meeting_planning_runs import generation_state
        from app.domain.conversation_meeting_planning import label

        return {
            **generation_state(),
            "request_label": label(row) if row else None,
            "items": [
                _plain({k: r[k] for k in ("id", "root_id", "version", "sequence", "created_at")})
                | {"title": r["source_snapshot"]["title"]}
                for r in rows[:20]
            ],
            "record": _plain(row) if row else None,
            "latest_id": str(current(c, row)["id"]) if row else None,
            "source_changes": differences,
            "next_before_id": rows[19]["sequence"] if len(rows) > 20 else None,
            "can_manage": is_allowed(ctx.user.role, Action.MEETING_MANAGE)
            and status not in ("completed", "archived"),
        }
