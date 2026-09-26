"""Exact reservation coverage and approved baseline inputs for portfolio batch application."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.baseline_changes import (
    approval_blockers,
    latest_baseline,
    latest_policy,
    manual_dependency_gaps,
    responsibility_gaps,
)
from app.domain.cross_project_schedule_runtime import active_applications
from app.domain.portfolio_comparisons import readable
from app.domain.portfolio_execution_preparations import date_values
from app.domain.portfolio_selections import (
    comparison,
    decisions,
    parts,
    recheck_comparison,
    selection,
    state,
)
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.project_scenario_capacity import evaluate_scenario_capacity, get_scenario
from app.domain.resource_capacity import CapacityCheckDraft
from app.domain.resource_priorities import PREFIX
from app.domain.resource_reservations import ReservationDraft, _project
from app.domain.resource_schedule_preparations import current_solver, get_schedule
from app.domain.schedule_nodes import require_reservable_node
from app.domain.task_dependency_graph import dependency_graph_has_cycle
from app.domain.working_time import CalendarDefinition, WorkingTime, ceil_minute, minute_quantity


class PortfolioApplicationPreview(Contract):
    preparation_id: UUID
    expected_selection_digest: Digest


def preparation(c: Connection, context: AuthContext, identity: UUID) -> Any:
    t = tables.portfolio_execution_preparations
    saved = (
        c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if saved is None:
        raise ProductWorkAccessError("组合执行准备不存在或不可读取")
    return saved


def residual(desired: list[dict[str, Any]], covered: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Sweep additive real occupancy; reserve only the uncovered amount in each interval."""
    events: dict[datetime, list[tuple[int, Decimal]]] = defaultdict(list)
    for side, spans in enumerate((desired, covered)):
        for span in spans:
            start = datetime.fromisoformat(span["start"]).astimezone(UTC)
            end = datetime.fromisoformat(span["end"]).astimezone(UTC)
            amount = Decimal(span["units"])
            events[start].append((side, amount))
            events[end].append((side, -amount))
    points = sorted(events)
    running = [Decimal(0), Decimal(0)]
    result: list[dict[str, str]] = []
    with localcontext() as ctx:
        ctx.prec = 48
        for index, left in enumerate(points[:-1]):
            for side, amount in events[left]:
                running[side] += amount
            right = points[index + 1]
            missing = max(Decimal(0), running[0] - running[1])
            if not missing or right <= left:
                continue
            start_iso, end_iso, units = left.isoformat(), right.isoformat(), str(missing)
            if (
                result
                and result[-1]["end"] == start_iso
                and Decimal(result[-1]["units"]) == missing
            ):
                result[-1]["end"] = end_iso
            else:
                result.append({"start": start_iso, "end": end_iso, "units": units})
    return result


