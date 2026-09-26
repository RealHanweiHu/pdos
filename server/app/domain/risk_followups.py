"""Named risk correction work using actual Tasks and their original immutable audit."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.firmware_package_tasks import NewTask
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.risk_references import KINDS, query
from app.domain.risks import (
    RiskNotConfirmedError,
    RiskNotFoundError,
    RiskVersionConflictError,
)
from app.domain.tasks import TaskDraft, TaskService


class FollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    new_task: NewTask


def authorize(c: Connection, ctx: AuthContext, project: UUID, action: Action) -> None:
    KnowledgeCorrectionService._authorize(c, ctx.tenant.id, ctx.user.id, project, action)


def basis(c: Connection, ctx: AuthContext, project: UUID, risk: UUID) -> dict[str, Any]:
    r = tables.risks
    row = (
        c.execute(
            select(r).where(
                r.c.tenant_id == ctx.tenant.id,
                r.c.project_id == project,
                r.c.id == risk,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RiskNotFoundError
    groups = []
    for kind, (label, action) in KINDS.items():
        statement = query(kind, ctx.tenant.id, project, risk)
        refs = c.execute(statement.order_by(statement.selected_columns.id)).mappings().all()
        if kind == "handoff" and not refs:
            continue
        if refs:
            authorize(c, ctx, project, action)
        groups.append({"kind": kind, "label": label, "items": [_plain(dict(ref)) for ref in refs]})
    return {"risk": _plain(dict(row)), "references": groups}


def receipt(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    row: Any,
    current_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    saved = row["context"]["risk_followup"]
    for group in saved["basis"]["references"]:
        if group["items"]:
            authorize(c, ctx, project, KINDS[group["kind"]][1])
    task = TaskService._get_record(
        c, tenant_id=ctx.tenant.id, project_id=project, task_id=row["entity_id"]
    )
    current = current_basis or basis(c, ctx, project, UUID(saved["basis"]["risk"]["id"]))
    compared = {
        "risk": current["risk"],
        "references": [
            {
                **group,
                "items": [
                    item
                    for item in group["items"]
                    if not (group["kind"] == "task" and item["id"] == str(task.id))
                ],
            }
            for group in current["references"]
        ],
    }
    return {
        "source_changed": digest(compared) != digest(saved["basis"]),
        "request_id": saved["request_id"],
        "task_id": str(task.id),
        "created_at": row["timestamp"],
        "actor_user_id": str(row["actor_user_id"]),
        "actor_name": saved["actor_name"],
        "original": dict(row["after_snapshot"])
        | {
            "expected_output": saved["assignment"]["expected_output"],
            "assignee_name": saved["assignee_name"],
        },
        "reason": saved["reason"],
        "basis": saved["basis"],
        "task": {
            "title": task.title,
            "status": task.status,
            "assignee_user_id": str(task.assignee_user_id) if task.assignee_user_id else None,
            "due_date": task.due_date,
            "expected_output": task.expected_output,
            "completion_evidence_ref": task.completion_evidence_ref,
            "updated_at": task.updated_at,
        },
        "href": f"/projects?project={project}&tab=work-items&entity_id={task.id}",
    }


def audit_query(ctx: AuthContext, project: UUID, risk: UUID) -> Any:
    a = tables.audit_log
    return select(a).where(
        a.c.tenant_id == ctx.tenant.id,
        a.c.project_id == project,
        a.c.action == "task.create",
        a.c.context["risk_followup"]["basis"]["risk"]["id"].as_string() == str(risk),
    )


def prepare(engine: Engine, ctx: AuthContext, project: UUID, risk: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        authorize(c, ctx, project, Action.WORK_ITEM_VIEW)
        source = basis(c, ctx, project, risk)
        can_create = source["risk"]["draft_state"] == "confirmed"
        try:
            authorize(c, ctx, project, Action.WORK_ITEM_EDIT)
        except KnowledgeAccessError:
            can_create = False
        p, s, u, m = tables.projects, tables.stages, tables.users, tables.project_members
        workflow = c.execute(
            select(p.c.workflow_id).where(p.c.tenant_id == ctx.tenant.id, p.c.id == project)
        ).scalar_one()
        stages = [
            dict(row)
            for row in c.execute(
                select(s.c.id, s.c.name)
                .where(
                    s.c.tenant_id == ctx.tenant.id,
                    s.c.workflow_id == workflow,
                )
                .order_by(s.c.sequence)
            ).mappings()
        ]
        people = [
            dict(row)
            for row in c.execute(
                select(u.c.id, u.c.display_name)
                .join(
                    m,
                    (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id),
                )
                .where(
                    m.c.tenant_id == ctx.tenant.id,
                    m.c.project_id == project,
                    u.c.is_active.is_(True),
                    u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
        ]
        rows = (
            c.execute(
                audit_query(ctx, project, risk).order_by(tables.audit_log.c.id.desc()).limit(21)
            )
            .mappings()
            .all()
        )
        return {
            "basis": source,
            "digest": digest(source),
            "stages": stages,
            "people": people,
            "can_create": can_create,
            "recent": [receipt(c, ctx, project, row, source) for row in rows[:20]],
            "has_more": len(rows) > 20,
        }


def read(
    engine: Engine, ctx: AuthContext, project: UUID, risk: UUID, request: UUID
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        authorize(c, ctx, project, Action.WORK_ITEM_VIEW)
        a = tables.audit_log
        row = (
            c.execute(
                audit_query(ctx, project, risk).where(
                    a.c.actor_user_id == ctx.user.id,
                    a.c.context["risk_followup"]["request_id"].as_string() == str(request),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RiskNotFoundError
        return receipt(c, ctx, project, row)


def create(
    engine: Engine, ctx: AuthContext, project: UUID, risk: UUID, body: FollowupRequest
) -> dict[str, Any]:
    signature = digest(body.model_dump(mode="json"))
    with engine.begin() as c:
        authorize(c, ctx, project, Action.WORK_ITEM_EDIT)
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"risk-followup:{ctx.tenant.id}:{ctx.user.id}:{body.request_id}"},
        )
        a = tables.audit_log
        existing = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == ctx.tenant.id,
                    a.c.actor_user_id == ctx.user.id,
                    a.c.action == "task.create",
                    a.c.context["risk_followup"]["request_id"].as_string() == str(body.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            saved = existing["context"]["risk_followup"]
            if (
                existing["project_id"] != project
                or saved["basis"]["risk"]["id"] != str(risk)
                or saved["request_digest"] != signature
            ):
                raise RiskVersionConflictError
            return receipt(c, ctx, project, existing)
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise RiskNotFoundError
        source = basis(c, ctx, project, risk)
        if source["risk"]["draft_state"] != "confirmed":
            raise RiskNotConfirmedError
        if digest(source) != body.expected_digest:
            raise RiskVersionConflictError
        task = body.new_task
        TaskService._validate_member(
            c, tenant_id=ctx.tenant.id, project_id=project, user_id=task.assignee_user_id
        )
        assignee_name = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == ctx.tenant.id,
                tables.users.c.id == task.assignee_user_id,
            )
        ).scalar_one()
        created = TaskService(engine).create(
            tenant_id=ctx.tenant.id,
            actor_user_id=ctx.user.id,
            project_id=project,
            connection=c,
            audit_context={
                "risk_followup": {
                    "actor_name": ctx.user.display_name,
                    "assignee_name": assignee_name,
                    "request_id": str(body.request_id),
                    "request_digest": signature,
                    "reason": body.reason,
                    "basis": source,
                    "assignment": body.new_task.model_dump(mode="json"),
                }
            },
            draft=TaskDraft(
                stage_id=task.stage_id,
                parent_task_id=None,
                assignee_user_id=task.assignee_user_id,
                title=task.title,
                description=(
                    task.description
                    + "\n\n风险处理依据："
                    + body.reason
                    + f"\n原风险：/projects?project={project}&tab=work-items&entity_id={risk}"
                ),
                priority=task.priority,
                start_date=task.start_date,
                due_date=task.due_date,
                dependency_task_ids=(),
                kind="risk_action",
                source_entity_id=risk,
                expected_output=task.expected_output,
            ),
        )
        recorded = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == ctx.tenant.id, a.c.event_id == f"task:{created.id}:created"
                )
            )
            .mappings()
            .one()
        )
        return receipt(c, ctx, project, recorded)
