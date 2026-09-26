"""Human source-backed mechanical interfaces and hardware substitution review packages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.firmware_package_tasks import NewTask, _task
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import TERMINAL_TASK_STATUSES, TaskDraft, TaskService
from app.domain.test_verification_paths import _authorize

SourceKind = Literal["specification", "bom_item", "document"]


class EngineeringReviewError(ValueError):
    pass


class ReviewSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: UUID
    kind: SourceKind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=2000)


class ReviewLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: UUID
    parameter: str = Field(min_length=1, max_length=256)
    baseline_value: str | None = Field(default=None, min_length=1, max_length=4000)
    proposed_value: str | None = Field(default=None, min_length=1, max_length=4000)
    unit: str | None = Field(default=None, max_length=64)
    baseline_sources: list[UUID] = Field(default_factory=list, max_length=20)
    proposed_sources: list[UUID] = Field(default_factory=list, max_length=20)
    verdict: Literal["compatible", "incompatible", "unknown"]
    basis: str = Field(min_length=1, max_length=4000)
    verification_criteria: str = Field(min_length=1, max_length=4000)
    new_task: NewTask | None = None
    existing_task_id: UUID | None = None
    existing_task_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def references_and_task(self) -> ReviewLine:
        if (
            self.baseline_value
            and not self.baseline_sources
            or self.proposed_value
            and not self.proposed_sources
        ):
            raise ValueError("已填写的原值和拟议值都需要对应出处")
        if self.verdict == "compatible" and (not self.baseline_value or not self.proposed_value):
            raise ValueError("缺少原值或拟议值时，兼容性应保留待验证")
        if self.new_task and self.existing_task_id:
            raise ValueError("同一对照项请选择新建或关联原任务")
        if self.verdict != "compatible" and not (self.new_task or self.existing_task_id):
            raise ValueError("未知或不兼容的项目需要具名验证任务")
        if self.existing_task_id and not self.existing_task_digest:
            raise ValueError("请先核对原任务的当前状态")
        return self


class ReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    parent_id: UUID | None = None
    kind: Literal["mechanical_interface", "hardware_substitution", "spec_bom_review"]
    title: str = Field(min_length=1, max_length=512)
    scope: str = Field(min_length=1, max_length=10000)
    proposed_change: str = Field(min_length=1, max_length=10000)
    unknown_impacts: str = Field(min_length=1, max_length=10000)
    coordination: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    sources: list[ReviewSource] = Field(min_length=1, max_length=100)
    lines: list[ReviewLine] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_keys(self) -> ReviewDraft:
        keys = {s.key for s in self.sources}
        if len(keys) != len(self.sources) or len({(s.kind, s.id) for s in self.sources}) != len(
            self.sources
        ):
            raise ValueError("同一出处请合并定位说明后引用一次")
        if len({line.key for line in self.lines}) != len(self.lines):
            raise ValueError("对照项标识重复")
        for line in self.lines:
            if not set(line.baseline_sources + line.proposed_sources).issubset(keys):
                raise ValueError("对照项只能引用本资料中已核对的出处")
        return self


def source_table(kind: SourceKind) -> Any:
    return {
        "specification": tables.specifications,
        "bom_item": tables.development_bom_items,
        "document": tables.documents,
    }[kind]


def source(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: SourceKind, id: UUID
) -> dict[str, Any]:
    t = source_table(kind)
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EngineeringReviewError("出处已不可用或不属于本项目")
    if kind == "document":
        return _plain(
            {
                key: row[key]
                for key in (
                    "id",
                    "filename",
                    "media_type",
                    "sha256",
                    "classification",
                    "created_at",
                )
            }
        )
    result = dict(row)
    if kind == "bom_item":
        bom = (
            c.execute(
                select(tables.development_boms).where(
                    tables.development_boms.c.tenant_id == tenant_id,
                    tables.development_boms.c.project_id == project_id,
                    tables.development_boms.c.id == row["bom_id"],
                )
            )
            .mappings()
            .one()
        )
        result["bom"] = {
            key: bom[key]
            for key in ("id", "code", "name", "version", "bom_type", "specification_id")
        }
    return _plain(result)


def sources(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    kind: SourceKind,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    t = source_table(kind)
    q = select(t.c.id).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
    if after_id:
        q = q.where(t.c.id > after_id)
    with engine.connect() as c:
        ids = list(c.execute(q.order_by(t.c.id).limit(51)).scalars())
        items = [source(c, context.tenant.id, project_id, kind, id) for id in ids[:50]]
    return {
        "items": [{"id": s["id"], "kind": kind, "snapshot": s, "digest": digest(s)} for s in items],
        "next_cursor": str(ids[49]) if len(ids) > 50 else None,
    }


def options(engine: Engine, *, context: AuthContext, project_id: UUID) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect() as c:
        workflow = c.execute(
            select(tables.projects.c.workflow_id).where(
                tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project_id
            )
        ).scalar_one()
        stages = [
            dict(r)
            for r in c.execute(
                select(tables.stages.c.id, tables.stages.c.name)
                .where(
                    tables.stages.c.tenant_id == context.tenant.id,
                    tables.stages.c.workflow_id == workflow,
                )
                .order_by(tables.stages.c.sequence)
            ).mappings()
        ]
        u, m = tables.users, tables.project_members
        members = [
            dict(r)
            for r in c.execute(
                select(u.c.id, u.c.display_name)
                .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                .where(
                    u.c.tenant_id == context.tenant.id,
                    m.c.project_id == project_id,
                    u.c.is_active.is_(True),
                    u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
        ]
    return _plain({"stages": stages, "members": members})


def history(
    engine: Engine, *, context: AuthContext, project_id: UUID, before_id: UUID | None = None
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    t, u = tables.engineering_review_packages, tables.users
    q = (
        select(t, u.c.display_name.label("created_by_name"))
        .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
        .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
    )
    with engine.connect() as c:
        if before_id:
            boundary = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.id == before_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if boundary is None:
                raise EngineeringReviewError("分页位置已不可用")
            q = q.where(
                (t.c.created_at < boundary["created_at"])
                | ((t.c.created_at == boundary["created_at"]) & (t.c.id < before_id))
            )
        items = [
            dict(r)
            for r in c.execute(
                q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)
            ).mappings()
        ]
    return _plain(
        {"items": items[:20], "next_cursor": items[19]["id"] if len(items) > 20 else None}
    )


def read(
    engine: Engine, *, context: AuthContext, project_id: UUID, package_id: UUID
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    p, links_table = tables.engineering_review_packages, tables.engineering_review_tasks
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        package = (
            c.execute(
                select(p).where(
                    p.c.tenant_id == context.tenant.id,
                    p.c.project_id == project_id,
                    p.c.id == package_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if package is None:
            raise EngineeringReviewError("评审资料不存在")
        latest = c.execute(
            select(p.c.id)
            .where(p.c.tenant_id == context.tenant.id, p.c.root_id == package["root_id"])
            .order_by(p.c.revision_number.desc())
            .limit(1)
        ).scalar_one()
        refs = []
        for ref in package["snapshot"]["sources"]:
            try:
                current = source(c, context.tenant.id, project_id, ref["kind"], UUID(ref["id"]))
            except EngineeringReviewError:
                current = None
            refs.append(
                {
                    **ref,
                    "current": current,
                    "current_digest": digest(current) if current else None,
                    "changed": not current or digest(current) != ref["expected_digest"],
                }
            )
        # Include older still-open tasks so a new review never conceals unfinished work.
        links = (
            c.execute(
                select(links_table)
                .join(
                    p,
                    (p.c.tenant_id == links_table.c.tenant_id)
                    & (p.c.id == links_table.c.package_id),
                )
                .where(
                    links_table.c.tenant_id == context.tenant.id,
                    links_table.c.project_id == project_id,
                    p.c.root_id == package["root_id"],
                )
                .order_by(links_table.c.created_at, links_table.c.id)
            )
            .mappings()
            .all()
        )
        tasks = [
            {**_plain(dict(link)), "task": _task(c, context.tenant.id, project_id, link["task_id"])}
            for link in links
        ]
        for item in tasks:
            item["digest"] = digest(item["task"])
    return _plain({"package": dict(package), "latest_id": latest, "sources": refs, "tasks": tasks})


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, draft: ReviewDraft
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    needs_tasks = any(line.new_task or line.existing_task_id for line in draft.lines)
    access = ProjectAccessService(SqlProjectAccessRepository(engine))
    if needs_tasks:
        access.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT)
    fingerprint = digest({"project_id": str(project_id), **draft.model_dump(mode="json")})
    p = tables.engineering_review_packages
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise EngineeringReviewError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
        if needs_tasks:
            access.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT)
        receipt = (
            c.execute(
                select(p).where(
                    p.c.tenant_id == context.tenant.id,
                    p.c.created_by_user_id == context.user.id,
                    p.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt:
            if receipt["request_digest"] != fingerprint:
                raise EngineeringReviewError("同一提交请求不能改写为不同评审，请重新核对")
            return _plain(dict(receipt))
        id = uuid4()
        root_id, revision = id, 1
        if draft.parent_id:
            parent = (
                c.execute(
                    select(p).where(
                        p.c.tenant_id == context.tenant.id,
                        p.c.project_id == project_id,
                        p.c.id == draft.parent_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if parent is None:
                raise EngineeringReviewError("原评审资料不存在")
            latest = c.execute(
                select(p.c.id)
                .where(p.c.tenant_id == context.tenant.id, p.c.root_id == parent["root_id"])
                .order_by(p.c.revision_number.desc())
                .limit(1)
            ).scalar_one()
            if latest != draft.parent_id or parent["snapshot"]["kind"] != draft.kind:
                raise EngineeringReviewError("请读取同类评审的最新资料后修订")
            root_id, revision = parent["root_id"], parent["revision_number"] + 1
        refs = []
        for ref in draft.sources:
            current = source(c, context.tenant.id, project_id, ref.kind, ref.id)
            if digest(current) != ref.expected_digest:
                raise EngineeringReviewError("规格、BOM或文件已变化，请重新核对出处")
            refs.append({**ref.model_dump(mode="json"), "snapshot": current})
        links, lines = [], []
        for line in draft.lines:
            task_id = line.existing_task_id
            if line.new_task:
                task = TaskService(engine).create(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                    draft=TaskDraft(
                        **line.new_task.model_dump(), parent_task_id=None, dependency_task_ids=()
                    ),
                    connection=c,
                )
                task_id = task.id
            elif task_id:
                current_task = _task(c, context.tenant.id, project_id, task_id)
                if (
                    current_task["kind"] != "task"
                    or current_task["status"] in TERMINAL_TASK_STATUSES
                    or digest(current_task) != line.existing_task_digest
                ):
                    raise EngineeringReviewError("原验证任务已结束或已变化，请重新核对")
            if task_id:
                links.append(
                    {
                        "id": uuid4(),
                        "tenant_id": context.tenant.id,
                        "project_id": project_id,
                        "package_id": id,
                        "line_key": line.key,
                        "task_id": task_id,
                        "created_at": datetime.now(UTC),
                    }
                )
            lines.append(
                {
                    **line.model_dump(
                        mode="json",
                        exclude={"new_task", "existing_task_id", "existing_task_digest"},
                    ),
                    "task_id": str(task_id) if task_id else None,
                }
            )
        snapshot = {
            **draft.model_dump(
                mode="json", exclude={"request_id", "parent_id", "sources", "lines"}
            ),
            "sources": refs,
            "lines": lines,
        }
        row = (
            c.execute(
                p.insert()
                .values(
                    id=id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    root_id=root_id,
                    parent_id=draft.parent_id,
                    revision_number=revision,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    snapshot=snapshot,
                )
                .returning(p)
            )
            .mappings()
            .one()
        )
        if links:
            c.execute(tables.engineering_review_tasks.insert(), links)
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=id,
            record_type="engineering_review_package",
            action="prepared",
            before=None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))


def task_context(
    c: Connection, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> list[dict[str, Any]]:
    p, links_table = tables.engineering_review_packages, tables.engineering_review_tasks
    packages = (
        c.execute(
            select(p)
            .join(
                links_table,
                (links_table.c.tenant_id == p.c.tenant_id) & (links_table.c.package_id == p.c.id),
            )
            .where(
                links_table.c.tenant_id == tenant_id,
                links_table.c.project_id == project_id,
                links_table.c.task_id == task_id,
            )
            .distinct()
            .order_by(p.c.revision_number.desc(), p.c.id)
        )
        .mappings()
        .all()
    )
    seen = set()
    contexts = []
    for package in packages:
        if package["root_id"] in seen:
            continue
        seen.add(package["root_id"])
        latest_id = c.execute(
            select(p.c.id)
            .where(
                p.c.tenant_id == tenant_id,
                p.c.project_id == project_id,
                p.c.root_id == package["root_id"],
            )
            .order_by(p.c.revision_number.desc())
            .limit(1)
        ).scalar_one()
        snapshot = package["snapshot"]
        lines = [line for line in snapshot["lines"] if line["task_id"] == str(task_id)]
        contexts.append(
            _plain(
                {
                    "package_id": package["id"],
                    "latest_id": latest_id,
                    "revision_number": package["revision_number"],
                    "title": snapshot["title"],
                    "scope": snapshot["scope"],
                    "unknown_impacts": snapshot["unknown_impacts"],
                    "lines": lines,
                }
            )
        )
    return contexts
