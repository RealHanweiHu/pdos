"""Shared resource identities, immutable availability and candidate capacity checks."""

from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, case, func, literal_column, select, text
from sqlalchemy.engine import RowMapping

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    Contract,
    Quantity,
    ResourceCapacity,
    SourceRef,
    Text,
    TimeWindow,
)
from app.db.schema import tables
from app.domain.plan_scenarios import _calendar_access, _candidate
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.working_time import CalendarDefinition, WorkingTime
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

ResourceKind = Literal[
    "person", "skill_group", "laboratory", "bench", "equipment", "mold", "fixture", "pilot_line"
]


class ResourceDraft(Contract):
    request_id: UUID
    name: str = Field(min_length=1, max_length=256, pattern=r"\S")
    kind: ResourceKind
    user_id: UUID | None = None

    @model_validator(mode="after")
    def person_identity(self) -> Self:
        if (self.kind == "person") != (self.user_id is not None):
            raise ValueError("人员资源须绑定实际用户，其余资源不绑定个人身份")
        return self


class CapacityDraft(Contract):
    request_id: UUID
    resource_id: UUID
    expected_version: int = Field(ge=0)
    calendar_version_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime
    parallel_units: Quantity = Field(ge=0, le=1000)
    basis: Text

    @model_validator(mode="after")
    def window(self) -> Self:
        start, end = self.window_start.astimezone(UTC), self.window_end.astimezone(UTC)
        if not timedelta(0) < end - start <= timedelta(days=3660):
            raise ValueError("容量覆盖窗口须为正且不超过十年")
        if any(value.second or value.microsecond for value in (start, end)):
            raise ValueError("容量窗口按整分钟填写")
        return self


class Demand(Contract):
    capacity_version_id: UUID
    units: Quantity = Field(gt=0, le=1000)
    contributes_effort: bool
    occupancy_policy: Literal["working_only", "through_waiting"]
    basis: Text


class CapacityCheckDraft(Contract):
    request_id: UUID
    demands: dict[str, tuple[Demand, ...]] = Field(max_length=1000)
    no_resource_reasons: dict[str, Text] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if sum(len(value) for value in self.demands.values()) > 2000:
            raise ValueError("一次检查最多2000条资源需求")
        for values in self.demands.values():
            if len({value.capacity_version_id for value in values}) != len(values):
                raise ValueError("同一节点不能重复选择同一容量版本")
        return self


def _event(
    connection: Connection, context: AuthContext, event_type: str, row: Any, action: str
) -> None:
    EventAuditWriter(connection, tenant_id=context.tenant.id, actor_user_id=context.user.id).record(
        EventDraft(
            event_id=f"{action}:{row['id']}",
            event_type=event_type,
            source="planning_service",
            entity_id=row["id"],
            payload={"record_id": str(row["id"])},
        ),
        AuditDraft(action=action, after_snapshot=_plain(row)),
    )


