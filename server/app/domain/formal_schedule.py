"""One current approved schedule definition, with legacy initial application preserved."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.schedule_node_state import additional_state, certification_status


def current_plan(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> dict[str, Any] | None:
    records = tables.schedule_time_records
    baseline = (
        connection.execute(
            select(records)
            .where(
                records.c.tenant_id == tenant_id,
                records.c.project_id == project_id,
                records.c.time_kind == "baseline",
            )
            .order_by(records.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if baseline is None:
        return None
    initial = (
        connection.execute(
            select(tables.initial_plan_applications).where(
                tables.initial_plan_applications.c.tenant_id == tenant_id,
                tables.initial_plan_applications.c.project_id == project_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if initial is not None and initial["baseline_id"] == baseline["id"]:
        snapshot = initial["snapshot"]["plan_snapshot"]
        plan = snapshot["candidate"]["plan"]
        scenario = snapshot["scenario"]
        bindings = tables.task_plan_bindings
        mapping = {
            row["node_key"]: row["schedule_node_id"]
            for row in connection.execute(
                select(bindings).where(
                    bindings.c.tenant_id == tenant_id,
                    bindings.c.project_id == project_id,
                    bindings.c.application_id == initial["id"],
                )
            ).mappings()
        }
        allocations = {
            key: scenario["inputs"]["node_allocations"].get(
                key, scenario["inputs"]["default_allocation"]
            )
            for key in mapping
        }
        initial_start = datetime.fromisoformat(scenario["inputs"]["start"])
        allocations = {
            key: {
                **value,
                "not_before": max(
                    initial_start,
                    datetime.fromisoformat(value["not_before"])
                    if value.get("not_before")
                    else initial_start,
                ).isoformat(),
            }
            for key, value in allocations.items()
        }
        capacity_inputs = snapshot["capacity_inputs"]
    else:
        applications = tables.baseline_change_applications
        requests = tables.baseline_change_requests
        applied = (
            connection.execute(
                select(applications, requests.c.snapshot)
                .join(
                    requests,
                    (requests.c.tenant_id == applications.c.tenant_id)
                    & (requests.c.project_id == applications.c.project_id)
                    & (requests.c.id == applications.c.change_id),
                )
                .where(
                    applications.c.tenant_id == tenant_id,
                    applications.c.project_id == project_id,
                    applications.c.baseline_id == baseline["id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if applied is None:
            raise ProductWorkError("当前基线缺少完整应用回执，不能回退读取旧计划")
        snapshot = applied["snapshot"]
        plan = snapshot["plan"]
        links = tables.project_schedule_scenario_nodes
        mapping = {
            row["node_key"]: row["node_id"]
            for row in connection.execute(
                select(links).where(
                    links.c.tenant_id == tenant_id,
                    links.c.project_id == project_id,
                    links.c.scenario_id == applied["scenario_id"],
                )
            ).mappings()
        }
        allocations = {
            node["node_key"]: {
                "calendar_version_id": node["allocation"]["calendar_key"],
                "parallel_units": node["allocation"]["parallel_units"],
                "allocation_basis": node["allocation"]["allocation_basis"],
                "not_before": node["estimate"].get("not_before")
                if node.get("estimate")
                and not node.get("actual_start")
                and not node.get("actual_finish")
                else node["allocation"].get("not_before"),
            }
            for node in snapshot["result"]["nodes"]
        }
        capacity_inputs = snapshot["capacity_inputs"]
    if set(mapping) != {node["node_key"] for node in plan["nodes"]} or set(mapping) != set(
        allocations
    ):
        raise ProductWorkError("当前正式计划的节点、日历或映射不完整")
    nodes = {
        row["id"]: dict(row)
        for row in connection.execute(
            select(tables.schedule_nodes).where(
                tables.schedule_nodes.c.tenant_id == tenant_id,
                tables.schedule_nodes.c.project_id == project_id,
                tables.schedule_nodes.c.id.in_(mapping.values()),
            )
        ).mappings()
    }
    if set(nodes) != set(mapping.values()):
        raise ProductWorkError("当前正式计划存在缺失的业务节点")
    return {
        "baseline_id": baseline["id"],
        "baseline_version": baseline["version"],
        "plan": plan,
        "allocations": allocations,
        "capacity_inputs": capacity_inputs,
        "nodes": [
            {**nodes[node_id], "schedule_node_id": node_id, "node_key": key}
            for key, node_id in sorted(mapping.items())
        ],
    }


def current_states(
    connection: Connection, tenant_id: UUID, project_id: UUID, formal: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from app.domain.schedule_actual_corrections import effective_observations
    from app.domain.schedule_nodes import SOURCES
    from app.domain.schedule_source_actuals import latest_observations

    observations = effective_observations(connection, tenant_id, project_id)
    points = {(row["node_id"], row["point"]): row for row in observations}
    generic = {
        row["node_id"]: row for row in latest_observations(connection, tenant_id, project_id)
    }
    sources = {}
    for kind, (table, column, _) in SOURCES.items():
        ids = [node[column] for node in formal["nodes"] if node["node_kind"] == kind]
        if ids:
            sources[kind] = {
                row["id"]: row
                for row in connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.id.in_(ids),
                    )
                ).mappings()
            }
    plan_nodes = {node["node_key"]: node for node in formal["plan"]["nodes"]}
    states, titles = [], {}
    source: Any
    for node in formal["nodes"]:
        key, kind = node["node_key"], node["node_kind"]
        state = {
            "node_key": key,
            "node_id": str(node["id"]),
            "node_kind": kind,
            "task_id": str(node["task_id"]) if node["task_id"] else None,
            "assignee_user_id": plan_nodes[key].get("owner_user_id"),
            "actual_start_event": None,
            "actual_finish_event": None,
        }
        titles[key] = plan_nodes[key]["title"]
        if kind == "task":
            source = sources[kind][node["task_id"]]
            start, finish = points.get((node["id"], "start")), points.get((node["id"], "finish"))
            missing = []
            if source["status"] in ("in_progress", "blocked", "done") and not start:
                missing.append("正式任务缺少实际开工依据")
            if source["status"] == "done" and not finish:
                missing.append("任务已完成但缺少实际结束依据")
            state.update(
                status=source["status"],
                assignee_user_id=str(source["assignee_user_id"])
                if source["assignee_user_id"]
                else None,
                actual_start=start["observed_at"].isoformat() if start else None,
                actual_finish=finish["observed_at"].isoformat() if finish else None,
                actual_start_event=start["event_row_id"] if start else None,
                actual_finish_event=finish["event_row_id"] if finish else None,
                input_unknown=missing,
            )
            titles[key] = source["title"]
        else:
            observation = generic.get(node["id"])
            source = None if kind == "milestone" else sources[kind][node[SOURCES[kind][1]]]
            virtual = {
                **_plain(node),
                "actual": _plain(observation) if observation else None,
                "source_status": source["status"]
                if source
                else observation["source_status"]
                if observation
                else "checkpoint",
                "source_draft_state": source.get("draft_state") if source else None,
            }
            if kind == "certification":
                virtual["source_status"] = certification_status(source)
            state.update(additional_state(virtual))
            if kind == "test_run":
                state["expected_completion_at"] = (
                    source["expected_completion_at"].isoformat()
                    if source["expected_completion_at"]
                    else None
                )
            state["source_digest"] = digest(_plain(source)) if source else digest(_plain(node))
            if observation:
                state["actual_observation"] = {
                    "id": str(observation["id"]),
                    "version": observation["version"],
                }
                if observation.get("actual_correction"):
                    state["actual_correction"] = observation["actual_correction"]
        states.append(state)
    return states, titles
