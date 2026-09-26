"""Versioned calendars and stored, read-only initial-plan scheduling scenarios."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import PlanCandidate, Quantity, Text, WorkCalendar
from app.db.schema import tables
from app.domain.initial_plan_candidates import _record, _source, _source_selector
from app.domain.plan_scheduling import NodeAllocation, schedule_plan
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.working_time import CalendarDefinition, WorkInterval
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CalendarDraft(Input):
    request_id: UUID
    calendar_id: UUID | None = None
    expected_version: int = Field(ge=0)
    name: Text
    timezone: str
    working_weekdays: tuple[int, ...]
    holidays: tuple[date, ...] = ()
    intervals: tuple[WorkInterval, ...] = Field(min_length=1, max_length=12)
    ambiguous_time: Literal["reject", "earlier", "later"] = "reject"
    reason: Text


class AllocationDraft(Input):
    calendar_version_id: UUID
    parallel_units: Quantity = Field(gt=0, le=1000)
    allocation_basis: Text
    not_before: AwareDatetime | None = None


class ScenarioDraft(Input):
    request_id: UUID
    start: AwareDatetime
    default_allocation: AllocationDraft
    node_allocations: dict[str, AllocationDraft] = Field(default_factory=dict)


def _calendar_access(context: AuthContext) -> None:
    if context.user.role not in {
        Role.OWNER,
        Role.ADMIN,
        Role.PROJECT_MANAGER,
        Role.ENGINEER,
        Role.QUALITY,
    }:
        raise ProductWorkAccessError("仅内部成员可读取工作日历")


def _candidate(connection: Any, context: AuthContext, candidate_id: UUID) -> Any:
    row = (
        connection.execute(
            select(tables.initial_plan_candidates).where(
                tables.initial_plan_candidates.c.tenant_id == context.tenant.id,
                tables.initial_plan_candidates.c.id == candidate_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("计划候选不存在或不可访问")
    _source(connection, context, row["market_space_id"], _source_selector(row))
    return row


class PlanScenarioService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def calendars(self, context: AuthContext) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.connect() as connection:
            table = tables.work_calendar_versions
            ranked = (
                select(
                    table,
                    func.row_number()
                    .over(partition_by=table.c.calendar_id, order_by=table.c.version.desc())
                    .label("position"),
                )
                .where(table.c.tenant_id == context.tenant.id)
                .subquery()
            )
            rows = connection.execute(
                select(ranked).where(ranked.c.position == 1).order_by(ranked.c.name)
            ).mappings()
            return {
                "items": [_plain(row) for row in rows],
                "can_manage": is_allowed(context.user.role, Action.TENANT_MANAGE),
            }

    def publish_calendar(self, context: AuthContext, draft: CalendarDraft) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == context.tenant.id)
                .with_for_update()
            ).scalar_one()
            table = tables.work_calendar_versions
            fingerprint = digest(draft.model_dump(mode="json"))
            previous = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous:
                if previous["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号对应的日历内容已改变")
                return _plain(previous)
            latest = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.calendar_id == draft.calendar_id,
                    )
                    .order_by(table.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
                if draft.calendar_id
                else None
            )
            if (draft.calendar_id is not None and latest is None) or draft.expected_version != (
                latest["version"] if latest else 0
            ):
                raise ProductWorkError("日历版本已变化或不存在，请刷新")
            calendar = WorkCalendar(
                id=draft.calendar_id or uuid4(),
                tenant_id=context.tenant.id,
                version=draft.expected_version + 1,
                timezone=draft.timezone,
                working_weekdays=draft.working_weekdays,
                holidays=draft.holidays,
                hours_per_workday=Decimal(
                    sum(item.end_minute - item.start_minute for item in draft.intervals)
                )
                / 60,
            )
            definition = CalendarDefinition(
                calendar=calendar, intervals=draft.intervals, ambiguous_time=draft.ambiguous_time
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        calendar_id=calendar.id,
                        version=calendar.version,
                        name=draft.name,
                        definition=definition.model_dump(mode="json"),
                        definition_digest=digest(definition.model_dump(mode="json")),
                        reason=draft.reason,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"work-calendar:{row['id']}",
                    event_type="WORK_CALENDAR_PUBLISHED",
                    source="planning_service",
                    entity_id=row["id"],
                    payload={"calendar_id": str(calendar.id), "version": calendar.version},
                ),
                AuditDraft(action="work_calendar.published", after_snapshot=_plain(row)),
            )
            return _plain(row)

    def list(self, context: AuthContext, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _candidate(connection, context, candidate_id)
            table = tables.initial_plan_scenarios
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(51)
                ).mappings()
            )
            return {"items": [_plain(row) for row in rows[:50]], "has_more": len(rows) > 50}

    def calculate(
        self, context: AuthContext, candidate_id: UUID, draft: ScenarioDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = _candidate(connection, context, candidate_id)
            connection.execute(
                select(tables.initial_plan_candidates.c.id)
                .where(
                    tables.initial_plan_candidates.c.tenant_id == context.tenant.id,
                    tables.initial_plan_candidates.c.id == candidate_id,
                )
                .with_for_update()
            ).scalar_one()
            table = tables.initial_plan_scenarios
            fingerprint = digest(draft.model_dump(mode="json"))
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.candidate_id == candidate_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号对应的情景输入已变化")
                return _plain(prior)
            record = _record(connection, context, candidate)
            if not record["source_is_current"] or not record["template_is_current"]:
                raise ProductWorkError("计划来源或模板已变化，请先修订候选")
            plan = PlanCandidate.model_validate(candidate["plan"])
            if set(draft.node_allocations) - {node.node_key for node in plan.nodes}:
                raise ProductWorkError("节点配置包含计划外的编号")
            assignments = {
                node.node_key: draft.node_allocations.get(node.node_key, draft.default_allocation)
                for node in plan.nodes
            }
            calendar_ids = {item.calendar_version_id for item in assignments.values()}
            rows = {
                row["id"]: row
                for row in connection.execute(
                    select(tables.work_calendar_versions).where(
                        tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                        tables.work_calendar_versions.c.id.in_(calendar_ids),
                    )
                ).mappings()
            }
            if set(rows) != calendar_ids:
                raise ProductWorkError("所选日历版本不存在或不可访问")
            calendars = {
                str(key): CalendarDefinition.model_validate(row["definition"])
                for key, row in rows.items()
            }
            allocations = {
                key: NodeAllocation(
                    calendar_key=str(value.calendar_version_id),
                    parallel_units=value.parallel_units,
                    allocation_basis=value.allocation_basis,
                    not_before=value.not_before,
                )
                for key, value in assignments.items()
            }
            result = _plain(schedule_plan(plan, draft.start, calendars, allocations))
            result["current_missing"] = record["missing"]
            result["calendar_names"] = {
                str(key): {"name": row["name"], "version": row["version"]}
                for key, row in rows.items()
            }
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        candidate_id=candidate_id,
                        inputs=draft.model_dump(mode="json"),
                        result=result,
                        candidate_digest=digest(candidate["plan"]),
                        result_digest=digest(result),
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for calendar_id in calendar_ids:
                connection.execute(
                    tables.initial_plan_scenario_calendars.insert().values(
                        tenant_id=context.tenant.id,
                        scenario_id=row["id"],
                        calendar_version_id=calendar_id,
                    )
                )
            EventAuditWriter(
                connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"plan-scenario:{row['id']}",
                    event_type="PLAN_SCENARIO_CALCULATED",
                    source="planning_service",
                    entity_id=row["id"],
                    payload={
                        "candidate_id": str(candidate_id),
                        "algorithm_version": result["algorithm_version"],
                        "result_digest": row["result_digest"],
                    },
                ),
                AuditDraft(action="plan_scenario.calculated", after_snapshot=_plain(row)),
            )
            return _plain(row)
