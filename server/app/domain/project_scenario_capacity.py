"""Capacity evidence for fixed multi-object schedule scenarios and current reservations."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.forecast_capacity import reservation_differences
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.project_schedule_scenarios import scenario_basis
from app.domain.resource_capacity import CapacityCheckDraft, evaluate_capacity
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def get_scenario(
    connection: Connection, context: AuthContext, project_id: UUID, scenario_id: UUID
) -> Any:
    row = (
        connection.execute(
            select(tables.project_schedule_scenarios).where(
                tables.project_schedule_scenarios.c.tenant_id == context.tenant.id,
                tables.project_schedule_scenarios.c.project_id == project_id,
                tables.project_schedule_scenarios.c.id == scenario_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("计划情景不存在或不属于当前项目")
    return row


def evaluate_scenario_capacity(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    scenario: Any,
    draft: CapacityCheckDraft,
    *,
    result_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured = scenario_basis(connection, context, project_id)
    if captured["basis_digest"] != scenario["basis_digest"]:
        raise ProductWorkError("情景依据或实际进展已变化，请重新计算情景后检查容量")
    mapping = dict(
        connection.execute(
            select(
                tables.project_schedule_scenario_nodes.c.node_id,
                tables.project_schedule_scenario_nodes.c.node_key,
            ).where(
                tables.project_schedule_scenario_nodes.c.tenant_id == context.tenant.id,
                tables.project_schedule_scenario_nodes.c.project_id == project_id,
                tables.project_schedule_scenario_nodes.c.scenario_id == scenario["id"],
            )
        )
        .tuples()
        .all()
    )
    fixed_result = result_override if result_override is not None else scenario["result"]
    all_nodes = fixed_result["nodes"]
    if set(mapping.values()) != {node["node_key"] for node in all_nodes}:
        raise ProductWorkError("情景节点映射不完整")
    nodes = [node for node in all_nodes if not node.get("actual_finish")]
    projection = {
        **fixed_result,
        "nodes": [
            {
                **node,
                "start": node["remaining_work_start"],
                "work_minutes": node["remaining_work_minutes"],
            }
            for node in nodes
        ],
    }
    from app.domain.resource_schedule_preparations import capacity_for_origin

    result = capacity_for_origin(connection, context, project_id, scenario, draft, projection)
    if result is None:
        result = evaluate_capacity(
            connection,
            context,
            {"id": scenario["id"], "result": projection, "result_digest": digest(projection)},
            draft,
            covered_project_id=project_id,
            covered_node_keys=mapping,
        )
    result["project_scenario_id"] = result.pop("scenario_id")
    result["remaining_projection_digest"] = result.pop("scenario_digest")
    result["schedule_as_of"] = fixed_result["as_of"]
    result["reservation_match_policy"] = "same_project_node_resource_union"
    uncertain = {key for issue in result["unknown"] for key in issue["node_key"].split(", ")}
    result["reservation_differences"] = reservation_differences(
        connection,
        context.tenant.id,
        project_id,
        result,
        datetime.fromisoformat(fixed_result["as_of"]),
        {
            node["node_key"]
            for node in nodes
            if node["node_key"] in uncertain
            or node.get("remaining_work_start") is None
            or node.get("remaining_work_minutes") is None
            or (
                not draft.demands.get(node["node_key"])
                and node["node_key"] not in draft.no_resource_reasons
            )
        },
        node_keys=mapping,
    )
    result["baseline_changed"] = False
    return result


class ProjectScenarioCapacityService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, context: AuthContext, project_id: UUID, scenario_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            scenario = get_scenario(connection, context, project_id, scenario_id)
            table = tables.project_scenario_capacity_checks
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.scenario_id == scenario_id,
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(51)
                ).mappings()
            )
            from app.domain.formal_schedule import current_plan

            formal = current_plan(connection, context.tenant.id, project_id)
            if formal is None:
                raise ProductWorkError("缺少当前正式计划")
            origin, saved = (
                tables.project_resource_schedule_preparations,
                tables.project_resource_schedules,
            )
            original_inputs = connection.execute(
                select(saved.c.inputs)
                .join(
                    origin,
                    (origin.c.tenant_id == saved.c.tenant_id)
                    & (origin.c.schedule_id == saved.c.id),
                )
                .where(
                    origin.c.tenant_id == context.tenant.id,
                    origin.c.project_id == project_id,
                    origin.c.scenario_id == scenario_id,
                )
            ).scalar_one_or_none()
            initial = original_inputs if original_inputs is not None else formal["capacity_inputs"]
            remaining = {
                node["node_key"]
                for node in scenario["result"]["nodes"]
                if not node.get("actual_finish")
            }
            return {
                "items": [_plain(row) for row in rows[:50]],
                "has_more": len(rows) > 50,
                "initial_demands": {
                    key: value for key, value in initial["demands"].items() if key in remaining
                },
                "initial_no_resource_reasons": {
                    key: value
                    for key, value in initial.get("no_resource_reasons", {}).items()
                    if key in remaining
                },
            }

    def check(
        self, context: AuthContext, project_id: UUID, scenario_id: UUID, draft: CapacityCheckDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self.check_in_connection(connection, context, project_id, scenario_id, draft)

    def check_in_connection(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        scenario_id: UUID,
        draft: CapacityCheckDraft,
    ) -> dict[str, Any]:
        _project(connection, context, project_id, write=True)
        scenario = get_scenario(connection, context, project_id, scenario_id)
        table = tables.project_scenario_capacity_checks
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "scenario_id": str(scenario_id),
                **draft.model_dump(mode="json"),
            }
        )
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
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("请求编号已用于另一项情景容量检查")
            return _plain(prior)
        result = evaluate_scenario_capacity(connection, context, project_id, scenario, draft)
        row = (
            connection.execute(
                table.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    inputs=draft.model_dump(mode="json"),
                    result=result,
                    result_digest=digest(result),
                    scenario_basis_digest=scenario["basis_digest"],
                    created_by_user_id=context.user.id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        capacity_ids = sorted(
            {
                demand.capacity_version_id
                for demands in draft.demands.values()
                for demand in demands
            },
            key=str,
        )
        if capacity_ids:
            connection.execute(
                tables.project_scenario_capacity_versions.insert(),
                [
                    {
                        "tenant_id": context.tenant.id,
                        "check_id": row["id"],
                        "capacity_version_id": capacity_id,
                    }
                    for capacity_id in capacity_ids
                ],
            )
        EventAuditWriter(
            connection,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"project-scenario-capacity:{row['id']}",
                event_type="PROJECT_SCENARIO_CAPACITY_CHECKED",
                source="planning_service",
                entity_id=row["id"],
                payload={"scenario_id": str(scenario_id), "check_id": str(row["id"])},
            ),
            AuditDraft(
                action="project_schedule_scenario.capacity_check",
                after_snapshot={
                    "id": str(row["id"]),
                    "scenario_id": str(scenario_id),
                    "result_digest": row["result_digest"],
                    "status": result["status"],
                },
            ),
        )
        return _plain(row)
