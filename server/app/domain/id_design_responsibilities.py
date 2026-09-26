"""Unfrozen design ownership succession through the real revision workflow."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.id_design import DesignRevisionDraft, IdDesignService, _get, _latest
from app.domain.id_design_freeze import frozen_variant
from app.domain.preproject_responsibilities import Reassign as Reassign
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

AUDIT_ACTION = "id_design.responsibility.changed"
CONTENT_FIELDS = (
    "brief",
    "envelope",
    "cmf",
    "layout",
    "interfaces",
    "document_id",
    "external_file_reference_id",
)


def current(
    c: Connection, ctx: AuthContext, project: UUID, id: UUID, project_status: str
) -> dict[str, Any]:
    row = _get(c, ctx, project, tables.id_design_revisions, id)
    variant = _get(c, ctx, project, tables.id_design_variants, row["variant_id"])
    latest = _latest(c, ctx, project, row["variant_id"])
    return {
        "revision": _plain(row),
        "title": variant["title"],
        "latest_revision_id": str(latest["id"]),
        "frozen": bool(frozen_variant(c, ctx, project, row["variant_id"])),
        "project_status": project_status,
    }


def manageable(ctx: AuthContext, value: dict[str, Any]) -> bool:
    return bool(
        is_allowed(ctx.user.role, Action.PRODUCT_ENGINEERING_EDIT)
        and value["project_status"] in {"approved", "active", "on_hold"}
        and not value["frozen"]
        and value["latest_revision_id"] == value["revision"]["id"]
        and (
            value["revision"]["owner_user_id"] == str(ctx.user.id)
            or is_allowed(ctx.user.role, Action.PROJECT_EDIT)
        )
    )


def members(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    u, m = tables.users, tables.project_members
    return [
        _plain(r)
        for r in c.execute(
            select(u.c.id, u.c.display_name)
            .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
            .where(
                u.c.tenant_id == tenant,
                m.c.project_id == project,
                u.c.is_active.is_(True),
                u.c.role.in_(
                    [r.value for r in Role if is_allowed(r, Action.PRODUCT_ENGINEERING_EDIT)]
                ),
            )
            .order_by(u.c.display_name, u.c.id)
        ).mappings()
    ]


def history_statement(tenant: UUID, project: UUID, variant: UUID, before: int | None = None) -> Any:
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
        a.c.context["variant_id"].as_string() == str(variant),
    )
    if before is not None:
        q = q.where(a.c.id < before)
    return q.order_by(a.c.id.desc()).limit(21)


def people(c: Connection, tenant: UUID, ids: list[Any]) -> dict[str, str]:
    return {
        str(r.id): r.display_name
        for r in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant,
                tables.users.c.id.in_([UUID(str(id)) for id in ids]),
            )
        )
    }


def read(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    _role(ctx, Action.PRODUCT_ENGINEERING_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        p = _project(c, ctx, project)
        value = current(c, ctx, project, id, p["status"])
        row = value["revision"]
        history = (
            c.execute(history_statement(ctx.tenant.id, project, UUID(row["variant_id"]), before))
            .mappings()
            .all()
        )
        return {
            "record": row,
            "digest": digest(value),
            "title": value["title"],
            "latest_revision_id": value["latest_revision_id"],
            "frozen": value["frozen"],
            "people": people(c, ctx.tenant.id, [row["owner_user_id"]]),
            "can_manage": manageable(ctx, value),
            "members": members(c, ctx.tenant.id, project),
            "responsibilities": [
                {
                    "role": "owner",
                    "key": None,
                    "label": "设计负责人",
                    "user_id": row["owner_user_id"],
                }
            ],
            "history": [_plain(h) for h in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    _role(ctx, Action.PRODUCT_ENGINEERING_EDIT)
    if command.role != "owner" or command.key is not None:
        raise ProductWorkError("仅可调整未冻结设计的负责人")
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"design-owner:{ctx.tenant.id}:{ctx.user.id}:{command.request_id}"},
        )
        p = _project(c, ctx, project, write=True)
        signature = digest(
            {"project_id": str(project), "revision_id": str(id), **command.model_dump(mode="json")}
        )
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == ctx.tenant.id,
                    a.c.actor_user_id == ctx.user.id,
                    a.c.action == AUDIT_ACTION,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("此请求编号已用于其他责任调整")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        value = current(c, ctx, project, id, p["status"])
        if digest(value) != command.expected_digest:
            raise ProductWorkError("方案版本或冻结状态已变化，请重新核对")
        if not manageable(ctx, value):
            raise ProductWorkError("仅当前负责人或项目管理者可为最新未冻结方案调整责任")
        before = value["revision"]
        if before["owner_user_id"] == str(command.user_id):
            raise ProductWorkError("请选择不同的接手人")
        if str(command.user_id) not in {r["id"] for r in members(c, ctx.tenant.id, project)}:
            raise ProductWorkError("接手人须为具有设计办理权限的有效项目成员")
        after = IdDesignService(engine).revise_in_transaction(
            c,
            ctx,
            project,
            DesignRevisionDraft(
                request_id=command.request_id,
                variant_id=UUID(before["variant_id"]),
                expected_version=before["version"],
                title=value["title"],
                owner_user_id=command.user_id,
                reason=command.reason,
                **{field: before[field] for field in CONTENT_FIELDS},
            ),
        )
        if after["artifact_snapshot"] != before["artifact_snapshot"]:
            raise ProductWorkError(
                "原主图档或文件引用已变化，请先核对并修订设计内容；本次责任调整未生效"
            )
        receipt = EventAuditWriter(
            c, tenant_id=ctx.tenant.id, project_id=project, actor_user_id=ctx.user.id
        ).record(
            EventDraft(
                event_id=f"design-owner:{id}:{ctx.user.id}:{command.request_id}",
                event_type="ID_DESIGN_RECORDED",
                source="design_service",
                entity_id=id,
                payload={"record_id": after["id"], "action": "responsibility_changed"},
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=before,
                after_snapshot=after,
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "role": "owner",
                    "responsibility_label": "设计负责人",
                    "variant_id": before["variant_id"],
                    "replacement_id": after["id"],
                    "people": people(
                        c, ctx.tenant.id, [ctx.user.id, before["owner_user_id"], command.user_id]
                    ),
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": receipt.audit_row_id,
            "record": after,
        }