def booking_plan(
    c: Connection,
    context: AuthContext,
    project: UUID,
    source: Any,
    scenario: Any,
    capacity: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    solver = current_solver(c, context, project, source)
    by_key = {n["node_key"]: n for n in scenario["result"]["nodes"]}
    owners = {n["node_key"]: n["owner_user_id"] for n in scenario["plan"]["nodes"]}
    r, i = tables.resource_reservations, tables.resource_reservation_intervals
    targets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for span in capacity["demand_intervals"]:
        targets[(span["node_key"], span["resource_id"])].append(span)
    additions: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    blockers: list[str] = []
    pending: list[dict[str, Any]] = []
    for (key, resource_id), desired in sorted(targets.items()):
        node = by_key[key]
        demand = next(
            d
            for d in solver.draft.demands[key]
            if str(solver.profiles[d.capacity_version_id]["resource_id"]) == resource_id
        )
        profile = solver.profiles[demand.capacity_version_id]
        priority = next(p for p in solver.policies if p["resource_id"] == resource_id)
        rows = list(
            c.execute(
                select(r)
                .where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.project_id == project,
                    r.c.node_id == UUID(node["node_id"]),
                    r.c.resource_id == UUID(resource_id),
                    r.c.state.in_(("reserved", "proposed")),
                )
                .order_by(r.c.created_at, r.c.id)
            ).mappings()
        )
        intervals = list(
            c.execute(
                select(i)
                .where(
                    i.c.tenant_id == context.tenant.id,
                    i.c.reservation_id.in_([v["id"] for v in rows if v["state"] == "reserved"]),
                )
                .order_by(i.c.start, i.c.end, i.c.reservation_id)
            ).mappings()
        )
        actual = {v["id"]: v for v in rows}
        spans = [
            {
                "start": v["start"].isoformat(),
                "end": v["end"].isoformat(),
                "units": str(actual[v["reservation_id"]]["parallel_units"]),
            }
            for v in intervals
        ]
        confirmed = [
            {
                "id": str(v["id"]),
                "payload_digest": digest(_plain(v)),
                "window_start": v["window_start"].isoformat(),
                "window_end": v["window_end"].isoformat(),
                "units": str(v["parallel_units"]),
            }
            for v in rows
            if v["state"] == "reserved"
        ]
        coverage.append(
            {
                "node_id": node["node_id"],
                "node_key": key,
                "resource_id": resource_id,
                "resource_name": profile["resource_name"],
                "desired_intervals": desired,
                "reservations": confirmed,
                "covered_intervals": spans,
            }
        )
        used = set()
        gaps = residual(desired, spans)
        if gaps:
            try:
                require_reservable_node(c, context, project, UUID(node["node_id"]))
            except ProductWorkError as error:
                blockers.append(f"{key}：{error}")
        for gap in gaps:
            start, end = datetime.fromisoformat(gap["start"]), datetime.fromisoformat(gap["end"])
            if end <= now:
                blockers.append(
                    f"{key} / {profile['resource_name']}：未覆盖的预约时段已结束，请重算方案"
                )
            if any(v.second or v.microsecond for v in (start, end)):
                blockers.append(f"{key} / {profile['resource_name']}：预约时段须按原整分钟规则核对")
            match = next(
                (
                    v
                    for v in rows
                    if v["state"] == "proposed"
                    and v["contract"]["priority_policy_version"] == PREFIX + priority["policy_id"]
                    and v["id"] not in used
                    and v["capacity_version_id"] == demand.capacity_version_id
                    and v["window_start"] == start
                    and v["window_end"] == end
                    and v["parallel_units"] == Decimal(gap["units"])
                    and v["occupancy_policy"] == demand.occupancy_policy
                ),
                None,
            )
            owner = (
                match["owner_user_id"] if match else UUID(owners[key]) if owners.get(key) else None
            )
            if owner is None:
                blockers.append(f"{key}：尚无具名预约负责人")
                owner_name = None
            else:
                try:
                    owner_name = _person(c, context, project, owner)["display_name"]
                except ProductWorkError:
                    blockers.append(f"{key}：预约负责人已不属于当前有效项目参与人")
                    owner_name = None
            if match:
                used.add(match["id"])
            draft = {
                "node_id": node["node_id"],
                "capacity_version_id": str(demand.capacity_version_id),
                "window_start": gap["start"],
                "window_end": gap["end"],
                "parallel_units": gap["units"],
                "occupancy_policy": demand.occupancy_policy,
                "basis": demand.basis,
            }
            try:
                ReservationDraft.model_validate({"request_id": str(source["id"]), **draft})
            except ValueError:
                blockers.append(
                    f"{key} / {profile['resource_name']}：拟预约不符合现有窗口或数量规则"
                )
            additions.append(
                {
                    "key": digest({"project_id": str(project), **draft}),
                    "project_id": str(project),
                    "node_key": key,
                    "resource_id": resource_id,
                    "resource_name": profile["resource_name"],
                    "owner_user_id": str(owner) if owner else None,
                    "owner_name": owner_name,
                    "draft": draft,
                    "priority": priority,
                    "existing_proposal_basis": match["basis"] if match else None,
                    "existing_proposal_id": str(match["id"]) if match else None,
                    "existing_proposal_digest": digest(_plain(match)) if match else None,
                    "already_started": start <= now,
                }
            )
        pending.extend(
            {
                "id": str(v["id"]),
                "payload_digest": digest(_plain(v)),
                "node_key": key,
                "resource_name": profile["resource_name"],
            }
            for v in rows
            if v["state"] == "proposed" and v["id"] not in used
        )
    if len(additions) > 2000:
        raise ProductWorkError("单项目拟新增预约超过2000段，请调整方案；未截断占用清单")
    return {
        "additions": additions,
        "coverage": coverage,
        "unselected_proposals": pending,
        "blockers": blockers,
    }


