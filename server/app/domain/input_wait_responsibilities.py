"""Human ownership of missing-input follow-up, separate from model authority."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.findings import FindingApplyPermissionError, FindingService
from app.domain.preproject_responsibilities import Reassign as Reassign
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

AUDIT_ACTION = "application_input.responsibility.changed"


def authorize(c: Connection, ctx: AuthContext, project: UUID, action: Action) -> None:
    try:
        FindingService._authorize_user(
            c, tenant_id=ctx.tenant.id, project_id=project, user_id=ctx.user.id, action=action
        )
    except FindingApplyPermissionError as exc:
        raise ProductWorkAccessError("当前没有此项目的办理权限") from exc


def current(
    c: Connection, tenant: UUID, project: UUID, id: UUID, lock: bool = False
) -> dict[str, Any]:
    w, r, f, a = (
        tables.application_input_waits,
        tables.agent_runs,
        tables.findings,
        tables.application_authorizations,
    )
    row = (
        c.execute(
            select(w)
            .join(r, (r.c.tenant_id == w.c.tenant_id) & (r.c.id == w.c.run_id))
            .where(w.c.tenant_id == tenant, w.c.id == id, r.c.project_id == project)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("待补充事项不存在或不可访问")
    fq = select(f).where(
        f.c.tenant_id == tenant,
        f.c.project_id == project,
        f.c.id == row["finding_id"],
        f.c.run_id == row["run_id"],
    )
    finding = c.execute(fq.with_for_update() if lock else fq).mappings().one_or_none()
    if finding is None or finding["finding_type"] != "test_plan_change":
        raise ProductWorkError("请在此运行的原业务入口办理责任接续")
    if lock:
        row = (
            c.execute(select(w).where(w.c.tenant_id == tenant, w.c.id == id).with_for_update())
            .mappings()
            .one()
        )
    auth = (
        c.execute(select(a).where(a.c.tenant_id == tenant, a.c.run_id == row["run_id"]))
        .mappings()
        .one_or_none()
    )
    run_status = c.execute(
        select(r.c.status).where(r.c.tenant_id == tenant, r.c.id == row["run_id"])
    ).scalar_one()
    project_status = c.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == tenant, tables.projects.c.id == project
        )
    ).scalar_one()
    return {
        "wait": _plain(row),
        "finding": _plain(finding),
        "authorization": _plain(auth) if auth else None,
        "run_status": run_status,
        "project_status": project_status,
    }


def changeable(value: dict[str, Any], now: Any) -> bool:
    from datetime import datetime

    w = value["wait"]
    return bool(
        w["resolved_at"] is None
        and datetime.fromisoformat(w["expires_at"]) > now
        and value["run_status"] == "waiting_input"
        and value["finding"]["status"] == "pending_review"
        and value["authorization"]
        and value["project_status"] not in {"completed", "archived"}
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
                    [role.value for role in Role if is_allowed(role, Action.FINDING_REVIEW)]
                ),
            )
            .order_by(u.c.display_name, u.c.id)
        ).mappings()
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
        a.c.entity_id == id,
        a.c.action == AUDIT_ACTION,
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
                tables.users.c.id.in_([UUID(str(id)) for id in ids if id]),
            )
        )
    }


def read(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, ctx, project, Action.FINDING_VIEW)
        value = current(c, ctx.tenant.id, project, id)
        w, auth = value["wait"], value["authorization"] or {}
        history = c.execute(history_statement(ctx.tenant.id, project, id, before)).mappings().all()
        return {
            "record": w,
            "digest": digest(value),
            "title": w["body"]["goal"],
            "people": people(c, ctx.tenant.id, [w["owner_user_id"], auth.get("principal_id")]),
            "principal_id": auth.get("principal_id"),
            "run_status": value["run_status"],
            "can_manage": is_allowed(ctx.user.role, Action.PROJECT_EDIT)
            and changeable(value, c.execute(select(func.clock_timestamp())).scalar_one()),
            "members": members(c, ctx.tenant.id, project),
            "responsibilities": [
                {
                    "role": "owner",
                    "key": None,
                    "label": "补充信息与人审负责人",
                    "user_id": w["owner_user_id"],
                }
            ],
            "history": [_plain(row) for row in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    if command.role != "owner" or command.key is not None:
        raise ProductWorkError("仅可调整补充信息与人审负责人")
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"wait-owner:{ctx.tenant.id}:{ctx.user.id}:{command.request_id}"},
        )
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise ProductWorkAccessError("项目不可访问")
        authorize(c, ctx, project, Action.PROJECT_EDIT)
        signature = digest(
            {"project_id": str(project), "wait_id": str(id), **command.model_dump(mode="json")}
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
                raise ProductWorkError("此请求编号已用于其他调整")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        value = current(c, ctx.tenant.id, project, id, lock=True)
        if digest(value) != command.expected_digest:
            raise ProductWorkError("原问题、候选或运行状态已变化，请重新核对")
        if not changeable(value, c.execute(select(func.clock_timestamp())).scalar_one()):
            raise ProductWorkError("等待已结束、授权已到期或项目已结束，请回查原运行与建议")
        before = value["wait"]
        if before["owner_user_id"] == str(command.user_id):
            raise ProductWorkError("请选择不同的接手人")
        if str(command.user_id) not in {r["id"] for r in members(c, ctx.tenant.id, project)}:
            raise ProductWorkError("接手人须为已有建议审核权限的有效项目成员")
        w = tables.application_input_waits
        after = (
            c.execute(
                w.update()
                .where(w.c.tenant_id == ctx.tenant.id, w.c.id == id)
                .values(owner_user_id=command.user_id)
                .returning(w)
            )
            .mappings()
            .one()
        )
        receipt = EventAuditWriter(
            c, tenant_id=ctx.tenant.id, project_id=project, actor_user_id=ctx.user.id
        ).record(
            EventDraft(
                event_id=f"wait-owner:{id}:{ctx.user.id}:{command.request_id}",
                event_type="APPLICATION_INPUT_RESPONSIBILITY_CHANGED",
                source="application_wait_service",
                entity_id=id,
                payload={"run_id": before["run_id"], "finding_id": before["finding_id"]},
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=before,
                after_snapshot=_plain(after),
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "role": "owner",
                    "responsibility_label": "补充信息与人审负责人",
                    "people": people(
                        c, ctx.tenant.id, [ctx.user.id, before["owner_user_id"], command.user_id]
                    ),
                    "basis_digest": command.expected_digest,
                    "authorization_principal_id": value["authorization"]["principal_id"],
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": receipt.audit_row_id,
            "record": _plain(after),
        }
