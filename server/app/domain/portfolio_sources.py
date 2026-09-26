"""Actual project, schedule, cost and evidence versions for portfolio alternatives."""

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.cost_backtests import source_state as cost_source_state
from app.domain.cost_definition_feedback import cost_access
from app.domain.cost_freezes import row
from app.domain.document_previews import DocumentPreviewMissing, document_row, metadata
from app.domain.portfolio_scoring import PortfolioComparison, PortfolioPolicy, arithmetic
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.resource_capacity import CapacityCheckDraft, Demand, _compute, capacity_sources
from app.domain.resource_reservations import _project
from app.domain.resource_schedule_preparations import current_solver, get_schedule
from app.domain.resource_schedule_solver import _union_existing
from app.domain.working_time import CalendarDefinition, WorkingTime


def combined_capacity(
    c: Connection, context: AuthContext, selections: list[tuple[Any, Any]]
) -> dict[str, Any]:
    with localcontext() as decimal_context:
        decimal_context.prec = 48
        return _combined_capacity(c, context, selections)


def _combined_capacity(
    c: Connection, context: AuthContext, selections: list[tuple[Any, Any]]
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    calendars: dict[str, Any] = {}
    demands: dict[str, tuple[Demand, ...]] = {}
    reasons: dict[str, str] = {}
    ids: dict[UUID, str] = {}
    project_keys: dict[str, set[str]] = {}
    for saved, _solver in selections:
        project = str(saved["project_id"])
        prefix = UUID(project).hex + ":"
        project_keys[project] = set()
        for original in saved["result"]["nodes"]:
            if original.get("actual_finish"):
                continue
            key = prefix + original["node_key"]
            project_keys[project].add(key)
            ids[UUID(original["node_id"])] = key
            nodes.append(
                {
                    **original,
                    "node_key": key,
                    "start": original["remaining_work_start"],
                    "work_minutes": original["remaining_work_minutes"],
                }
            )
        for key, value in saved["result"]["calendars"].items():
            if key in calendars and digest(calendars[key]) != digest(value):
                raise ProductWorkError("同一日历版本的固定规则不同，请重新计算来源方案")
            calendars[key] = value
        for key, values in saved["inputs"]["demands"].items():
            demands[prefix + key] = tuple(Demand.model_validate(v) for v in values)
        reasons.update({prefix + k: v for k, v in saved["inputs"]["no_resource_reasons"].items()})
    if len(nodes) > 1000:
        raise ProductWorkError("单个组合目前最多核对1000个未完成节点；未截断或省略项目")
    command = CapacityCheckDraft(
        request_id=selections[0][0]["id"], demands=demands, no_resource_reasons=reasons
    )
    profiles, raw, missing = capacity_sources(c, context, command)
    r, i = tables.resource_reservations, tables.resource_reservation_intervals
    reserved = [
        {
            "resource_id": str(v["resource_id"]),
            "start": v["start"].isoformat(),
            "end": v["end"].isoformat(),
            "units": str(v["units"]),
            **({"covered_node_key": ids[v["node_id"]]} if v["node_id"] in ids else {}),
        }
        for v in c.execute(
            select(
                r.c.resource_id,
                r.c.node_id,
                i.c.start,
                i.c.end,
                func.sum(r.c.parallel_units).label("units"),
            )
            .join(i, (i.c.tenant_id == r.c.tenant_id) & (i.c.reservation_id == r.c.id))
            .where(
                r.c.tenant_id == context.tenant.id,
                r.c.resource_id.in_({p["resource_id"] for p in profiles.values()}),
                r.c.state == "reserved",
            )
            .group_by(r.c.resource_id, r.c.node_id, i.c.start, i.c.end)
            .order_by(r.c.resource_id, r.c.node_id, i.c.start, i.c.end)
        ).mappings()
    ]
    reserved.extend(v for v in raw if v.get("origin") == "legacy_inventory")
    fixed = {"nodes": nodes, "calendars": calendars}
    scenario = {"id": command.request_id, "result": fixed, "result_digest": digest(fixed)}
    result = _compute(
        scenario, demands, profiles, reasons, reserved, missing, match_existing_reservations=True
    )
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in result["demand_intervals"]:
        by_key[span["node_key"]].append(span)
    priority_checks = []
    for saved, solver in selections:
        project = str(saved["project_id"])
        keys = project_keys[project]
        occupied = list(reserved)
        for key, spans in by_key.items():
            if key not in keys:
                occupied = _union_existing(occupied, spans, key)
        own_demands = {k: v for k, v in demands.items() if k in keys}
        own_profiles = {
            d.capacity_version_id: profiles[d.capacity_version_id]
            for values in own_demands.values()
            for d in values
        }
        own = {
            "id": saved["id"],
            "result_digest": saved["result_digest"],
            "result": {
                "nodes": [n for n in nodes if n["node_key"] in keys],
                "calendars": calendars,
            },
        }
        checked = _compute(
            own,
            own_demands,
            own_profiles,
            {k: v for k, v in reasons.items() if k in keys},
            [*occupied, *solver.pending],
            missing & {p["resource_id"] for p in own_profiles.values()},
            match_existing_reservations=True,
        )
        priority_checks.append(
            {
                "project_id": project,
                "status": checked["status"],
                "conflicts": checked["conflicts"],
                "unknown": checked["unknown"],
                "priority_intervals": solver.pending,
            }
        )
    limit = {str(p["resource_id"]): p["parallel_units"] for p in profiles.values()}
    utilization = [
        Decimal(r["peak_units"]) / limit[r["resource_id"]]
        for r in result["resources"]
        if limit[r["resource_id"]] > 0
    ]
    result["pressure"] = (
        str(max(utilization, default=Decimal(0)))
        if not result["unknown"]
        and all(
            limit[v["resource_id"]] > 0 or Decimal(v["peak_units"]) == 0
            for v in result["resources"]
        )
        else None
    )
    result["priority_checks"] = priority_checks
    result["feasible"] = result["status"] == "capacity_clear" and all(
        v["status"] == "capacity_clear" for v in priority_checks
    )
    return result


def capture(
    c: Connection,
    context: AuthContext,
    command: PortfolioComparison,
    policy_row: Any,
    *,
    require_recent_request: bool = True,
) -> dict[str, Any]:
    now: datetime = c.execute(select(func.clock_timestamp())).scalar_one()
    if require_recent_request and not (
        now - timedelta(minutes=15) <= command.comparison_at <= now + timedelta(minutes=1)
    ):
        raise ProductWorkError("比较准备时点已过期或不正确，请重新预览")
    policy = PortfolioPolicy.model_validate(policy_row["body"])
    projects, calendars = {}, {}
    for scoped in sorted(command.projects, key=lambda v: str(v.project_id)):
        project = _project(c, context, scoped.project_id, write=True)
        cost_access(c, context, scoped.project_id)
        projects[str(scoped.project_id)] = {
            "id": str(project["id"]),
            "name": project["name"],
            "status": project["status"],
        }
        calendar = (
            c.execute(
                select(tables.work_calendar_versions).where(
                    tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                    tables.work_calendar_versions.c.id == scoped.calendar_version_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if calendar is None:
            raise ProductWorkError("指定比较日历不存在")
        engine = WorkingTime(CalendarDefinition.model_validate(calendar["definition"]))
        calendars[str(scoped.project_id)] = {
            "id": str(calendar["id"]),
            "definition": calendar["definition"],
            "evidence": _plain(asdict(engine.evidence)),
        }
    c.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
    alternatives: list[dict[str, Any]] = []
    levels = {level.key for level in policy.risk_levels}
    for alternative in command.alternatives:
        selections, values, source_blockers = [], [], []
        times = []
        for choice in alternative.choices:
            project = projects[str(choice.project_id)]
            saved = get_schedule(c, context, choice.project_id, choice.schedule_id)
            scheduled_at = datetime.fromisoformat(saved["result"]["as_of"])
            times.append(scheduled_at)
            if (
                scheduled_at > now
                or Decimal(str((now - scheduled_at).total_seconds())) / 3600
                > policy.max_source_age_hours
            ):
                source_blockers.append(f"{project['name']}：资源日期来源超出本政策允许账龄")
            solver = None
            try:
                solver = current_solver(c, context, choice.project_id, saved)
            except ProductWorkError as error:
                source_blockers.append(f"{project['name']}：{error}")
            if solver is not None:
                selections.append((saved, solver))
            cost = None
            if choice.cost_rollup_id is not None:
                cost_row = row(
                    c,
                    context.tenant.id,
                    choice.project_id,
                    tables.cost_rollups,
                    choice.cost_rollup_id,
                )
                state = cost_source_state(c, context.tenant.id, choice.project_id, cost_row)
                quotes_current = all(
                    date.fromisoformat(entry["payload"]["valid_from"])
                    <= now.date()
                    <= date.fromisoformat(entry["payload"]["valid_until"])
                    for entry in cost_row["snapshot"]["inputs"]
                    if entry["payload"].get("stage") == "quote"
                )
                cost = {
                    "id": str(cost_row["id"]),
                    "title": cost_row["title"],
                    "calculation_digest": cost_row["calculation_digest"],
                    "source_digest": cost_row["source_digest"],
                    "command": cost_row["command"],
                    "result": {
                        key: cost_row["result"][key]
                        for key in (
                            "complete",
                            "unit_total",
                            "nre_total",
                            "known_unit_subtotal",
                            "known_nre_subtotal",
                            "gaps",
                            "warnings",
                        )
                    },
                    "quotes_current": quotes_current,
                    "current": state["current"]
                    and quotes_current
                    and (
                        now - timedelta(microseconds=int(policy.max_source_age_hours * 3600000000))
                    ).date()
                    <= date.fromisoformat(cost_row["command"]["as_of"])
                    <= now.date(),
                }
            evidence = None
            if choice.quality_level is not None:
                if choice.quality_level not in levels or choice.evidence_id is None:
                    raise ProductWorkError("质量风险等级须来自本次固定政策，并关联实际资料")
                try:
                    evidence = metadata(
                        document_row(c, context.tenant.id, choice.project_id, choice.evidence_id)
                    )
                except DocumentPreviewMissing as error:
                    raise ProductWorkError(str(error)) from error
            values.append(
                {
                    "project_id": str(choice.project_id),
                    "project_name": project["name"],
                    "schedule_id": str(saved["id"]),
                    "scenario_id": str(saved["scenario_id"]),
                    "schedule_digest": saved["result_digest"],
                    "schedule_source_digest": saved["source_digest"],
                    "schedule_as_of": saved["result"]["as_of"],
                    "finish": saved["result"]["project_finish"],
                    "schedule_status": saved["result"]["solution_status"],
                    "cost": cost,
                    "quality_level": choice.quality_level,
                    "quality_evidence": evidence,
                    "quality_basis": choice.quality_basis,
                    "quality_evidence_location": choice.evidence_location,
                    "quality_fact_kind": "named_hypothesis",
                    "scope_basis": choice.scope_basis,
                }
            )
        if (max(times) - min(times)).total_seconds() > policy.max_asof_spread_minutes * 60:
            source_blockers.append("各项目资源日期的计算时点差距超出本政策范围")
        capacity = (
            combined_capacity(c, context, selections)
            if not source_blockers and len(selections) == len(alternative.choices)
            else None
        )
        blockers = list(source_blockers)
        if capacity is None or not capacity["feasible"]:
            blockers.append("组合容量或在先申请仍有冲突/缺项，不能进入可行方案排名")
        if any(v["schedule_status"] != "candidate_found" for v in values):
            blockers.append("至少一个项目的资源日期仍有未解约束")
        alternatives.append(
            {
                "key": alternative.key,
                "title": alternative.title,
                "strategy": alternative.strategy,
                "assumptions": alternative.assumptions,
                "projects": values,
                "source_blockers": source_blockers,
                "blockers": blockers,
                "capacity_pressure": capacity["pressure"] if capacity else None,
                "capacity": capacity,
            }
        )
    all_times = [
        datetime.fromisoformat(v["schedule_as_of"]) for a in alternatives for v in a["projects"]
    ]
    if (max(all_times) - min(all_times)).total_seconds() > policy.max_asof_spread_minutes * 60:
        for alternative_value in alternatives:
            message = "备选之间的资源日期计算时点差距超出本政策范围"
            alternative_value["source_blockers"].append(message)
            alternative_value["blockers"].append(message)
    result = arithmetic(command, policy, alternatives, calendars)
    snapshot = {
        "inputs": command.model_dump(mode="json"),
        "policy": _plain(policy_row),
        "projects": list(projects.values()),
        "calendars": calendars,
        "comparison_at": command.comparison_at.isoformat(),
        "result": result,
    }
    return {"snapshot": snapshot, "payload_digest": digest(snapshot)}
