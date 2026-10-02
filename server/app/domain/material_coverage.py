"""Observed supply gaps and date-grain delivery comparisons against fixed Build demand."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.material_allocations import MaterialAllocationService, _key
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.schedule_forecasts import capture_basis
from app.domain.work_calendars import CalendarCalculationError, WorkCalendarCalculator
from app.domain.working_time import CalendarDefinition

POLICY = "supply.observed_gap.date_comparison.v1"


class CoverageSelection(Contract):
    time_kind: Literal["baseline", "commitment", "forecast"] = "baseline"
    long_cycle_threshold_days: int | None = Field(default=None, strict=True, ge=1, le=36600)
    expected_date_timezone_confirmed: bool = False
    date_basis: Text | None = None

    @model_validator(mode="after")
    def confirmed_basis(self) -> Self:
        if self.expected_date_timezone_confirmed and not self.date_basis:
            raise ValueError("确认到货日期采用需料节点日历时区时，请说明核对依据")
        return self


def _schedule(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    revision: dict[str, Any] | None,
    observed_at: datetime,
) -> dict[str, Any]:
    if revision is None:
        return {"node": None, "calendar": None, "times": {}, "issues": ["尚未固定批次需求"]}
    node_id = UUID(revision["need_by_node_id"])
    n, records, times = (
        tables.schedule_nodes,
        tables.schedule_time_records,
        tables.schedule_time_nodes,
    )
    node = (
        c.execute(
            select(n).where(
                n.c.tenant_id == tenant_id, n.c.project_id == project_id, n.c.id == node_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        return {"node": None, "calendar": None, "times": {}, "issues": ["原需料节点已不可读取"]}
    windows: dict[str, Any] = {}
    for kind in ("baseline", "commitment", "forecast"):
        query = (
            select(
                records.c.id, records.c.version, records.c.created_at, times.c.start, times.c.end
            )
            .outerjoin(
                times,
                (times.c.tenant_id == records.c.tenant_id)
                & (times.c.record_id == records.c.id)
                & (times.c.node_id == node_id),
            )
            .where(
                records.c.tenant_id == tenant_id,
                records.c.project_id == project_id,
                records.c.time_kind == kind,
            )
        )
        # Commitments update a selected scope; baseline/forecast replace the full project version.
        if kind == "commitment":
            query = query.where(times.c.node_id == node_id)
        row = c.execute(query.order_by(records.c.version.desc()).limit(1)).mappings().one_or_none()
        windows[kind] = (
            {**dict(row), "state": "available" if row["start"] else "start_unknown"}
            if row
            else {"state": "missing", "start": None, "end": None}
        )
    issues: list[str] = []
    formal = None
    try:
        formal = current_plan(c, tenant_id, project_id)
    except ProductWorkError as error:
        issues.append(str(error))
    bound = (
        next((item for item in formal["nodes"] if item["id"] == node_id), None) if formal else None
    )
    calendar = None
    if bound and formal:
        calendar_id = UUID(formal["allocations"][bound["node_key"]]["calendar_version_id"])
        row = (
            c.execute(
                select(tables.work_calendar_versions).where(
                    tables.work_calendar_versions.c.tenant_id == tenant_id,
                    tables.work_calendar_versions.c.id == calendar_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            definition = CalendarDefinition.model_validate(row["definition"])
            calculator = WorkCalendarCalculator(definition.calendar)
            calendar = {
                "version_id": str(row["id"]),
                "name": row["name"],
                "version": row["version"],
                "definition_digest": row["definition_digest"],
                "evidence": asdict(calculator.evidence),
                "today": calculator.local_date(observed_at).isoformat(),
            }
            for window in windows.values():
                window["local_start_date"] = (
                    calculator.local_date(window["start"]).isoformat()
                    if window.get("start")
                    else None
                )
    else:
        issues.append("需料节点不在当前正式计划中，请先核对正式节点与日历")
        for window in windows.values():
            if window["state"] == "available":
                window["state"] = "outside_current_plan"
    if windows["forecast"].get("id"):
        run = (
            c.execute(
                select(tables.schedule_forecast_runs.c.basis_digest).where(
                    tables.schedule_forecast_runs.c.tenant_id == tenant_id,
                    tables.schedule_forecast_runs.c.project_id == project_id,
                    tables.schedule_forecast_runs.c.record_id == windows["forecast"]["id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        current_digest = None
        try:
            current_digest = capture_basis(c, tenant_id, project_id)["basis_digest"]
        except ProductWorkError as error:
            issues.append(str(error))
        if run is None or current_digest is None or run["basis_digest"] != current_digest:
            windows["forecast"]["state"] = "stale"
        windows["forecast"]["basis_current"] = (
            run is not None and current_digest is not None and run["basis_digest"] == current_digest
        )
    return _plain(
        {
            "node": {"id": node_id, "title": node["title"], "build_id": node["build_id"]},
            "calendar": calendar,
            "times": windows,
            "issues": issues,
        }
    )


def _delivery(
    source: dict[str, Any], need_date: date | None, today: date | None, command: CoverageSelection
) -> dict[str, Any]:
    expected = date.fromisoformat(source["expected_date"]) if source.get("expected_date") else None
    if source["supply_kind"] == "on_hand":
        timing = "on_hand"
    elif expected is None:
        timing = "arrival_date_unknown"
    elif not command.expected_date_timezone_confirmed or today is None:
        timing = "date_basis_unknown"
    elif expected < today:
        timing = "arrival_overdue"
    elif need_date is None:
        timing = "need_date_unknown"
    elif expected < need_date:
        timing = "before_need_date"
    elif expected == need_date:
        timing = "same_day_time_unknown"
    else:
        timing = "after_need_date"
    lead = source.get("lead_time_days")
    threshold = command.long_cycle_threshold_days
    long_cycle = (
        "threshold_unknown"
        if threshold is None
        else "lead_unknown"
        if lead is None
        else "long_cycle"
        if lead >= threshold
        else "below_threshold"
    )
    return {
        "timing": timing,
        "days_after_need": (expected - need_date).days
        if expected and need_date and command.expected_date_timezone_confirmed
        else None,
        "days_overdue": (today - expected).days
        if expected and today and command.expected_date_timezone_confirmed and expected < today
        else None,
        "long_cycle": long_cycle,
        "lead_time_days": lead,
    }


def calculate(
    data: dict[str, Any], schedule: dict[str, Any], command: CoverageSelection
) -> dict[str, Any]:
    with localcontext() as arithmetic:
        arithmetic.prec = 2048
        return _calculate(data, schedule, command)


def _calculate(
    data: dict[str, Any], schedule: dict[str, Any], command: CoverageSelection
) -> dict[str, Any]:
    selected = schedule["times"].get(command.time_kind, {})
    need_date = (
        date.fromisoformat(selected["local_start_date"])
        if selected.get("state") == "available" and selected.get("local_start_date")
        else None
    )
    today = date.fromisoformat(schedule["calendar"]["today"]) if schedule["calendar"] else None
    pools = []
    views = {}
    references = {
        line["material_reference"] for line in data["lines"] if line["material_reference"]
    }
    allocations_by_line: dict[str, list[dict[str, Any]]] = {}
    for allocation in data["allocations"]:
        if data["revision"] and allocation["revision_id"] == data["revision"]["id"]:
            allocations_by_line.setdefault(allocation["bom_item_id"], []).append(allocation)
    for original in data["pools"]:
        source = original["source"]
        reference = source["external_item_id"] if source else original["pool_key"][2]
        if reference not in references:
            continue
        view = {
            **original,
            "delivery": _delivery(source, need_date, today, command)
            if source
            else {
                "timing": "source_unreadable",
                "long_cycle": "source_unreadable",
                "lead_time_days": None,
                "days_after_need": None,
                "days_overdue": None,
            },
        }
        pools.append(view)
        if source:
            views[_key(source)] = view
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for line in data["lines"]:
        # Unmapped lines stay separate; no guessed part-number mapping.
        key = (line["material_reference"] or f"unmapped:{line['bom_item_id']}", line["unit"])
        group = grouped.setdefault(
            key,
            {
                "material_reference": line["material_reference"],
                "unit": line["unit"],
                "lines": [],
                "required": Decimal(0),
                "allocated_on_hand": Decimal(0),
                "qualified_issued": Decimal(0),
                "qualified_issued_before_date": Decimal(0),
                "allocated_before_date": Decimal(0),
                "allocated_same_day": Decimal(0),
                "allocated_late": Decimal(0),
                "allocated_overdue": Decimal(0),
                "allocated_unverified": Decimal(0),
                "allocated_frozen": Decimal(0),
                "issues": [],
            },
        )
        group["lines"].append(
            {
                "bom_item_id": line["bom_item_id"],
                "part_number": line["part_number"],
                "required_quantity": line["required_quantity"],
                "critical": line["critical"],
            }
        )
        group["required"] += Decimal(line["required_quantity"])
        for allocation in allocations_by_line.get(line["bom_item_id"], []):
            group["qualified_issued"] += Decimal(allocation.get("qualified_received_quantity", "0"))
            for lot in allocation.get("received_lots", []):
                if (
                    lot["qualified"]
                    and need_date
                    and datetime.fromisoformat(lot["occurred_at"])
                    .astimezone(ZoneInfo(schedule["calendar"]["evidence"]["timezone"]))
                    .date()
                    < need_date
                ):
                    group["qualified_issued_before_date"] += Decimal(lot["quantity"])

            pool = views.get(_key(allocation))
            amount = Decimal(allocation["remaining_quantity"])
            if pool is not None and pool["state"] == "quality_frozen":
                group["allocated_frozen"] += amount
                group["issues"].append("quality_frozen")
                continue
            if (
                pool is None
                or pool["state"] != "current"
                or pool["source"]["quality_status"] != "released"
                or (
                    allocation.get("supply_grant_id")
                    and allocation["supply_grant_id"] != pool["source"].get("source_grant_id")
                )
            ):
                group["allocated_unverified"] += amount
                continue
            timing = pool["delivery"]["timing"]
            bucket = {
                "on_hand": "allocated_on_hand",
                "before_need_date": "allocated_before_date",
                "same_day_time_unknown": "allocated_same_day",
                "after_need_date": "allocated_late",
                "arrival_overdue": "allocated_overdue",
            }.get(timing, "allocated_unverified")
            group[bucket] += amount
    for group in grouped.values():
        matching = [
            pool
            for pool in pools
            if pool["source"]
            and pool["source"]["external_item_id"] == group["material_reference"]
            and pool["source"]["unit"] == group["unit"]
        ]
        available_on_hand, available_before_date = Decimal(0), Decimal(0)
        unknown = (
            bool(data["pool_limit_reached"]) or not matching or not group["material_reference"]
        )
        hidden = [
            pool
            for pool in pools
            if not pool["source"]
            and pool.get("pool_key", [None, None, None])[2] == group["material_reference"]
        ]
        if hidden:
            unknown = True
            group["issues"].append("current_source_unreadable")
        for pool in matching:
            source = pool["source"]
            if pool["state"] == "quality_frozen":
                group["issues"].append("quality_frozen")
                continue
            if pool["state"] != "current" or source["quality_status"] != "released":
                unknown = True
                group["issues"].append(
                    pool["state"] if pool["state"] != "current" else "quality_unknown"
                )
                continue
            if pool["delivery"]["timing"] == "on_hand":
                available_on_hand += Decimal(pool["available_quantity"])
            elif pool["delivery"]["timing"] == "before_need_date":
                available_before_date += Decimal(pool["available_quantity"])
            elif pool["delivery"]["timing"] in {
                "arrival_date_unknown",
                "date_basis_unknown",
                "need_date_unknown",
                "same_day_time_unknown",
            }:
                group["issues"].append(pool["delivery"]["timing"])
        if group["allocated_unverified"]:
            unknown = True
            group["issues"].append("allocated_source_unknown")
        group["unallocated_on_hand"] = available_on_hand
        group["unallocated_before_date"] = available_before_date
        group["allocated_on_hand_gap"] = max(
            group["required"] - group["allocated_on_hand"] - group["qualified_issued"],
            Decimal(0),
        )
        group["on_hand_ready"] = group["allocated_on_hand_gap"] == 0
        group["allocated_date_gap"] = (
            max(
                group["required"]
                - group["allocated_on_hand"]
                - group["qualified_issued_before_date"]
                - group["allocated_before_date"],
                Decimal(0),
            )
            if need_date
            else None
        )
        group["known_on_hand_gap"] = max(
            group["required"]
            - group["allocated_on_hand"]
            - group["qualified_issued"]
            - available_on_hand,
            Decimal(0),
        )
        group["observed_on_hand_gap"] = (
            Decimal(0)
            if group["qualified_issued"] + group["allocated_on_hand"] >= group["required"]
            else None
            if unknown
            else group["known_on_hand_gap"]
        )
        group["known_before_date_gap"] = (
            max(
                group["required"]
                - group["allocated_on_hand"]
                - group["qualified_issued_before_date"]
                - group["allocated_before_date"]
                - available_on_hand
                - available_before_date,
                Decimal(0),
            )
            if need_date
            else None
        )
        timing_unknown = any(
            issue
            in {
                "arrival_date_unknown",
                "date_basis_unknown",
                "need_date_unknown",
                "same_day_time_unknown",
            }
            for issue in group["issues"]
        )
        group["observed_before_date_gap"] = (
            None if unknown or timing_unknown else group["known_before_date_gap"]
        )
        group["source_state"] = "incomplete" if unknown else "observed_scope_only"
        group["pool_ids"] = [pool["source"]["id"] for pool in matching]
        group["issues"] = sorted(set(group["issues"]))
    rows = [
        _plain(
            {
                **group,
                "material_key": digest(
                    {
                        "material_reference": group["material_reference"],
                        "unit": group["unit"],
                        "unmapped_item": group["lines"][0]["bom_item_id"]
                        if not group["material_reference"]
                        else None,
                    }
                ),
            }
        )
        for group in grouped.values()
    ]
    basis = {
        "policy": POLICY,
        "selection": command.model_dump(mode="json"),
        "revision_id": data["revision"]["id"] if data["revision"] else None,
        "revision_digest": data["revision"]["content_digest"] if data["revision"] else None,
        "build": data["build"],
        "schedule": schedule,
        "allocations": data["allocations"],
        "pools": pools,
        "pool_limit_reached": data["pool_limit_reached"],
        "materials": rows,
    }
    required_rows = [row for row in rows if Decimal(row["required"]) > 0]
    critical_rows = [row for row in required_rows if any(line["critical"] for line in row["lines"])]
    kit = {
        "material_count": len(required_rows),
        "ready_count": sum(row["on_hand_ready"] for row in required_rows),
        "critical_count": len(critical_rows),
        "critical_ready_count": sum(row["on_hand_ready"] for row in critical_rows),
        "ready": bool(required_rows) and all(row["on_hand_ready"] for row in required_rows),
        "critical_ready": all(row["on_hand_ready"] for row in critical_rows)
        if critical_rows else None,
        "basis": "本批次明确分配的合格现货及领用时合格净领料；未分配与预计供给不计齐套",
    }
    basis["kit"] = kit
    return {
        "digest": digest(basis),
        "as_of": data["as_of"],
        **basis,
        "need_date": need_date.isoformat() if need_date else None,
        "need_date_passed": bool(need_date and today and need_date < today),
        "totals": {
            "material_count": len(rows),
            "source_incomplete_count": sum(row["source_state"] == "incomplete" for row in rows),
            "on_hand_gap_count": sum(
                row["observed_on_hand_gap"] is not None and Decimal(row["observed_on_hand_gap"]) > 0
                for row in rows
            ),
            "long_cycle_pool_count": sum(
                pool["delivery"]["long_cycle"] == "long_cycle" for pool in pools
            ),
            "long_cycle_unknown_pool_count": sum(
                pool["delivery"]["long_cycle"]
                in {"threshold_unknown", "lead_unknown", "source_unreadable"}
                for pool in pools
            ),
            "overdue_receipt_pool_count": sum(
                pool["delivery"]["timing"] == "arrival_overdue" for pool in pools
            ),
        },
    }


class MaterialCoverageService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: CoverageSelection
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            return self.read(c, context, project_id, build_id, command)

    @staticmethod
    def read(
        c: Connection,
        context: AuthContext,
        project_id: UUID,
        build_id: UUID,
        command: CoverageSelection,
    ) -> dict[str, Any]:
        data = MaterialAllocationService.read(c, context, project_id, build_id)
        try:
            schedule = _schedule(
                c,
                context.tenant.id,
                project_id,
                data["revision"],
                datetime.fromisoformat(data["as_of"]),
            )
        except CalendarCalculationError as error:
            schedule = {
                "node": None,
                "calendar": None,
                "times": {},
                "issues": [f"需料节点日历不可计算：{error}"],
            }
        return calculate(data, schedule, command)
