"""Tenant-wide source ownership with licence and observation history preserved."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.preproject_responsibilities import Reassign as Reassign
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

AUDIT_ACTION = "research_source.responsibility.changed"


def record(c: Connection, context: AuthContext, id: UUID, *, lock: bool = False) -> Any:
    t = tables.research_sources
    q = select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == id)
    row = c.execute(q.with_for_update() if lock else q).mappings().one_or_none()
    if row is None:
        raise ProductWorkAccessError("研究来源不存在或不可访问")
    return row


def members(c: Connection, tenant: UUID) -> list[dict[str, Any]]:
    u = tables.users
    return [
        _plain(r)
        for r in c.execute(
            select(u.c.id, u.c.display_name)
            .where(
                u.c.tenant_id == tenant,
                u.c.is_active.is_(True),
                u.c.role.in_(
                    [role.value for role in Role if is_allowed(role, Action.RESEARCH_SOURCE_MANAGE)]
                ),
            )
            .order_by(u.c.display_name, u.c.id)
        ).mappings()
    ]


def history_statement(tenant: UUID, id: UUID, before: int | None = None) -> Any:
    a = tables.audit_log
    q = select(
        a.c.id,
        a.c.timestamp.label("created_at"),
        a.c.actor_user_id,
        a.c.before_snapshot,
        a.c.after_snapshot,
        a.c.context,
    ).where(
        a.c.tenant_id == tenant,
        a.c.entity_id == id,
        a.c.action == AUDIT_ACTION,
    )
    if before is not None:
        q = q.where(a.c.id < before)
    return q.order_by(a.c.id.desc()).limit(21)


def read(
    engine: Engine, context: AuthContext, id: UUID, before: int | None = None
) -> dict[str, Any]:
    _role(context, Action.EVIDENCE_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        row = record(c, context, id)
        names = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id == row["owner_user_id"],
                )
            ).mappings()
        }
        history = c.execute(history_statement(context.tenant.id, id, before)).mappings().all()
        return {
            "record": _plain(row),
            "digest": digest(_plain(row)),
            "people": names,
            "can_manage": row["status"] == "active"
            and is_allowed(context.user.role, Action.RESEARCH_SOURCE_MANAGE),
            "members": members(c, context.tenant.id),
            "responsibilities": [
                {
                    "role": "owner",
                    "key": None,
                    "label": "研究来源负责人",
                    "user_id": str(row["owner_user_id"]),
                }
            ],
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(engine: Engine, context: AuthContext, id: UUID, command: Reassign) -> dict[str, Any]:
    _role(context, Action.RESEARCH_SOURCE_MANAGE)
    if command.role != "owner" or command.key is not None:
        raise ProductWorkError("研究来源只接受负责人调整")
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"source-owner:{context.tenant.id}:{context.user.id}:{command.request_id}"},
        )
        before = record(c, context, id, lock=True)
        signature = digest({"source_id": str(id), **command.model_dump(mode="json")})
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.actor_user_id == context.user.id,
                    a.c.action == AUDIT_ACTION,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("此请求编号已用于其他来源责任调整")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        if digest(_plain(before)) != command.expected_digest:
            raise ProductWorkError("原来源资料或负责人已变化，请刷新后重新核对")
        if before["status"] != "active":
            raise ProductWorkError("停用来源保留原责任记录")
        if before["owner_user_id"] == command.user_id:
            raise ProductWorkError("请选择不同的接手人")
        if str(command.user_id) not in {r["id"] for r in members(c, context.tenant.id)}:
            raise ProductWorkError("接手人须为本租户有效且已有来源管理权限的成员")
        t = tables.research_sources
        after = (
            c.execute(
                t.update()
                .where(t.c.tenant_id == context.tenant.id, t.c.id == id)
                .values(
                    owner_user_id=command.user_id,
                    updated_at=datetime.now(UTC),
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        names = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        [context.user.id, before["owner_user_id"], command.user_id]
                    ),
                )
            ).mappings()
        }
        receipt = EventAuditWriter(
            c, tenant_id=context.tenant.id, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"source-owner:{id}:{context.user.id}:{command.request_id}",
                event_type="RESEARCH_SOURCE_CHANGED",
                source="evidence_service",
                entity_id=id,
                payload={
                    "source_id": str(id),
                    "source_type": before["source_type"],
                    "action": "responsibility_changed",
                },
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=_plain(before),
                after_snapshot=_plain(after),
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "role": "owner",
                    "responsibility_label": "研究来源负责人",
                    "people": names,
                    "previous_user_id": str(before["owner_user_id"]),
                    "next_user_id": str(command.user_id),
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": receipt.audit_row_id,
            "record": _plain(after),
        }
