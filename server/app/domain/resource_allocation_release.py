"""Explicit release of legacy allocations with same-transaction reconciliation evidence."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_inventory import (
    ReconciliationDraft,
    ResourceInventoryService,
    _source,
    lock_inventory,
)
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft

ACTION = "legacy_resource.allocation_released"


class Release(Contract):
    request_id: UUID
    source_digest: Digest
    expected_sequence: int = Field(ge=0)
    reason: Text


def latest(c: Connection, tenant: UUID, id: UUID) -> Any:
    t = tables.legacy_resource_reconciliations
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.legacy_resource_id == id)
            .order_by(t.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def read(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        p = _project(c, context, project)
        source, stamp = _source(c, context, project, id)
        current = latest(c, context.tenant.id, id)
        name = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == source["assigned_user_id"],
            )
        ).scalar_one_or_none()
        a = tables.audit_log
        query = select(
            a.c.id,
            a.c.timestamp.label("created_at"),
            a.c.actor_user_id,
            a.c.before_snapshot,
            a.c.after_snapshot,
            a.c.context,
        ).where(
            a.c.tenant_id == context.tenant.id,
            a.c.project_id == project,
            a.c.entity_id == id,
            a.c.action == ACTION,
        )
        if before is not None:
            query = query.where(a.c.id < before)
        history = list(c.execute(query.order_by(a.c.id.desc()).limit(21)).mappings())
        return {
            "source": _plain(source),
            "source_digest": stamp,
            "assigned_name": name,
            "sequence": current["sequence"] if current else 0,
            "reconciliation": _plain(current) if current else None,
            "can_release": is_allowed(context.user.role, Action.TENANT_MANAGE)
            and p["status"] not in ("completed", "archived")
            and source["status"] in ("planned", "active"),
            "history": [_plain(row) for row in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def release(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Release
) -> dict[str, Any]:
    _role(context, Action.TENANT_MANAGE)
    with engine.begin() as c:
        p = _project(c, context, project, write=True)
        lock_inventory(c, context.tenant.id)
        signature = digest(
            {"project_id": str(project), "resource_id": str(id), **command.model_dump(mode="json")}
        )
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.project_id == project,
                    a.c.action == ACTION,
                    a.c.actor_user_id == context.user.id,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("请求编号已用于另一项分配释放")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "reconciliation": prior["after_snapshot"],
            }
        source, stamp = _source(c, context, project, id)
        previous = latest(c, context.tenant.id, id)
        sequence = previous["sequence"] if previous else 0
        if p["status"] in ("completed", "archived") or source["status"] not in (
            "planned",
            "active",
        ):
            raise ProductWorkError("只能结束未关闭项目的计划中或有效分配")
        if stamp != command.source_digest or sequence != command.expected_sequence:
            raise ProductWorkError("原分配或盘点依据已变化，请刷新后重新核对")
        people = {
            str(row.id): row.display_name
            for row in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_([source["assigned_user_id"], context.user.id]),
                )
            )
        }
        c.execute(
            tables.resources.update()
            .where(
                tables.resources.c.tenant_id == context.tenant.id,
                tables.resources.c.project_id == project,
                tables.resources.c.id == id,
            )
            .values(status="released", updated_at=datetime.now(UTC))
        )
        _, released_stamp = _source(c, context, project, id)
        result = ResourceInventoryService(engine).reconcile(
            context,
            project,
            ReconciliationDraft(
                request_id=command.request_id,
                legacy_resource_id=id,
                expected_sequence=sequence,
                source_digest=released_stamp,
                disposition="retained_released",
                basis=command.reason,
            ),
            connection=c,
            audit_draft=AuditDraft(
                action=ACTION,
                before_snapshot={
                    "source": _plain(source),
                    "reconciliation": _plain(previous) if previous else None,
                },
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "people": people,
                },
            ),
        )
        audit_id = c.execute(
            select(a.c.id).where(
                a.c.tenant_id == context.tenant.id,
                a.c.project_id == project,
                a.c.action == ACTION,
                a.c.actor_user_id == context.user.id,
                a.c.context["request_id"].as_string() == str(command.request_id),
            )
        ).scalar_one()
        return {
            "request_id": str(command.request_id),
            "audit_id": audit_id,
            "reconciliation": result,
        }