def capture(
    c: Connection, context: AuthContext, command: PortfolioApplicationPreview
) -> dict[str, Any]:
    _role(context, Action.TENANT_MANAGE)
    package = preparation(c, context, command.preparation_id)
    initial = selection(c, context, package["selection_id"])
    original = comparison(c, context, initial["comparison_id"])
    readable(c, context, original["inputs"])
    participants = parts(c, context, initial["id"])
    for part in participants:
        _project(c, context, part["project_id"], write=True)
    saved = selection(c, context, initial["id"], lock=True)
    if (
        saved["payload_digest"] != command.expected_selection_digest
        or package["selection_digest"] != saved["payload_digest"]
    ):
        raise ProductWorkError("所选执行准备与原组合同意版本不一致")
    consents = decisions(c, context, saved["id"])
    if state(consents, len(participants)) != "approved_for_preparation":
        raise ProductWorkError("原组合采用申请已结束或尚未全部同意")
    recheck_comparison(c, context, original)
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    t = tables.portfolio_execution_projects
    bound = list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == context.tenant.id, t.c.preparation_id == package["id"])
            .order_by(t.c.project_id)
        ).mappings()
    )
    if {p["project_id"] for p in participants} != {p["project_id"] for p in bound}:
        raise ProductWorkError("执行准备的项目范围不完整")
    items: list[dict[str, Any]] = []
    blockers: list[str] = []
    scenarios: dict[UUID, Any] = {}
    for part in bound:
        project = part["project_id"]
        p = _project(c, context, project)
        request = (
            c.execute(
                select(tables.baseline_change_requests).where(
                    tables.baseline_change_requests.c.tenant_id == context.tenant.id,
                    tables.baseline_change_requests.c.project_id == project,
                    tables.baseline_change_requests.c.id == part["change_id"],
                )
            )
            .mappings()
            .one()
        )
        decision = (
            c.execute(
                select(tables.baseline_change_decisions).where(
                    tables.baseline_change_decisions.c.tenant_id == context.tenant.id,
                    tables.baseline_change_decisions.c.project_id == project,
                    tables.baseline_change_decisions.c.change_id == request["id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if c.execute(
            select(tables.baseline_change_applications.c.id).where(
                tables.baseline_change_applications.c.tenant_id == context.tenant.id,
                tables.baseline_change_applications.c.change_id == request["id"],
            )
        ).first():
            raise ProductWorkError("此项目已有基线应用，请读取原整批回执")
        local = []
        if p["status"] not in ("approved", "active"):
            local.append("当前项目状态不允许确认正式预约")
        if request["payload_digest"] != part["change_digest"]:
            raise ProductWorkError("原正式基线申请版本不一致")
        if (
            decision is None
            or decision["action"] != "approve"
            or decision["approved_payload_digest"] != part["change_digest"]
        ):
            local.append("原正式基线申请尚未按此版本获批")
        policy = latest_policy(c, context.tenant.id, project)
        baseline = latest_baseline(c, context.tenant.id, project)
        if (
            policy is None
            or policy["id"] != request["policy_id"]
            or baseline["id"] != request["base_baseline_id"]
        ):
            raise ProductWorkError("原批准政策或基线已变化，请重新准备组合")
        _person(c, context, project, policy["approver_user_id"])
        if (
            decision
            and decision["action"] == "approve"
            and policy["approver_user_id"] != decision["actor_user_id"]
        ):
            local.append("正式基线批准人与当前政策不一致")
        scenario = get_scenario(c, context, project, part["scenario_id"])
        source = get_schedule(c, context, project, part["schedule_id"])
        snap = request["snapshot"]
        scenarios[project] = snap
        if date_values(snap["result"]) != date_values(source["result"]):
            raise ProductWorkError("正式申请日期与获同意组合方案不一致")
        capacity = evaluate_scenario_capacity(
            c,
            context,
            project,
            scenario,
            CapacityCheckDraft.model_validate(snap["capacity_inputs"]),
            result_override=snap["result"],
        )
        if digest(capacity) != digest(snap["capacity"]):
            raise ProductWorkError("正式基线申请的容量依据已变化，请重新准备组合")
        local.extend(
            approval_blockers(
                snap["result"], capacity, responsibility_gaps(c, context, project, snap["plan"])
            )
        )
        local.extend(
            manual_dependency_gaps(c, context.tenant.id, project, snap["plan"], snap["result"])
        )
        bookings = booking_plan(c, context, project, source, scenario, capacity, now)
        local.extend(bookings["blockers"])
        blockers.extend(f"{p['name']}：{v}" for v in local)
        items.append(
            {
                "project_id": str(project),
                "project_name": p["name"],
                "change_id": str(request["id"]),
                "change_digest": request["payload_digest"],
                "decision": _plain(decision) if decision else None,
                "baseline_id": str(baseline["id"]),
                "baseline_version": baseline["version"],
                "policy_id": str(policy["id"]),
                "scenario_id": str(scenario["id"]),
                "schedule_id": str(source["id"]),
                "source_result_digest": source["result_digest"],
                "bookings": bookings,
                "blockers": local,
            }
        )
    if sum(len(p["bookings"]["additions"]) for p in items) > 4000:
        raise ProductWorkError("组合新增预约超过4000段，请调整方案；未截断项目")
    cross_checks = joint_constraints(c, context, scenarios)
    blockers.extend(v["reason"] for v in cross_checks if not v["satisfied"])
    plan = {
        "cross_project_checks": cross_checks,
        "preparation_id": str(package["id"]),
        "selection_id": str(saved["id"]),
        "selection_digest": saved["payload_digest"],
        "comparison_digest": original["payload_digest"],
        "items": items,
        "blockers": blockers,
        "ready": not blockers,
        "reservation_policy": (
            "reuse_exact_pending_or_add_uncovered_intervals; preserve_existing_confirmed"
        ),
        "baseline_policy": "exact_approved_requests_in_one_transaction",
        "applied": False,
        "commitments_changed": False,
    }
    return {"plan": plan, "payload_digest": digest(plan)}


def joint_constraints(
    c: Connection, context: AuthContext, scenarios: dict[UUID, Any]
) -> list[dict[str, Any]]:
    edges: dict[UUID, tuple[tuple[UUID, UUID], ...]] = {}
    nodes = {}
    for project, snap in scenarios.items():
        mapping = {n["node_key"]: UUID(n["node_id"]) for n in snap["result"]["nodes"]}
        nodes.update({UUID(n["node_id"]): (project, n) for n in snap["result"]["nodes"]})
        edges[project] = tuple(
            (mapping[e["successor"]], mapping[e["predecessor"]])
            for e in snap["plan"]["dependencies"]
        )
    results = [
        {
            "kind": "joint_dependency_graph",
            "satisfied": not dependency_graph_has_cycle(
                c,
                tenant_id=context.tenant.id,
                project_id=next(iter(scenarios)),
                formal_projects=edges,
            ),
            "reason": "全部拟基线与当前手工/跨项目依赖合并后存在循环，须重新比较",
        }
    ]
    for application in active_applications(c, context.tenant.id):
        if (
            application["predecessor_project_id"] not in scenarios
            or application["successor_project_id"] not in scenarios
        ):
            continue
        a, b = (
            nodes.get(application["predecessor_node_id"]),
            nodes.get(application["successor_node_id"]),
        )
        if a is None or b is None:
            results.append(
                {
                    "kind": "cross_project_dates",
                    "application_id": str(application["id"]),
                    "satisfied": False,
                    "reason": "组合所选计划移除了仍有效跨项目依赖的端点",
                }
            )
            continue
        proposal = (
            c.execute(
                select(tables.cross_project_schedule_proposals).where(
                    tables.cross_project_schedule_proposals.c.tenant_id == context.tenant.id,
                    tables.cross_project_schedule_proposals.c.id == application["proposal_id"],
                )
            )
            .mappings()
            .one()
        )
        relation = proposal["relation"]
        anchor = a[1]["finish" if relation[0] == "f" else "start"]
        target = b[1]["finish" if relation[1] == "f" else "start"]
        bound = None
        if anchor is not None and target is not None:
            point = datetime.fromisoformat(anchor)
            lag = proposal["lag"]
            if proposal["lag_unit"] == "calendar_days":
                minutes = int((abs(lag) * 1440).to_integral_value(rounding=ROUND_CEILING))
                bound = ceil_minute(point) + timedelta(minutes=minutes if lag >= 0 else -minutes)
            else:
                definition = scenarios[b[0]]["result"]["calendars"][
                    b[1]["allocation"]["calendar_key"]
                ]["definition"]
                engine = WorkingTime(CalendarDefinition.model_validate(definition))
                bound = engine.advance(point, minute_quantity(lag) * (1 if lag >= 0 else -1))
        results.append(
            {
                "kind": "cross_project_dates",
                "application_id": str(application["id"]),
                "predecessor_node_id": str(application["predecessor_node_id"]),
                "successor_node_id": str(application["successor_node_id"]),
                "relation": relation,
                "lag": str(proposal["lag"]),
                "lag_unit": proposal["lag_unit"],
                "required_at": bound.isoformat() if bound else None,
                "selected_at": target,
                "satisfied": bound is not None
                and target is not None
                and datetime.fromisoformat(target) >= bound,
                "reason": "所选项目日期未满足原跨项目依赖，请重算组合",
            }
        )
    return results


class PortfolioApplicationPlanService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, context: AuthContext, command: PortfolioApplicationPreview) -> dict[str, Any]:
        with self.engine.begin() as c:
            return capture(c, context, command)
