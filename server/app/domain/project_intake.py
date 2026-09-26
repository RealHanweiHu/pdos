"""Versioned in-progress project observations and explicit initialization work."""

from contextlib import nullcontext
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_compensation_results import document_snapshot
from app.domain.issue_intake_compensations import task_view
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_intake_progress import earlier_work, progress
from app.domain.project_intake_work import (
    IntakeBusinessRef,
    TaskDependencyRef,
    business_snapshot,
    freeze_context,
    task_dependency_snapshots,
    work_order,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import TaskDraft, TaskService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: UUID
    kind: Literal["phase", "progress", "date", "responsibility", "gap", "other"]
    document_id: UUID
    expected_document_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordinal: int = Field(ge=1)
    expected_fragment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: int = Field(ge=0, lt=20000)
    end: int = Field(gt=0, le=20000)

    @model_validator(mode="after")
    def range_valid(self) -> "Observation":
        if self.end <= self.start:
            raise ValueError("请选择完整的非空原文")
        return self


class InitializationWork(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: UUID
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20000)
    expected_output: str | None = Field(default=None, max_length=20000)
    stage_id: UUID | None = None
    assignee_user_id: UUID | None = None
    start_date: date | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    observation_keys: list[UUID] = Field(default_factory=list, max_length=30)
    basis_note: str = Field(min_length=1, max_length=2000)
    reuse_task_id: UUID | None = None
    expected_task_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    source: IntakeBusinessRef | None = None
    predecessors: list[TaskDependencyRef] = Field(default_factory=list, max_length=50)
    predecessor_work_keys: list[UUID] = Field(default_factory=list, max_length=49)

    @model_validator(mode="after")
    def valid(self) -> "InitializationWork":
        if (self.reuse_task_id is None) != (self.expected_task_digest is None):
            raise ValueError("复用任务需要固定其当前版本")
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("本次计划完成日期不能早于开始日期")
        if len(self.observation_keys) != len(set(self.observation_keys)):
            raise ValueError("任务来源不能重复选择")
        if self.reuse_task_id and (self.source or self.predecessors or self.predecessor_work_keys):
            raise ValueError("关联已有任务保留原来源和依赖；修改请到原任务办理")
        if (
            len({ref.id for ref in self.predecessors}) != len(self.predecessors)
            or len(set(self.predecessor_work_keys)) != len(self.predecessor_work_keys)
            or self.key in self.predecessor_work_keys
        ):
            raise ValueError("前置工作不能重复或指向自身")
        self.predecessors.sort(key=lambda ref: str(ref.id))
        self.predecessor_work_keys.sort(key=str)
        self.observation_keys.sort(key=str)
        return self


class IntakeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_project_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    review_note: str = Field(min_length=1, max_length=4000)
    mapped_stage_id: UUID | None = None
    observations: list[Observation] = Field(default_factory=list, max_length=30)
    work: list[InitializationWork] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def references(self) -> "IntakeProposal":
        keys = {item.key for item in self.observations}
        if len(keys) != len(self.observations) or len({item.key for item in self.work}) != len(
            self.work
        ):
            raise ValueError("原文与工作条目标识不能重复")
        if any(set(item.observation_keys) - keys for item in self.work):
            raise ValueError("工作引用必须属于本次保存的原文")
        by_key = {item.key: item for item in self.work}
        work_order(by_key, list(by_key))
        return self


def work_payload(item: InitializationWork) -> dict[str, Any]:
    value = item.model_dump(mode="json")
    # Empty extensions retain the exact original work contract and replay digest.
    for key in ("source", "predecessors", "predecessor_work_keys"):
        if not value[key]:
            value.pop(key)
    return value


class IntakeApply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_keys: list[UUID] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    reviewed: Literal[True]

    @model_validator(mode="after")
    def unique(self) -> "IntakeApply":
        if len(set(self.work_keys)) != len(self.work_keys):
            raise ValueError("不能重复选择工作条目")
        self.work_keys.sort(key=str)
        return self


def authorize(c: Connection, ctx: AuthContext, project: UUID, write: bool = False) -> None:
    KnowledgeCorrectionService._authorize(
        c,
        ctx.tenant.id,
        ctx.user.id,
        project,
        Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW,
    )


def project_basis(c: Connection, ctx: AuthContext, project: UUID) -> dict[str, Any]:
    p, s = tables.projects, tables.stages
    row = (
        c.execute(
            select(
                p.c.id,
                p.c.name,
                p.c.status,
                p.c.workflow_id,
                p.c.current_stage_id,
                p.c.owner_user_id,
                p.c.start_date,
                p.c.target_date,
                p.c.updated_at,
            ).where(p.c.tenant_id == ctx.tenant.id, p.c.id == project)
        )
        .mappings()
        .one()
    )
    stages = [
        _plain(item)
        for item in c.execute(
            select(s.c.id, s.c.code, s.c.name, s.c.sequence, s.c.description)
            .where(s.c.tenant_id == ctx.tenant.id, s.c.workflow_id == row["workflow_id"])
            .order_by(s.c.sequence)
        ).mappings()
    ]
    value = {"project": _plain(row), "stages": stages}
    return value | {"digest": digest(value)}


def source_read(
    c: Connection, ctx: AuthContext, project: UUID, source: Observation
) -> dict[str, Any]:
    KnowledgeCorrectionService._authorize(
        c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
    )
    d, f = tables.documents, tables.document_fragments
    document = (
        c.execute(
            select(d).where(
                d.c.tenant_id == ctx.tenant.id,
                d.c.project_id == project,
                d.c.id == source.document_id,
                d.c.classification == "internal",
            )
        )
        .mappings()
        .one_or_none()
    )
    if document is None or digest(document_snapshot(document)) != source.expected_document_digest:
        raise ConversationError("来源文件已变化或不属于本项目内部资料，请重新核对")
    fragment = (
        c.execute(
            select(f.c.ordinal, f.c.locator, f.c.text).where(
                f.c.tenant_id == ctx.tenant.id,
                f.c.project_id == project,
                f.c.document_id == source.document_id,
                f.c.ordinal == source.ordinal,
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        fragment is None
        or digest(dict(fragment)) != source.expected_fragment_digest
        or source.end > len(fragment["text"])
    ):
        raise ConversationError("原文范围或抽取版本已变化，请重新选择")
    return {
        "key": str(source.key),
        "kind": source.kind,
        "document": document_snapshot(document),
        "ordinal": source.ordinal,
        "locator": fragment["locator"],
        "start": source.start,
        "end": source.end,
        "quote": fragment["text"][source.start : source.end],
        "extraction_metadata_digest": digest(document["extraction_metadata"]),
        "document_href": (
            f"/projects?project={project}&tab=documents&document_id={source.document_id}"
        ),
    }


def work_gaps(item: InitializationWork) -> list[str]:
    if item.reuse_task_id:
        return []
    return [
        label
        for label, value in (
            ("当前阶段归属", item.stage_id),
            ("本次具名负责人", item.assignee_user_id),
            ("本次完成日期", item.due_date),
            ("交付要求", item.expected_output),
        )
        if not value
    ]


def proposal_row(c: Connection, ctx: AuthContext, project: UUID, identity: UUID) -> Any:
    t = tables.project_intake_proposals
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConversationError("初始化版本不属于当前项目")
    return row


def record_event(
    c: Connection, ctx: AuthContext, project: UUID, proposal: UUID, record: UUID, action: str
) -> None:
    EventAuditWriter(
        c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"project-intake:{record}:{action}",
            event_type="PROJECT_INTAKE_RECORDED",
            source="project_intake_service",
            entity_id=proposal,
            payload={"proposal_id": str(proposal), "record_id": str(record), "action": action},
        ),
        AuditDraft(
            action=f"project.intake_{action}",
            after_snapshot={"proposal_id": str(proposal), "record_id": str(record)},
        ),
    )


class ProjectIntakeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def overview(
        self, ctx: AuthContext, project: UUID, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            basis = project_basis(c, ctx, project)
            p, u, m = tables.project_intake_proposals, tables.users, tables.project_members
            latest = c.execute(
                select(func.coalesce(func.max(p.c.revision), 0)).where(
                    p.c.tenant_id == ctx.tenant.id, p.c.project_id == project
                )
            ).scalar_one()
            query = (
                select(
                    p.c.id,
                    p.c.revision,
                    p.c.created_at,
                    p.c.created_by_user_id,
                    p.c.purpose,
                    u.c.display_name.label("actor_name"),
                )
                .join(u, (u.c.tenant_id == p.c.tenant_id) & (u.c.id == p.c.created_by_user_id))
                .where(p.c.tenant_id == ctx.tenant.id, p.c.project_id == project)
            )
            if before_revision:
                query = query.where(p.c.revision < before_revision)
            versions = c.execute(query.order_by(p.c.revision.desc()).limit(21)).mappings().all()
            members = [
                _plain(row)
                for row in c.execute(
                    select(u.c.id, u.c.display_name)
                    .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                    .where(
                        m.c.project_id == project,
                        m.c.tenant_id == ctx.tenant.id,
                        u.c.is_active.is_(True),
                        u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                    )
                    .order_by(u.c.display_name, u.c.id)
                ).mappings()
            ]
            return basis | {
                "latest_revision": latest,
                "members": members,
                "versions": [_plain(row) for row in versions[:20]],
                "next_revision": versions[19]["revision"] if len(versions) > 20 else None,
            }

    def sources(
        self, ctx: AuthContext, project: UUID, search: str = "", before_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            d = tables.documents
            query = select(d).where(
                d.c.tenant_id == ctx.tenant.id,
                d.c.project_id == project,
                d.c.classification == "internal",
            )
            if search.strip():
                query = query.where(d.c.filename.icontains(search.strip(), autoescape=True))
            if before_id:
                query = query.where(d.c.id < before_id)
            result = c.execute(query.order_by(d.c.id.desc()).limit(51)).mappings().all()
            return {
                "items": [
                    document_snapshot(row)
                    | {
                        "digest": digest(document_snapshot(row)),
                        "fragment_count": row["fragment_count"],
                    }
                    for row in result[:50]
                ],
                "next_id": str(result[49]["id"]) if len(result) > 50 else None,
            }

    def source_text(
        self, ctx: AuthContext, project: UUID, identity: UUID, after: int = 0
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            d, f = tables.documents, tables.document_fragments
            document = (
                c.execute(
                    select(d).where(
                        d.c.tenant_id == ctx.tenant.id,
                        d.c.project_id == project,
                        d.c.id == identity,
                        d.c.classification == "internal",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if document is None:
                raise ConversationError("资料不属于当前项目内部原件")
            result = (
                c.execute(
                    select(f.c.ordinal, f.c.locator, f.c.text)
                    .where(
                        f.c.tenant_id == ctx.tenant.id,
                        f.c.project_id == project,
                        f.c.document_id == identity,
                        f.c.ordinal > after,
                    )
                    .order_by(f.c.ordinal)
                    .limit(11)
                )
                .mappings()
                .all()
            )
            return {
                "document": document_snapshot(document),
                "digest": digest(document_snapshot(document)),
                "extraction_metadata": document["extraction_metadata"],
                "fragments": [_plain(row) | {"digest": digest(dict(row))} for row in result[:10]],
                "next_after": result[9]["ordinal"] if len(result) > 10 else None,
            }

    def task_options(
        self, ctx: AuthContext, project: UUID, search: str = "", before_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            t = tables.tasks
            query = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
            if search.strip():
                query = query.where(t.c.title.icontains(search.strip(), autoescape=True))
            if before_id:
                query = query.where(t.c.id < before_id)
            result = c.execute(query.order_by(t.c.id.desc()).limit(51)).mappings().all()
            dependency_views = task_dependency_snapshots(
                c, ctx.tenant.id, project, list(result[:50])
            )
            return {
                "items": [
                    task_view(row)
                    | {
                        "digest": digest(task_view(row)),
                        "dependency_snapshot": dependency_views[row["id"]],
                        "dependency_digest": digest(dependency_views[row["id"]]),
                    }
                    for row in result[:50]
                ],
                "next_id": str(result[49]["id"]) if len(result) > 50 else None,
            }

    def work_sources(
        self,
        ctx: AuthContext,
        project: UUID,
        kind: Literal["issue", "risk", "decision"],
        search: str = "",
        before_id: UUID | None = None,
        target_id: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            t = {"issue": tables.issues, "risk": tables.risks, "decision": tables.decisions}[kind]
            query = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
            if kind == "risk":
                query = query.where(t.c.draft_state == "confirmed")
            if target_id is not None:
                query = query.where(t.c.id == target_id)
            if search.strip():
                query = query.where(t.c.title.icontains(search.strip(), autoescape=True))
            if before_id:
                query = query.where(t.c.id < before_id)
            result = c.execute(query.order_by(t.c.id.desc()).limit(51)).mappings().all()
            snapshots = [business_snapshot(row, kind, c) for row in result[:50]]
            return {
                "items": [value | {"digest": digest(value)} for value in snapshots],
                "next_id": str(result[49]["id"]) if len(result) > 50 else None,
            }

    def save(
        self,
        ctx: AuthContext,
        project: UUID,
        body: IntakeProposal,
        *,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        signature_input = body.model_dump(mode="json", exclude={"request_id"})
        signature_input["work"] = [work_payload(item) for item in body.work]
        signature = digest(signature_input)
        with nullcontext(connection) if connection is not None else self.engine.begin() as c:
            authorize(c, ctx, project, write=True)
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目暂不可办理")
            t = tables.project_intake_proposals
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                if old["request_digest"] != signature:
                    raise ConversationError("此请求已对应另一份现状版本")
                return _plain(old)
            basis = project_basis(c, ctx, project)
            latest = c.execute(
                select(func.coalesce(func.max(t.c.revision), 0)).where(
                    t.c.tenant_id == ctx.tenant.id, t.c.project_id == project
                )
            ).scalar_one()
            if latest != body.expected_revision or basis["digest"] != body.expected_project_digest:
                raise ConversationError("已有更新版本或项目现状变化，请读取后再保存新版本")
            stage_ids = {item["id"] for item in basis["stages"]}
            if body.mapped_stage_id and str(body.mapped_stage_id) not in stage_ids:
                raise ConversationError("阶段映射必须来自当前项目流程")
            sources = [source_read(c, ctx, project, item) for item in body.observations]
            if sum(len(item["quote"]) for item in sources) > 200000:
                raise ConversationError("本次原文超过20万字，请缩小选段")
            reuse_snapshots = {}
            contexts = {}
            for item in body.work:
                context = freeze_context(c, ctx, project, item.source, item.predecessors)
                if context:
                    contexts[str(item.key)] = context
                if item.stage_id and str(item.stage_id) not in stage_ids:
                    raise ConversationError("工作阶段不属于本项目")
                TaskService._validate_member(
                    c, tenant_id=ctx.tenant.id, project_id=project, user_id=item.assignee_user_id
                )
                if item.reuse_task_id:
                    target = (
                        c.execute(
                            select(tables.tasks).where(
                                tables.tasks.c.tenant_id == ctx.tenant.id,
                                tables.tasks.c.project_id == project,
                                tables.tasks.c.id == item.reuse_task_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if target is None or digest(task_view(target)) != item.expected_task_digest:
                        raise ConversationError("所选已有任务已变化，请重新读取当前任务")
                    reuse_snapshots[str(item.key)] = task_view(target)
            identity = uuid4()
            draft = body.model_dump(
                mode="json", exclude={"request_id", "expected_revision", "expected_project_digest"}
            )
            draft["work"] = [work_payload(item) for item in body.work]
            if contexts:
                draft["work_context"] = contexts
            draft["reuse_tasks"] = reuse_snapshots
            gaps = {str(item.key): work_gaps(item) for item in body.work}
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        revision=latest + 1,
                        request_id=body.request_id,
                        request_digest=signature,
                        purpose=body.purpose,
                        draft=draft,
                        sources=sources,
                        project_snapshot=basis,
                        gaps=gaps,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            record_event(c, ctx, project, identity, identity, "save")
            return _plain(row)

    def get(self, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        from app.domain.intake_ai_observations import adoption_origins

        with self.engine.connect() as c:
            authorize(c, ctx, project)
            row = proposal_row(c, ctx, project, identity)
            current = project_basis(c, ctx, project)
            source_states = []
            for value in row["draft"]["observations"]:
                try:
                    snapshot = source_read(c, ctx, project, Observation.model_validate(value))
                    source_states.append(
                        {
                            "key": value["key"],
                            "current": snapshot
                            == next(item for item in row["sources"] if item["key"] == value["key"]),
                        }
                    )
                except ConversationError:
                    source_states.append({"key": value["key"], "current": False})
            b = tables.project_intake_work
            bound = (
                c.execute(
                    select(b).where(
                        b.c.tenant_id == ctx.tenant.id,
                        b.c.project_id == project,
                        b.c.work_key.in_([UUID(item["key"]) for item in row["draft"]["work"]]),
                    )
                )
                .mappings()
                .all()
            )
            task_ids = [item["task_id"] for item in bound]
            current_tasks = (
                {
                    str(item["id"]): task_view(item)
                    for item in c.execute(
                        select(tables.tasks).where(
                            tables.tasks.c.tenant_id == ctx.tenant.id,
                            tables.tasks.c.project_id == project,
                            tables.tasks.c.id.in_(task_ids),
                        )
                    ).mappings()
                }
                if task_ids
                else {}
            )
            extended_ids = [
                item["task_id"] for item in bound if "dependencies" in item["task_snapshot"]
            ]
            if extended_ids:
                task_rows = list(
                    c.execute(
                        select(tables.tasks).where(
                            tables.tasks.c.tenant_id == ctx.tenant.id,
                            tables.tasks.c.project_id == project,
                            tables.tasks.c.id.in_(extended_ids),
                        )
                    ).mappings()
                )
                current_tasks.update(
                    {
                        str(key): value
                        for key, value in task_dependency_snapshots(
                            c, ctx.tenant.id, project, task_rows
                        ).items()
                    }
                )
            context_states = {}
            for raw_item in row["draft"]["work"]:
                item = InitializationWork.model_validate(raw_item)
                try:
                    context = freeze_context(c, ctx, project, item.source, item.predecessors)
                    context_states[str(item.key)] = {
                        "current": context
                        == row["draft"].get("work_context", {}).get(str(item.key), {})
                    }
                except ConversationError as error:
                    context_states[str(item.key)] = {"current": False, "reason": str(error)}
            work_digests = {
                item["key"]: digest(
                    {
                        "work": item,
                        "sources": [
                            source
                            for source in row["sources"]
                            if source["key"] in item["observation_keys"]
                        ],
                    }
                )
                for item in row["draft"]["work"]
            }
            a = tables.project_intake_applications
            receipts = (
                c.execute(
                    select(a)
                    .where(
                        a.c.tenant_id == ctx.tenant.id,
                        a.c.project_id == project,
                        a.c.proposal_id == identity,
                    )
                    .order_by(a.c.created_at.desc(), a.c.id.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            public_bindings = [
                _plain(item)
                | {
                    "current_task": current_tasks.get(str(item["task_id"])),
                    "matches_proposal": item["input_digest"]
                    == work_digests.get(str(item["work_key"])),
                }
                for item in bound
            ]
            return _plain(row) | {
                "current_project": current,
                "project_current": current == row["project_snapshot"],
                "source_states": source_states,
                "context_states": context_states,
                "bindings": public_bindings,
                "ai_adoptions": adoption_origins(c, ctx, project, identity),
                "receipts": [_plain(item) for item in receipts],
                "progress": progress(
                    c,
                    ctx,
                    project,
                    row,
                    public_bindings,
                    source_states,
                    context_states,
                    current == row["project_snapshot"],
                ),
            }

    def earlier_work(
        self, ctx: AuthContext, project: UUID, identity: UUID, before_id: UUID | None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            row = proposal_row(c, ctx, project, identity)
            return earlier_work(c, ctx, project, row, before_id)

    def apply(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: IntakeApply
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            authorize(c, ctx, project, write=True)
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目暂不可办理")
            a, b = tables.project_intake_applications, tables.project_intake_work
            row = proposal_row(c, ctx, project, identity)
            old = (
                c.execute(
                    select(a).where(
                        a.c.tenant_id == ctx.tenant.id,
                        a.c.project_id == project,
                        a.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                if old["proposal_id"] != identity or old["request_digest"] != signature:
                    raise ConversationError("此办理请求已对应其他初始化工作")
                return _plain(old)
            p = tables.project_intake_proposals
            latest = c.execute(
                select(func.max(p.c.revision)).where(
                    p.c.tenant_id == ctx.tenant.id, p.c.project_id == project
                )
            ).scalar_one()
            if row["revision"] != latest:
                raise ConversationError("已有更新的现状版本，请在最新版本继续办理")
            if row["request_digest"] != body.expected_digest or row[
                "project_snapshot"
            ] != project_basis(c, ctx, project):
                raise ConversationError("初始化版本或项目现状已变化，请核对后保存新版本")
            sources = [
                source_read(c, ctx, project, Observation.model_validate(item))
                for item in row["draft"]["observations"]
            ]
            if sources != row["sources"]:
                raise ConversationError("原文来源已变化，请重新核对")
            raw_work = {UUID(item["key"]): item for item in row["draft"]["work"]}
            work = {
                UUID(item["key"]): InitializationWork.model_validate(item)
                for item in row["draft"]["work"]
            }
            if set(body.work_keys) - set(work):
                raise ConversationError("所选工作不属于这份初始化版本")
            receipt_id, results = uuid4(), []
            resolved_tasks: dict[UUID, UUID] = {}
            for key in work_order(work, body.work_keys):
                item = work[key]
                selected_sources = [
                    source for source in sources if UUID(source["key"]) in item.observation_keys
                ]
                item_digest = digest({"work": raw_work[key], "sources": selected_sources})
                prior = (
                    c.execute(
                        select(b).where(
                            b.c.tenant_id == ctx.tenant.id,
                            b.c.project_id == project,
                            b.c.work_key == key,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior is not None:
                    if prior["input_digest"] != item_digest:
                        raise ConversationError(
                            "此项工作已办理且内容不同，请进入原任务修正；独立的新工作应另建条目"
                        )
                    resolved_tasks[key] = prior["task_id"]
                    results.append(
                        {
                            "work_key": str(key),
                            "task_id": str(prior["task_id"]),
                            "status": "reused",
                            "href": (
                                f"/projects?project={project}&tab=work-items"
                                f"&entity_id={prior['task_id']}"
                            ),
                        }
                    )
                    continue
                context = freeze_context(c, ctx, project, item.source, item.predecessors)
                if context != row["draft"].get("work_context", {}).get(str(key), {}):
                    raise ConversationError("任务来源或前置依赖与原核对版本不同，请重新保存")
                dependency_ids = {ref.id for ref in item.predecessors}
                for predecessor in item.predecessor_work_keys:
                    if predecessor not in resolved_tasks:
                        binding = (
                            c.execute(
                                select(b).where(
                                    b.c.tenant_id == ctx.tenant.id,
                                    b.c.project_id == project,
                                    b.c.work_key == predecessor,
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        expected = digest(
                            {
                                "work": raw_work[predecessor],
                                "sources": [
                                    source
                                    for source in sources
                                    if UUID(source["key"]) in work[predecessor].observation_keys
                                ],
                            }
                        )
                        if binding is None or binding["input_digest"] != expected:
                            raise ConversationError(
                                "前置工作尚未按本版办理，请连同前置工作选择，或核对其原任务"
                            )
                        resolved_tasks[predecessor] = binding["task_id"]
                    dependency_ids.add(resolved_tasks[predecessor])
                if work_gaps(item):
                    raise ConversationError(
                        "所选工作还有负责人、阶段、日期或交付要求缺项，请补齐或暂不选择"
                    )
                if item.reuse_task_id:
                    target = (
                        c.execute(
                            select(tables.tasks)
                            .where(
                                tables.tasks.c.tenant_id == ctx.tenant.id,
                                tables.tasks.c.project_id == project,
                                tables.tasks.c.id == item.reuse_task_id,
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if target is None or digest(task_view(target)) != item.expected_task_digest:
                        raise ConversationError("已有任务已变化，请重新读取核对后关联")
                    task_id = target["id"]
                    snapshot = task_view(target)
                    status = "linked"
                else:
                    task = TaskService(self.engine).create(
                        tenant_id=ctx.tenant.id,
                        actor_user_id=ctx.user.id,
                        project_id=project,
                        connection=c,
                        draft=TaskDraft(
                            stage_id=item.stage_id,
                            parent_task_id=None,
                            assignee_user_id=item.assignee_user_id,
                            title=item.title,
                            description=item.description,
                            priority=item.priority,
                            start_date=item.start_date,
                            due_date=item.due_date,
                            dependency_task_ids=tuple(sorted(dependency_ids, key=str)),
                            kind=f"{item.source.kind}_action"
                            if item.source and item.source.kind in {"issue", "risk"}
                            else "task",
                            source_entity_id=item.source.id
                            if item.source and item.source.kind in {"issue", "risk"}
                            else None,
                            expected_output=item.expected_output,
                        ),
                    )
                    task_id = task.id
                    target = (
                        c.execute(
                            select(tables.tasks).where(
                                tables.tasks.c.tenant_id == ctx.tenant.id,
                                tables.tasks.c.project_id == project,
                                tables.tasks.c.id == task_id,
                            )
                        )
                        .mappings()
                        .one()
                    )
                    snapshot = task_view(target)
                    status = "created"
                if item.source or item.predecessors or item.predecessor_work_keys:
                    snapshot = task_dependency_snapshots(c, ctx.tenant.id, project, [target])[
                        task_id
                    ]
                c.execute(
                    b.insert().values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        proposal_id=identity,
                        work_key=key,
                        task_id=task_id,
                        input_digest=item_digest,
                        work_snapshot=raw_work[key],
                        source_snapshot=selected_sources,
                        task_snapshot=snapshot,
                        link_kind=status,
                        created_by_user_id=ctx.user.id,
                    )
                )
                resolved_tasks[key] = task_id
                results.append(
                    {
                        "work_key": str(key),
                        "task_id": str(task_id),
                        "status": status,
                        "href": snapshot["href"],
                    }
                )
            receipt = (
                c.execute(
                    a.insert()
                    .values(
                        id=receipt_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        proposal_id=identity,
                        request_id=body.request_id,
                        request_digest=signature,
                        reason=body.reason,
                        results=results,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(a)
                )
                .mappings()
                .one()
            )
            record_event(c, ctx, project, identity, receipt_id, "apply")
            return _plain(receipt)

    def decision_work(
        self, ctx: AuthContext, project: UUID, decision: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            d, b, p, t = (
                tables.decisions,
                tables.project_intake_work,
                tables.project_intake_proposals,
                tables.tasks,
            )
            row = (
                c.execute(
                    select(d).where(
                        d.c.tenant_id == ctx.tenant.id,
                        d.c.project_id == project,
                        d.c.id == decision,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationError("此决策不属于本项目")
            current = business_snapshot(row, "decision", c)
            query = (
                select(b, p.c.revision, p.c.draft)
                .join(p, (p.c.tenant_id == b.c.tenant_id) & (p.c.id == b.c.proposal_id))
                .where(
                    b.c.tenant_id == ctx.tenant.id,
                    b.c.project_id == project,
                    b.c.work_snapshot["source"]["kind"].astext == "decision",
                    b.c.work_snapshot["source"]["id"].astext == str(decision),
                )
            )
            if before_id:
                query = query.where(b.c.id < before_id)
            bindings = list(c.execute(query.order_by(b.c.id.desc()).limit(21)).mappings())
            tasks = {
                value["id"]: task_view(value)
                for value in c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id.in_([value["task_id"] for value in bindings[:20]]),
                    )
                ).mappings()
            }
            return {
                "items": [
                    {
                        "id": str(value["id"]),
                        "proposal_id": str(value["proposal_id"]),
                        "revision": value["revision"],
                        "basis_note": value["work_snapshot"]["basis_note"],
                        "created_at": value["created_at"].isoformat(),
                        "task": tasks.get(value["task_id"]),
                        "source_current": value["draft"]
                        .get("work_context", {})
                        .get(str(value["work_key"]), {})
                        .get("source")
                        == current,
                    }
                    for value in bindings[:20]
                ],
                "next_id": str(bindings[19]["id"]) if len(bindings) > 20 else None,
            }
