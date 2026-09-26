"""Atomic owner succession through original reservation commands and immutable receipts."""

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.quality_responsibilities import Reassign as Reassign
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
    _project,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

AUDIT_ACTION = "resource_reservation.owner_transferred"


def record(c: Connection, tenant: UUID, project: UUID, id: UUID) -> Any:
    t = tables.resource_reservations
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("原预约不存在或不可访问")
    return row


def allowed(context: AuthContext, row: Any, project: Any) -> bool:
    if project["status"] in ("completed", "archived") or row["state"] not in (
        "proposed",
        "reserved",
    ):
        return False
    admin = is_allowed(context.user.role, Action.TENANT_MANAGE)
    if row["state"] == "reserved":
        return admin and project["status"] in ("approved", "active")
    return admin or row["owner_user_id"] == context.user.id


def members(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, str]]:
    u, m = tables.users, tables.project_members
    rows = c.execute(
        select(u.c.id, u.c.display_name, u.c.role)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(u.c.tenant_id == tenant, m.c.project_id == project, u.c.is_active.is_(True))
    ).mappings()
    return [
        {"id": str(r["id"]), "name": r["display_name"]}
        for r in rows
        if is_allowed(Role(r["role"]), Action.WORK_ITEM_EDIT)
    ]


def history_statement(tenant: UUID, project: UUID, id: UUID, before: int | None = None) -> Any:
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
        a.c.project_id == project,
        a.c.action == AUDIT_ACTION,
        or_(a.c.entity_id == id, a.c.context["replacement_id"].as_string() == str(id)),
    )
    if before is not None:
        q = q.where(a.c.id < before)
    return q.order_by(a.c.id.desc()).limit(21)


def read(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    _role(context, Action.WORK_ITEM_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        p = _project(c, context, project)
        row = record(c, context.tenant.id, project, id)
        owner = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == row["owner_user_id"],
            )
        ).scalar_one()
        resource = c.execute(
            select(tables.planning_resources.c.name).where(
                tables.planning_resources.c.tenant_id == context.tenant.id,
                tables.planning_resources.c.id == row["resource_id"],
            )
        ).scalar_one()
        history = (
            c.execute(history_statement(context.tenant.id, project, id, before)).mappings().all()
        )
        return {
            "record": {**_plain(row), "status": row["state"], "title": resource},
            "owner_name": owner,
            "digest": digest(_plain(row)),
            "can_reassign": is_allowed(context.user.role, Action.WORK_ITEM_EDIT)
            and allowed(context, row, p),
            "members": members(c, context.tenant.id, project),
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def transfer(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    try:
        return _transfer(engine, context, project, id, command)
    except IntegrityError as exc:
        raise ProductWorkError("预约移交未生效，旧预约仍保留；请核对容量与当前占用") from exc


def _transfer(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    _role(context, Action.WORK_ITEM_EDIT)
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {
                "key": (
                    f"reservation-owner:{context.tenant.id}:{context.user.id}:{command.request_id}"
                )
            },
        )
        p = _project(c, context, project, write=True)
        signature = digest(
            {
                "project_id": str(project),
                "reservation_id": str(id),
                **command.model_dump(mode="json"),
            }
        )
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
                raise ProductWorkError("此请求编号已用于另一项预约移交")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        c.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
        old = record(c, context.tenant.id, project, id)
        if not allowed(context, old, p):
            raise ProductWorkAccessError(
                "提案由原负责人或资源管理员移交；正式预约须由资源管理员在已批准或活动项目办理"
            )
        if digest(_plain(old)) != command.expected_digest:
            raise ProductWorkError("原预约已有变化，请刷新后重新核对")
        if str(command.owner_user_id) not in {
            r["id"] for r in members(c, context.tenant.id, project)
        }:
            raise ProductWorkError("接手人须为有办理权限的有效项目成员")
        if command.owner_user_id == old["owner_user_id"]:
            raise ProductWorkError("请选择不同的预约接手人")
        service = ResourceReservationService(engine)
        closed = service._act_in_transaction(
            c,
            context,
            project,
            id,
            ReservationAction(
                request_id=uuid5(command.request_id, "close-original"),
                expected_digest=command.expected_digest,
                action="release" if old["state"] == "reserved" else "cancel",
                reason=command.reason,
            ),
        )
        new = service._propose_in_transaction(
            c,
            context,
            project,
            ReservationDraft(
                request_id=uuid5(command.request_id, "new-owner-proposal"),
                node_id=old["node_id"],
                capacity_version_id=old["capacity_version_id"],
                window_start=old["window_start"],
                window_end=old["window_end"],
                parallel_units=old["parallel_units"],
                occupancy_policy=old["occupancy_policy"],
                basis=old["basis"],
            ),
            owner_user_id=command.owner_user_id,
        )
        if old["state"] == "reserved":
            new = service._act_in_transaction(
                c,
                context,
                project,
                UUID(new["id"]),
                ReservationAction(
                    request_id=uuid5(command.request_id, "approve-new-owner"),
                    expected_digest=new["payload_digest"],
                    action="reserve",
                    reason=command.reason,
                ),
            )
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        [context.user.id, old["owner_user_id"], command.owner_user_id]
                    ),
                )
            ).mappings()
        }
        receipt = EventAuditWriter(
            c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"reservation-owner:{command.request_id}",
                event_type="RESOURCE_RESERVATION_OWNER_TRANSFERRED",
                source="planning_service",
                entity_id=id,
                payload={"previous_id": str(id), "replacement_id": new["id"]},
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=_plain(old),
                after_snapshot=new,
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "people": people,
                    "replacement_id": new["id"],
                    "closed_original": closed,
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": receipt.audit_row_id,
            "record": new,
        }