def _intervals(
    engine: WorkingTime, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    if end <= start:
        return []
    first, last = start.astimezone(engine.zone).date(), end.astimezone(engine.zone).date()
    if (last - first).days > 3660:
        raise ProductWorkError("容量检查窗口超过十年，请拆分情景")
    result = []
    for offset in range((last - first).days + 1):
        for left, right in engine.intervals(first + timedelta(days=offset)):
            a, b = max(left, start), min(right, end)
            if a < b:
                result.append((a, b))
    return result


def _compute(
    scenario: Any,
    demands: dict[str, tuple[Demand, ...]],
    profiles: dict[UUID, Any],
    no_resource_reasons: dict[str, str],
    reserved_intervals: list[dict[str, Any]],
    legacy_missing: set[UUID],
    match_existing_reservations: bool = False,
) -> dict[str, Any]:
    nodes = {item["node_key"]: item for item in scenario["result"]["nodes"]}
    if (set(demands) | set(no_resource_reasons)) - set(nodes):
        raise ProductWorkError("资源需求包含情景之外的节点")
    unknown, warnings = [], []
    for profile in profiles.values():
        if profile["resource_id"] in legacy_missing:
            unknown.append(
                {
                    "node_key": "资源盘点",
                    "reason": f"{profile['resource_name']}存在尚未归并的旧资源占用",
                }
            )
    groups: dict[UUID, dict[str, Any]] = {}
    events_count = 0
    for key, node in nodes.items():
        allocations = demands.get(key, ())
        if key in no_resource_reasons:
            if allocations or node["work_minutes"] != 0:
                raise ProductWorkError("仅零工时节点可明确声明无需资源，不能同时填写资源占用")
            continue
        if not allocations:
            unknown.append(
                {"node_key": key, "reason": "尚未明确资源需求；零工时里程碑也须说明所需资源"}
            )
            continue
        if sum(
            (item.units for item in allocations if item.contributes_effort), Decimal(0)
        ) != Decimal(node["allocation"]["parallel_units"]):
            unknown.append(
                {
                    "node_key": key,
                    "reason": "提供工时的资源投入总量与排程假设不同，请重新排程或调整资源需求",
                }
            )
        if node["start"] is None or node["work_minutes"] is None:
            unknown.append({"node_key": key, "reason": "工作时间未知，无法计算资源占用"})
            continue
        calendar = CalendarDefinition.model_validate(
            scenario["result"]["calendars"][node["allocation"]["calendar_key"]]["definition"]
        )
        engine = WorkingTime(calendar)
        saved_rules = scenario["result"]["calendars"][node["allocation"]["calendar_key"]]
        if any(
            saved_rules.get(name) != value
            for name, value in _plain(asdict(engine.evidence)).items()
        ):
            raise ProductWorkError("本机时区规则与排程记录不同，请重新计算情景")
        start = datetime.fromisoformat(node["start"]).astimezone(UTC)
        end = engine.advance(start, node["work_minutes"])
        spans = _intervals(engine, start, end)
        for demand in allocations:
            profile = profiles[demand.capacity_version_id]
            resource_id = profile["resource_id"]
            if resource_id in groups and groups[resource_id]["profile"]["id"] != profile["id"]:
                raise ProductWorkError("同一资源在一次检查中须使用同一容量版本")
            group = groups.setdefault(
                resource_id, {"profile": profile, "demands": [], "node_keys": set()}
            )
            group["node_keys"].add(key)
            if not profile["is_current"]:
                warnings.append(
                    {"node_key": key, "reason": f"{profile['resource_name']}容量已有新版本"}
                )
            if not profile["person_active"]:
                unknown.append(
                    {"node_key": key, "reason": f"{profile['resource_name']}关联人员已失效"}
                )
            occupied = spans
            if demand.occupancy_policy == "through_waiting":
                if node["finish"] is None:
                    unknown.append({"node_key": key, "reason": "持续占用的结束时间未知"})
                    continue
                finish = datetime.fromisoformat(node["finish"]).astimezone(UTC)
                occupied = [(start, finish)] if finish > start else []
            for left, right in occupied:
                group["demands"].append((left, right, key, demand.units))
                events_count += 2
                if events_count > 100000:
                    raise ProductWorkError("容量区间过多，请缩小检查情景")
    resources: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    relevant_bookings: list[dict[str, Any]] = []
    for resource_id, group in groups.items():
        profile = group["profile"]
        spans = group["demands"]
        if not spans:
            resources.append(
                {
                    "resource_id": str(resource_id),
                    "name": profile["resource_name"],
                    "node_keys": sorted(group["node_keys"]),
                    "peak_units": "0",
                    "workload_hours": "0",
                }
            )
            continue
        start, end = min(item[0] for item in spans), max(item[1] for item in spans)
        capacity_start, capacity_end = (
            profile["window_start"].astimezone(UTC),
            profile["window_end"].astimezone(UTC),
        )
        engine = WorkingTime(CalendarDefinition.model_validate(profile["calendar_definition"]))
        if _plain(asdict(engine.evidence)) != profile["calendar_evidence"]:
            raise ProductWorkError("容量发布时的时区规则已变化，请发布新的容量版本")
        available = _intervals(engine, max(start, capacity_start), min(end, capacity_end))
        points: dict[datetime, list[tuple[str | None, Decimal]]] = {}
        for left, right, key, units in spans:
            points.setdefault(left, []).append((key, units))
            points.setdefault(right, []).append((key, -units))
        for booking in reserved_intervals:
            if str(resource_id) != booking["resource_id"]:
                continue
            left = max(start, datetime.fromisoformat(booking["start"]))
            right = min(end, datetime.fromisoformat(booking["end"]))
            if left < right:
                relevant_bookings.append(
                    {**booking, "start": left.isoformat(), "end": right.isoformat()}
                )
                reservation_key = (
                    "\0" + booking["covered_node_key"] if booking.get("covered_node_key") else None
                )
                points.setdefault(left, []).append((reservation_key, Decimal(booking["units"])))
                points.setdefault(right, []).append((reservation_key, -Decimal(booking["units"])))
        for left, right in available:
            points.setdefault(left, []).append(("", profile["parallel_units"]))
            points.setdefault(right, []).append(("", -profile["parallel_units"]))
        points.setdefault(capacity_start, [])
        points.setdefault(capacity_end, [])
        active: dict[str | None, Decimal] = {}
        capacity = Decimal(0)
        peak = Decimal(0)
        workload = Decimal(0)
        ordered = sorted(points)
        for index, left in enumerate(ordered[:-1]):
            for key, delta in points[left]:
                if key != "":
                    active[key] = active.get(key, Decimal(0)) + delta
                else:
                    capacity += delta
            right = ordered[index + 1]
            desired = {
                key: value
                for key, value in active.items()
                if key is not None and not key.startswith("\0")
            }
            covered = {
                key[1:]: value
                for key, value in active.items()
                if key is not None and key.startswith("\0")
            }
            amount = active.get(None, Decimal(0)) + sum(
                (
                    max(desired.get(key, Decimal(0)), covered.get(key, Decimal(0)))
                    for key in desired.keys() | covered.keys()
                ),
                Decimal(0),
            )
            own_amount = sum(desired.values(), Decimal(0))
            if own_amount <= 0:
                continue
            peak = max(peak, amount)
            workload += own_amount * Decimal(int((right - left).total_seconds())) / Decimal(3600)
            affected = sorted(key for key, value in desired.items() if value > 0)
            outside = left < capacity_start or right > capacity_end
            if outside:
                unknown.append(
                    {
                        "node_key": ", ".join(affected),
                        "reason": (
                            f"{profile['resource_name']}：{left.isoformat()} 至 "
                            f"{right.isoformat()} 超出已声明容量窗口"
                        ),
                    }
                )
            elif amount > capacity:
                conflict = {
                    "resource_id": str(resource_id),
                    "resource_name": profile["resource_name"],
                    "start": left.isoformat(),
                    "end": right.isoformat(),
                    "demand_units": str(amount),
                    "available_units": str(capacity),
                    "node_keys": affected,
                }
                if (
                    conflicts
                    and all(
                        conflicts[-1][name] == conflict[name]
                        for name in ("resource_id", "demand_units", "available_units", "node_keys")
                    )
                    and conflicts[-1]["end"] == conflict["start"]
                ):
                    conflicts[-1]["end"] = conflict["end"]
                else:
                    conflicts.append(conflict)
                if len(conflicts) + len(unknown) > 10000:
                    raise ProductWorkError("容量冲突/缺项超过10000条，请缩小情景")
        resources.append(
            {
                "resource_id": str(resource_id),
                "name": profile["resource_name"],
                "node_keys": sorted(group["node_keys"]),
                "peak_units": str(peak),
                "workload_hours": str(workload),
            }
        )
    return {
        "algorithm_version": "forecast.capacity_union.v2"
        if match_existing_reservations
        else "plan.capacity_intervals.v1",
        **(
            {
                "demand_intervals": [
                    {
                        "resource_id": str(resource_id),
                        "node_key": key,
                        "start": left.isoformat(),
                        "end": right.isoformat(),
                        "units": str(units),
                    }
                    for resource_id, group in groups.items()
                    for left, right, key, units in group["demands"]
                ]
            }
            if match_existing_reservations
            else {}
        ),
        "scenario_id": str(scenario["id"]),
        "scenario_digest": scenario["result_digest"],
        "status": "conflicts" if conflicts else "unknown" if unknown else "capacity_clear",
        "resources": resources,
        "conflicts": conflicts,
        "unknown": unknown,
        "warnings": warnings,
        "waiting_policy": "explicit_per_demand",
        "reservation_coverage": "legacy_pending" if legacy_missing else "current_ledger",
        "reservation_evidence": relevant_bookings,
        "reservation_evidence_digest": digest({"intervals": relevant_bookings}),
        "ready_for_application": False,
        "profiles": [_plain(profiles[key]) for key in sorted(profiles, key=str)],
    }


class ResourceCapacityService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, context: AuthContext) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.connect() as connection:
            resources = list(
                connection.execute(
                    select(tables.planning_resources)
                    .where(tables.planning_resources.c.tenant_id == context.tenant.id)
                    .order_by(tables.planning_resources.c.name)
                ).mappings()
            )
            capacities = tables.resource_capacity_versions
            ranked = (
                select(
                    capacities,
                    func.row_number()
                    .over(
                        partition_by=capacities.c.resource_id, order_by=capacities.c.version.desc()
                    )
                    .label("position"),
                )
                .where(capacities.c.tenant_id == context.tenant.id)
                .subquery()
            )
            profiles = {
                row["resource_id"]: _plain(row)
                for row in connection.execute(
                    select(ranked).where(ranked.c.position == 1)
                ).mappings()
            }
            can_manage = is_allowed(context.user.role, Action.TENANT_MANAGE)
            people = (
                list(
                    connection.execute(
                        select(tables.users.c.id, tables.users.c.display_name)
                        .where(
                            tables.users.c.tenant_id == context.tenant.id,
                            tables.users.c.is_active.is_(True),
                            tables.users.c.role.in_(
                                ("owner", "admin", "project_manager", "engineer", "quality")
                            ),
                        )
                        .order_by(tables.users.c.display_name)
                    ).mappings()
                )
                if can_manage
                else []
            )
            return {
                "items": [
                    {**_plain(row), "capacity": profiles.get(row["id"])} for row in resources
                ],
                "can_manage": can_manage,
                "people": [_plain(row) for row in people],
            }

    def create(self, context: AuthContext, draft: ResourceDraft) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == context.tenant.id)
                .with_for_update()
            ).scalar_one()
            table = tables.planning_resources
            prior = (
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
            fingerprint = digest(draft.model_dump(mode="json"))
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于不同资源")
                return _plain(prior)
            if draft.user_id:
                user = connection.execute(
                    select(tables.users.c.id).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id == draft.user_id,
                        tables.users.c.is_active.is_(True),
                        tables.users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                    )
                ).first()
                if user is None:
                    raise ProductWorkError("请选择当前有效内部人员")
                if connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id, table.c.user_id == draft.user_id
                    )
                ).first():
                    raise ProductWorkError("该人员已有统一资源身份，请使用已有资源")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        name=draft.name,
                        kind=draft.kind,
                        user_id=draft.user_id,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection, context, "PLANNING_RESOURCE_CREATED", row, "planning_resource.created"
            )
            return _plain(row)

    def publish(self, context: AuthContext, draft: CapacityDraft) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            resource = (
                connection.execute(
                    select(tables.planning_resources)
                    .where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id == draft.resource_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if resource is None:
                raise ProductWorkError("资源不存在")
            active_reservation = connection.execute(
                select(tables.resource_reservations.c.id)
                .where(
                    tables.resource_reservations.c.tenant_id == context.tenant.id,
                    tables.resource_reservations.c.resource_id == draft.resource_id,
                    tables.resource_reservations.c.state == "reserved",
                    tables.resource_reservations.c.window_end > datetime.now(UTC),
                )
                .limit(1)
            ).first()
            table = tables.resource_capacity_versions
            prior = (
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
            fingerprint = digest(draft.model_dump(mode="json"))
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于不同容量")
                return _plain(prior)
            latest = (
                connection.execute(
                    select(func.max(table.c.version)).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.resource_id == draft.resource_id,
                    )
                ).scalar_one()
                or 0
            )
            if active_reservation:
                raise ProductWorkError("请先释放受影响的未来预约，再发布新的容量版本")
            if latest != draft.expected_version:
                raise ProductWorkError("容量已有新版本，请刷新")
            if resource["kind"] == "person" and draft.parallel_units > 1:
                raise ProductWorkError("单个人员的并行容量不能超过1，团队请使用技能组")
            calendar = (
                connection.execute(
                    select(tables.work_calendar_versions).where(
                        tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                        tables.work_calendar_versions.c.id == draft.calendar_version_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if calendar is None:
                raise ProductWorkError("日历版本不存在")
            definition = CalendarDefinition.model_validate(calendar["definition"])
            engine = WorkingTime(definition)
            row_id = uuid4()
            unit: Literal["person_hours", "equipment_hours", "slots"] = (
                "person_hours"
                if resource["kind"] in {"person", "skill_group"}
                else "equipment_hours"
            )
            with localcontext() as calculation_context:
                calculation_context.prec = 48
                hours = (
                    Decimal(engine.working_minutes(draft.window_start, draft.window_end))
                    * draft.parallel_units
                    / Decimal(60)
                ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            contract = ResourceCapacity(
                id=row_id,
                tenant_id=context.tenant.id,
                resource_id=resource["id"],
                calendar_id=definition.calendar.id,
                calendar_version=definition.calendar.version,
                window=TimeWindow(start=draft.window_start, end=draft.window_end),
                capacity=hours,
                unit=unit,
                source=SourceRef(
                    tenant_id=context.tenant.id,
                    kind="resource_capacity_version",
                    ref_id=row_id,
                    version=latest + 1,
                ),
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=row_id,
                        tenant_id=context.tenant.id,
                        resource_id=resource["id"],
                        version=latest + 1,
                        calendar_version_id=calendar["id"],
                        window_start=draft.window_start,
                        window_end=draft.window_end,
                        parallel_units=draft.parallel_units,
                        capacity_contract=contract.model_dump(mode="json"),
                        calendar_evidence=_plain(asdict(engine.evidence)),
                        basis=draft.basis,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for interval_start, interval_end in _intervals(
                engine, draft.window_start.astimezone(UTC), draft.window_end.astimezone(UTC)
            ):
                connection.execute(
                    tables.resource_capacity_intervals.insert().values(
                        tenant_id=context.tenant.id,
                        capacity_version_id=row["id"],
                        start=interval_start,
                        end=interval_end,
                    )
                )
            _event(
                connection,
                context,
                "RESOURCE_CAPACITY_PUBLISHED",
                row,
                "resource_capacity.published",
            )
            return _plain(row)

    def checks(self, context: AuthContext, candidate_id: UUID, scenario_id: UUID) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.connect() as connection:
            _candidate(connection, context, candidate_id)
            self._scenario(connection, context, candidate_id, scenario_id)
            table = tables.plan_capacity_checks
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id, table.c.scenario_id == scenario_id
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(51)
                ).mappings()
            )
            return {"items": [_plain(row) for row in rows[:50]], "has_more": len(rows) > 50}

    @staticmethod
    def _scenario(
        connection: Connection, context: AuthContext, candidate_id: UUID, scenario_id: UUID
    ) -> Any:
        table = tables.initial_plan_scenarios
        row = (
            connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.candidate_id == candidate_id,
                    table.c.id == scenario_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkAccessError("排程情景不存在或不属于当前候选")
        return row

    def check(
        self, context: AuthContext, candidate_id: UUID, scenario_id: UUID, draft: CapacityCheckDraft
    ) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.begin() as connection:
            _candidate(connection, context, candidate_id)
            scenario = self._scenario(connection, context, candidate_id, scenario_id)
            connection.execute(
                select(tables.initial_plan_scenarios.c.id)
                .where(
                    tables.initial_plan_scenarios.c.id == scenario_id,
                    tables.initial_plan_scenarios.c.tenant_id == context.tenant.id,
                )
                .with_for_update()
            ).scalar_one()
            table = tables.plan_capacity_checks
            fingerprint = digest(draft.model_dump(mode="json"))
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.scenario_id == scenario_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于不同容量检查")
                return _plain(prior)
            result = evaluate_capacity(connection, context, scenario, draft)
            capacity_ids = {
                item.capacity_version_id for values in draft.demands.values() for item in values
            }
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        scenario_id=scenario_id,
                        inputs=draft.model_dump(mode="json"),
                        result=result,
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
            for capacity_id in sorted(capacity_ids, key=str):
                connection.execute(
                    tables.plan_capacity_check_versions.insert().values(
                        tenant_id=context.tenant.id,
                        check_id=row["id"],
                        capacity_version_id=capacity_id,
                    )
                )
            _event(connection, context, "PLAN_CAPACITY_CHECKED", row, "plan_capacity.checked")
            return _plain(row)


def evaluate_capacity(
    connection: Connection,
    context: AuthContext,
    scenario: Any,
    draft: CapacityCheckDraft,
    *,
    covered_project_id: UUID | None = None,
    covered_node_keys: dict[UUID, str] | None = None,
) -> dict[str, Any]:
    profiles, reserved_intervals, legacy_missing = capacity_sources(
        connection,
        context,
        draft,
        covered_project_id=covered_project_id,
        covered_node_keys=covered_node_keys,
    )
    with localcontext() as calculation_context:
        calculation_context.prec = 48
        result = _compute(
            scenario,
            draft.demands,
            profiles,
            draft.no_resource_reasons,
            reserved_intervals,
            legacy_missing,
            match_existing_reservations=covered_project_id is not None,
        )
    return result


def capacity_sources(
    connection: Connection,
    context: AuthContext,
    draft: CapacityCheckDraft,
    *,
    covered_project_id: UUID | None = None,
    covered_node_keys: dict[UUID, str] | None = None,
) -> tuple[dict[UUID, Any], list[dict[str, Any]], set[UUID]]:
    profiles = {}
    capacity_ids = {
        value.capacity_version_id for values in draft.demands.values() for value in values
    }
    cap = tables.resource_capacity_versions
    resource = tables.planning_resources
    cal = tables.work_calendar_versions
    resource_ids = set(
        connection.execute(
            select(cap.c.resource_id).where(
                cap.c.tenant_id == context.tenant.id, cap.c.id.in_(capacity_ids)
            )
        ).scalars()
    )
    connection.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
    resource_rows = list(
        connection.execute(
            select(resource)
            .where(resource.c.tenant_id == context.tenant.id, resource.c.id.in_(resource_ids))
            .order_by(resource.c.id)
            .with_for_update()
        ).mappings()
    )
    from app.domain.resource_reservations import legacy_inventory_missing

    legacy_missing = {
        row["id"] for row in resource_rows if legacy_inventory_missing(connection, context, row)
    }
    booking = tables.resource_reservations
    intervals = tables.resource_reservation_intervals
    coverage = {}
    if covered_project_id is not None:
        from app.domain.resource_reservations import _project

        _project(connection, context, covered_project_id)
        if covered_node_keys is None:
            from app.domain.formal_schedule import current_plan

            formal = current_plan(connection, context.tenant.id, covered_project_id)
            coverage = {node["id"]: node["node_key"] for node in formal["nodes"]} if formal else {}
    if covered_node_keys is not None:
        if covered_project_id is None or len(set(covered_node_keys.values())) != len(
            covered_node_keys
        ):
            raise ProductWorkError("预约覆盖映射须绑定唯一项目节点")
        valid_ids = set(
            connection.execute(
                select(tables.schedule_nodes.c.id).where(
                    tables.schedule_nodes.c.tenant_id == context.tenant.id,
                    tables.schedule_nodes.c.project_id == covered_project_id,
                    tables.schedule_nodes.c.id.in_(covered_node_keys),
                )
            ).scalars()
        )
        if valid_ids != set(covered_node_keys):
            raise ProductWorkError("预约覆盖节点不属于当前项目")
        coverage = covered_node_keys
    coverage_key = (
        case(coverage, value=booking.c.node_id, else_=None) if coverage else literal_column("NULL")
    ).label("covered_node_key")
    reserved_intervals = [
        {
            "resource_id": str(row["resource_id"]),
            "start": row["start"].isoformat(),
            "end": row["end"].isoformat(),
            "units": str(row["units"]),
            **({"covered_node_key": row["covered_node_key"]} if row["covered_node_key"] else {}),
        }
        for row in connection.execute(
            select(
                booking.c.resource_id,
                coverage_key,
                intervals.c.start,
                intervals.c.end,
                func.sum(booking.c.parallel_units).label("units"),
            )
            .join(
                intervals,
                (intervals.c.tenant_id == booking.c.tenant_id)
                & (intervals.c.reservation_id == booking.c.id),
            )
            .where(
                booking.c.tenant_id == context.tenant.id,
                booking.c.resource_id.in_(resource_ids),
                booking.c.state == "reserved",
            )
            .group_by(
                booking.c.resource_id,
                intervals.c.start,
                intervals.c.end,
                *([coverage_key] if coverage else []),
            )
            .order_by(
                booking.c.resource_id,
                intervals.c.start,
                intervals.c.end,
                *([coverage_key] if coverage else []),
            )
        ).mappings()
    ]
    legacy_spans: Iterable[RowMapping] = (
        connection.execute(
            text(
                'SELECT resource_id,start,"end",SUM(parallel_units) AS units '
                "FROM cehub_project.current_legacy_resource_allocations WHERE"
                " tenant_id=:tenant AND resource_id=ANY(:resources) GROUP BY "
                'resource_id,start,"end" ORDER BY resource_id,start,"end"'
            ),
            {"tenant": context.tenant.id, "resources": list(resource_ids)},
        ).mappings()
        if resource_ids
        else []
    )
    reserved_intervals.extend(
        {
            "resource_id": str(row["resource_id"]),
            "start": row["start"].isoformat(),
            "end": row["end"].isoformat(),
            "units": str(row["units"]),
            "origin": "legacy_inventory",
        }
        for row in legacy_spans
    )
    newer = cap.alias("newer_capacity")
    rows = connection.execute(
        select(
            cap,
            resource.c.name.label("resource_name"),
            resource.c.kind,
            resource.c.user_id,
            cal.c.definition.label("calendar_definition"),
        )
        .join(
            resource,
            (resource.c.tenant_id == cap.c.tenant_id) & (resource.c.id == cap.c.resource_id),
        )
        .join(
            cal,
            (cal.c.tenant_id == cap.c.tenant_id) & (cal.c.id == cap.c.calendar_version_id),
        )
        .where(cap.c.tenant_id == context.tenant.id, cap.c.id.in_(capacity_ids))
    ).mappings()
    for row in rows:
        current = (
            connection.execute(
                select(newer.c.id)
                .where(
                    newer.c.tenant_id == context.tenant.id,
                    newer.c.resource_id == row["resource_id"],
                    newer.c.version > row["version"],
                )
                .limit(1)
            ).first()
            is None
        )
        active = (
            row["user_id"] is None
            or connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id == row["user_id"],
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(
                        ("owner", "admin", "project_manager", "engineer", "quality")
                    ),
                )
            ).first()
            is not None
        )
        profiles[row["id"]] = {**dict(row), "is_current": current, "person_active": active}
    if set(profiles) != capacity_ids:
        raise ProductWorkError("容量版本不存在或不可访问")
    return profiles, reserved_intervals, legacy_missing
