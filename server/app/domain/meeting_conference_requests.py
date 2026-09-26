"""Explicit project meeting conference requests and named ambiguity resolution."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain import tencent_meeting_bindings
from app.domain.meeting_recurrence_commands import authorize
from app.domain.meeting_rescheduling import external_signature, record
from app.domain.meetings import MeetingNotFoundError, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.dingtalk_conference import valid_booking as dingtalk_valid_booking
from app.integrations.tencent_conference import valid_booking as tencent_valid_booking
from app.settings import Settings

T = tables.meeting_conference_requests
ACTIVE = ("pending", "sending", "uncertain")
FIELDS = (
    "id",
    "tenant_id",
    "project_id",
    "title",
    "meeting_type",
    "status",
    "scheduled_start_at",
    "scheduled_end_at",
    "organizer_user_id",
    "external_provider",
    "external_meeting_id",
    "external_join_url",
    "external_bound_at",
    "archived_at",
    "deleted_at",
)


class Draft(Contract):
    request_id: UUID
    provider: Literal["dingtalk", "tencent_meeting"] = "dingtalk"
    operation: Literal["create", "update", "cancel", "query"]
    expected_digest: Digest
    reason: Text


class Submit(Draft):
    preview_digest: Digest
    authorize_external_operation: Literal[True]


class Resolve(Contract):
    request_id: UUID
    target_request_id: UUID
    expected_digest: Digest
    outcome: Literal["withdraw", "not_executed", "completed"]
    evidence: Text
    external_meeting_id: str | None = Field(default=None, min_length=1, max_length=256)
    join_url: str | None = Field(default=None, max_length=1024)
    confirmed: Literal[True]


def meeting_snapshot(row: Any) -> dict[str, Any]:
    return _plain({key: row[key] for key in FIELDS})


def lock_key(id: UUID) -> int:
    return int.from_bytes(id.bytes[:8], "big", signed=True)


def scope(ctx: AuthContext, project: UUID, meeting: UUID) -> tuple[Any, ...]:
    return T.c.tenant_id == ctx.tenant.id, T.c.project_id == project, T.c.meeting_id == meeting


def enabled(settings: Settings, provider: str) -> bool:
    return (
        settings.tencent_meeting_enabled
        if provider == "tencent_meeting"
        else settings.dingtalk_conference_enabled
    )


def valid_booking(provider: str, id: object, url: object) -> bool:
    return (
        tencent_valid_booking(id, url)
        if provider == "tencent_meeting"
        else dingtalk_valid_booking(id, url)
    )


def remote_key(provider: str) -> str:
    return "meeting_id" if provider == "tencent_meeting" else "scheduleConferenceId"


def identity(
    c: Connection, ctx: AuthContext, settings: Settings, provider: str = "dingtalk"
) -> dict[str, Any]:
    if provider == "tencent_meeting":
        return tencent_meeting_bindings.identity(c, ctx, settings)
    b, u = tables.dingtalk_tenant_bindings, tables.dingtalk_user_bindings
    tenant = (
        c.execute(select(b).where(b.c.tenant_id == ctx.tenant.id, b.c.status == "active"))
        .mappings()
        .one_or_none()
    )
    user = (
        c.execute(
            select(u).where(
                u.c.tenant_id == ctx.tenant.id, u.c.user_id == ctx.user.id, u.c.status == "active"
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        tenant is None
        or user is None
        or not user["union_id"]
        or not settings.dingtalk_client_id
        or settings.dingtalk_client_secret is None
        or tenant["client_id"] != settings.dingtalk_client_id
        or tenant["corp_id"] != user["corp_id"]
    ):
        raise MeetingStateError("当前租户应用或本人钉钉绑定未就绪，请先完成原集成配置")
    return {
        "corp_id": tenant["corp_id"],
        "client_id": tenant["client_id"],
        "union_id": user["union_id"],
        "binding_id": str(user["id"]),
        "bound_at": user["bound_at"].isoformat(),
        "actor_name": ctx.user.display_name,
    }


def origin(c: Connection, ctx: AuthContext, project: UUID, meeting: UUID) -> Any:
    return (
        c.execute(
            select(T)
            .where(
                *scope(ctx, project, meeting),
                T.c.operation == "create",
                T.c.result["external_meeting_id"].astext.is_not(None),
            )
            .order_by(T.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def request_snapshot(
    c: Connection, ctx: AuthContext, project: UUID, meeting: UUID, draft: Draft, settings: Settings
) -> dict[str, Any]:
    authorize(c, ctx, project, write=True)
    row = record(c, ctx, project, meeting)
    snap = meeting_snapshot(row)
    if digest(snap) != draft.expected_digest:
        raise MeetingStateError("会议已变化，请刷新并重新预览")
    if row["deleted_at"] or row["archived_at"]:
        raise MeetingStateError("已归档或删除会议保留原记录")
    actual_version = c.execute(
        select(tables.users.c.auth_version).where(
            tables.users.c.tenant_id == ctx.tenant.id,
            tables.users.c.id == ctx.user.id,
            tables.users.c.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if actual_version != ctx.user.auth_version:
        raise MeetingStateError("办理人授权已变化，请重新登录后核对")
    current = identity(c, ctx, settings, draft.provider)
    # Conference credentials always represent the actual, named requester.
    member = c.execute(
        select(tables.project_members.c.user_id).where(
            tables.project_members.c.tenant_id == ctx.tenant.id,
            tables.project_members.c.project_id == project,
            tables.project_members.c.user_id == ctx.user.id,
        )
    ).scalar_one_or_none()
    if member is None or not ctx.user.is_active or ctx.tenant.status != "active":
        raise MeetingStateError("外部办理人须为当前有效项目成员")
    old = origin(c, ctx, project, meeting)
    payload: dict[str, Any] = (
        {"userid": current["external_user_id"], "instanceid": 5}
        if draft.provider == "tencent_meeting"
        else {"creatorUnionId": current["union_id"]}
    )
    remote_field = remote_key(draft.provider)
    if draft.operation == "create":
        if old is not None or row["external_provider"] or row["status"] != "scheduled":
            raise MeetingStateError("本场已有外部预约记录、绑定或不再可预约，请回查原会议")
        if row["organizer_user_id"] != ctx.user.id:
            raise MeetingStateError("仅会议组织人本人可使用自己的已确认账号创建预约")
    else:
        if old is None or old["actor_user_id"] != ctx.user.id:
            raise MeetingStateError("请由本入口原预约人办理；手工绑定会议沿用原提供方人工核对")
        if old["provider"] != draft.provider:
            raise MeetingStateError("请在原预约提供方办理，不得切换其他账号操作原会议")
        old_identity = old["snapshot"]["identity"]
        identity_fields = (
            ("app_id", "sdk_id", "application_fingerprint", "external_user_id", "binding_id")
            if draft.provider == "tencent_meeting"
            else ("corp_id", "client_id", "union_id", "binding_id", "bound_at")
        )
        if any(current[k] != old_identity[k] for k in identity_fields):
            raise MeetingStateError("原预约人账号绑定已变化，请在原提供方人工核对")
        payload[remote_field] = old["result"]["external_meeting_id"]
        if draft.operation == "update" and (
            row["status"] != "scheduled"
            or row["external_provider"] != draft.provider
            or row["external_meeting_id"] != payload[remote_field]
        ):
            raise MeetingStateError("仅当前绑定且尚未开始的原预约可同步改期")
        if draft.operation == "cancel" and row["status"] != "cancelled":
            raise MeetingStateError("请先在本地取消本场会议，再单独确认外部取消")
    if draft.operation in ("create", "update"):
        if row["scheduled_start_at"] <= datetime.now(UTC):
            raise MeetingStateError("仅可提交未来的会议安排")
        if draft.provider == "tencent_meeting":
            if row["scheduled_start_at"].microsecond or row["scheduled_end_at"].microsecond:
                raise MeetingStateError("腾讯会议按整秒预约，请先将本地起止时间调整为整秒")
            payload.update(
                subject=row["title"],
                start_time=str(int(row["scheduled_start_at"].timestamp())),
                end_time=str(int(row["scheduled_end_at"].timestamp())),
            )
            if draft.operation == "create":
                payload.update(type=0, meeting_type=0, settings={"auto_record_type": "none"})
        else:
            payload.update(
                title=row["title"],
                startTime=int(row["scheduled_start_at"].timestamp() * 1000),
                endTime=int(row["scheduled_end_at"].timestamp() * 1000),
            )
    if draft.provider == "tencent_meeting" and draft.operation == "cancel":
        payload.update(reason_code=1, reason_detail=draft.reason)
    return {
        **({"provider": "tencent_meeting"} if draft.provider == "tencent_meeting" else {}),
        "meeting": snap,
        "identity": current,
        "payload": payload,
        "actor_auth_version": ctx.user.auth_version,
        "reason": draft.reason,
        "operation": draft.operation,
        "origin_request_id": str(old["id"]) if old else None,
    }


def emit(c: Connection, row: Any, action: str, result: Any, actor: UUID | None) -> None:
    meeting = row["snapshot"]["meeting"]
    EventAuditWriter(
        c, tenant_id=row["tenant_id"], project_id=row["project_id"], actor_user_id=actor
    ).record(
        EventDraft(
            event_id=f"meeting-conference:{row['id']}:{action}",
            event_type="MEETING_STATE_CHANGED",
            source="meeting_service",
            entity_id=row["meeting_id"],
            payload={
                "meeting_id": str(row["meeting_id"]),
                "meeting_type": meeting["meeting_type"],
                "status": meeting["status"],
                "action": action,
            },
        ),
        AuditDraft(
            action=f"meeting.conference_request_{action}",
            after_snapshot=_plain(result),
            context={
                "request_id": str(row["id"]),
                "actor_name": row["snapshot"]["identity"]["actor_name"],
                "operation": row["operation"],
                "reason": row["snapshot"]["reason"],
            },
        ),
    )


def read(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    meeting: UUID,
    settings: Settings,
    before: int | None = None,
    provider: Literal["dingtalk", "tencent_meeting"] = "dingtalk",
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        status = authorize(c, ctx, project)
        row = record(c, ctx, project, meeting)
        q = select(T).where(*scope(ctx, project, meeting))
        if before is not None:
            q = q.where(T.c.sequence < before)
        rows = list(c.execute(q.order_by(T.c.sequence.desc()).limit(21)).mappings())
        active = (
            c.execute(select(T).where(*scope(ctx, project, meeting), T.c.status.in_(ACTIVE)))
            .mappings()
            .one_or_none()
        )
        original = origin(c, ctx, project, meeting)
        provider = (
            active["provider"]
            if active is not None
            else original["provider"]
            if original is not None
            else provider
        )
        try:
            who, problem = identity(c, ctx, settings, provider), None
        except MeetingStateError as error:
            who, problem = None, str(error)
        return {
            "meeting": meeting_snapshot(row),
            "digest": digest(meeting_snapshot(row)),
            "enabled": enabled(settings, provider),
            "selected_provider": provider,
            "identity": who,
            "configuration_problem": problem,
            "can_manage": is_allowed(ctx.user.role, Action.MEETING_MANAGE)
            and status not in ("completed", "archived"),
            "current_user_id": str(ctx.user.id),
            "active": {**_plain(active), "digest": digest(_plain(active))} if active else None,
            "origin": _plain(original) if original is not None else None,
            "items": [_plain(r) for r in rows[:20]],
            "next_before_id": rows[19]["sequence"] if len(rows) > 20 else None,
        }


def preview(
    engine: Engine, ctx: AuthContext, project: UUID, meeting: UUID, draft: Draft, settings: Settings
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        snap = request_snapshot(c, ctx, project, meeting, draft, settings)
        return {
            "snapshot": snap,
            "preview_digest": digest(snap),
            "enabled": enabled(settings, draft.provider),
        }


def submit(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    meeting: UUID,
    command: Submit,
    settings: Settings,
) -> dict[str, Any]:
    signature = digest(
        command.model_dump(
            mode="json", exclude={"provider"} if command.provider == "dingtalk" else set()
        )
    )
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        authorize(c, ctx, project, write=True)
        prior = c.execute(select(T).where(T.c.id == command.request_id)).mappings().one_or_none()
        if prior:
            if (
                prior["tenant_id"],
                prior["project_id"],
                prior["meeting_id"],
                prior["actor_user_id"],
                prior["request_digest"],
            ) != (ctx.tenant.id, project, meeting, ctx.user.id, signature):
                raise MeetingStateError("请求标识已被使用，请核对原请求")
            return _plain(prior)
        if not enabled(settings, command.provider):
            raise MeetingStateError("外部会议服务尚未启用；可预览，本次不会排队外发")
        if c.execute(
            select(T.c.id).where(*scope(ctx, project, meeting), T.c.status.in_(ACTIVE))
        ).first():
            raise MeetingStateError("本场仍有待办或结果不明请求，请先处理原请求")
        snap = request_snapshot(c, ctx, project, meeting, command, settings)
        if digest(snap) != command.preview_digest:
            raise MeetingStateError("会议或账号绑定已变化，请重新预览")
        values = dict(
            id=command.request_id,
            provider=command.provider,
            tenant_id=ctx.tenant.id,
            project_id=project,
            meeting_id=meeting,
            actor_user_id=ctx.user.id,
            actor_auth_version=ctx.user.auth_version,
            operation=command.operation,
            request_digest=signature,
            snapshot=snap,
            status="pending",
            created_at=datetime.now(UTC),
        )
        saved = c.execute(T.insert().values(**values).returning(T)).mappings().one()
        emit(c, saved, "queued", saved, ctx.user.id)
        return _plain(saved)


def apply_booking(c: Connection, row: Any, result: dict[str, Any], now: datetime) -> bool:
    """Attach only to the exact reviewed local meeting; preserve stale remote results."""
    t = tables.meetings
    current = (
        c.execute(
            select(t).where(
                t.c.tenant_id == row["tenant_id"],
                t.c.project_id == row["project_id"],
                t.c.id == row["meeting_id"],
            )
        )
        .mappings()
        .one()
    )
    if meeting_snapshot(current) != row["snapshot"]["meeting"]:
        return False
    if row["operation"] == "create":
        c.execute(
            t.update()
            .where(t.c.tenant_id == row["tenant_id"], t.c.id == row["meeting_id"])
            .values(
                external_provider=row["provider"],
                external_meeting_id=result["external_meeting_id"],
                external_join_url=result["join_url"],
                external_bound_at=now,
                external_bound_by_user_id=row["actor_user_id"],
                source=row["provider"],
                updated_at=now,
            )
        )
    return True


def resolve(
    engine: Engine, ctx: AuthContext, project: UUID, meeting: UUID, command: Resolve
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        authorize(c, ctx, project, write=True)
        row = (
            c.execute(
                select(T).where(*scope(ctx, project, meeting), T.c.id == command.target_request_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise MeetingNotFoundError
        # A live worker holds the matching session lock across network IO and receipt commit.
        if not c.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key(row["id"])}
        ).scalar_one():
            raise MeetingStateError("外部请求仍在办理，请稍后刷新结果")
        if row["actor_user_id"] != ctx.user.id:
            raise MeetingStateError("请由原发起人核对该请求的外部结果")
        signature = digest(command.model_dump(mode="json"))
        if row["result"] and row["result"].get("resolution_request_id") == str(command.request_id):
            if row["result"].get("resolution_digest") != signature:
                raise MeetingStateError("请按原核对请求重试")
            return _plain(row)
        if digest(_plain(row)) != command.expected_digest:
            raise MeetingStateError("原请求已变化，请刷新后核对")
        if (command.outcome == "withdraw" and row["status"] != "pending") or (
            command.outcome != "withdraw" and row["status"] != "uncertain"
        ):
            raise MeetingStateError("仅未派发请求可撤回；结果不明须核对实际外部结果")
        result: dict[str, Any] = {
            "method": "human_attestation",
            "outcome": command.outcome,
            "evidence": command.evidence,
            "resolution_request_id": str(command.request_id),
            "resolution_digest": signature,
            "confirmed_by": str(ctx.user.id),
            "confirmed_name": ctx.user.display_name,
        }
        now = datetime.now(UTC)
        if command.outcome == "completed":
            if row["operation"] == "query":
                raise MeetingStateError("查询失败请重新查询，无需人工宣告成功")
            if row["operation"] == "create":
                if not valid_booking(
                    row["provider"], command.external_meeting_id, command.join_url
                ):
                    raise MeetingStateError("请填写在原提供方核对的预约ID及HTTPS入会地址")
                result.update(
                    external_meeting_id=command.external_meeting_id, join_url=command.join_url
                )
            else:
                result["external_meeting_id"] = row["snapshot"]["payload"][
                    remote_key(row["provider"])
                ]
            try:
                with c.begin_nested():
                    result["matches_current_meeting"] = apply_booking(c, row, result, now)
            except IntegrityError:
                result["matches_current_meeting"] = False
                result["local_binding_error"] = "CONFERENCE_LOCAL_BINDING_REQUIRES_REVIEW"
            if result["matches_current_meeting"]:
                current = record(c, ctx, project, meeting)
                result["current_signature"] = external_signature(current)
                result["current_meeting_digest"] = digest(meeting_snapshot(current))
        if command.outcome == "completed":
            from app.domain.meeting_recurring_notifications import after_booking
            from app.settings import get_settings

            after_booking(c, ctx, row, result, get_settings(), now)
        status = "withdrawn" if command.outcome == "withdraw" else "resolved"
        saved = (
            c.execute(
                T.update()
                .where(T.c.id == row["id"])
                .values(status=status, result=result, completed_at=now)
                .returning(T)
            )
            .mappings()
            .one()
        )
        emit(c, saved, "resolved", saved, ctx.user.id)
        return _plain(saved)
