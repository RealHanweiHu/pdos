"""Real project tasks for correcting business effects of amended intake sources."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.firmware_package_tasks import NewTask
from app.domain.issue_intake_corrections import public_source, source_states
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import TaskDraft, TaskScopeError, TaskService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CompensationSources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[UUID] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_sources(self) -> "CompensationSources":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("请勿重复选择同一来源")
        self.source_ids.sort(key=str)
        return self


class CompensationAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_row_id: UUID
    issue_id: UUID
    new_task: NewTask
    completion_criteria: str = Field(min_length=1, max_length=10000)


class CompensationBatch(CompensationSources):
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignments: list[CompensationAssignment] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def unique_assignments(self) -> "CompensationBatch":
        keys = [(item.source_row_id, item.issue_id) for item in self.assignments]
        if len(set(keys)) != len(keys) or any(source not in self.source_ids for source, _ in keys):
            raise ValueError("每条来源对同一问题只安排一次，且应属于本次预览来源")
        if not self.reason.strip():
            raise ValueError("请填写本批任务安排依据")
        self.assignments.sort(key=lambda item: (str(item.source_row_id), str(item.issue_id)))
        return self


def task_view(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "title",
                "description",
                "assignee_user_id",
                "stage_id",
                "status",
                "start_date",
                "due_date",
                "expected_output",
                "completion_evidence_ref",
                "updated_at",
            )
        }
    ) | {"href": f"/projects?project={row['project_id']}&tab=work-items&entity_id={row['id']}"}


def bindings(
    c: Connection,
    tenant: UUID,
    project: UUID,
    source_ids: list[UUID],
    *,
    task_id: UUID | None = None,
) -> list[dict[str, Any]]:
    t = tables.issue_intake_compensations
    query = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project)
    query = (
        query.where(t.c.task_id == task_id)
        if task_id
        else query.where(t.c.source_row_id.in_(source_ids))
    )
    rows = c.execute(query.order_by(t.c.created_at, t.c.id)).mappings().all()
    if not rows:
        return []
    sources = (
        c.execute(
            select(tables.issue_intake_rows).where(
                tables.issue_intake_rows.c.tenant_id == tenant,
                tables.issue_intake_rows.c.id.in_({row["source_row_id"] for row in rows}),
            )
        )
        .mappings()
        .all()
    )
    states = source_states(c, tenant, list(sources))
    tasks = {
        row["id"]: task_view(row)
        for row in c.execute(
            select(tables.tasks).where(
                tables.tasks.c.tenant_id == tenant,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id.in_({row["task_id"] for row in rows}),
            )
        ).mappings()
    }
    return [
        _plain(row)
        | {
            "task": tasks[row["task_id"]],
            "current_source": states[row["source_row_id"]],
            "source_changed": states[row["source_row_id"]]["revision"] != row["source_revision"],
        }
        for row in rows
    ]


def basis(c: Connection, ctx: AuthContext, project: UUID, source_ids: list[UUID]) -> dict[str, Any]:
    KnowledgeCorrectionService._authorize(
        c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
    )
    t, h = tables.issue_intake_rows, tables.issue_intake_corrections
    sources = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id.in_(source_ids)
            )
            .order_by(t.c.id)
        )
        .mappings()
        .all()
    )
    if len(sources) != len(source_ids):
        raise ConversationError("所选来源不完整或不属于本项目，请重新读取")
    states = source_states(c, ctx.tenant.id, list(sources))
    history = (
        c.execute(
            select(h)
            .where(
                h.c.tenant_id == ctx.tenant.id,
                h.c.project_id == project,
                h.c.source_row_id.in_(source_ids),
            )
            .order_by(h.c.source_row_id, h.c.revision)
        )
        .mappings()
        .all()
    )
    touched = {source["id"]: {source["issue_id"]} for source in sources}
    latest = {}
    for row in history:
        latest[row["source_row_id"]] = row
        touched[row["source_row_id"]].update(
            identity for identity in (row["previous_issue_id"], row["target_issue_id"]) if identity
        )
    issue_ids = set().union(*touched.values())
    issues = {
        row["id"]: target_snapshot(row)
        for row in c.execute(
            select(tables.issues).where(
                tables.issues.c.tenant_id == ctx.tenant.id,
                tables.issues.c.project_id == project,
                tables.issues.c.id.in_(issue_ids),
            )
        ).mappings()
    }
    entries = [
        {
            "source": public_source(source),
            "current_source": states[source["id"]],
            "correction": _plain(latest[source["id"]]) if source["id"] in latest else None,
            "issues": [issues[identity] for identity in sorted(touched[source["id"]], key=str)],
        }
        for source in sources
    ]
    return {"entries": entries, "digest": digest(entries)}


class IssueIntakeCompensations:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, ctx: AuthContext, project: UUID, body: CompensationSources) -> dict[str, Any]:
        with self.engine.connect() as c:
            result = basis(c, ctx, project, body.source_ids)
            result["bindings"] = bindings(c, ctx.tenant.id, project, body.source_ids)
            u, m = tables.users, tables.project_members
            result["members"] = [
                _plain(row)
                for row in c.execute(
                    select(u.c.id, u.c.display_name)
                    .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                    .where(
                        u.c.tenant_id == ctx.tenant.id,
                        m.c.project_id == project,
                        u.c.is_active.is_(True),
                        u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                    )
                    .order_by(u.c.display_name, u.c.id)
                ).mappings()
            ]
            workflow_id = c.execute(
                select(tables.projects.c.workflow_id).where(
                    tables.projects.c.tenant_id == ctx.tenant.id, tables.projects.c.id == project
                )
            ).scalar_one()
            s = tables.stages
            result["stages"] = [
                _plain(row)
                for row in c.execute(
                    select(s.c.id, s.c.name)
                    .where(s.c.tenant_id == ctx.tenant.id, s.c.workflow_id == workflow_id)
                    .order_by(s.c.sequence)
                ).mappings()
            ]
            return result

    def assign(self, ctx: AuthContext, project: UUID, body: CompensationBatch) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
            )
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            batches = tables.issue_intake_compensation_batches
            prior = (
                c.execute(
                    select(batches).where(
                        batches.c.tenant_id == ctx.tenant.id,
                        batches.c.project_id == project,
                        batches.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("本请求已对应其他任务安排，请读取原批次")
                return _plain(prior)
            current = basis(c, ctx, project, body.source_ids)
            if current["digest"] != body.expected_digest:
                raise ConversationError("来源处理或相关问题已有变化，请刷新后重新核对本批任务")
            entries = {UUID(item["source"]["id"]): item for item in current["entries"]}
            batch_id, results = uuid4(), []
            for item in body.assignments:
                entry = entries[item.source_row_id]
                if entry["correction"] is None:
                    raise ConversationError("所选来源尚无纠错记录，请先核对并记录来源纠错")
                issue = next(
                    (issue for issue in entry["issues"] if issue["id"] == str(item.issue_id)), None
                )
                if issue is None:
                    raise ConversationError("任务关联问题未在此来源的原记录或纠错历史中出现")
                t = tables.issue_intake_compensations
                signature_item = digest(item.model_dump(mode="json"))
                existing = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == ctx.tenant.id,
                            t.c.source_row_id == item.source_row_id,
                            t.c.source_revision == entry["current_source"]["revision"],
                            t.c.issue_id == item.issue_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing["assignment_digest"] != signature_item:
                        raise ConversationError(
                            "此来源版本和问题已有补偿任务，请进入原任务继续办理"
                        )
                    results.append(
                        {
                            "source_row_id": str(item.source_row_id),
                            "issue_id": str(item.issue_id),
                            "task_id": str(existing["task_id"]),
                            "status": "reused",
                        }
                    )
                    continue
                new_task = item.new_task
                details = (
                    new_task.description
                    + "\n\n导入来源纠错："
                    + entry["source"]["locator"]
                    + "\n"
                    + (f"/projects?project={project}&tab=work-items&entity_id={item.issue_id}")
                )
                try:
                    task = TaskService(self.engine).create(
                        tenant_id=ctx.tenant.id,
                        actor_user_id=ctx.user.id,
                        project_id=project,
                        connection=c,
                        draft=TaskDraft(
                            stage_id=new_task.stage_id,
                            parent_task_id=None,
                            assignee_user_id=new_task.assignee_user_id,
                            title=new_task.title,
                            description=details,
                            priority=new_task.priority,
                            start_date=new_task.start_date,
                            due_date=new_task.due_date,
                            dependency_task_ids=(),
                            kind="issue_action",
                            source_entity_id=item.issue_id,
                            expected_output=new_task.expected_output,
                        ),
                    )
                except TaskScopeError as error:
                    raise ConversationError(
                        "本批任务阶段或负责人已不可用，请核对后重试；本批尚未提交"
                    ) from error
                identity = uuid4()
                c.execute(
                    t.insert().values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        batch_id=batch_id,
                        source_row_id=item.source_row_id,
                        source_revision=entry["current_source"]["revision"],
                        issue_id=item.issue_id,
                        task_id=task.id,
                        assignment_digest=signature_item,
                        snapshot={
                            "source": entry["source"],
                            "correction": entry["correction"],
                            "issue": issue,
                            "assignment": item.model_dump(mode="json"),
                            "completion_criteria": item.completion_criteria,
                            "batch_reason": body.reason,
                        },
                        created_by_user_id=ctx.user.id,
                    )
                )
                EventAuditWriter(
                    c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
                ).record(
                    EventDraft(
                        event_id=f"issue-intake-compensation:{identity}",
                        event_type="ISSUE_INTAKE_SOURCE_RECORDED",
                        source="issue_intake_service",
                        entity_id=item.source_row_id,
                        payload={
                            "source_row_id": str(item.source_row_id),
                            "record_id": str(identity),
                            "action": "task_assigned",
                        },
                    ),
                    AuditDraft(
                        action="issue_intake.compensation_task",
                        after_snapshot={
                            "task_id": str(task.id),
                            "issue_id": str(item.issue_id),
                            "source_revision": entry["current_source"]["revision"],
                        },
                        context={"reason": body.reason},
                    ),
                )
                results.append(
                    {
                        "source_row_id": str(item.source_row_id),
                        "issue_id": str(item.issue_id),
                        "task_id": str(task.id),
                        "status": "created",
                    }
                )
            receipt = (
                c.execute(
                    batches.insert()
                    .values(
                        id=batch_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        request_id=body.request_id,
                        request_digest=signature,
                        request_snapshot=body.model_dump(mode="json"),
                        results=results,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(batches)
                )
                .mappings()
                .one()
            )
            return _plain(receipt)
