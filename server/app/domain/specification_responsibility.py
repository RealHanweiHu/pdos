"""Owner succession through a new specification version and an immutable audit receipt."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_engineering import (
    ProductEngineeringService,
    SpecificationDraft,
    _specification_snapshot,
)
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.quality_responsibilities import Reassign as Reassign
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft

ACTION = "specification.owner_revised"


def record(c: Connection, tenant: UUID, project: UUID, id: UUID) -> Any:
    t = tables.specifications
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原规格不存在或不可访问")
    return row


def latest(c: Connection, row: Any) -> Any:
    t = tables.specifications
    return (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == row["tenant_id"],
                t.c.project_id == row["project_id"],
                t.c.code == row["code"],
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )


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
        if is_allowed(Role(r["role"]), Action.PRODUCT_ENGINEERING_EDIT)
    ]


def read(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_ENGINEERING_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        p = _project(c, context, project)
        row = record(c, context.tenant.id, project, id)
        current = latest(c, row)
        a = tables.audit_log
        q = select(
            a.c.id,
            a.c.timestamp.label("created_at"),
            a.c.actor_user_id,
            a.c.before_snapshot,
            a.c.after_snapshot,
            a.c.context,
        ).where(
            a.c.tenant_id == context.tenant.id,
            a.c.project_id == project,
            a.c.action == ACTION,
            a.c.context["specification_code"].as_string() == row["code"],
        )
        if before is not None:
            q = q.where(a.c.id < before)
        history = list(c.execute(q.order_by(a.c.id.desc()).limit(21)).mappings())
        owner = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == row["owner_user_id"],
            )
        ).scalar_one_or_none()
        return {
            "record": _plain(row),
            "digest": digest(_plain(row)),
            "owner_name": owner,
            "latest_id": str(current["id"]),
            "latest_version": current["version"],
            "can_reassign": current["id"] == id
            and p["status"] not in ("completed", "archived")
            and is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT),
            "members": members(c, context.tenant.id, project),
            "history": [_plain(h) for h in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def transfer(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_ENGINEERING_EDIT)
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {
                "key": (
                    f"specification-owner:{context.tenant.id}"
                    f":{context.user.id}:{command.request_id}"
                )
            },
        )
        p = _project(c, context, project, write=True)
        signature = digest(
            {
                "project_id": str(project),
                "specification_id": str(id),
                **command.model_dump(mode="json"),
            }
        )
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.actor_user_id == context.user.id,
                    a.c.action == ACTION,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("同一请求不能用于其他规格或调整内容")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        old = record(c, context.tenant.id, project, id)
        if p["status"] in ("completed", "archived") or latest(c, old)["id"] != id:
            raise ProductWorkError("只能接续未结束项目的当前规格版本")
        if digest(_plain(old)) != command.expected_digest:
            raise ProductWorkError("原规格已有变化，请重新核对")
        if command.owner_user_id == old["owner_user_id"]:
            raise ProductWorkError("请选择不同的接手人")
        if str(command.owner_user_id) not in {
            m["id"] for m in members(c, context.tenant.id, project)
        }:
            raise ProductWorkError("接手人须为有产品工程办理权限的有效项目成员")
        people = {
            str(r.id): r.display_name
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        [old["owner_user_id"], command.owner_user_id, context.user.id]
                    ),
                )
            )
        }
        new = ProductEngineeringService(engine).create_specification(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
            draft=SpecificationDraft(
                code=old["code"],
                title=old["title"],
                version=old["version"] + 1,
                content=old["content"],
                requirement_id=old["requirement_id"],
                owner_user_id=command.owner_user_id,
                verification_method=old["verification_method"],
                acceptance_criteria=old["acceptance_criteria"],
                criticality=old["criticality"],
            ),
            connection=c,
            audit_draft=AuditDraft(
                action=ACTION,
                before_snapshot=_plain(old),
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "specification_code": old["code"],
                    "previous_id": str(id),
                    "reason": command.reason,
                    "people": people,
                },
            ),
        )
        after = _specification_snapshot(new)
        audit_id = c.execute(
            select(a.c.id).where(
                a.c.tenant_id == context.tenant.id,
                a.c.project_id == project,
                a.c.action == ACTION,
                a.c.actor_user_id == context.user.id,
                a.c.context["request_id"].as_string() == str(command.request_id),
            )
        ).scalar_one()
        return {"request_id": str(command.request_id), "audit_id": audit_id, "record": after}
