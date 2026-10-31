from uuid import UUID, uuid4

from pydantic import Field, field_validator
from sqlalchemy import select, text

from pdos_next.database import category_transaction, require_context, tenant_session
from pdos_next.domain.preproject.access import human
from pdos_next.errors import DomainError
from pdos_next.models import Project
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context, digest

from .models import ProjectSet, ProjectSetLink


class SaveSet(StrictModel):
    set_id: UUID | None = None
    expected_revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    request_key: UUID

    @field_validator("name")
    @classmethod
    def name_required(cls, value):
        if not value.strip():
            raise ValueError("请输入项目集名称")
        return value.strip()


class Link(StrictModel):
    project_id: UUID
    expected_revision: int = Field(ge=0)


class MoveProjects(StrictModel):
    set_id: UUID | None
    projects: list[Link] = Field(min_length=1, max_length=100)
    request_key: UUID


def check(s, ctx):
    require_context(s, ctx)
    human(s, ctx)
    if ctx.category_id is not None:
        raise DomainError("FORBIDDEN_SCOPE", "项目集属于组织工作区。", 403)


def lock(s, ctx):
    check(s, ctx)
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"project-sets:{ctx.tenant_id}"},
    )


def set_view(row):
    return {
        "id": str(row.set_id),
        "revision": row.revision,
        "name": row.name,
        "description": row.description,
    }


def link_view(row):
    return {
        "project_id": str(row.project_id),
        "set_id": str(row.set_id) if row.set_id else None,
        "revision": row.revision,
    }


def listing(s, ctx):
    check(s, ctx)
    sets = s.scalars(
        select(ProjectSet)
        .where(ProjectSet.tenant_id == ctx.tenant_id)
        .distinct(ProjectSet.set_id)
        .order_by(ProjectSet.set_id, ProjectSet.revision.desc())
    )
    links = s.scalars(
        select(ProjectSetLink)
        .where(ProjectSetLink.tenant_id == ctx.tenant_id)
        .distinct(ProjectSetLink.project_id)
        .order_by(ProjectSetLink.project_id, ProjectSetLink.revision.desc())
    )
    return {"items": [set_view(row) for row in sets], "links": [link_view(row) for row in links]}


def save(s, ctx, data):
    lock(s, ctx)
    fingerprint = digest(data.model_dump(mode="json"))
    prior = s.scalar(
        select(ProjectSet).where(
            ProjectSet.tenant_id == ctx.tenant_id,
            ProjectSet.author_id == ctx.actor_id,
            ProjectSet.request_key == data.request_key,
        )
    )
    if prior:
        if prior.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求已绑定其他内容。")
        return set_view(prior)
    current = (
        s.scalar(
            select(ProjectSet)
            .where(ProjectSet.tenant_id == ctx.tenant_id, ProjectSet.set_id == data.set_id)
            .order_by(ProjectSet.revision.desc())
            .limit(1)
        )
        if data.set_id
        else None
    )
    if data.set_id and current is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目集不存在或不在当前组织。", 403)
    if data.expected_revision != (current.revision if current else 0):
        raise DomainError("VERSION_CONFLICT", "项目集已由同事修改，请刷新后重试。")
    identity = uuid4()
    row = ProjectSet(
        id=identity,
        tenant_id=ctx.tenant_id,
        set_id=data.set_id or identity,
        revision=data.expected_revision + 1,
        name=data.name,
        description=data.description.strip(),
        author_id=ctx.actor_id,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    return set_view(row)


def move(s, ctx, data):
    lock(s, ctx)
    fingerprint = digest(data.model_dump(mode="json"))
    if len({p.project_id for p in data.projects}) != len(data.projects):
        raise DomainError("VALIDATION_FAILED", "项目不能重复选择。", 422)
    if data.set_id and not s.scalar(
        select(ProjectSet.id).where(
            ProjectSet.tenant_id == ctx.tenant_id,
            ProjectSet.id == data.set_id,
            ProjectSet.revision == 1,
        )
    ):
        raise DomainError("FORBIDDEN_SCOPE", "目标项目集不可用。", 403)
    # Recheck current project visibility even on retry, before returning any stored link.
    for item in data.projects:
        if not s.scalar(
            select(Project.id).where(
                Project.tenant_id == ctx.tenant_id, Project.id == item.project_id
            )
        ):
            raise DomainError("FORBIDDEN_SCOPE", "所选项目权限已变化，请刷新。", 403)
    previous = list(
        s.scalars(
            select(ProjectSetLink).where(
                ProjectSetLink.tenant_id == ctx.tenant_id,
                ProjectSetLink.author_id == ctx.actor_id,
                ProjectSetLink.request_key == data.request_key,
            )
        )
    )
    if previous:
        if any(row.request_sha256 != fingerprint for row in previous) or len(previous) != len(
            data.projects
        ):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原移动请求已绑定其他内容。")
        return {"items": [link_view(row) for row in previous]}
    result = []
    for item in data.projects:
        latest = s.scalar(
            select(ProjectSetLink)
            .where(
                ProjectSetLink.tenant_id == ctx.tenant_id,
                ProjectSetLink.project_id == item.project_id,
            )
            .order_by(ProjectSetLink.revision.desc())
            .limit(1)
        )
        if item.expected_revision != (latest.revision if latest else 0):
            raise DomainError("VERSION_CONFLICT", "所选项目的归属已被修改，请刷新后重试。")
        row = ProjectSetLink(
            tenant_id=ctx.tenant_id,
            project_id=item.project_id,
            set_id=data.set_id,
            revision=item.expected_revision + 1,
            author_id=ctx.actor_id,
            request_key=data.request_key,
            request_sha256=fingerprint,
        )
        s.add(row)
        result.append(row)
    s.flush()
    return {"items": [link_view(row) for row in result]}


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/project-sets")
    def get(ctx: Context = auth_dependency):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        ) as s:
            return listing(s, ctx)

    @app.post("/v1/project-sets")
    def put(data: SaveSet, ctx: Context = auth_dependency):
        return category_transaction(engine, ctx, lambda s: save(s, ctx, data))

    @app.post("/v1/project-sets/move")
    def post(data: MoveProjects, ctx: Context = auth_dependency):
        return category_transaction(engine, ctx, lambda s: move(s, ctx, data))
