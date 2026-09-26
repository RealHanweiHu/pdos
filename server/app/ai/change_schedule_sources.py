"""Read existing schedule evidence for an ECR; never recalculate or write a plan."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, String, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.db.schema import tables
from app.domain.formal_schedule import current_plan, current_states
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.schedule_forecasts import capture_local_basis
from app.domain.schedule_network import capture_network

MAX_NODES = 200
MAX_OCCUPANCY_ROWS = 500


def _latest(
    c: Connection, table: Any, tenant: UUID, project: UUID, *predicates: Any, order: Any
) -> dict[str, Any] | None:
    row = (
        c.execute(
            select(table)
            .where(table.c.tenant_id == tenant, table.c.project_id == project, *predicates)
            .order_by(*(order if isinstance(order, tuple) else (order,)))
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def read_sources(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    ecr_id: UUID,
    graph: dict[str, Any],
    depth: int,
) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    gaps: list[str] = []
    fingerprints: dict[str, str] = {}

    def add(key: str, label: str, fields: dict[str, Any]) -> None:
        fields = _plain(fields)
        refs.append(
            {
                "reference_id": key,
                "category": "schedule",
                "label": label,
                "fields": fields,
                "source_digest": digest(fields),
            }
        )

    bindings, followups = tables.change_execution_tasks, tables.change_execution_followups
    execution_links: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in c.execute(
        select(
            bindings.c.id, bindings.c.task_id, bindings.c.scope_version_id, bindings.c.item_key
        ).where(
            bindings.c.tenant_id == tenant_id,
            bindings.c.project_id == project_id,
            bindings.c.ecr_id == ecr_id,
        )
    ).mappings():
        execution_links[row["task_id"]].append({"kind": "scope_task", **dict(row)})
    for row in c.execute(
        select(
            followups.c.id,
            followups.c.task_id,
            followups.c.binding_id,
            followups.c.source_result_id,
            bindings.c.scope_version_id,
        )
        .join(
            bindings,
            (bindings.c.tenant_id == followups.c.tenant_id)
            & (bindings.c.project_id == followups.c.project_id)
            & (bindings.c.id == followups.c.binding_id),
        )
        .where(
            followups.c.tenant_id == tenant_id,
            followups.c.project_id == project_id,
            bindings.c.ecr_id == ecr_id,
        )
    ).mappings():
        execution_links[row["task_id"]].append({"kind": "follow_up_task", **dict(row)})
    for entries in execution_links.values():
        entries.sort(key=lambda row: str(row["id"]))
    task_ids = set(execution_links)
    objects: dict[str, list[UUID]] = defaultdict(list)
    for node in graph["nodes"]:
        objects[node["kind"]].append(UUID(node["id"]))
    nodes = tables.schedule_nodes
    roots = {
        row["id"]: dict(row)
        for row in c.execute(
            select(nodes).where(
                nodes.c.tenant_id == tenant_id,
                nodes.c.project_id == project_id,
                or_(
                    nodes.c.task_id.in_(task_ids),
                    nodes.c.build_id.in_(objects["build"]),
                    nodes.c.test_run_id.in_(objects["test_run"]),
                    nodes.c.certification_id.in_(objects["certification"]),
                ),
            )
        ).mappings()
    }
    fingerprints["root_bindings"] = digest([_plain(roots[k]) for k in sorted(roots, key=str)])
    formal = None
    try:
        formal = current_plan(c, tenant_id, project_id)
    except ProductWorkError:
        gaps.append("当前正式基线缺少完整应用依据，请回排程办理")
    if formal is None:
        gaps.append("未读取到可用的正式计划；原任务日期不等于基线、预测或承诺")
    all_nodes = {n["id"]: n for n in formal["nodes"]} if formal else {}
    all_nodes.update({id: row for id, row in roots.items() if id not in all_nodes})
    selected = set(sorted(roots, key=str)[:MAX_NODES])
    dependencies: list[dict[str, Any]] = []
    if formal:
        d = tables.schedule_plan_dependencies
        dependencies = [
            dict(row)
            for row in c.execute(
                select(d)
                .where(
                    d.c.tenant_id == tenant_id,
                    d.c.project_id == project_id,
                    d.c.baseline_id == formal["baseline_id"],
                )
                .order_by(d.c.id)
            ).mappings()
        ]
        for _ in range(depth):
            adjacent = {
                row[key]
                for row in dependencies
                if row["predecessor_node_id"] in selected or row["successor_node_id"] in selected
                for key in ("predecessor_node_id", "successor_node_id")
            }
            additions = sorted(adjacent - selected, key=str)
            room = max(0, MAX_NODES - len(selected))
            selected.update(additions[:room])
            if len(additions) > room:
                gaps.append("相关正式依赖节点达到单次读取上限，不能据此判断全部排期影响")
                break
        fingerprints["formal_plan"] = digest(_plain(formal))
        fingerprints["formal_dependencies"] = digest([_plain(d) for d in dependencies])
    if len(roots) > MAX_NODES:
        gaps.append("直接关联的排程节点超过单次读取上限")
    if not roots:
        gaps.append("当前影响对象及变更执行任务尚无明确的排程节点绑定，不能推断无排期影响")
    missing_tasks = task_ids - {n["task_id"] for n in roots.values() if n["task_id"]}
    if missing_tasks:
        gaps.append(f"{len(missing_tasks)} 项变更执行/补齐任务尚未绑定正式排程节点")

    record = tables.schedule_time_records
    latest_forecast = _latest(
        c,
        record,
        tenant_id,
        project_id,
        record.c.time_kind == "forecast",
        order=record.c.version.desc(),
    )
    forecast = (
        _latest(
            c,
            tables.schedule_forecast_runs,
            tenant_id,
            project_id,
            tables.schedule_forecast_runs.c.record_id == latest_forecast["id"],
            order=tables.schedule_forecast_runs.c.record_id,
        )
        if latest_forecast
        else None
    )
    states: dict[str, dict[str, Any]] = {}
    basis_is_current: bool | None = None
    if formal:
        try:
            capture = capture_local_basis(c, tenant_id, project_id)
            network = capture_network(c, tenant_id, project_id, capture["basis"])
            current_digest = digest(
                {
                    **capture["basis"],
                    **({"external_input_digest": digest(network)} if network else {}),
                }
            )
            fingerprints["current_forecast_basis"] = current_digest
            states = {s["node_id"]: s for s in capture["basis"]["tasks"]}
            if forecast:
                basis_is_current = forecast["basis_digest"] == current_digest
        except (ProductWorkError, ValueError):
            gaps.append("预测的完整依赖依据未能核对；需在正式排程重新计算确认")
            local_states, _ = current_states(c, tenant_id, project_id, formal)
            states = {s["node_id"]: s for s in local_states}
    if not forecast:
        gaps.append("尚无实际保存的预测版本")
    elif basis_is_current is not True:
        gaps.append("保存的预测已过期或无法确认仍有效；日期只作历史对照")
    if forecast:
        fingerprints["forecast"] = digest(_plain(forecast))

    times = tables.schedule_time_nodes
    rank_query = select(
        times.c.node_id,
        times.c.start,
        times.c.end,
        record.c.id.label("record_id"),
        record.c.time_kind,
        record.c.version,
        func.row_number()
        .over(partition_by=(times.c.node_id, record.c.time_kind), order_by=record.c.version.desc())
        .label("position"),
    )
    ranked = (
        rank_query.join(
            record,
            (record.c.tenant_id == times.c.tenant_id)
            & (record.c.project_id == times.c.project_id)
            & (record.c.id == times.c.record_id),
        )
        .where(
            times.c.tenant_id == tenant_id,
            times.c.project_id == project_id,
            times.c.node_id.in_(selected),
            or_(
                record.c.time_kind.in_(("actual", "commitment")),
                record.c.id == formal["baseline_id"] if formal else false(),
                record.c.id == latest_forecast["id"] if latest_forecast else false(),
            ),
        )
        .subquery()
    )
    windows: dict[UUID, dict[str, Any]] = defaultdict(dict)
    for row in c.execute(select(ranked).where(ranked.c.position == 1)).mappings():
        windows[row["node_id"]][row["time_kind"]] = _plain(dict(row))
    keys = {all_nodes[id].get("node_key") for id in selected if id in all_nodes}
    calendar_ids = {
        UUID(formal["allocations"][key]["calendar_version_id"])
        for key in keys
        if formal and key in formal["allocations"]
    }
    forecast_nodes = {n["node_key"]: n for n in forecast["result"]["nodes"]} if forecast else {}
    plan_nodes = {n["node_key"]: n for n in formal["plan"]["nodes"]} if formal else {}
    for id in sorted(selected, key=str):
        node = all_nodes.get(id)
        if node is None:
            gaps.append("正式依赖有节点缺少当前绑定资料")
            continue
        key = node.get("node_key")
        source_kind = node["node_kind"]
        source_id = node.get(
            {
                "task": "task_id",
                "build": "build_id",
                "gate": "gate_id",
                "test_run": "test_run_id",
                "certification": "certification_id",
            }.get(source_kind, "")
        )
        state = states.get(str(id))
        add(
            "schedule-node:" + str(id),
            "正式排程 · "
            + (plan_nodes.get(key, {}).get("title") or node.get("title") or "业务节点"),
            {
                "node_id": str(id),
                "node_kind": source_kind,
                "source_object": f"{source_kind}:{source_id}" if source_id else None,
                "relation_to_change": "direct_binding" if id in roots else "formal_dependency",
                "change_execution_links": execution_links.get(node.get("task_id"), []),
                "in_current_baseline": key in plan_nodes,
                "four_times": {
                    kind: windows[id].get(kind)
                    for kind in ("baseline", "forecast", "commitment", "actual")
                },
                "effective_actual": state,
                "plan_definition": plan_nodes.get(key),
                "forecast_is_current": basis_is_current,
                "saved_forecast": forecast_nodes.get(key),
                "allocation": formal["allocations"].get(key) if formal else None,
                "formal_resource_requirements": formal["capacity_inputs"]
                .get("demands", {})
                .get(key)
                if formal
                else None,
                "formal_no_resource_reason": formal["capacity_inputs"]
                .get("no_resource_reasons", {})
                .get(key)
                if formal
                else None,
            },
        )
    for dependency in dependencies:
        if {dependency["predecessor_node_id"], dependency["successor_node_id"]} <= selected:
            add(
                "schedule-dependency:" + str(dependency["id"]),
                "原基线中的正式依赖",
                {
                    k: dependency[k]
                    for k in (
                        "baseline_id",
                        "predecessor_node_id",
                        "successor_node_id",
                        "relation",
                        "lag",
                        "lag_unit",
                    )
                },
            )

    commitment_ids = {
        UUID(w["commitment"]["record_id"]) for w in windows.values() if w.get("commitment")
    }
    confirmations = tables.schedule_commitment_confirmations
    confirmed = {
        r["record_id"]: dict(r)
        for r in c.execute(
            select(confirmations).where(
                confirmations.c.tenant_id == tenant_id,
                confirmations.c.project_id == project_id,
                confirmations.c.record_id.in_(commitment_ids),
            )
        ).mappings()
    }
    for row in c.execute(
        select(record)
        .where(
            record.c.tenant_id == tenant_id,
            record.c.project_id == project_id,
            record.c.id.in_(commitment_ids),
        )
        .order_by(record.c.version)
    ).mappings():
        confirmation = confirmed.get(row["id"])
        add(
            "schedule-commitment:" + str(row["id"]),
            "原具名承诺 · v" + str(row["version"]),
            {
                "record_id": row["id"],
                "version": row["version"],
                "approval": row["contract"].get("approval"),
                "sources": row["contract"].get("sources", []),
                "confirmation": {
                    k: confirmation[k]
                    for k in (
                        "id",
                        "policy_id",
                        "forecast_record_id",
                        "capacity_check_id",
                        "scope_label",
                        "reason",
                        "approved_by_user_id",
                        "created_at",
                    )
                }
                if confirmation
                else None,
                "basis_is_latest_forecast": confirmation["forecast_record_id"]
                == forecast["record_id"]
                if confirmation and forecast
                else None,
                "interpretation": (
                    "承诺是原具名确认的历史事实；当前可兑现性须按最新预测与容量重新核对"
                ),
            },
        )
    if forecast and selected:
        _capacity_sources(
            c, tenant_id, project_id, forecast, keys, add, fingerprints, gaps, calendar_ids
        )
    calendars = tables.work_calendar_versions
    for calendar in c.execute(
        select(calendars)
        .where(calendars.c.tenant_id == tenant_id, calendars.c.id.in_(calendar_ids))
        .order_by(calendars.c.id)
    ).mappings():
        add(
            "schedule-calendar:" + str(calendar["id"]),
            "固定工作日历 · " + calendar["name"],
            {k: calendar[k] for k in ("id", "name", "version", "definition", "definition_digest")},
        )
    head = {
        "baseline_id": str(formal["baseline_id"]) if formal else None,
        "baseline_version": formal["baseline_version"] if formal else None,
        "forecast_record_id": str(forecast["record_id"]) if forecast else None,
        "forecast_is_current": basis_is_current,
        "related_node_count": len(selected),
        "direct_node_count": len(roots),
        "dependency_depth": depth,
        "unbound_execution_task_count": len(missing_tasks),
        "gaps": sorted(set(gaps)),
        "interpretation": (
            "基线/预测/承诺/实际分别取原版本。正式依赖说明排程关系，"
            "不等于变更影响已获批；未重算任何日期或容量。"
        ),
    }
    add("schedule-overview:" + str(ecr_id), "相关排程四时间与覆盖说明", head)
    return {
        "references": [refs[-1], *refs[:-1]],
        "gaps": sorted(set(gaps)),
        "digest": digest({"references": refs, "fingerprints": fingerprints}),
    }


def _capacity_sources(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    forecast: dict[str, Any],
    node_keys: set[Any],
    add: Callable[[str, str, dict[str, Any]], None],
    fingerprints: dict[str, str],
    gaps: list[str],
    calendar_ids: set[UUID],
) -> None:
    table = tables.forecast_capacity_checks
    check = _latest(
        c,
        table,
        tenant_id,
        project_id,
        table.c.forecast_record_id == forecast["record_id"],
        order=(table.c.created_at.desc(), table.c.id.desc()),
    )
    if check is None:
        gaps.append("最新预测尚无保存的容量检查")
        return
    fingerprints["capacity_check"] = digest(_plain(check))
    result = check["result"]
    demanded = {
        d["capacity_version_id"]
        for key, demands in check["inputs"].get("demands", {}).items()
        if key in node_keys
        for d in demands
    }
    profiles = [p for p in result.get("profiles", []) if p["id"] in demanded]
    resource_ids = {UUID(p["resource_id"]) for p in profiles}
    cap = tables.resource_capacity_versions
    resource = tables.planning_resources
    newest = {
        str(r["resource_id"]): dict(r)
        for r in c.execute(
            select(cap, resource.c.name.label("resource_name"))
            .join(
                resource,
                (resource.c.tenant_id == cap.c.tenant_id) & (resource.c.id == cap.c.resource_id),
            )
            .where(cap.c.tenant_id == tenant_id, cap.c.resource_id.in_(resource_ids))
            .distinct(cap.c.resource_id)
            .order_by(cap.c.resource_id, cap.c.version.desc())
        ).mappings()
    }
    fingerprints["capacity_versions"] = digest([_plain(newest[k]) for k in sorted(newest)])
    for profile in profiles:
        current = newest.get(profile["resource_id"])
        calendar_ids.add(UUID(profile["calendar_version_id"]))
        if current:
            calendar_ids.add(current["calendar_version_id"])
        add(
            "schedule-capacity:" + profile["id"],
            "资源容量 · " + profile["resource_name"],
            {
                "checked_profile": {
                    k: profile.get(k)
                    for k in (
                        "id",
                        "version",
                        "resource_id",
                        "resource_name",
                        "window_start",
                        "window_end",
                        "parallel_units",
                        "basis",
                        "calendar_version_id",
                    )
                },
                "latest_profile": {
                    k: current[k]
                    for k in (
                        "id",
                        "version",
                        "window_start",
                        "window_end",
                        "parallel_units",
                        "basis",
                        "calendar_version_id",
                    )
                }
                if current
                else None,
                "version_is_current": current is not None and str(current["id"]) == profile["id"],
            },
        )
    # Only anonymous aggregate occupancy is exposed, never other projects' people or records.
    booking, interval = tables.resource_reservations, tables.resource_reservation_intervals
    from_clause = booking.join(
        interval,
        (interval.c.tenant_id == booking.c.tenant_id) & (interval.c.reservation_id == booking.c.id),
    )
    filters = (
        booking.c.tenant_id == tenant_id,
        booking.c.resource_id.in_(resource_ids),
        booking.c.state == "reserved",
    )
    signature = func.concat_ws(
        ":",
        cast(booking.c.id, String),
        cast(booking.c.version, String),
        cast(booking.c.parallel_units, String),
        cast(interval.c.start, String),
        cast(interval.c.end, String),
    )
    fingerprints["resource_occupancy"] = str(
        c.execute(
            select(
                func.md5(
                    func.string_agg(
                        signature,
                        aggregate_order_by(
                            literal(","), booking.c.id, interval.c.start, interval.c.end
                        ),
                    )
                )
            )
            .select_from(from_clause)
            .where(*filters)
        ).scalar_one()
    )
    occupancy = (
        c.execute(
            select(
                booking.c.resource_id,
                interval.c.start,
                interval.c.end,
                func.sum(booking.c.parallel_units).label("units"),
            )
            .select_from(from_clause)
            .where(*filters)
            .group_by(booking.c.resource_id, interval.c.start, interval.c.end)
            .order_by(booking.c.resource_id, interval.c.start, interval.c.end)
            .limit(MAX_OCCUPANCY_ROWS + 1)
        )
        .mappings()
        .all()
    )
    add(
        "schedule-capacity-check:" + str(check["id"]),
        "保存的预测容量检查与当前占用",
        {
            "check_id": check["id"],
            "forecast_record_id": forecast["record_id"],
            "created_at": check["created_at"],
            "saved_status": result["status"],
            "saved_conflict_count": len(result.get("conflicts", [])),
            "saved_unknown_count": len(result.get("unknown", [])),
            "saved_conflicts": [
                r
                for r in result.get("conflicts", [])
                if r.get("resource_id") in {str(id) for id in resource_ids}
            ],
            "saved_unknown": result.get("unknown", []),
            "current_occupancy": [_plain(dict(r)) for r in occupancy[:MAX_OCCUPANCY_ROWS]],
            "occupancy_truncated": len(occupancy) > MAX_OCCUPANCY_ROWS,
            "current_capacity_status": "requires_recheck",
            "interpretation": (
                "保存的检查不等于当前可兑现。当前占用只含共享预约汇总，"
                "旧系统占用及资源资格仍由原容量检查核验；未重新计算容量或更改预约。"
            ),
        },
    )
    gaps.append("容量仅提供原检查和当前预约汇总；正式安排或承诺前须在原流程重新检查")
    if len(occupancy) > MAX_OCCUPANCY_ROWS:
        gaps.append("当前共享预约汇总超出单次展示容量，后续条目已省略")
