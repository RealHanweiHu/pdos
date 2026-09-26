"""Named reassignment of open quality work, retaining prior execution responsibility."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, Select, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

Kind = Literal["complaint", "ncr", "capa", "certification"]
TABLES = {
    "complaint": tables.complaints,
    "ncr": tables.nonconformance_reports,
    "capa": tables.capa_actions,
    "certification": tables.certifications,
}
OWNER_ACTIONS = {
    "complaint": Action.COMPLAINT_CREATE,
    "ncr": Action.CAPA_MANAGE,
    "capa": Action.CAPA_EXECUTE,
    "certification": Action.QUALITY_MANAGE,
}
AUDIT_ACTION = "quality.responsibility.changed"


class Reassign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_user_id: UUID
    reason: str = Field(min_length=1, max_length=2048)


def authorize(c: Connection, context: AuthContext, project: UUID, action: Action) -> None:
    FindingService._authorize_user(
        c, tenant_id=context.tenant.id, project_id=project, user_id=context.user.id, action=action
    )


def snapshot(c: Connection, tenant: UUID, project: UUID, kind: Kind, id: UUID) -> dict[str, Any]:
    t = TABLES[kind]
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原质量记录不存在或不可访问")
    parent = None
    if kind == "capa":
        n = tables.nonconformance_reports
        parent = (
            c.execute(
                select(n.c.id, n.c.status, n.c.updated_at).where(
                    n.c.tenant_id == tenant, n.c.project_id == project, n.c.id == row["ncr_id"]
                )
            )
            .mappings()
            .one()
        )
    p = c.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == tenant, tables.projects.c.id == project
        )
    ).scalar_one()
    return {
        "kind": kind,
        "record": _plain(row),
        "parent": _plain(parent) if parent else None,
        "project_status": p,
    }


def open_work(value: dict[str, Any]) -> bool:
    return (
        value["project_status"] not in ("completed", "archived")
        and value["record"]["status"] not in ("completed", "closed")
        and (value["kind"] != "certification" or value["record"]["status"] == "draft")
        and (value["parent"] is None or value["parent"]["status"] != "closed")
    )


def can_reassign(context: AuthContext, kind: Kind, record: dict[str, Any]) -> bool:
    if kind == "certification":
        return is_allowed(context.user.role, Action.QUALITY_MANAGE) and (
            record["owner_user_id"] == str(context.user.id)
            or is_allowed(context.user.role, Action.PROJECT_EDIT)
        )
    return is_allowed(context.user.role, Action.CAPA_MANAGE)


def members(c: Connection, tenant: UUID, project: UUID, kind: Kind) -> list[dict[str, str]]:
    u, m = tables.users, tables.project_members
    values = c.execute(
        select(u.c.id, u.c.display_name, u.c.role)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(u.c.tenant_id == tenant, m.c.project_id == project, u.c.is_active.is_(True))
        .order_by(u.c.display_name, u.c.id)
    ).mappings()
    return [
        {"id": str(r["id"]), "name": r["display_name"]}
        for r in values
        if is_allowed(Role(r["role"]), OWNER_ACTIONS[kind])
    ]


def history_statement(
    tenant: UUID, project: UUID, kind: Kind, id: UUID, before: int | None = None
) -> Select[Any]:
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
        a.c.entity_id == id,
        a.c.action == AUDIT_ACTION,
        a.c.context["kind"].as_string() == kind,
    )
    if before is not None:
        q = q.where(a.c.id < before)
    return q.order_by(a.c.id.desc()).limit(21)


def historical_capa_owners(c: Connection, tenant: UUID, project: UUID, ncr: UUID) -> set[UUID]:
    """Changing the current assignee must not erase participation for four-eyes review."""
    a, t = tables.audit_log, tables.capa_actions
    rows = c.execute(
        select(a.c.before_snapshot)
        .join(
            t,
            (t.c.tenant_id == a.c.tenant_id)
            & (t.c.project_id == a.c.project_id)
            & (t.c.id == a.c.entity_id),
        )
        .where(
            a.c.tenant_id == tenant,
            a.c.project_id == project,
            a.c.action == AUDIT_ACTION,
            a.c.context["kind"].as_string() == "capa",
            t.c.ncr_id == ncr,
        )
    ).scalars()
    return {UUID(r["owner_user_id"]) for r in rows if r and r.get("owner_user_id")}


def read(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    kind: Kind,
    id: UUID,
    before: int | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        current = snapshot(c, context.tenant.id, project, kind, id)
        owner = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == UUID(current["record"]["owner_user_id"]),
            )
        ).scalar_one()
        history = (
            c.execute(history_statement(context.tenant.id, project, kind, id, before))
            .mappings()
            .all()
        )
        return {
            **current,
            "digest": digest(current),
            "owner_name": owner,
            "can_reassign": can_reassign(context, kind, current["record"]) and open_work(current),
            "members": members(c, context.tenant.id, project, kind),
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(
    engine: Engine, context: AuthContext, project: UUID, kind: Kind, id: UUID, request: Reassign
) -> dict[str, Any]:
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"quality-owner:{context.tenant.id}:{context.user.id}:{request.request_id}"},
        )
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(
            c,
            context,
            project,
            Action.QUALITY_MANAGE if kind == "certification" else Action.CAPA_MANAGE,
        )
        signature = digest(
            {
                "project_id": str(project),
                "kind": kind,
                "id": str(id),
                **request.model_dump(mode="json"),
            }
        )
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.actor_user_id == context.user.id,
                    a.c.action == AUDIT_ACTION,
                    a.c.context["request_id"].as_string() == str(request.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("此请求编号已用于另一项责任调整")
            return {
                "request_id": str(request.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        current = snapshot(c, context.tenant.id, project, kind, id)
        if not can_reassign(context, kind, current["record"]):
            raise PermissionError("由当前认证负责人或有权项目管理人办理")
        if digest(current) != request.expected_digest:
            raise ProductWorkError("原质量记录已有进展，请刷新核对再调整负责人")
        if not open_work(current):
            raise ProductWorkError("已结束质量工作或项目保留原负责人，不可移交")
        old = current["record"]
        if old["owner_user_id"] == str(request.owner_user_id):
            raise ProductWorkError("请选择不同的接手人")
        eligible = members(c, context.tenant.id, project, kind)
        new = next((r for r in eligible if r["id"] == str(request.owner_user_id)), None)
        if new is None:
            raise ProductWorkError("接手人须为有效项目成员且具备此项质量职责")
        t = TABLES[kind]
        after = (
            c.execute(
                t.update()
                .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == id)
                .values(owner_user_id=request.owner_user_id, updated_at=datetime.now(UTC))
                .returning(t)
            )
            .mappings()
            .one()
        )
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        [UUID(old["owner_user_id"]), request.owner_user_id, context.user.id]
                    ),
                )
            ).mappings()
        }
        receipt = EventAuditWriter(
            c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"quality-responsibility:{uuid4()}",
                event_type="QUALITY_RESPONSIBILITY_CHANGED",
                source="quality_service",
                entity_id=id,
                payload={"kind": kind, "record_id": str(id)},
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=old,
                after_snapshot=_plain(after),
                context={
                    "kind": kind,
                    "request_id": str(request.request_id),
                    "request_digest": signature,
                    "reason": request.reason,
                    "people": people,
                    "basis_digest": request.expected_digest,
                },
            ),
        )
        return {
            "request_id": str(request.request_id),
            "audit_id": receipt.audit_row_id,
            "record": _plain(after),
        }
