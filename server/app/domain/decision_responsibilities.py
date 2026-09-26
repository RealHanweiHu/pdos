"""Decision follow-up succession, separately preserving the approved decision."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.decisions import DecisionService, _decision_statement, _record_from_row
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import _project
from app.domain.tasks import TaskService, TaskUpdate
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

AUDIT_ACTION = "decision.responsibility.changed"


class Reassign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_user_id: UUID
    transfer_task: bool = False
    reason: str = Field(min_length=1, max_length=2048)


def current(c: Connection, tenant: UUID, project: UUID, id: UUID) -> dict[str, Any]:
    d = tables.decisions
    row = (
        c.execute(select(d).where(d.c.tenant_id == tenant, d.c.project_id == project, d.c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原决定不存在或不可访问")
    rich = (
        c.execute(
            _decision_statement().where(
                d.c.tenant_id == tenant, d.c.project_id == project, d.c.id == id
            )
        )
        .mappings()
        .one()
    )
    decision = DecisionService._with_execution(c, tenant, _record_from_row(rich))
    task = None
    ordinary = False
    if row["follow_up_task_id"]:
        t = tables.tasks
        task = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == tenant,
                    t.c.project_id == project,
                    t.c.id == row["follow_up_task_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        formal = c.execute(
            select(tables.schedule_nodes.c.id).where(
                tables.schedule_nodes.c.tenant_id == tenant,
                tables.schedule_nodes.c.project_id == project,
                tables.schedule_nodes.c.task_id == row["follow_up_task_id"],
            )
        ).first()
        ordinary = (
            task is not None
            and task["kind"] == "task"
            and task["status"] not in ("done", "skipped")
            and formal is None
        )
    return {
        "decision": _plain(row),
        "effective_follow_up_state": decision.follow_up_state,
        "task": _plain(task) if task else None,
        "task_transferable": ordinary,
    }


def members(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, str]]:
    u, m = tables.users, tables.project_members
    rows = c.execute(
        select(u.c.id, u.c.display_name, u.c.role)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(u.c.tenant_id == tenant, m.c.project_id == project, u.c.is_active.is_(True))
        .order_by(u.c.display_name, u.c.id)
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
        a.c.entity_id == id,
        a.c.action == AUDIT_ACTION,
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
        value = current(c, context.tenant.id, project, id)
        ids = [value["decision"]["owner_user_id"], value["decision"]["approver_user_id"]]
        if value["task"]:
            ids.append(value["task"]["assignee_user_id"])
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_([UUID(id) for id in ids if id]),
                )
            ).mappings()
        }
        history = (
            c.execute(history_statement(context.tenant.id, project, id, before)).mappings().all()
        )
        return {
            **value,
            "digest": digest(value),
            "people": people,
            "members": members(c, context.tenant.id, project),
            "can_reassign": is_allowed(context.user.role, Action.WORK_ITEM_EDIT)
            and value["effective_follow_up_state"] == "pending"
            and p["status"] not in ("completed", "archived"),
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    try:
        return _reassign(engine, context, project, id, command)
    except IntegrityError as exc:
        raise ProductWorkError(
            "责任调整未生效，请核对原任务和当前项目资料；原责任保持不变"
        ) from exc


def _reassign(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: Reassign
) -> dict[str, Any]:
    _role(context, Action.WORK_ITEM_EDIT)
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"decision-owner:{context.tenant.id}:{context.user.id}:{command.request_id}"},
        )
        p = _project(c, context, project, write=True)
        signature = digest(
            {"project_id": str(project), "decision_id": str(id), **command.model_dump(mode="json")}
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
                raise ProductWorkError("此请求编号已用于另一项责任调整")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        before = current(c, context.tenant.id, project, id)
        if digest(before) != command.expected_digest:
            raise ProductWorkError("原决定、执行任务或执行依据已有变化，请刷新核对")
        if before["effective_follow_up_state"] != "pending" or p["status"] in (
            "completed",
            "archived",
        ):
            raise ProductWorkError("仅未结束项目中的待执行决定可调整责任")
        decision = before["decision"]
        if decision["owner_user_id"] == str(command.owner_user_id):
            raise ProductWorkError("请选择不同的决策跟进负责人")
        if str(command.owner_user_id) not in {
            m["id"] for m in members(c, context.tenant.id, project)
        }:
            raise ProductWorkError("接手人须为有办理权限的有效项目成员")
        if command.transfer_task:
            if not before["task_transferable"]:
                raise ProductWorkError(
                    "仅可同步移交未结束、未纳入正式排程的普通任务；其他任务须在原流程办理"
                )
            TaskService(engine).update(
                connection=c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                task_id=UUID(before["task"]["id"]),
                patch=TaskUpdate(changes={"assignee_user_id": command.owner_user_id}),
            )
        c.execute(
            tables.decisions.update()
            .where(
                tables.decisions.c.tenant_id == context.tenant.id,
                tables.decisions.c.project_id == project,
                tables.decisions.c.id == id,
            )
            .values(owner_user_id=command.owner_user_id, updated_at=datetime.now(UTC))
        )
        after = current(c, context.tenant.id, project, id)
        ids = [context.user.id, command.owner_user_id]
        if decision["owner_user_id"]:
            ids.append(UUID(decision["owner_user_id"]))
        if before["task"] and before["task"]["assignee_user_id"]:
            ids.append(UUID(before["task"]["assignee_user_id"]))
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(ids)
                )
            ).mappings()
        }
        receipt = EventAuditWriter(
            c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"decision-owner:{id}:{command.request_id}",
                event_type="DECISION_RESPONSIBILITY_CHANGED",
                source="development_case_service",
                entity_id=id,
                payload={"decision_id": str(id), "task_transferred": command.transfer_task},
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=before,
                after_snapshot=after,
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "people": people,
                    "transfer_task": command.transfer_task,
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": receipt.audit_row_id,
            "record": after,
        }
