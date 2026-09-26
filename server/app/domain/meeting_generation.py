"""Bounded recurring meeting generation with independently authorized external requests."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain import meeting_conference_requests as conferences
from app.domain import meeting_recurring_conferences as recurring_conferences
from app.domain import meeting_recurring_notifications as recurring_notifications
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.meeting_recurrence_commands import (
    Window,
    authorize,
    existing_in_window,
    existing_item,
    replay,
    validate_people,
)
from app.domain.meeting_recurrence_roster import record as recurrence_record
from app.domain.meeting_scheduling import (
    MeetingSchedulingService,
    RecurrenceValidationError,
    _recurrence,
    occurrence_times,
    occurrences_between,
)
from app.domain.meetings import MeetingScopeError, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.settings import Settings, get_settings

CHANGE = "meeting_recurrence.automation_changed"
SCAN = "meeting_recurrence.automation_scanned"


class Draft(Contract):
    request_id: UUID
    expected_policy_digest: Digest | None
    expected_recurrence_digest: Digest
    status: Literal["enabled", "paused"]
    active_from: date
    active_until: date
    lead_days: int = Field(ge=1, le=60)
    reason: Text
    conference_provider: Literal["dingtalk", "tencent_meeting"] | None = None
    authorize_external_conference: bool = False
    notification_mode: Literal["none", "in_app", "dingtalk"] = "none"
    authorize_notifications: bool = False

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 0 <= (self.active_until - self.active_from).days <= 366:
            raise ValueError("自动生成有效日期须有先后顺序且不超过367个自然日")
        if (
            self.status == "enabled"
            and self.conference_provider is not None
            and not self.authorize_external_conference
        ):
            raise ValueError("启用周期外部预约须明确确认使用本人账号预约后续新场次")
        if (
            self.status == "enabled"
            and self.notification_mode != "none"
            and not self.authorize_notifications
        ):
            raise ValueError("自动参会通知须明确确认本版范围、名单和通知渠道")
        return self


class Save(Draft):
    preview_digest: Digest


def policy(c: Connection, tenant: UUID, recurrence: UUID) -> Any:
    t = tables.meeting_generation_policies
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.recurrence_id == recurrence))
        .mappings()
        .one_or_none()
    )


def review(
    c: Connection, ctx: AuthContext, project: UUID, id: UUID, draft: Draft, now: datetime
) -> dict[str, Any]:
    row = recurrence_record(c, ctx, project, id)
    old = policy(c, ctx.tenant.id, id)
    if draft.expected_policy_digest != (digest(_plain(old)) if old else None):
        raise MeetingStateError("自动生成配置或运行状态已变化，请重新读取")
    if draft.expected_recurrence_digest != digest(_plain(row)):
        raise MeetingStateError("周期时间或默认名单已变化，请重新核对")
    rec = _recurrence(row)
    today = now.astimezone(ZoneInfo(rec.timezone)).date()
    if draft.status == "enabled":
        if rec.status != "active" or draft.active_until < today:
            raise MeetingStateError("请启用周期并填写尚未过期的自动生成期限")
        validate_people(c, ctx, project, rec)
    lower, upper = (
        max(today, draft.active_from),
        min(today + timedelta(days=draft.lead_days), draft.active_until),
    )
    items = []
    skipped = []
    existing: dict[date, Any] = {}
    if draft.status == "enabled" and lower <= upper:
        existing = existing_in_window(c, ctx, project, rec, Window(since=lower, through=upper))
        for day in occurrences_between(rec, start=lower, end=upper):
            if day in existing:
                items.append(existing_item(existing[day]))
                continue
            start, end = occurrence_times(rec, day)
            if start <= now:
                skipped.append(str(day))
                continue
            items.append(
                {"date": str(day), "start_at": start.isoformat(), "end_at": end.isoformat()}
            )
    external_provider = (
        draft.conference_provider
        if draft.status == "enabled"
        else old["conference_provider"]
        if old
        else None
    )
    external_identity = None
    if external_provider is not None:
        external_identity = (
            conferences.identity(c, ctx, get_settings(), external_provider)
            if draft.status == "enabled"
            else old["conference_identity"]
        )
    queued = recurring_conferences.pending(c, ctx.tenant.id, old["id"]) if old else []
    person_ids = (
        {ctx.user.id}
        | {UUID(p["user_id"]) for p in rec.default_participants}
        | {UUID(p["owner_user_id"]) for p in rec.agenda_template if p.get("owner_user_id")}
    )
    if old:
        person_ids.add(old["organizer_user_id"])
    people = {
        str(p.id): p.display_name
        for p in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == ctx.tenant.id,
                tables.users.c.id.in_(person_ids),
            )
        )
    }
    notice_scope = (
        recurring_notifications.notification_scope(
            c, ctx, project, row, draft.notification_mode, get_settings()
        )
        if draft.status == "enabled"
        else old["notification_scope"]
        if old
        else None
    )
    result = {
        "notification_scope": notice_scope,
        "notification_delivery_enabled": get_settings().dingtalk_delivery_enabled,
        "conference_provider": external_provider,
        "conference_identity": external_identity,
        "conference_service_enabled": conferences.enabled(get_settings(), external_provider)
        if external_provider
        else False,
        "pending_conference_requests": [
            {
                "id": str(item["id"]),
                "meeting_id": str(item["meeting_id"]),
                "title": item["snapshot"]["meeting"]["title"],
            }
            for item in queued
        ],
        "people": people,
        "effective_start_date": str(rec.start_date),
        "before": _plain(old) if old else None,
        "record": _plain(row),
        "organizer_user_id": str(ctx.user.id)
        if draft.status == "enabled" or not old
        else str(old["organizer_user_id"]),
        "since": str(lower),
        "through": str(upper),
        "items": items,
        "timezone": rec.timezone,
        "today": str(today),
        "skipped_elapsed_dates": skipped,
        "retained_items": [
            existing_item(r)
            for day, r in existing.items()
            if str(day) not in {item["date"] for item in items}
        ],
        "status": draft.status,
        "active_from": str(draft.active_from),
        "active_until": str(draft.active_until),
        "lead_days": draft.lead_days,
    }
    return {**result, "preview_digest": digest(result)}


def read(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    id: UUID,
    *,
    service_enabled: bool,
    before: int | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        project_status = authorize(c, ctx, project)
        row = recurrence_record(c, ctx, project, id)
        current = policy(c, ctx.tenant.id, id)
        a = tables.audit_log
        q = select(
            a.c.id,
            a.c.timestamp,
            a.c.actor_user_id,
            a.c.action,
            a.c.before_snapshot,
            a.c.after_snapshot,
            a.c.context,
        ).where(
            a.c.tenant_id == ctx.tenant.id,
            a.c.project_id == project,
            a.c.entity_id == id,
            a.c.action.in_((CHANGE, SCAN)),
        )
        if before is not None:
            q = q.where(a.c.id < before)
        rows = list(c.execute(q.order_by(a.c.id.desc()).limit(21)).mappings())
        organizer = None
        if current:
            organizer = c.execute(
                select(tables.users.c.display_name).where(
                    tables.users.c.tenant_id == ctx.tenant.id,
                    tables.users.c.id == current["organizer_user_id"],
                )
            ).scalar_one()
        return {
            "policy": _plain(current) if current else None,
            "record": _plain(row),
            "effective_start_date": str(_recurrence(row).start_date),
            "policy_digest": digest(_plain(current)) if current else None,
            "recurrence_digest": digest(_plain(row)),
            "organizer_name": organizer,
            "actor_name": ctx.user.display_name,
            "actor_id": str(ctx.user.id),
            "today": str(datetime.now(UTC).astimezone(ZoneInfo(row["timezone"])).date()),
            "configuration_changed": bool(
                current and current["recurrence_digest"] != digest(_plain(row))
            ),
            "service_enabled": service_enabled,
            "conference_services": {
                provider: conferences.enabled(get_settings(), provider)
                for provider in ("dingtalk", "tencent_meeting")
            },
            "can_manage": is_allowed(ctx.user.role, Action.MEETING_MANAGE)
            and project_status not in ("completed", "archived"),
            "history": [_plain(r) for r in rows[:20]],
            "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
        }


def preview(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, draft: Draft
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, ctx, project, write=True)
        return review(c, ctx, project, id, draft, datetime.now(UTC))


def save(engine: Engine, ctx: AuthContext, project: UUID, id: UUID, draft: Save) -> dict[str, Any]:
    excluded = (
        {"notification_mode", "authorize_notifications"}
        if draft.notification_mode == "none" and not draft.authorize_notifications
        else set()
    )
    if draft.conference_provider is None and not draft.authorize_external_conference:
        excluded |= {"conference_provider", "authorize_external_conference"}
    signature = digest(
        {
            "recurrence_id": str(id),
            **draft.model_dump(
                mode="json",
                exclude=excluded,
            ),
        }
    )
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingStateError("项目不存在")
        authorize(c, ctx, project, write=True)
        prior = replay(c, ctx, project, CHANGE, draft.request_id, signature)
        if prior:
            return prior
        now = datetime.now(UTC)
        viewed = review(c, ctx, project, id, draft, now)
        if viewed["preview_digest"] != draft.preview_digest:
            raise MeetingStateError("预览范围或周期配置已变化，请重新核对")
        old = policy(c, ctx.tenant.id, id)
        row = recurrence_record(c, ctx, project, id)
        t = tables.meeting_generation_policies
        withdrawn = recurring_conferences.withdraw_pending(c, ctx, old, now) if old else []
        values = dict(
            notification_scope=viewed["notification_scope"],
            conference_provider=viewed["conference_provider"],
            conference_identity=viewed["conference_identity"],
            version=old["version"] + 1 if old else 1,
            status=draft.status,
            organizer_user_id=ctx.user.id
            if draft.status == "enabled" or not old
            else old["organizer_user_id"],
            organizer_auth_version=ctx.user.auth_version
            if draft.status == "enabled" or not old
            else old["organizer_auth_version"],
            active_from=draft.active_from,
            active_until=draft.active_until,
            lead_days=draft.lead_days,
            recurrence_digest=digest(_plain(row)),
            recurrence_snapshot=_plain(row),
            next_check_at=now if draft.status == "enabled" else None,
            failure_count=0,
            last_scan_at=None,
            last_error_code=None,
            updated_at=now,
        )
        if old:
            c.execute(
                t.update()
                .where(t.c.tenant_id == ctx.tenant.id, t.c.id == old["id"])
                .values(**values)
            )
        else:
            c.execute(
                t.insert().values(
                    id=uuid4(),
                    tenant_id=ctx.tenant.id,
                    project_id=project,
                    recurrence_id=id,
                    created_at=now,
                    **values,
                )
            )
        after = {
            "recurrence_id": str(id),
            "policy": _plain(policy(c, ctx.tenant.id, id)),
            "withdrawn_conference_request_ids": withdrawn,
        }
        written = EventAuditWriter(
            c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
        ).record(
            EventDraft(
                event_id=f"{CHANGE}:{id}:{draft.request_id}",
                event_type="MEETING_RECURRENCE_UPDATED",
                source="meeting_scheduling_service",
                entity_id=id,
                payload={"recurrence_id": str(id), "status": row["status"]},
            ),
            AuditDraft(
                action=CHANGE,
                before_snapshot=_plain(old) if old else None,
                after_snapshot=after,
                context={
                    "request_id": str(draft.request_id),
                    "request_digest": signature,
                    "reason": draft.reason,
                    "actor_name": ctx.user.display_name,
                    "organizer_name": viewed["people"].get(str(values["organizer_user_id"])),
                    "review": viewed,
                },
            ),
        )
        return {"request_id": str(draft.request_id), "audit_id": written.audit_row_id, **after}


class GenerationWorker:
    def __init__(self, engine: Engine, *, enabled: bool = False, settings: Settings | None = None):
        self.engine = engine
        self.enabled = enabled
        self.settings = settings

    def run_next(self) -> bool:
        if not self.enabled:
            return False
        now = datetime.now(UTC)
        t = tables.meeting_generation_policies
        with self.engine.connect() as c:
            candidates = list(
                c.execute(
                    select(t)
                    .where(t.c.status == "enabled", t.c.next_check_at <= now)
                    .order_by(t.c.next_check_at, t.c.id)
                    .limit(20)
                ).mappings()
            )
        for candidate in candidates:
            ctx = AuthRepository(self.engine).find_user_context(candidate["organizer_user_id"])
            with self.engine.begin() as c:
                lock = c.execute(
                    select(tables.projects.c.id)
                    .where(
                        tables.projects.c.tenant_id == candidate["tenant_id"],
                        tables.projects.c.id == candidate["project_id"],
                    )
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if lock is None:
                    continue
                current = policy(c, candidate["tenant_id"], candidate["recurrence_id"])
                if not current or current["status"] != "enabled" or current["next_check_at"] > now:
                    continue
                if current["organizer_user_id"] != candidate["organizer_user_id"]:
                    continue
                self._scan(c, current, ctx, now)
                return True
        return False

    def _scan(self, c: Connection, row: Any, ctx: AuthContext | None, now: datetime) -> None:
        result: dict[str, Any] = {"items": [], "skipped_elapsed_dates": [], "outcome": "generated"}
        next_at: datetime | None = None
        status, code, failure_count = "enabled", None, 0
        try:
            # Every materialisation and its receipt either commit together or roll back.
            with c.begin_nested():
                if (
                    ctx is None
                    or ctx.tenant.id != row["tenant_id"]
                    or ctx.tenant.status != "active"
                    or not ctx.user.is_active
                ):
                    raise KnowledgeAccessError("自动生成组织者或租户当前不可用")
                authorize(c, ctx, row["project_id"], write=True)
                tenant_status = c.execute(
                    select(tables.tenants.c.status).where(tables.tenants.c.id == row["tenant_id"])
                ).scalar_one()
                if tenant_status != "active":
                    raise KnowledgeAccessError("当前租户不可继续自动生成")
                version = c.execute(
                    select(tables.users.c.auth_version).where(
                        tables.users.c.tenant_id == row["tenant_id"],
                        tables.users.c.id == row["organizer_user_id"],
                    )
                ).scalar_one()
                if version != row["organizer_auth_version"]:
                    raise KnowledgeAccessError("组织者身份凭据已变化，需由本人重新确认")
                source = recurrence_record(c, ctx, row["project_id"], row["recurrence_id"])
                if (
                    digest(_plain(source)) != row["recurrence_digest"]
                    or source["status"] != "active"
                ):
                    raise MeetingStateError("周期配置已变化或暂停，请重新确认自动生成")
                rec = _recurrence(source)
                validate_people(c, ctx, row["project_id"], rec)
                if row["conference_provider"] is not None:
                    external_identity = conferences.identity(
                        c, ctx, self.settings or get_settings(), row["conference_provider"]
                    )
                    if external_identity != row["conference_identity"]:
                        raise MeetingStateError("周期外部预约的本人账号已变化，请重新核对")
                zone = ZoneInfo(rec.timezone)
                today = now.astimezone(zone).date()
                if today > row["active_until"]:
                    status, result["outcome"] = "paused", "expired"
                else:
                    since, through = (
                        max(today, row["active_from"]),
                        min(today + timedelta(days=row["lead_days"]), row["active_until"]),
                    )
                    result.update(since=str(since), through=str(through), timezone=rec.timezone)
                    service = MeetingSchedulingService(self.engine)
                    existing = (
                        existing_in_window(
                            c, ctx, row["project_id"], rec, Window(since=since, through=through)
                        )
                        if since <= through
                        else {}
                    )
                    for day in occurrences_between(rec, start=since, end=through):
                        start, _ = (
                            (existing[day]["scheduled_start_at"], existing[day]["scheduled_end_at"])
                            if day in existing
                            else occurrence_times(rec, day)
                        )
                        if day not in existing and start <= now:
                            result["skipped_elapsed_dates"].append(str(day))
                            continue
                        generated = service._materialise(
                            tenant_id=row["tenant_id"],
                            recurrence=rec,
                            occurrence=day,
                            actor_user_id=ctx.user.id,
                            now=now,
                            connection=c,
                        )
                        conference = (
                            recurring_conferences.enqueue(
                                c,
                                ctx,
                                row,
                                generated.meeting.id,
                                self.settings or get_settings(),
                                now,
                            )
                            if generated.created and row["conference_provider"] is not None
                            else None
                        )
                        notification = (
                            recurring_notifications.local(
                                c,
                                ctx,
                                row,
                                generated.meeting.id,
                                self.settings or get_settings(),
                                now,
                            )
                            if generated.created
                            else None
                        )
                        result["items"].append(
                            {
                                "notification": notification,
                                "conference": conference,
                                "date": str(day),
                                "meeting_id": str(generated.meeting.id),
                                "created": generated.created,
                                "status": generated.meeting.status,
                                "archived": generated.meeting.archived_at is not None,
                                "deleted": generated.meeting.deleted_at is not None,
                                "start_at": generated.meeting.scheduled_start_at.isoformat(),
                                "end_at": generated.meeting.scheduled_end_at.isoformat(),
                            }
                        )
                    included = {item["date"] for item in result["items"]}
                    result["retained_items"] = [
                        existing_item(r) for day, r in existing.items() if str(day) not in included
                    ]
                    next_at = datetime.combine(
                        today + timedelta(days=1), time(0, 5), zone
                    ).astimezone(UTC)
        except (
            KnowledgeAccessError,
            KnowledgeVersionError,
            MeetingScopeError,
            MeetingStateError,
            RecurrenceValidationError,
        ) as error:
            status, code, result = (
                "attention",
                "RECHECK_REQUIRED",
                {"outcome": "needs_review", "message": str(error), "items": []},
            )
        except Exception:
            failure_count = min(row["failure_count"] + 1, 3)
            status = "attention" if failure_count >= 3 else "enabled"
            code, result = "GENERATION_FAILED", {"outcome": "failed", "items": []}
            next_at = now + timedelta(minutes=15 * failure_count) if status == "enabled" else None
        t = tables.meeting_generation_policies
        c.execute(
            t.update()
            .where(t.c.tenant_id == row["tenant_id"], t.c.id == row["id"])
            .values(
                status=status,
                next_check_at=next_at if status == "enabled" else None,
                last_scan_at=now,
                failure_count=failure_count,
                last_error_code=code,
                updated_at=now,
            )
        )
        run_id = uuid4()
        EventAuditWriter(
            c, tenant_id=row["tenant_id"], actor_user_id=None, project_id=row["project_id"]
        ).record(
            EventDraft(
                event_id=f"{SCAN}:{row['id']}:{run_id}",
                event_type="MEETING_RECURRENCE_UPDATED",
                source="meeting_scheduling_service",
                entity_id=row["recurrence_id"],
                payload={"recurrence_id": str(row["recurrence_id"]), "status": status},
            ),
            AuditDraft(
                action=SCAN,
                before_snapshot=_plain(row),
                after_snapshot={
                    "run_id": str(run_id),
                    "policy_version": row["version"],
                    "organizer_user_id": str(row["organizer_user_id"]),
                    "status": status,
                    "error_code": code,
                    "next_check_at": next_at.isoformat()
                    if status == "enabled" and next_at
                    else None,
                    **result,
                },
                context={
                    "trigger": "automatic_generation_with_conference"
                    if row["conference_provider"]
                    else "automatic_local_generation",
                    "organizer_name": ctx.user.display_name if ctx else None,
                },
            ),
        )
