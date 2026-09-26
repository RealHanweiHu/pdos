"""Private human meeting plans, followed by a separate atomic local meeting application."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select, update

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.meeting_planning_context import bound_source
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.meeting_plan import CAPABILITY, FINDING_TYPE, RUN_VERSION, Input, Plan
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meeting_preparation import TEMPLATES, write_agenda
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class HumanAgenda(Input):
    original_number: int | None = Field(default=None, ge=1, le=12)
    title: str = Field(min_length=1, max_length=256)
    detail: str = Field(min_length=1, max_length=5000)
    expected_output: str = Field(min_length=1, max_length=2000)
    owner_user_id: UUID | None = None


class HumanParticipant(Input):
    user_id: UUID
    participation: Literal["required", "optional"]


class HumanPlan(Input):
    title: str = Field(min_length=1, max_length=240)
    meeting_type: str
    purpose: str = Field(min_length=1, max_length=3000)
    timezone: str = Field(min_length=1, max_length=64)
    scheduled_start_at: AwareDatetime
    scheduled_end_at: AwareDatetime
    participants: tuple[HumanParticipant, ...] = Field(max_length=99)
    agenda: tuple[HumanAgenda, ...] = Field(min_length=1, max_length=12)
    question_responses: tuple[str, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.meeting_type not in TEMPLATES:
            raise ValueError("请选择现有会议类型")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("请选择有效 IANA 时区") from error
        duration = (self.scheduled_end_at - self.scheduled_start_at).total_seconds()
        if not 300 <= duration <= 43200:
            raise ValueError("正式会议时长须为5分钟至12小时")
        if len({p.user_id for p in self.participants}) != len(self.participants):
            raise ValueError("参会人员不能重复")
        origins = [a.original_number for a in self.agenda if a.original_number is not None]
        if len(set(origins)) != len(origins):
            raise ValueError("每条原议题最多对应一条人工议题，新增议题请标为人工新增")
        if any(not q.strip() or len(q) > 2000 for q in self.question_responses):
            raise ValueError("请逐项填写待确认问题的核对结果（最多2000字）")
        return self


class Review(Input):
    request_id: UUID
    decision: Literal["accepted", "rejected"]
    comment: str = Field(min_length=1, max_length=5000)
    edited: HumanPlan | None = None
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.decision == "accepted" and (self.edited is None or self.preview_digest is None):
            raise ValueError("接受前须核对正式安排并预览差异")
        if self.decision == "rejected" and (self.edited is not None or self.preview_digest):
            raise ValueError("拒绝不保存接受稿")
        return self


class Apply(Input):
    request_id: UUID
    accepted_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]


def prepare(finding: RowMapping, source: dict[str, Any], body: HumanPlan) -> dict[str, Any]:
    assessment = finding["proposed_payload"]["assessment"]
    original = Plan.model_validate(assessment["plan"])
    people = {UUID(p["id"]) for p in source["participants"]}
    if UUID(source["author_id"]) in {p.user_id for p in body.participants}:
        raise MeetingStateError("原发起人已作为组织者参会，不要重复列为必需或可选人员")
    selected = {p.user_id for p in body.participants} | {UUID(source["author_id"])}
    if not selected <= people:
        raise MeetingStateError("参会人须来自原已核对候选；增加人员请先修订起草资料")
    if any(a.owner_user_id is not None and a.owner_user_id not in selected for a in body.agenda):
        raise MeetingStateError("议题负责人须在本次正式参会名单内")
    if len(body.question_responses) != len(assessment["open_questions"]):
        raise MeetingStateError("请逐项核对原建议中的待确认问题")
    if any(a.original_number and a.original_number > len(original.agenda) for a in body.agenda):
        raise MeetingStateError("人工议题对应的原建议编号不存在")
    human = body.model_dump(mode="json")
    human["scheduled_start_at"] = body.scheduled_start_at.astimezone(UTC).isoformat()
    human["scheduled_end_at"] = body.scheduled_end_at.astimezone(UTC).isoformat()
    changes: list[dict[str, Any]] = []
    old = original.model_dump(mode="json")
    for key in ("title", "meeting_type", "purpose"):
        if old[key] != human[key]:
            changes.append({"field": key, "before": old[key], "after": human[key]})
    original_people = [
        {"user_id": p["user_id"], "participation": p["participation"]} for p in old["participants"]
    ]
    if original_people != human["participants"]:
        changes.append(
            {"field": "participants", "before": original_people, "after": human["participants"]}
        )
    changes.append(
        {
            "field": "schedule",
            "before": {
                "start": source["proposed_start_at"],
                "end": source["proposed_end_at"],
                "timezone": source["timezone"],
            },
            "after": {
                "start": human["scheduled_start_at"],
                "end": human["scheduled_end_at"],
                "timezone": body.timezone,
            },
        }
    )
    retained = set()
    for position, item in enumerate(human["agenda"], 1):
        number = item["original_number"]
        before = None
        if number:
            retained.add(number)
            raw = old["agenda"][number - 1]
            before = {
                "title": raw["title"],
                "detail": raw["detail"],
                "expected_output": raw["expected_output"],
                "owner_user_id": raw["suggested_owner_id"],
            }
        after = {key: item[key] for key in ("title", "detail", "expected_output", "owner_user_id")}
        changes.append(
            {
                "field": "agenda",
                "original_number": number,
                "position": position,
                "action": "added"
                if before is None
                else "modified"
                if before != after
                else "retained",
                "before": before,
                "after": after,
            }
        )
    for number, item in enumerate(old["agenda"], 1):
        if number not in retained:
            changes.append(
                {
                    "field": "agenda",
                    "original_number": number,
                    "action": "removed",
                    "before": item,
                    "after": None,
                }
            )
    payload = {
        "version": "meeting-plan-human-v1",
        "brief_id": finding["proposed_payload"]["brief_id"],
        "source_digest": finding["proposed_payload"]["source_digest"],
        "organizer_user_id": source["author_id"],
        "plan": human,
        "changes": changes,
    }
    return {
        "accepted_payload": payload,
        "preview_digest": digest(payload),
        "changes": changes,
        "meeting_agenda": agenda_values(body),
    }


def agenda_values(body: HumanPlan) -> list[dict[str, Any]]:
    return [
        {
            "title": "会议目的",
            "item_kind": "information",
            "detail": body.purpose,
            "owner_user_id": None,
        }
    ] + [
        {
            "title": a.title,
            "detail": f"{a.detail}\n\n期望产出：{a.expected_output}",
            "owner_user_id": a.owner_user_id,
            "item_kind": "topic",
        }
        for a in body.agenda
    ]


class MeetingPlanningReview:
    def __init__(self, engine: Engine):
        self.engine = engine

    def rows(
        self, c: Connection, ctx: AuthContext, project: UUID, identity: UUID, *, write: bool = False
    ) -> tuple[RowMapping, RowMapping]:
        KnowledgeCorrectionService._authorize(
            c, ctx.tenant.id, ctx.user.id, project, Action.MEETING_MANAGE
        )
        KnowledgeCorrectionService._authorize(
            c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
        )
        if write and not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        f, r = tables.findings, tables.agent_runs
        query = (
            select(f)
            .join(r, (r.c.tenant_id == f.c.tenant_id) & (r.c.id == f.c.run_id))
            .where(
                f.c.tenant_id == ctx.tenant.id,
                f.c.project_id == project,
                f.c.id == identity,
                f.c.finding_type == FINDING_TYPE,
                r.c.context_version == RUN_VERSION,
                r.c.requested_by_user_id == ctx.user.id,
            )
        )
        if write:
            query = query.with_for_update(of=f)
        finding = c.execute(query).mappings().one_or_none()
        if finding is None:
            raise MeetingNotFoundError
        run = (
            c.execute(select(r).where(r.c.tenant_id == ctx.tenant.id, r.c.id == finding["run_id"]))
            .mappings()
            .one()
        )
        return finding, run

    @staticmethod
    def current(c: Connection, ctx: AuthContext, project: UUID, run: RowMapping) -> None:
        try:
            bound_source(c, ctx.tenant.id, project, ctx.user.id, run["run_context"])
        except BudgetLedgerError as error:
            raise MeetingStateError(
                "原起草版本、人员或资料已变化，请基于最新资料重新起草和核对"
            ) from error

    @staticmethod
    def receipt(c: Connection, finding: RowMapping | dict[str, Any]) -> dict[str, Any]:
        a = tables.finding_actions
        actions = (
            c.execute(
                select(a)
                .where(
                    a.c.tenant_id == finding["tenant_id"],
                    a.c.finding_id == finding["id"],
                    a.c.action.in_(("accepted", "rejected", "applied")),
                )
                .order_by(a.c.created_at)
            )
            .mappings()
            .all()
        )
        return _plain(
            {
                "finding": dict(finding),
                "actions": [dict(a) for a in actions],
                "accepted_digest": digest(finding["accepted_payload"])
                if finding["accepted_payload"]
                else None,
                "meeting_href": (
                    f"/projects?project={finding['project_id']}&tab=decisions"
                    f"&meeting={finding['applied_entity_id']}"
                )
                if finding["applied_entity_id"]
                else None,
            }
        )

    @staticmethod
    def replay(c: Connection, finding: RowMapping, request: UUID, signature: str) -> bool:
        a = tables.finding_actions
        row = c.execute(
            select(a.c.detail).where(
                a.c.tenant_id == finding["tenant_id"],
                a.c.finding_id == finding["id"],
                a.c.detail["request_id"].astext == str(request),
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if row.get("request_digest") != signature:
            raise MeetingStateError("同一请求不能更换核对或创建内容，请读取原回执")
        return True

    @staticmethod
    def record(
        c: Connection,
        ctx: AuthContext,
        finding: RowMapping,
        action: str,
        now: datetime,
        detail: dict[str, Any],
    ) -> None:
        c.execute(
            tables.finding_actions.insert().values(
                id=uuid4(),
                tenant_id=ctx.tenant.id,
                project_id=finding["project_id"],
                finding_id=finding["id"],
                action=action,
                actor_user_id=ctx.user.id,
                from_status=finding["status"],
                to_status=action,
                detail=detail,
                created_at=now,
            )
        )
        EventAuditWriter(
            c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=finding["project_id"]
        ).record(
            EventDraft(
                event_id=f"meeting-plan:{finding['id']}:{action}",
                event_type="MEETING_PLAN_FINDING_RECORDED",
                source="meeting_service",
                entity_id=finding["id"],
                payload={"finding_id": str(finding["id"]), "action": action},
                occurred_at=now,
            ),
            AuditDraft(
                action=f"meeting_plan.{action}",
                before_snapshot={"finding_id": str(finding["id"]), "status": finding["status"]},
                after_snapshot={"finding_id": str(finding["id"]), "status": action, **detail},
            ),
        )

    def origin(self, ctx: AuthContext, project: UUID, meeting: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.MEETING_VIEW
            )
            m, f, u = tables.meetings, tables.findings, tables.users
            if (
                c.execute(
                    select(m.c.id).where(
                        m.c.tenant_id == ctx.tenant.id,
                        m.c.project_id == project,
                        m.c.id == meeting,
                        m.c.deleted_at.is_(None),
                    )
                ).first()
                is None
            ):
                raise MeetingNotFoundError
            row = (
                c.execute(
                    select(
                        f.c.id,
                        f.c.reviewed_by_user_id,
                        f.c.reviewed_at,
                        f.c.applied_at,
                        u.c.display_name,
                    )
                    .join(u, (u.c.tenant_id == f.c.tenant_id) & (u.c.id == f.c.applied_by_user_id))
                    .where(
                        f.c.tenant_id == ctx.tenant.id,
                        f.c.project_id == project,
                        f.c.finding_type == FINDING_TYPE,
                        f.c.status == "applied",
                        f.c.applied_entity_type == "meeting",
                        f.c.applied_entity_id == meeting,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return {"origin": None}
            return {
                "origin": _plain(
                    {
                        "creator_name": row["display_name"],
                        "reviewed_at": row["reviewed_at"],
                        "applied_at": row["applied_at"],
                        "own_finding_id": row["id"]
                        if row["reviewed_by_user_id"] == ctx.user.id
                        else None,
                    }
                )
            }

    def get(self, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            finding, run = self.rows(c, ctx, project, identity)
            if finding["status"] != "applied":
                require_live_key(CAPABILITY)
            reason = None
            try:
                self.current(c, ctx, project, run)
            except MeetingStateError as error:
                reason = str(error)
            return self.receipt(c, finding) | {
                "source": run["run_context"]["meeting_planning_source"],
                "source_current": reason is None,
                "source_reason": reason,
            }

    def preview(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: HumanPlan
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            finding, run = self.rows(c, ctx, project, identity, write=True)
            if finding["status"] != "pending_review":
                raise MeetingStateError("已有核对回执，请读取原结果")
            self.current(c, ctx, project, run)
            return _plain(prepare(finding, run["run_context"]["meeting_planning_source"], body))

    def review(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: Review
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        signature = digest(body.model_dump(mode="json"))
        with self.engine.begin() as c:
            finding, run = self.rows(c, ctx, project, identity, write=True)
            if self.replay(c, finding, body.request_id, signature):
                return self.receipt(c, finding)
            if finding["status"] != "pending_review":
                raise MeetingStateError("此建议已有核对回执，不可覆盖")
            payload = None
            if body.edited is not None:
                self.current(c, ctx, project, run)
                prepared = prepare(
                    finding, run["run_context"]["meeting_planning_source"], body.edited
                )
                if prepared["preview_digest"] != body.preview_digest:
                    raise MeetingStateError("人工稿与预览不一致，请重新预览后接受")
                payload = prepared["accepted_payload"]
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            values = {
                "status": body.decision,
                "reviewed_by_user_id": ctx.user.id,
                "reviewed_at": now,
                "review_comment": body.comment,
                "accepted_payload": payload,
                "updated_at": now,
            }
            c.execute(
                update(tables.findings)
                .where(
                    tables.findings.c.tenant_id == ctx.tenant.id, tables.findings.c.id == identity
                )
                .values(**values)
            )
            self.record(
                c,
                ctx,
                finding,
                body.decision,
                now,
                {
                    "request_id": str(body.request_id),
                    "request_digest": signature,
                    "preview_digest": body.preview_digest,
                    "comment": body.comment,
                },
            )
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=ctx.tenant.id, evaluated_at=now
            )
            return self.receipt(c, dict(finding) | values)

    def apply(self, ctx: AuthContext, project: UUID, identity: UUID, body: Apply) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        signature = digest(body.model_dump(mode="json"))
        with self.engine.begin() as c:
            finding, run = self.rows(c, ctx, project, identity, write=True)
            if self.replay(c, finding, body.request_id, signature):
                return self.receipt(c, finding)
            if finding["status"] != "accepted" or finding["reviewed_by_user_id"] != ctx.user.id:
                raise MeetingStateError(
                    "请先由原发起人接受人工稿，再独立创建会议；已有创建请读取原回执"
                )
            payload = finding["accepted_payload"]
            if digest(payload) != body.accepted_digest:
                raise MeetingStateError("接受稿版本不一致，请重新读取核对回执")
            self.current(c, ctx, project, run)
            f = tables.findings
            if c.execute(
                select(f.c.id).where(
                    f.c.tenant_id == ctx.tenant.id,
                    f.c.project_id == project,
                    f.c.finding_type == FINDING_TYPE,
                    f.c.origin_key == finding["origin_key"],
                    f.c.status == "applied",
                )
            ).first():
                raise MeetingStateError(
                    "同一原要求已有实际会议，请回查原创建回执并在实际会议中修改"
                )
            plan = HumanPlan.model_validate(payload["plan"])
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            if plan.scheduled_start_at <= now:
                raise MeetingStateError("正式开始时间已过，请基于最新安排重新起草并核对")
            meeting = MeetingService(self.engine).create(
                tenant_id=ctx.tenant.id,
                project_id=project,
                actor_user_id=ctx.user.id,
                organizer_user_id=ctx.user.id,
                meeting_type=plan.meeting_type,
                title=plan.title,
                scheduled_start_at=plan.scheduled_start_at,
                scheduled_end_at=plan.scheduled_end_at,
                participants=[(p.user_id, p.participation) for p in plan.participants],
                source="agent_drafted",
                now=now,
                connection=c,
            )
            write_agenda(
                c,
                tenant_id=ctx.tenant.id,
                project_id=project,
                meeting_id=meeting.id,
                items=agenda_values(plan),
                now=now,
            )
            values = {
                "status": "applied",
                "applied_by_user_id": ctx.user.id,
                "applied_at": now,
                "applied_entity_type": "meeting",
                "applied_entity_id": meeting.id,
                "updated_at": now,
            }
            c.execute(
                update(f).where(f.c.tenant_id == ctx.tenant.id, f.c.id == identity).values(**values)
            )
            self.record(
                c,
                ctx,
                finding,
                "applied",
                now,
                {
                    "request_id": str(body.request_id),
                    "request_digest": signature,
                    "accepted_digest": body.accepted_digest,
                    "meeting_id": str(meeting.id),
                    "agenda": _plain({"items": agenda_values(plan)})["items"],
                },
            )
            return self.receipt(c, dict(finding) | values)
