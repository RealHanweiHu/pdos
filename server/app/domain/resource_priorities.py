"""Immutable resource priority policy and deterministic pending-reservation order."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_capacity import _event

PREFIX = "resource.priority.v1:"


class ProjectRank(Contract):
    project_id: UUID
    rank: int = Field(ge=1, le=1000)
    basis: Text


class PriorityDraft(Contract):
    request_id: UUID
    resource_id: UUID
    expected_version: int = Field(ge=0)
    status: Literal["active", "suspended"]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    default_rank: int = Field(ge=1, le=1000)
    ranks: list[ProjectRank] = Field(default_factory=list, max_length=200)
    reason: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("政策有效期须为正")
        if len({v.project_id for v in self.ranks}) != len(self.ranks):
            raise ValueError("同一项目不可重复设置优先级")
        return self


def latest(c: Connection, tenant: UUID, resource: UUID) -> Any:
    p = tables.resource_priority_versions
    return (
        c.execute(
            select(p)
            .where(p.c.tenant_id == tenant, p.c.resource_id == resource)
            .order_by(p.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def rank(policy: Any, project: UUID) -> int:
    return next(
        (int(v["rank"]) for v in policy["body"]["ranks"] if v["project_id"] == str(project)),
        int(policy["body"]["default_rank"]),
    )


def active(c: Connection, tenant: UUID, resource: UUID) -> Any:
    policy = latest(c, tenant, resource)
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    if (
        policy is None
        or policy["status"] != "active"
        or not policy["valid_from"] <= now < policy["valid_until"]
    ):
        raise ProductWorkError("此资源缺少当前有效优先级政策，请由资源管理员发布后再提出或确认预约")
    return policy


def bind(c: Connection, context: AuthContext, reservation: Any, policy: Any) -> None:
    c.execute(
        tables.resource_priority_bindings.insert().values(
            tenant_id=context.tenant.id,
            project_id=reservation["project_id"],
            reservation_id=reservation["id"],
            policy_id=policy["id"],
            rank=rank(policy, reservation["project_id"]),
            created_at=func.clock_timestamp(),
        )
    )


def confirm(c: Connection, context: AuthContext, reservation: Any) -> dict[str, Any]:
    policy = active(c, context.tenant.id, reservation["resource_id"])
    if reservation["contract"]["priority_policy_version"] != PREFIX + str(policy["id"]):
        raise ProductWorkError("预约采用的优先级政策已有变化，请取消旧提案并按当前政策重新提出")
    # The database uses the same interval sweep under the resource lock at confirmation.
    conflict = c.execute(
        select(func.cehub_project.resource_priority_conflict(context.tenant.id, reservation["id"]))
    ).scalar_one()
    if conflict:
        raise ProductWorkError("同窗口有排序更前的待确认预约；请先办理或调整其窗口，再确认本预约")
    return {
        "policy_id": str(policy["id"]),
        "version": policy["version"],
        "rank": rank(policy, reservation["project_id"]),
        "ordering": "项目级别数值升序，同级按提案时间与编号；已有正式预约不自动让路",
    }


class ResourcePriorityService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        resource_id: UUID,
        before: int | None = None,
        search: str | None = None,
        queue_before: UUID | None = None,
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.connect() as c:
            p = tables.resource_priority_versions
            current = latest(c, context.tenant.id, resource_id)
            query = select(p).where(
                p.c.tenant_id == context.tenant.id, p.c.resource_id == resource_id
            )
            if before is not None:
                query = query.where(p.c.version < before)
            history = list(c.execute(query.order_by(p.c.version.desc()).limit(21)).mappings())
            projects = tables.projects
            q = select(projects.c.id, projects.c.name, projects.c.status).where(
                projects.c.tenant_id == context.tenant.id,
            )
            if search:
                q = q.where(projects.c.name.icontains(search, autoescape=True))
            candidates = list(
                c.execute(q.order_by(projects.c.name, projects.c.id).limit(201)).mappings()
            )
            bookings, bindings = tables.resource_reservations, tables.resource_priority_bindings
            queue_query = (
                select(
                    bookings.c.id,
                    bookings.c.project_id,
                    projects.c.name.label("project_name"),
                    bookings.c.state,
                    bookings.c.created_at,
                    bookings.c.window_start,
                    bookings.c.window_end,
                    bookings.c.parallel_units,
                    bindings.c.rank,
                    bindings.c.policy_id,
                )
                .join(
                    projects,
                    (projects.c.tenant_id == bookings.c.tenant_id)
                    & (projects.c.id == bookings.c.project_id),
                )
                .outerjoin(
                    bindings,
                    (bindings.c.tenant_id == bookings.c.tenant_id)
                    & (bindings.c.reservation_id == bookings.c.id),
                )
                .where(
                    bookings.c.tenant_id == context.tenant.id,
                    bookings.c.resource_id == resource_id,
                    bookings.c.state.in_(("proposed", "reserved")),
                )
            )
            if queue_before is not None:
                position = (
                    c.execute(
                        select(bookings).where(
                            bookings.c.tenant_id == context.tenant.id,
                            bookings.c.resource_id == resource_id,
                            bookings.c.id == queue_before,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if position is None:
                    raise ProductWorkError("预约翻页位置不属于此资源")
                queue_query = queue_query.where(
                    (bookings.c.created_at < position["created_at"])
                    | (
                        (bookings.c.created_at == position["created_at"])
                        & (bookings.c.id < queue_before)
                    )
                )
            queue = list(
                c.execute(
                    queue_query.order_by(bookings.c.created_at.desc(), bookings.c.id.desc()).limit(
                        51
                    )
                ).mappings()
            )
            return {
                "queue": [_plain(dict(v)) for v in queue[:50]],
                "queue_cursor": str(queue[49]["id"]) if len(queue) > 50 else None,
                "current": _plain(dict(current)) if current else None,
                "history": [_plain(dict(v)) for v in history[:20]],
                "next_version": history[19]["version"] if len(history) > 20 else None,
                "projects": [_plain(dict(v)) for v in candidates[:200]],
                "projects_more": len(candidates) > 200,
            }

    def save(self, context: AuthContext, command: PriorityDraft) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as c:
            c.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
            resource = (
                c.execute(
                    select(tables.planning_resources)
                    .where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id == command.resource_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if resource is None:
                raise ProductWorkError("资源不存在")
            p = tables.resource_priority_versions
            signature = digest(command.model_dump(mode="json"))
            prior = (
                c.execute(
                    select(p).where(
                        p.c.tenant_id == context.tenant.id,
                        p.c.created_by_user_id == context.user.id,
                        p.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("此请求已保存其他政策内容")
                return _plain(dict(prior))
            current = latest(c, context.tenant.id, command.resource_id)
            version = current["version"] if current else 0
            if command.expected_version != version:
                raise ProductWorkError("优先级政策已有新版，请重新读取后核对")
            if (
                command.status == "active"
                and not command.valid_from <= datetime.now(UTC) < command.valid_until
            ):
                raise ProductWorkError("发布的有效政策须覆盖当前时间；未来生效请届时发布")
            ids = {v.project_id for v in command.ranks}
            found = set(
                c.execute(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == context.tenant.id,
                        tables.projects.c.id.in_(ids),
                    )
                ).scalars()
            )
            if found != ids:
                raise ProductWorkError("所选项目须为当前租户实际项目")
            saved = (
                c.execute(
                    p.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        resource_id=command.resource_id,
                        version=version + 1,
                        status=command.status,
                        valid_from=command.valid_from,
                        valid_until=command.valid_until,
                        body=command.model_dump(mode="json"),
                        request_id=command.request_id,
                        request_digest=signature,
                        created_by_user_id=context.user.id,
                        created_at=func.clock_timestamp(),
                    )
                    .returning(p)
                )
                .mappings()
                .one()
            )
            _event(
                c, context, "RESOURCE_PRIORITY_PUBLISHED", dict(saved), "resource_priority.publish"
            )
            return _plain(dict(saved))
