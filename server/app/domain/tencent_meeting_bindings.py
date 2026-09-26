"""Admin-attested enterprise identity mapping, activated separately by the named user."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.settings import Settings

T = tables.tencent_meeting_bindings
MAPPING_FIELDS = (
    "app_id",
    "sdk_id",
    "application_fingerprint",
    "external_user_id",
    "external_display_name",
)


class Command(Contract):
    request_id: UUID
    user_id: UUID
    expected_binding_id: UUID | None = None
    action: Literal["register", "confirm", "revoke"]
    external_user_id: str | None = Field(
        default=None, min_length=1, max_length=256, pattern=r"^\S+$"
    )
    external_display_name: str | None = Field(
        default=None, min_length=1, max_length=256, pattern=r"\S"
    )
    evidence: Text
    identity_checked: Literal[True]


def configured(settings: Settings, tenant: UUID) -> bool:
    return bool(
        settings.tencent_meeting_tenant_id == tenant
        and settings.tencent_meeting_app_id
        and settings.tencent_meeting_key_id
        and settings.tencent_meeting_secret
    )


def fingerprint(settings: Settings) -> str:
    return digest(
        {
            "app_id": settings.tencent_meeting_app_id,
            "sdk_id": settings.tencent_meeting_sdk_id or "",
            "application_key": settings.tencent_meeting_key_id,
        }
    )


def current(c: Connection, tenant: UUID, user: UUID) -> Any:
    return (
        c.execute(
            select(T)
            .where(T.c.tenant_id == tenant, T.c.user_id == user)
            .order_by(T.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def identity(c: Connection, ctx: AuthContext, settings: Settings) -> dict[str, Any]:
    row = current(c, ctx.tenant.id, ctx.user.id)
    if (
        not configured(settings, ctx.tenant.id)
        or row is None
        or row["status"] != "active"
        or row["application_fingerprint"] != fingerprint(settings)
    ):
        raise MeetingStateError(
            "腾讯会议企业应用或本人账号映射尚未就绪，请先由管理员登记并由本人确认"
        )
    return {
        "app_id": row["app_id"],
        "sdk_id": row["sdk_id"],
        "external_user_id": row["external_user_id"],
        "external_display_name": row["external_display_name"],
        "binding_id": str(row["id"]),
        "application_fingerprint": row["application_fingerprint"],
        "actor_name": ctx.user.display_name,
        "corp_id": row["app_id"],
    }


def authorize(c: Connection, ctx: AuthContext, *, admin: bool = False) -> None:
    actual = c.execute(
        select(tables.users.c.role, tables.users.c.auth_version).where(
            tables.users.c.tenant_id == ctx.tenant.id,
            tables.users.c.id == ctx.user.id,
            tables.users.c.is_active.is_(True),
        )
    ).one_or_none()
    if (
        ctx.tenant.status != "active"
        or actual is None
        or actual.auth_version != ctx.user.auth_version
        or not is_allowed(actual.role, Action.INTEGRATION_MANAGE if admin else Action.MEETING_VIEW)
    ):
        raise ObjectPermissionDeniedError


def read(
    engine: Engine,
    ctx: AuthContext,
    settings: Settings,
    user: UUID | None = None,
    q: str = "",
    before: int | None = None,
) -> dict[str, Any]:
    target = user or ctx.user.id
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, ctx, admin=target != ctx.user.id)
        admin = is_allowed(ctx.user.role, Action.INTEGRATION_MANAGE)
        u = tables.users
        person = (
            c.execute(
                select(u.c.id, u.c.display_name, u.c.username, u.c.is_active).where(
                    u.c.tenant_id == ctx.tenant.id, u.c.id == target
                )
            )
            .mappings()
            .one_or_none()
        )
        if person is None:
            raise MeetingStateError("未找到本租户用户")
        query = select(T).where(T.c.tenant_id == ctx.tenant.id, T.c.user_id == target)
        if before is not None:
            query = query.where(T.c.version < before)
        rows = list(c.execute(query.order_by(T.c.version.desc()).limit(21)).mappings())
        users = []
        if admin:
            users_query = select(u.c.id, u.c.display_name, u.c.username, u.c.is_active).where(
                u.c.tenant_id == ctx.tenant.id
            )
            if q.strip():
                users_query = users_query.where(
                    or_(
                        u.c.username.icontains(q.strip(), autoescape=True),
                        u.c.display_name.icontains(q.strip(), autoescape=True),
                    )
                )
            users = [
                _plain(r)
                for r in c.execute(
                    users_query.order_by(u.c.display_name, u.c.id).limit(51)
                ).mappings()
            ]
        row = current(c, ctx.tenant.id, target)
        return {
            "current": _plain(row) if row else None,
            "person": _plain(person),
            "is_self": target == ctx.user.id,
            "can_manage": admin,
            "configured": configured(settings, ctx.tenant.id),
            "enabled": settings.tencent_meeting_enabled
            and settings.tencent_meeting_tenant_id == ctx.tenant.id,
            "app_id": settings.tencent_meeting_app_id
            if settings.tencent_meeting_tenant_id == ctx.tenant.id
            else None,
            "sdk_id": settings.tencent_meeting_sdk_id
            if settings.tencent_meeting_tenant_id == ctx.tenant.id
            else None,
            "items": [_plain(r) for r in rows[:20]],
            "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
            "users": users[:50],
            "more_users": len(users) > 50,
        }


def save(engine: Engine, ctx: AuthContext, settings: Settings, command: Command) -> dict[str, Any]:
    signature = digest(command.model_dump(mode="json"))
    with engine.begin() as c:
        tenant_status = c.execute(
            select(tables.tenants.c.status)
            .where(tables.tenants.c.id == ctx.tenant.id)
            .with_for_update()
        ).scalar_one()
        if tenant_status != "active":
            raise ObjectPermissionDeniedError
        authorize(c, ctx, admin=command.action == "register" or command.user_id != ctx.user.id)
        prior = c.execute(select(T).where(T.c.id == command.request_id)).mappings().one_or_none()
        if prior:
            if (prior["tenant_id"], prior["actor_user_id"], prior["request_digest"]) != (
                ctx.tenant.id,
                ctx.user.id,
                signature,
            ):
                raise MeetingStateError("请使用原请求和原内容重试")
            return _plain(prior)
        old = current(c, ctx.tenant.id, command.user_id)
        if (old["id"] if old else None) != command.expected_binding_id:
            raise MeetingStateError("账号映射已变化，请刷新后重新核对")
        person = (
            c.execute(
                select(tables.users).where(
                    tables.users.c.tenant_id == ctx.tenant.id, tables.users.c.id == command.user_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if person is None or (not person["is_active"] and command.action != "revoke"):
            raise MeetingStateError("请核对当前有效的本租户人员")
        if command.action == "register":
            if (
                not configured(settings, ctx.tenant.id)
                or not command.external_user_id
                or not command.external_display_name
            ):
                raise MeetingStateError("请先配置本租户企业应用并完整填写核对过的企业用户ID和姓名")
            mapping = {
                "app_id": settings.tencent_meeting_app_id,
                "sdk_id": settings.tencent_meeting_sdk_id or "",
                "application_fingerprint": fingerprint(settings),
                "external_user_id": command.external_user_id,
                "external_display_name": command.external_display_name,
            }
            status = "pending"
        else:
            if old is None or old["status"] == "revoked":
                raise MeetingStateError("当前没有可办理的账号映射")
            mapping = {key: old[key] for key in MAPPING_FIELDS}
            if command.action == "confirm":
                if command.user_id != ctx.user.id or old["status"] != "pending":
                    raise MeetingStateError("仅本人可确认管理员登记的待确认映射")
                if not configured(settings, ctx.tenant.id) or mapping[
                    "application_fingerprint"
                ] != fingerprint(settings):
                    raise MeetingStateError("企业应用配置已变化，请由管理员重新登记")
            status = "active" if command.action == "confirm" else "revoked"
        if status != "revoked":
            latest = (
                select(T)
                .where(T.c.tenant_id == ctx.tenant.id)
                .distinct(T.c.user_id)
                .order_by(T.c.user_id, T.c.version.desc())
                .subquery()
            )
            if c.execute(
                select(latest.c.id).where(
                    latest.c.user_id != command.user_id,
                    latest.c.app_id == mapping["app_id"],
                    latest.c.external_user_id == mapping["external_user_id"],
                    latest.c.status.in_(("active", "pending")),
                )
            ).first():
                raise MeetingStateError("该企业用户ID已登记给其他人员，请先核对并解除原映射")
        values = dict(
            id=command.request_id,
            tenant_id=ctx.tenant.id,
            user_id=command.user_id,
            version=(old["version"] + 1) if old else 1,
            status=status,
            **mapping,
            actor_user_id=ctx.user.id,
            actor_name=ctx.user.display_name,
            evidence=command.evidence,
            request_digest=signature,
            created_at=datetime.now(UTC),
        )
        row = c.execute(T.insert().values(**values).returning(T)).mappings().one()
        EventAuditWriter(c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id).record(
            EventDraft(
                event_id=f"tencent-identity:{command.request_id}",
                event_type="TENCENT_MEETING_IDENTITY_CHANGED",
                source="tencent_meeting_service",
                entity_id=command.user_id,
                payload={"user_id": str(command.user_id), "status": status},
            ),
            AuditDraft(
                action="tencent_meeting.identity_changed",
                before_snapshot=_plain(old) if old else None,
                after_snapshot=_plain(row),
                context={
                    "evidence": command.evidence,
                    "method": "admin_registration_and_self_confirmation",
                },
            ),
        )
        return _plain(row)
