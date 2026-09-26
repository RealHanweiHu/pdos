"""Persistent human handoff of task context, separate from formal delivery acceptance."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.resource_reservations import _project
from app.domain.task_preparation import TaskPreparationService
from app.domain.task_takeover_knowledge import KnowledgeReference
from app.domain.task_takeover_knowledge import current as current_knowledge
from app.domain.task_takeover_knowledge import freeze as freeze_knowledge
from app.domain.task_takeover_knowledge import options as knowledge_options
from app.domain.task_takeover_residuals import (
    Residual,
)
from app.domain.task_takeover_residuals import (
    current as current_residuals,
)
from app.domain.task_takeover_residuals import (
    freeze as freeze_residuals,
)
from app.domain.tasks import TERMINAL_TASK_STATUSES, TaskNotFoundError
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

SECTIONS = ("goal", "constraints", "confirmed_facts", "open_items", "next_steps")


class PacketContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=5000)
    constraints: str = Field(min_length=1, max_length=5000)
    confirmed_facts: str = Field(min_length=1, max_length=10000)
    open_items: str = Field(min_length=1, max_length=10000)
    next_steps: str = Field(min_length=1, max_length=5000)


class PacketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["submitted", "accepted", "returned"]
    submission_id: UUID | None = None
    content: PacketContent | None = None
    residuals: list[Residual] = Field(default_factory=list, max_length=30)
    checked_residuals: list[str] = Field(default_factory=list, max_length=30)
    knowledge: list[KnowledgeReference] = Field(default_factory=list, max_length=10)
    checked_knowledge: list[UUID] = Field(default_factory=list, max_length=10)
    checked_sections: list[str] = Field(default_factory=list, max_length=5)
    note: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def valid_action(self) -> Self:
        if self.action == "submitted":
            if (
                self.content is None
                or self.submission_id is not None
                or self.checked_sections
                or self.checked_residuals
                or self.checked_knowledge
            ):
                raise ValueError("提交须填写完整交接内容")
        elif (
            self.content is not None
            or self.submission_id is None
            or self.residuals
            or self.knowledge
        ):
            raise ValueError("接收或退回须对应原交接包")
        if len(set(self.checked_sections)) != len(self.checked_sections) or not set(
            self.checked_sections
        ) <= set(SECTIONS):
            raise ValueError("核对项无效")
        if self.action == "accepted" and set(self.checked_sections) != set(SECTIONS):
            raise ValueError("接收前须逐项核对目标、约束、事实、遗留项和下一步")
        if len({(item.kind, item.id) for item in self.residuals}) != len(self.residuals):
            raise ValueError("同一遗留对象只关联一次")
        if len({item.push_id for item in self.knowledge}) != len(self.knowledge):
            raise ValueError("同一经验只关联一次")
        if len(set(self.checked_knowledge)) != len(self.checked_knowledge):
            raise ValueError("经验核对项不得重复")
        return self


def packet_state(
    c: Connection, ctx: AuthContext, project: UUID, task: UUID
) -> tuple[dict[str, Any], Any, str]:
    source = TaskPreparationService(c.engine).snapshot(ctx, project, task, c)
    source.pop("prepared_at", None)
    source.pop("basis_digest", None)
    t = tables.task_takeover_packets
    latest = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.task_id == task)
            .order_by(t.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return (
        source,
        latest,
        digest({"source": source, "latest_id": str(latest["id"]) if latest else None}),
    )


def read(
    engine: Engine, ctx: AuthContext, project: UUID, task: UUID, request_id: UUID | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        _project(c, ctx, project)
        t = tables.task_takeover_packets
        if request_id is not None:
            receipt = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.task_id == task,
                        t.c.actor_user_id == ctx.user.id,
                        t.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt is None:
                raise TaskNotFoundError
            return _plain(receipt)
        source, latest, state_digest = packet_state(c, ctx, project, task)
        entries = (
            c.execute(
                select(t)
                .where(
                    t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.task_id == task
                )
                .order_by(t.c.revision.desc())
                .limit(21)
            )
            .mappings()
            .all()
        )
        submission = latest
        if latest and latest["submission_id"]:
            submission = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id == latest["submission_id"],
                    )
                )
                .mappings()
                .one()
            )
        original_residuals = submission["payload"].get("residual_sources", []) if submission else []
        live_residuals = current_residuals(c, ctx.tenant.id, project, original_residuals)
        residual_views = [
            item
            | {
                "current": live_residuals.get((item["kind"], item["id"])),
                "changed": live_residuals.get((item["kind"], item["id"]), {}).get("digest")
                != item["expected_digest"],
            }
            for item in original_residuals
        ]
        knowledge_views = current_knowledge(
            c,
            ctx,
            project,
            task,
            submission["payload"].get("knowledge_sources", []) if submission else [],
        )
        receiver = source["task"]["assignee_user_id"]
        editable = is_allowed(Role(ctx.user.role), Action.WORK_ITEM_EDIT)
        return {
            "source": source,
            "digest": state_digest,
            "latest": _plain(latest) if latest else None,
            "submission": _plain(submission) if submission else None,
            "history": [_plain(item) for item in entries[:20]],
            "has_more": len(entries) > 20,
            "next_before_revision": entries[19]["revision"] if len(entries) > 20 else None,
            "knowledge_options": knowledge_options(c, ctx, project, task),
            "knowledge_sources": knowledge_views,
            "knowledge_unavailable": any(not item["available"] for item in knowledge_views),
            "residual_sources": residual_views,
            "residuals_changed": any(item["changed"] for item in residual_views),
            "source_changed": bool(submission and digest(submission["basis"]) != digest(source)),
            "can_submit": editable
            and bool(receiver)
            and receiver != str(ctx.user.id)
            and source["task"]["status"] not in TERMINAL_TASK_STATUSES,
            "can_review": editable
            and bool(
                latest
                and latest["action"] == "submitted"
                and latest["receiver_user_id"] == ctx.user.id
            )
            and receiver == str(ctx.user.id),
        }


def save(
    engine: Engine, ctx: AuthContext, project: UUID, task: UUID, body: PacketRequest
) -> dict[str, Any]:
    with engine.begin() as c:
        _project(c, ctx, project, write=True)
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"task-takeover:{ctx.tenant.id}:{ctx.user.id}:{body.request_id}"},
        )
        t = tables.task_takeover_packets
        signing = body.model_dump(mode="json")
        for field in ("residuals", "checked_residuals", "knowledge", "checked_knowledge"):
            if field not in body.model_fields_set:
                signing.pop(field)
        request_digest = digest({"project": str(project), "task": str(task), **signing})
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.actor_user_id == ctx.user.id,
                    t.c.request_id == body.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != request_digest:
                raise ProductWorkError("原请求编号已用于不同的交接内容")
            return _plain(prior)
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise TaskNotFoundError
        source, latest, current_digest = packet_state(c, ctx, project, task)
        if body.expected_digest != current_digest:
            raise ProductWorkError("任务或接手资料已变化，请刷新核对后提交")
        if source["task"]["status"] in TERMINAL_TASK_STATUSES:
            raise ProductWorkError("已结束任务保留历史，不再新增接手裁决")
        receiver = source["task"]["assignee_user_id"]
        if not receiver:
            raise ProductWorkError("请先通过原责任分派流程指定任务负责人")
        if body.action == "submitted":
            if receiver == str(ctx.user.id):
                raise ProductWorkError("交付人与接收人须为不同成员")
            member = c.execute(
                select(tables.users.c.id)
                .join(
                    tables.project_members,
                    (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.project_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.users.c.tenant_id == ctx.tenant.id,
                    tables.users.c.id == UUID(receiver),
                    tables.users.c.is_active.is_(True),
                    tables.project_members.c.project_id == project,
                )
            ).first()
            if member is None:
                raise ProductWorkError("当前接收人不是有效项目成员，请先完成责任分派")
            frozen = source
            residual_sources = freeze_residuals(c, ctx.tenant.id, project, task, body.residuals)
            knowledge_sources = freeze_knowledge(c, ctx, project, task, body.knowledge)
        else:
            if (
                not latest
                or latest["action"] != "submitted"
                or latest["id"] != body.submission_id
                or latest["receiver_user_id"] != ctx.user.id
                or receiver != str(ctx.user.id)
            ):
                raise ProductWorkError("只有当前具名接收人可办理最新交接包")
            if body.action == "accepted" and digest(latest["basis"]) != digest(source):
                raise ProductWorkError("交接依据已变化，请退回补齐后重新接收")
            residual_sources = latest["payload"].get("residual_sources", [])
            knowledge_sources = latest["payload"].get("knowledge_sources", [])
            if body.action == "accepted":
                if {str(item) for item in body.checked_knowledge} != {
                    item["push_id"] for item in knowledge_sources
                }:
                    raise ProductWorkError("请逐项核对交接经验的原文、版本和本任务适用说明")
                current_knowledge(c, ctx, project, task, knowledge_sources, lock=True)
                expected_keys = {f"{item['kind']}:{item['id']}" for item in residual_sources}
                if set(body.checked_residuals) != expected_keys or len(
                    body.checked_residuals
                ) != len(expected_keys):
                    raise ProductWorkError("请逐项核对每一条实际遗留工作的负责人、期限和接续事项")
                freeze_residuals(
                    c,
                    ctx.tenant.id,
                    project,
                    task,
                    [
                        Residual.model_validate(
                            {key: item[key] for key in ("kind", "id", "expected_digest", "note")}
                        )
                        for item in residual_sources
                    ],
                )
            frozen = latest["basis"]
        names = dict(
            c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == ctx.tenant.id,
                    tables.users.c.id.in_([ctx.user.id, UUID(receiver)]),
                )
            )
            .tuples()
            .all()
        )
        packet_id, now = uuid4(), datetime.now(UTC)
        payload = body.model_dump(mode="json") | {
            "knowledge_sources": knowledge_sources,
            "residual_sources": residual_sources,
            "actor_name": names[ctx.user.id],
            "receiver_name": names[UUID(receiver)],
        }
        result = (
            c.execute(
                t.insert()
                .values(
                    id=packet_id,
                    tenant_id=ctx.tenant.id,
                    project_id=project,
                    task_id=task,
                    revision=latest["revision"] + 1 if latest else 1,
                    action=body.action,
                    submission_id=body.submission_id,
                    actor_user_id=ctx.user.id,
                    receiver_user_id=UUID(receiver),
                    request_id=body.request_id,
                    request_digest=request_digest,
                    basis=frozen,
                    payload=payload,
                    created_at=now,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        EventAuditWriter(
            c, tenant_id=ctx.tenant.id, project_id=project, actor_user_id=ctx.user.id
        ).record(
            EventDraft(
                event_id=f"task-handoff:{packet_id}",
                event_type="TASK_TAKEOVER_RECORDED",
                source="task_takeover_service",
                entity_id=task,
                payload={"packet_id": str(packet_id), "action": body.action},
            ),
            AuditDraft(
                action=f"task.takeover.{body.action}",
                before_snapshot={"packet_id": str(latest["id"])} if latest else None,
                after_snapshot={
                    "packet_id": str(packet_id),
                    "revision": result["revision"],
                    "receiver_user_id": receiver,
                },
            ),
        )
        return _plain(result)


class TaskTakeoverIncompleteError(ValueError):
    pass


def guard_completion(c: Connection, tenant: UUID, project: UUID, task: UUID) -> None:
    t = tables.task_takeover_packets
    latest = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.task_id == task)
            .order_by(t.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if latest is None:
        return
    current = (
        c.execute(
            select(tables.tasks).where(
                tables.tasks.c.tenant_id == tenant,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id == task,
            )
        )
        .mappings()
        .one()
    )
    if latest["action"] != "accepted" or current["assignee_user_id"] != latest["receiver_user_id"]:
        raise TaskTakeoverIncompleteError(
            "交接资料尚未由当前任务负责人接收，请先在接手资料中接收或退回补齐"
        )
    actual = _plain(current)
    if any(
        actual[key] != latest["basis"]["task"][key]
        for key in ("title", "description", "assignee_user_id", "due_date", "expected_output")
    ):
        raise TaskTakeoverIncompleteError(
            "已接收的任务目标、输出或责任安排已变化，请更新交接包后重新接收"
        )


def history(
    engine: Engine, ctx: AuthContext, project: UUID, task: UUID, before_revision: int
) -> dict[str, Any]:
    with engine.connect() as c:
        _project(c, ctx, project)
        t = tables.task_takeover_packets
        entries = (
            c.execute(
                select(t)
                .where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.task_id == task,
                    t.c.revision < before_revision,
                )
                .order_by(t.c.revision.desc())
                .limit(21)
            )
            .mappings()
            .all()
        )
        return {
            "items": [_plain(item) for item in entries[:20]],
            "next_before_revision": entries[19]["revision"] if len(entries) > 20 else None,
        }
