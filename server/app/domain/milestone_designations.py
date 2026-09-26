"""Named business importance of actual milestones, with append-only revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class MilestoneDesignation(Contract):
    project_id: UUID
    node_id: UUID
    request_id: UUID
    expected_baseline_id: UUID
    expected_version: int = Field(ge=0)
    is_key: bool
    reason: Text


class DesignationHistory(Contract):
    project_id: UUID
    node_id: UUID
    before_version: int | None = Field(default=None, ge=1)


def records(
    c: Connection, tenant: UUID, project: UUID, *, latest_only: bool = True
) -> dict[UUID, list[Any]]:
    t = tables.schedule_milestone_designations
    names = tables.users
    query = (
        select(
            t,
            names.c.display_name.label("actor_name"),
            func.row_number()
            .over(partition_by=t.c.node_id, order_by=t.c.version.desc())
            .label("position"),
        )
        .join(names, (names.c.tenant_id == t.c.tenant_id) & (names.c.id == t.c.actor_user_id))
        .where(t.c.tenant_id == tenant, t.c.project_id == project)
        .order_by(t.c.node_id, t.c.version.desc())
    )
    if latest_only:
        q = query.subquery()
        query = select(q).where(q.c.position == 1)
    result: dict[UUID, list[Any]] = {}
    for row in c.execute(query).mappings():
        result.setdefault(row["node_id"], []).append(row)
    return result


def at(history: list[Any], moment: datetime) -> Any | None:
    return next((row for row in history if row["created_at"] <= moment), None)


def node_snapshot(node: Any) -> dict[str, Any]:
    return {
        k: node.get(k)
        for k in ("node_key", "title", "completion_criteria", "owner_user_id", "receiver_user_id")
    }


class MilestoneDesignationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def save(self, context: AuthContext, command: MilestoneDesignation) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as c:
                _project(c, context, command.project_id, write=True)
                _person(c, context, command.project_id, context.user.id)
                t = tables.schedule_milestone_designations
                fingerprint = digest(command.model_dump(mode="json"))
                prior = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.actor_user_id == context.user.id,
                            t.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["request_digest"] != fingerprint:
                        raise ProductWorkError("请求编号已用于另一项里程碑标记")
                    return _plain(prior)
                formal = current_plan(c, context.tenant.id, command.project_id)
                node = (
                    next(
                        (
                            v
                            for v in formal["nodes"]
                            if v["id"] == command.node_id and v["node_kind"] == "milestone"
                        ),
                        None,
                    )
                    if formal
                    else None
                )
                if not formal or not node or formal["baseline_id"] != command.expected_baseline_id:
                    raise ProductWorkError("里程碑或正式基线已变化，请重新读取")
                plan_node = next(
                    v for v in formal["plan"]["nodes"] if v["node_key"] == node["node_key"]
                )
                previous = (
                    c.execute(
                        select(t)
                        .where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.node_id == command.node_id,
                        )
                        .order_by(t.c.version.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                version = previous["version"] if previous else 0
                if version != command.expected_version:
                    raise ProductWorkError("业务重要性已被修订，请核对最新版本")
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=command.project_id,
                            node_id=command.node_id,
                            baseline_id=command.expected_baseline_id,
                            version=version + 1,
                            is_key=command.is_key,
                            reason=command.reason,
                            snapshot=node_snapshot(plan_node),
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=fingerprint,
                            created_at=now,
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                return _plain(row)
        except IntegrityError as error:
            raise ProductWorkError("里程碑标记未保存，请刷新原节点和历史后重试") from error

    def history(self, context: AuthContext, command: DesignationHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            _project(c, context, command.project_id)
            t, u = tables.schedule_milestone_designations, tables.users
            query = (
                select(t, u.c.display_name.label("actor_name"))
                .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.actor_user_id))
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == command.project_id,
                    t.c.node_id == command.node_id,
                )
            )
            if command.before_version:
                query = query.where(t.c.version < command.before_version)
            values = list(c.execute(query.order_by(t.c.version.desc()).limit(31)).mappings())
            return {
                "items": [_plain(v) for v in values[:30]],
                "next_before_version": values[29]["version"] if len(values) > 30 else None,
                "can_manage": is_allowed(context.user.role, Action.PROJECT_EDIT),
            }
