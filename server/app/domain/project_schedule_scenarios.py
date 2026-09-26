"""Immutable what-if schedules spanning registered business nodes, without baseline writes."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    Contract,
    Digest,
    Key,
    PlanCandidate,
    PlanDependency,
    PlanNode,
    Quantity,
    Text,
)
from app.db.schema import tables
from app.domain.plan_scheduling import NodeAllocation
from app.domain.product_workspace import (
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.domain.schedule_forecast_engine import ResourcePlacer, calculate_forecast
from app.domain.schedule_forecasts import RemainingEstimate, capture_basis
from app.domain.schedule_network import public_scenario, scenario_sources
from app.domain.schedule_node_state import additional_state
from app.domain.schedule_nodes import list_nodes
from app.domain.working_time import CalendarDefinition
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class AdditionalNode(Contract):
    node_id: UUID
    discipline: Key
    owner_user_id: UUID | None = None
    receiver_user_id: UUID | None = None
    expected_output: Text
    completion_criteria: Text
    effort_hours: Quantity | None = Field(ge=0)
    waiting_days: int = Field(ge=0, le=36600)
    estimate_basis: Text
    parallel_units: Quantity = Field(gt=0, le=1000)
    allocation_basis: Text
    not_before: AwareDatetime | None = None


class ScenarioEdge(Contract):
    predecessor_node_id: UUID
    successor_node_id: UUID
    relation: Literal["fs", "ss", "ff", "sf"]
    lag: Quantity
    lag_unit: Literal["working_hours", "calendar_days"]


class CertificationReplacement(Contract):
    previous_node_id: UUID
    replacement_node_id: UUID


class NodeResponsibilityChange(Contract):
    node_id: UUID
    owner_user_id: UUID
    receiver_user_id: UUID
    reason: Text


class ProjectScenarioDraft(Contract):
    request_id: UUID
    expected_basis_digest: Digest
    title: Text
    reason: Text
    additional_nodes: tuple[AdditionalNode, ...] = Field(default=(), max_length=1000)
    certification_replacements: tuple[CertificationReplacement, ...] = Field(
        default=(), max_length=1000
    )
    responsibility_changes: tuple[NodeResponsibilityChange, ...] = Field(
        default=(), max_length=1000
    )
    dependencies: tuple[ScenarioEdge, ...] = Field(max_length=5000)
    remaining_estimates: dict[UUID, RemainingEstimate] = Field(
        default_factory=dict, max_length=2000
    )

    @model_validator(mode="after")
    def unique_nodes(self) -> Self:
        if len({node.node_id for node in self.additional_nodes}) != len(self.additional_nodes):
            raise ValueError("新增节点不能重复")
        if len({item.previous_node_id for item in self.certification_replacements}) != len(
            self.certification_replacements
        ) or len({item.replacement_node_id for item in self.certification_replacements}) != len(
            self.certification_replacements
        ):
            raise ValueError("认证节点替换须一一对应，不能重复")
        if len({item.node_id for item in self.responsibility_changes}) != len(
            self.responsibility_changes
        ):
            raise ValueError("同一节点只能调整一次责任")
        return self


def certification_replacement_options(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    bound = {node["node_id"] for node in snapshot["original"]["tasks"]}
    old = {
        node["source_id"]: node
        for node in snapshot["nodes"]
        if node["node_kind"] == "certification" and node["id"] in bound
    }
    return [
        {
            "previous_node_id": old[node["replaces_certification_id"]]["id"],
            "replacement_node_id": node["id"],
            "previous_title": old[node["replaces_certification_id"]]["title"],
            "replacement_title": node["title"],
        }
        for node in snapshot["nodes"]
        if node["node_kind"] == "certification"
        and node["id"] not in bound
        and node.get("replaces_certification_id") in old
    ]


def scenario_basis(
    connection: Connection, context: AuthContext, project_id: UUID
) -> dict[str, Any]:
    original = capture_basis(connection, context.tenant.id, project_id)
    nodes = list_nodes(connection, context, project_id)
    calendar_ids = {UUID(node["calendar_version_id"]) for node in nodes}
    calendars = {
        str(row["id"]): row["definition"]
        for row in connection.execute(
            select(tables.work_calendar_versions).where(
                tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                tables.work_calendar_versions.c.id.in_(calendar_ids),
            )
        ).mappings()
    }
    body = {"original": original["basis"], "nodes": nodes, "calendars": calendars}
    stable = {
        **body,
        "original": {
            key: value for key, value in body["original"].items() if key != "external_dependencies"
        },
    }
    return {
        "snapshot": body,
        "network": original.get("network"),
        "basis_digest": digest(stable),
        "titles": original["titles"],
    }


def base_edges(basis: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {node["node_key"]: node["node_id"] for node in basis["original"]["tasks"]}
    return [
        {
            "predecessor_node_id": ids[edge["predecessor"]],
            "successor_node_id": ids[edge["successor"]],
            "relation": edge["relation"],
            "lag": edge["lag"],
            "lag_unit": edge["lag_unit"],
        }
        for edge in basis["original"]["plan"]["dependencies"]
    ]


class ProjectScheduleScenarioService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project_id: UUID, target_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            captured = scenario_basis(connection, context, project_id)
            base = captured["snapshot"]["original"]
            bound = {node["node_id"] for node in base["tasks"]}
            plan_by_key = {node["node_key"]: node for node in base["plan"]["nodes"]}
            table = tables.project_schedule_scenarios
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(31)
                ).mappings()
            )
            if target_id and not any(row["id"] == target_id for row in rows[:30]):
                target = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project_id,
                            table.c.id == target_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if target is None:
                    raise ProductWorkError("所选历史情景不属于此项目")
                rows = [target, *[row for row in rows if row["id"] != target_id]]
            prep = tables.project_resource_schedule_preparations
            origins = {
                row["scenario_id"]: _plain(dict(row))
                for row in connection.execute(
                    select(prep).where(
                        prep.c.tenant_id == context.tenant.id,
                        prep.c.project_id == project_id,
                        prep.c.scenario_id.in_([r["id"] for r in rows[:30]]),
                    )
                ).mappings()
            }
            members = select(tables.project_members.c.user_id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
            )
            people = list(
                connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name)
                    .where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.is_active.is_(True),
                        tables.users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                        or_(
                            tables.users.c.role.in_(("owner", "admin")),
                            tables.users.c.id.in_(members),
                        ),
                    )
                    .order_by(tables.users.c.display_name)
                    .limit(1000)
                ).mappings()
            )
            return {
                "people": [_plain(row) for row in people],
                "basis_digest": captured["basis_digest"],
                "base_nodes": [
                    {
                        **node,
                        "title": captured["titles"][node["node_key"]],
                        "owner_user_id": plan_by_key[node["node_key"]].get("owner_user_id"),
                        "receiver_user_id": plan_by_key[node["node_key"]].get("receiver_user_id"),
                    }
                    for node in base["tasks"]
                ],
                "additional_nodes": [
                    node for node in captured["snapshot"]["nodes"] if node["id"] not in bound
                ],
                "dependencies": base_edges(captured["snapshot"]),
                "certification_replacement_options": certification_replacement_options(
                    captured["snapshot"]
                ),
                "items": [
                    {
                        **public_scenario(row),
                        "resource_date_origin": origins.get(row["id"]),
                        "basis_is_current": row["basis_digest"] == captured["basis_digest"],
                    }
                    for row in rows[:30]
                ],
                "has_more": len(rows) > 30,
                "can_evaluate": is_allowed(context.user.role, Action.PROJECT_EDIT)
                and project["status"] not in ("completed", "archived"),
            }

    def evaluate(
        self, context: AuthContext, project_id: UUID, draft: ProjectScenarioDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as connection:
                return self.evaluate_in_connection(connection, context, project_id, draft)
        except IntegrityError as error:
            raise ProductWorkError("排程情景未保存，请刷新后核对节点和基线") from error

    def evaluate_in_connection(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        draft: ProjectScenarioDraft,
        *,
        calculation_as_of: datetime | None = None,
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        project = _project(connection, context, project_id, write=True)
        table = tables.project_schedule_scenarios
        signing = draft.model_dump(mode="json")
        if "responsibility_changes" not in draft.model_fields_set:
            signing.pop("responsibility_changes")
        if calculation_as_of is not None:
            signing["fixed_calculation_as_of"] = calculation_as_of.isoformat()
        fingerprint = digest({"project_id": str(project_id), **signing})
        prior = (
            connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.actor_user_id == context.user.id,
                    table.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("请求编号已用于另一份排程情景")
            return public_scenario(prior)
        if project["status"] in ("completed", "archived"):
            raise ProductWorkError("项目已结束")
        captured = scenario_basis(connection, context, project_id)
        if draft.expected_basis_digest != captured["basis_digest"]:
            raise ProductWorkError("节点、实际进展或基线依据已变化，请刷新后重新比较")
        snapshot = {**captured["snapshot"], "network": captured.get("network")}
        original = snapshot["original"]
        original_plan = PlanCandidate.model_validate(original["plan"])
        plan_nodes = list(original_plan.nodes)
        states = {node["node_key"]: node for node in original["tasks"]}
        ids = {node["node_id"]: node["node_key"] for node in original["tasks"]}
        allocations = {
            key: NodeAllocation(
                calendar_key=value["calendar_version_id"],
                parallel_units=value["parallel_units"],
                allocation_basis=value["allocation_basis"],
                not_before=value.get("not_before"),
            )
            for key, value in original["allocations"].items()
        }
        choices = {node["id"]: node for node in snapshot["nodes"]}
        allowed_replacements = {
            (item["previous_node_id"], item["replacement_node_id"])
            for item in certification_replacement_options(snapshot)
        }
        replacements = {
            str(item.previous_node_id): str(item.replacement_node_id)
            for item in draft.certification_replacements
        }
        additions = {str(item.node_id) for item in draft.additional_nodes}
        if any(
            (previous, replacement) not in allowed_replacements or replacement not in additions
            for previous, replacement in replacements.items()
        ):
            raise ProductWorkError("替换须选择同项目已关联原证书的新认证节点，并将其纳入情景")
        removed_keys = {ids[previous] for previous in replacements}
        plan_nodes = [node for node in plan_nodes if node.node_key not in removed_keys]
        for previous in replacements:
            key = ids.pop(previous)
            states.pop(key)
            allocations.pop(key)
        from app.domain.schedule_responsibility_changes import revise_responsibilities

        plan_nodes, responsibility_changes = revise_responsibilities(
            connection,
            context,
            project_id,
            plan_nodes,
            states,
            ids,
            draft.responsibility_changes,
        )
        for item in draft.additional_nodes:
            node = choices.get(str(item.node_id))
            if node is None or str(item.node_id) in ids:
                raise ProductWorkError("新增节点须为当前项目可访问且未纳入原计划的实际节点")
            if node["node_kind"] == "milestone" and (
                item.effort_hours != 0 or item.waiting_days != 0
            ):
                raise ProductWorkError("独立里程碑为零工时检查点；持续工作请使用业务任务")
            for person in (item.owner_user_id, item.receiver_user_id):
                if person:
                    _person(connection, context, project_id, person)
            key = "n_" + item.node_id.hex
            ids[str(item.node_id)] = key
            plan_nodes.append(
                PlanNode(
                    node_key=key,
                    title=node["title"],
                    discipline=item.discipline,
                    owner_user_id=item.owner_user_id,
                    receiver_user_id=item.receiver_user_id,
                    expected_output=item.expected_output,
                    completion_criteria=item.completion_criteria,
                    effort_hours=item.effort_hours,
                    waiting_days=item.waiting_days,
                    estimate_basis=item.estimate_basis,
                )
            )
            states[key] = {"node_key": key, **additional_state(node)}
            allocations[key] = NodeAllocation(
                calendar_key=node["calendar_version_id"],
                parallel_units=item.parallel_units,
                allocation_basis=item.allocation_basis,
                not_before=item.not_before,
            )
        if any(str(key) not in ids for key in draft.remaining_estimates):
            raise ProductWorkError("剩余估计只能引用本情景中的节点")
        proposed = {
            (
                edge.predecessor_node_id,
                edge.successor_node_id,
                edge.relation,
                edge.lag,
                edge.lag_unit,
            )
            for edge in draft.dependencies
        }
        for edge in base_edges(snapshot):
            if (
                edge["predecessor_node_id"] in replacements
                or edge["successor_node_id"] in replacements
            ):
                transferred = {
                    **edge,
                    "predecessor_node_id": replacements.get(
                        edge["predecessor_node_id"], edge["predecessor_node_id"]
                    ),
                    "successor_node_id": replacements.get(
                        edge["successor_node_id"], edge["successor_node_id"]
                    ),
                }
                if (
                    UUID(transferred["predecessor_node_id"]),
                    UUID(transferred["successor_node_id"]),
                    transferred["relation"],
                    Decimal(transferred["lag"]),
                    transferred["lag_unit"],
                ) not in proposed:
                    raise ProductWorkError("重新认证须完整转接原节点的前后依赖及滞后条件")
        edges = []
        for proposed_edge in draft.dependencies:
            if (
                str(proposed_edge.predecessor_node_id) not in ids
                or str(proposed_edge.successor_node_id) not in ids
            ):
                raise ProductWorkError("依赖两端必须已纳入本情景；跨项目关系须经双方授权接入")
            edges.append(
                PlanDependency(
                    predecessor=ids[str(proposed_edge.predecessor_node_id)],
                    successor=ids[str(proposed_edge.successor_node_id)],
                    relation=proposed_edge.relation,
                    lag=proposed_edge.lag,
                    lag_unit=proposed_edge.lag_unit,
                )
            )
        scenario_id = uuid4()
        plan = PlanCandidate.model_validate(
            {
                **original_plan.model_dump(mode="json"),
                "id": str(scenario_id),
                "version": 1,
                "nodes": [node.model_dump(mode="json") for node in plan_nodes],
                "dependencies": [edge.model_dump(mode="json") for edge in edges],
            }
        )
        now = calculation_as_of if calculation_as_of is not None else datetime.now(UTC)
        supplied = {
            ids[str(key)]: value.model_dump(mode="json")
            for key, value in draft.remaining_estimates.items()
        }
        external = scenario_sources(
            snapshot.get("network"),
            snapshot["original"],
            plan,
            states,
            allocations,
            snapshot["calendars"],
            ids,
            supplied,
            now,
        )
        result = calculate_forecast(
            plan,
            now,
            {
                key: CalendarDefinition.model_validate(value)
                for key, value in snapshot["calendars"].items()
            },
            allocations,
            states,
            {
                ids[str(key)]: value.model_dump(mode="json")
                for key, value in draft.remaining_estimates.items()
            },
            external,
        )
        for node in result["nodes"]:
            node["node_id"] = next(
                node_id for node_id, key in ids.items() if key == node["node_key"]
            )
            if node.get("origin") == "approved_initial_estimate":
                node["origin"] = "scenario_estimate"
        previous_edges = {digest(edge): edge for edge in base_edges(snapshot)}
        proposed_edges = {
            digest(edge.model_dump(mode="json")): edge.model_dump(mode="json")
            for edge in draft.dependencies
        }
        changes = {
            "responsibility_changes": responsibility_changes,
            "certification_replacements": [
                {
                    **item.model_dump(mode="json"),
                    "previous_title": choices[str(item.previous_node_id)]["title"],
                    "replacement_title": choices[str(item.replacement_node_id)]["title"],
                }
                for item in draft.certification_replacements
            ],
            "removed_nodes": list(replacements),
            "added_nodes": [str(node.node_id) for node in draft.additional_nodes],
            "added_dependencies": [
                edge for key, edge in proposed_edges.items() if key not in previous_edges
            ],
            "removed_dependencies": [
                edge for key, edge in previous_edges.items() if key not in proposed_edges
            ],
        }
        result.update(capacity_status="not_checked", changes=changes, applied=False)
        row = (
            connection.execute(
                table.insert()
                .values(
                    id=scenario_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    baseline_id=UUID(original["baseline_id"]),
                    title=draft.title,
                    reason=draft.reason,
                    inputs=draft.model_dump(mode="json"),
                    snapshot=snapshot,
                    basis_digest=captured["basis_digest"],
                    plan=plan.model_dump(mode="json"),
                    result=result,
                    result_digest=digest(result),
                    actor_user_id=context.user.id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        connection.execute(
            tables.project_schedule_scenario_nodes.insert(),
            [
                {
                    "tenant_id": context.tenant.id,
                    "project_id": project_id,
                    "scenario_id": scenario_id,
                    "node_id": UUID(node_id),
                    "node_key": key,
                }
                for node_id, key in ids.items()
            ],
        )
        EventAuditWriter(
            connection,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"project-scenario:{scenario_id}",
                event_type="PROJECT_SCHEDULE_SCENARIO_EVALUATED",
                source="planning_service",
                entity_id=scenario_id,
                payload={"scenario_id": str(scenario_id), "complete": result["complete"]},
            ),
            AuditDraft(
                action="project_schedule_scenario.evaluate",
                after_snapshot={
                    "id": str(scenario_id),
                    "result_digest": digest(result),
                    "changes": changes,
                },
                context={"reason": draft.reason},
            ),
        )
        return public_scenario(row)


def calculate_scenario_at(
    scenario: Any, as_of: datetime, resource_placer: ResourcePlacer | None = None
) -> dict[str, Any]:
    """Recompute a fixed scenario's assumptions at an explicit preparation time."""
    draft = ProjectScenarioDraft.model_validate(scenario["inputs"])
    snapshot = scenario["snapshot"]
    original = snapshot["original"]
    plan = PlanCandidate.model_validate(scenario["plan"])
    keys = {node.node_key for node in plan.nodes}
    states = {node["node_key"]: node for node in original["tasks"] if node["node_key"] in keys}
    ids = {node["node_id"]: node["node_key"] for node in scenario["result"]["nodes"]}
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    allocations = {
        key: NodeAllocation(
            calendar_key=value["calendar_version_id"],
            parallel_units=value["parallel_units"],
            allocation_basis=value["allocation_basis"],
            not_before=value.get("not_before"),
        )
        for key, value in original["allocations"].items()
        if key in keys
    }
    for item in draft.additional_nodes:
        node = nodes[str(item.node_id)]
        key = ids[str(item.node_id)]
        states[key] = {"node_key": key, **additional_state(node)}
        allocations[key] = NodeAllocation(
            calendar_key=node["calendar_version_id"],
            parallel_units=item.parallel_units,
            allocation_basis=item.allocation_basis,
            not_before=item.not_before,
        )
    supplied = {
        ids[str(key)]: estimate.model_dump(mode="json")
        for key, estimate in draft.remaining_estimates.items()
    }
    external = scenario_sources(
        snapshot.get("network"),
        original,
        plan,
        states,
        allocations,
        snapshot["calendars"],
        ids,
        supplied,
        as_of,
    )
    result = calculate_forecast(
        plan,
        as_of,
        {
            key: CalendarDefinition.model_validate(value)
            for key, value in snapshot["calendars"].items()
        },
        allocations,
        states,
        {
            ids[str(key)]: estimate.model_dump(mode="json")
            for key, estimate in draft.remaining_estimates.items()
        },
        external,
        resource_placer,
    )
    by_key = {key: node_id for node_id, key in ids.items()}
    for node in result["nodes"]:
        node["node_id"] = by_key[node["node_key"]]
        if node.get("origin") == "approved_initial_estimate":
            node["origin"] = "scenario_estimate"
    result.update(
        capacity_status="not_checked", changes=scenario["result"]["changes"], applied=False
    )
    return result
