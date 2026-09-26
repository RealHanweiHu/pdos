"""Transient node-level dependency networks; only necessary timing projections are public."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, or_, select

from app.contracts.common_objects import PlanCandidate
from app.db.schema import tables
from app.domain.cross_project_schedule_runtime import active_applications
from app.domain.plan_scheduling import NodeAllocation
from app.domain.product_workspace import digest
from app.domain.schedule_forecast_engine import calculate_forecast
from app.domain.working_time import CalendarDefinition


def latest_human_estimates(
    connection: Connection, tenant_id: UUID, project_id: UUID, local_basis: dict[str, Any]
) -> dict[str, Any]:
    runs = tables.schedule_forecast_runs
    records = tables.schedule_time_records
    row = connection.execute(
        select(runs.c.inputs)
        .join(
            records, (records.c.tenant_id == runs.c.tenant_id) & (records.c.id == runs.c.record_id)
        )
        .where(
            runs.c.tenant_id == tenant_id,
            runs.c.project_id == project_id,
            or_(
                runs.c.inputs["trigger"].as_string() == "human",
                (runs.c.inputs["trigger"].as_string().is_(None))
                & (runs.c.inputs["estimates"] != {}),
            ),
        )
        .order_by(records.c.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {}
    previous = {
        key: value
        for key, value in row["basis"].items()
        if key not in ("external_dependencies", "external_input_digest")
    }
    return row.get("estimates", {}) if digest(previous) == digest(local_basis) else {}


def capture_network(
    connection: Connection, tenant_id: UUID, project_id: UUID, root_basis: dict[str, Any]
) -> dict[str, Any] | None:
    from app.domain.schedule_forecasts import capture_local_basis

    applications = active_applications(connection, tenant_id)
    if not any(row["successor_project_id"] == project_id for row in applications):
        return None
    # Project revisits are legal. Closure is finite; actual node cycles are rejected separately.
    projects = {project_id}
    pending = [project_id]
    while pending:
        target = pending.pop()
        for app in applications:
            if (
                app["successor_project_id"] == target
                and app["predecessor_project_id"] not in projects
            ):
                projects.add(app["predecessor_project_id"])
                pending.append(app["predecessor_project_id"])
    applications = [app for app in applications if app["successor_project_id"] in projects]
    proposals = {
        row["id"]: row
        for row in connection.execute(
            select(tables.cross_project_schedule_proposals).where(
                tables.cross_project_schedule_proposals.c.tenant_id == tenant_id,
                tables.cross_project_schedule_proposals.c.id.in_(
                    [app["proposal_id"] for app in applications]
                ),
            )
        ).mappings()
    }
    bases = {
        pid: root_basis
        if pid == project_id
        else capture_local_basis(connection, tenant_id, pid)["basis"]
        for pid in sorted(projects, key=str)
    }
    nodes, allocations, states, calendars, estimates, edges = {}, {}, {}, {}, {}, []
    mappings, roots, fingerprints = {}, {}, {}
    for pid, basis in bases.items():
        mapping = {node["node_key"]: "n:" + UUID(node["node_id"]).hex for node in basis["tasks"]}
        mappings[pid] = mapping
        fingerprints[str(pid)] = {
            "baseline_id": basis["baseline_id"],
            "local_basis_digest": digest(basis),
        }
        if pid == project_id:
            roots = {value: key for key, value in mapping.items()}
        calendars.update(basis["calendars"])
        for node in basis["plan"]["nodes"]:
            key = mapping[node["node_key"]]
            # No partner titles, people, reasons or source document content enter this network.
            nodes[key] = {
                "node_key": key,
                "title": "排程节点",
                "discipline": "shared",
                "owner_user_id": None,
                "receiver_user_id": None,
                "expected_output": "已批准节点输出",
                "completion_criteria": "原节点完成判据",
                "effort_hours": node["effort_hours"],
                "waiting_days": node["waiting_days"],
                "estimate_basis": "已批准排程估算" if node["effort_hours"] is not None else None,
            }
            allocation = basis["allocations"][node["node_key"]]
            allocations[key] = {**allocation, "allocation_basis": "固定排程投入"}
        for state in basis["tasks"]:
            key = mapping[state["node_key"]]
            states[key] = {
                name: state[name]
                for name in ("node_id", "node_kind", "status", "actual_start", "actual_finish")
            }
            states[key].update(
                {
                    name: state[name]
                    for name in (
                        "actual_start_event",
                        "actual_finish_event",
                        "actual_observation",
                        "actual_correction",
                    )
                    if name in state
                }
            )
            states[key].update(
                node_key=key,
                input_unknown=["前置业务依据存在缺项"] if state.get("input_unknown") else [],
                input_warnings=["前置业务当前接收依据存在差异"]
                if state.get("input_warnings")
                else [],
            )
        for edge in basis["plan"]["dependencies"]:
            edges.append(
                {
                    **edge,
                    "predecessor": mapping[edge["predecessor"]],
                    "successor": mapping[edge["successor"]],
                }
            )
        if pid != project_id:
            supplied = latest_human_estimates(connection, tenant_id, pid, basis)
            for key, estimate in supplied.items():
                if key in mapping:
                    estimates[mapping[key]] = {
                        **estimate,
                        "basis": "前置项目当前进展下的人工剩余估计",
                    }
            fingerprints[str(pid)]["estimates_digest"] = digest(supplied)
    shared = []
    for app in applications:
        proposal = proposals[app["proposal_id"]]
        left, right = "n:" + app["predecessor_node_id"].hex, "n:" + app["successor_node_id"].hex
        current = (
            left in nodes
            and right in nodes
            and all(
                bases[app[f"{side}_project_id"]]["baseline_id"]
                == str(proposal[f"{side}_baseline_id"])
                for side in ("predecessor", "successor")
            )
        )
        if current:
            edges.append(
                {
                    "predecessor": left,
                    "successor": right,
                    "relation": proposal["relation"],
                    "lag": str(proposal["lag"]),
                    "lag_unit": proposal["lag_unit"],
                }
            )
        elif right in states:
            states[right]["input_unknown"].append("跨项目依赖的基线或节点已变化，须重新由双方确认")
        if app["successor_project_id"] == project_id:
            shared.append(
                {
                    "application_id": str(app["id"]),
                    "proposal_id": str(proposal["id"]),
                    "predecessor_project_id": str(app["predecessor_project_id"]),
                    "predecessor_node_id": str(app["predecessor_node_id"]),
                    "successor_node_id": str(app["successor_node_id"]),
                    "relation": proposal["relation"],
                    "lag": str(proposal["lag"]),
                    "lag_unit": proposal["lag_unit"],
                    "is_current": current,
                    "source_baseline_id": bases[app["predecessor_project_id"]]["baseline_id"],
                    "source_point": "start" if proposal["relation"][0] == "s" else "finish",
                    "target_point": "start" if proposal["relation"][1] == "s" else "finish",
                }
            )
    # Discard unrelated branches in upstream projects. They cannot affect root-node times.
    incoming: dict[str, set[str]] = {}
    for edge in edges:
        incoming.setdefault(edge["successor"], set()).add(edge["predecessor"])
    required, pending_keys = set(roots), list(roots)
    while pending_keys:
        for parent in incoming.get(pending_keys.pop(), ()):
            if parent not in required:
                required.add(parent)
                pending_keys.append(parent)
    return {
        "version": "schedule_network.v1",
        "root_keys": roots,
        "nodes": {key: nodes[key] for key in sorted(required)},
        "states": {key: states[key] for key in sorted(required)},
        "allocations": {key: allocations[key] for key in sorted(required)},
        "calendars": calendars,
        "estimates": {key: value for key, value in estimates.items() if key in required},
        "edges": [
            edge
            for edge in edges
            if edge["successor"] in required and edge["predecessor"] in required
        ],
        "shared": shared,
        "fingerprints": fingerprints,
    }


def project_sources(
    network: dict[str, Any],
    root_basis: dict[str, Any],
    as_of: datetime,
    root_estimates: dict[str, Any],
) -> list[dict[str, Any]]:
    estimates = {
        **network["estimates"],
        **{
            key: root_estimates[local]
            for key, local in network["root_keys"].items()
            if local in root_estimates
        },
    }
    definition = {
        **root_basis["plan"],
        "nodes": list(network["nodes"].values()),
        "dependencies": network["edges"],
    }
    allocations = {
        key: NodeAllocation(
            calendar_key=value["calendar_version_id"],
            parallel_units=value["parallel_units"],
            allocation_basis=value["allocation_basis"],
            not_before=value.get("not_before"),
        )
        for key, value in network["allocations"].items()
    }
    result = calculate_forecast(
        PlanCandidate.model_validate(definition),
        as_of,
        {
            key: CalendarDefinition.model_validate(value)
            for key, value in network["calendars"].items()
        },
        allocations,
        network["states"],
        estimates,
    )
    calculated = {row["node_key"]: row for row in result["nodes"]}
    input_digest = digest({"network": network, "root_estimates": root_estimates})
    projections = []
    for edge in network["shared"]:
        key = "n:" + UUID(edge["predecessor_node_id"]).hex
        state, prediction = network["states"].get(key), calculated.get(key)
        actual = (
            state.get("actual_" + edge["source_point"]) if state and edge["is_current"] else None
        )
        anchor = actual or (
            prediction.get(edge["source_point"]) if prediction and edge["is_current"] else None
        )
        projections.append(
            {
                **edge,
                "anchor": anchor,
                "anchor_kind": "actual" if actual else "forecast" if anchor else None,
                "forecast_ref": {
                    "record_id": None,
                    "version": None,
                    "network_input_digest": input_digest,
                    "as_of": as_of.isoformat(),
                    "algorithm_version": result["algorithm_version"],
                }
                if anchor and not actual
                else None,
                "source_observation_id": (state.get("actual_observation") or {}).get("id")
                if state
                else None,
                "source_event_row_id": state.get("actual_" + edge["source_point"] + "_event")
                if state
                else None,
                "unknown_reason": None
                if anchor
                else "跨项目依赖的基线或节点已变化，须重新申请并由双方确认"
                if not edge["is_current"]
                else "跨项目前置缺少实际进展或当前剩余估计",
            }
        )
    return projections


def public_forecast(row: Any) -> dict[str, Any]:
    from app.domain.product_workspace import _plain

    value = _plain(row)
    if "inputs" in value:
        value["inputs"] = {key: item for key, item in value["inputs"].items() if key != "network"}
    return value


def scenario_sources(
    network: dict[str, Any] | None,
    original: dict[str, Any],
    plan: Any,
    states: dict[str, Any],
    allocations: dict[str, Any],
    calendars: dict[str, Any],
    ids: dict[str, str],
    estimates: dict[str, Any],
    as_of: datetime,
) -> list[dict[str, Any]]:
    """Re-evaluate a proposed root plan against its frozen upstream node network."""
    from copy import deepcopy

    if not network:
        return list(original.get("external_dependencies", []))
    proposed = deepcopy(network)
    old_keys = set(proposed["root_keys"])
    by_local = {key: "n:" + UUID(node_id).hex for node_id, key in ids.items()}
    new_keys = set(by_local.values())
    removed = old_keys - new_keys
    cross_edges = [
        edge
        for edge in proposed["edges"]
        if (edge["predecessor"] in old_keys) != (edge["successor"] in old_keys)
    ]
    if any(edge["predecessor"] in removed or edge["successor"] in removed for edge in cross_edges):
        raise ValueError("情景不能直接移除跨项目依赖仍引用的节点，请先完成双方关系调整")
    proposed["edges"] = [
        edge
        for edge in proposed["edges"]
        if not (edge["predecessor"] in old_keys and edge["successor"] in old_keys)
    ]
    for collection in ("nodes", "states", "allocations", "estimates"):
        for key in old_keys:
            proposed[collection].pop(key, None)
    proposed["root_keys"] = {global_key: local for local, global_key in by_local.items()}
    proposed["calendars"].update(calendars)
    for node in plan.nodes:
        local, key = node.node_key, by_local[node.node_key]
        proposed["nodes"][key] = {**node.model_dump(mode="json"), "node_key": key}
        proposed["states"][key] = {**states[local], "node_key": key, "node_id": str(UUID(key[2:]))}
        allocation = allocations[local]
        proposed["allocations"][key] = {
            "calendar_version_id": allocation.calendar_key,
            "parallel_units": str(allocation.parallel_units),
            "allocation_basis": allocation.allocation_basis,
            "not_before": allocation.not_before.isoformat() if allocation.not_before else None,
        }
    proposed["edges"].extend(
        {
            **edge.model_dump(mode="json"),
            "predecessor": by_local[edge.predecessor],
            "successor": by_local[edge.successor],
        }
        for edge in plan.dependencies
    )
    return project_sources(
        proposed, {**original, "plan": plan.model_dump(mode="json")}, as_of, estimates
    )


def public_scenario(row: Any) -> dict[str, Any]:
    from app.domain.product_workspace import _plain

    value = _plain(row)
    if "snapshot" in value:
        value["snapshot"] = {
            key: item for key, item in value["snapshot"].items() if key != "network"
        }
    return value
