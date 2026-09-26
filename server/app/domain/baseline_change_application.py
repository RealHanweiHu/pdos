"""Independently apply an exact approved project baseline in one transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Digest,
    NodeTime,
    ScopeRef,
    SourceRef,
    Text,
    TimeRecord,
    TimeWindow,
)
from app.db.schema import tables
from app.domain.baseline_changes import (
    _event,
    approval_blockers,
    latest_baseline,
    latest_policy,
    responsibility_gaps,
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
from app.domain.resource_reservations import _project
from app.domain.schedule_forecasts import automatic_forecast
from app.domain.task_dependency_graph import dependency_graph_has_cycle


class BaselineApply(Contract):
    request_id: UUID
    expected_digest: Digest
    decision_id: UUID
    reason: Text


@dataclass
class BaselineApplicationReady:
    connection: Connection
    transaction: Any
    tenant_id: UUID
    actor_user_id: UUID
    project_id: UUID
    change_id: UUID
    command: BaselineApply
    values: dict[str, Any]
    consumed: bool = False


class BaselineApplicationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def apply(
        self, context: AuthContext, project_id: UUID, change_id: UUID, command: BaselineApply
    ) -> dict[str, Any]:
        try:
            return self._apply(context, project_id, change_id, command)
        except IntegrityError as error:
            raise ProductWorkError(
                "基线应用未生效：批准、基线或并发状态已变化，请刷新办理记录"
            ) from error

    def _apply(
        self, context: AuthContext, project_id: UUID, change_id: UUID, command: BaselineApply
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            prepared = self.prepare_in_connection(
                connection, context, project_id, change_id, command
            )
            if isinstance(prepared, BaselineApplicationReady):
                return self.write_prepared(connection, context, prepared)
            return prepared

    def prepare_in_connection(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        change_id: UUID,
        command: BaselineApply,
        *,
        preparation_id: UUID | None = None,
    ) -> BaselineApplicationReady | dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        tenant_id = context.tenant.id
        project = _project(connection, context, project_id, write=True)
        applications = tables.baseline_change_applications
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "change_id": str(change_id),
                **command.model_dump(mode="json"),
            }
        )
        prior = (
            connection.execute(
                select(applications).where(
                    applications.c.tenant_id == tenant_id,
                    applications.c.actor_user_id == context.user.id,
                    applications.c.request_id == command.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior is not None:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("请求编号已用于另一项基线应用")
            return _plain(prior)
        request = (
            connection.execute(
                select(tables.baseline_change_requests).where(
                    tables.baseline_change_requests.c.tenant_id == tenant_id,
                    tables.baseline_change_requests.c.project_id == project_id,
                    tables.baseline_change_requests.c.id == change_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if request is None:
            raise ProductWorkAccessError("基线变更不存在或不可访问")
        from app.domain.portfolio_execution_preparations import verify_baseline_origin

        verify_baseline_origin(
            connection, context, project_id, request, applying=True, preparation_id=preparation_id
        )
        if connection.execute(
            select(applications.c.id).where(
                applications.c.tenant_id == tenant_id,
                applications.c.change_id == change_id,
            )
        ).first():
            raise ProductWorkError("此申请已经应用，请查看原应用回执")
        if command.expected_digest != request["payload_digest"]:
            raise ProductWorkError("申请内容与所选批准版本不一致")
        decision = (
            connection.execute(
                select(tables.baseline_change_decisions).where(
                    tables.baseline_change_decisions.c.tenant_id == tenant_id,
                    tables.baseline_change_decisions.c.project_id == project_id,
                    tables.baseline_change_decisions.c.change_id == change_id,
                    tables.baseline_change_decisions.c.id == command.decision_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            decision is None
            or decision["action"] != "approve"
            or decision["approved_payload_digest"] != request["payload_digest"]
        ):
            raise ProductWorkError("此版本没有对应的实际批准记录")
        policy = latest_policy(connection, tenant_id, project_id)
        baseline = latest_baseline(connection, tenant_id, project_id)
        if (
            project["status"] not in ("approved", "active", "on_hold")
            or baseline["id"] != request["base_baseline_id"]
        ):
            raise ProductWorkError("项目状态或当前基线已变化，请重新准备变更")
        if (
            policy is None
            or policy["id"] != request["policy_id"]
            or policy["approver_user_id"] != decision["actor_user_id"]
        ):
            raise ProductWorkError("批准政策已变化，请重新准备变更")
        _person(connection, context, project_id, decision["actor_user_id"])
        # Same lock order as resource booking: project, then tenant inventory.
        # Hold through commit so the checked capacity cannot change mid-apply.
        connection.execute(select(func.cehub_project.lock_resource_inventory(tenant_id)))
        scenario = get_scenario(connection, context, project_id, request["scenario_id"])
        snapshot = request["snapshot"]
        capacity = evaluate_scenario_capacity(
            connection,
            context,
            project_id,
            scenario,
            CapacityCheckDraft.model_validate(snapshot["capacity_inputs"]),
            result_override=snapshot["result"],
        )
        if digest(capacity) != digest(snapshot["capacity"]):
            raise ProductWorkError("容量版本或预约已变化，请重新准备并审阅")
        blockers = approval_blockers(
            snapshot["result"],
            capacity,
            responsibility_gaps(connection, context, project_id, snapshot["plan"]),
        )
        if blockers:
            raise ProductWorkError("；".join(blockers[:12]))
        links = tables.project_schedule_scenario_nodes
        mapping = dict(
            connection.execute(
                select(links.c.node_key, links.c.node_id).where(
                    links.c.tenant_id == tenant_id,
                    links.c.project_id == project_id,
                    links.c.scenario_id == scenario["id"],
                )
            )
            .tuples()
            .all()
        )
        plan = snapshot["plan"]
        if set(mapping) != {node["node_key"] for node in plan["nodes"]}:
            raise ProductWorkError("获批节点与实际情景映射不完整")
        edges = tuple(
            (mapping[edge["successor"]], mapping[edge["predecessor"]])
            for edge in plan["dependencies"]
        )
        if preparation_id is None and dependency_graph_has_cycle(
            connection, tenant_id=tenant_id, project_id=project_id, formal_edges=edges
        ):
            raise ProductWorkError("拟应用排程与当前手工任务依赖构成循环，请调整后重新准备")
        from app.domain.cross_project_schedule_runtime import active_applications

        for cross in active_applications(connection, tenant_id):
            for side in ("predecessor", "successor"):
                if cross[f"{side}_project_id"] == project_id and cross[
                    f"{side}_node_id"
                ] not in set(mapping.values()):
                    raise ProductWorkError("跨项目依赖仍引用被移除节点，请先完成双方依赖调整")
        return BaselineApplicationReady(
            connection,
            connection.get_transaction(),
            tenant_id,
            context.user.id,
            project_id,
            change_id,
            command,
            dict(
                fingerprint=fingerprint,
                request=request,
                decision=decision,
                policy=policy,
                baseline=baseline,
                scenario=scenario,
                snapshot=snapshot,
                mapping=mapping,
                plan=plan,
            ),
        )

    def write_prepared(
        self,
        connection: Connection,
        context: AuthContext,
        ready: BaselineApplicationReady,
        *,
        forecast: bool = True,
    ) -> dict[str, Any]:
        if (
            ready.consumed
            or ready.connection is not connection
            or ready.transaction is None
            or not ready.transaction.is_active
            or ready.transaction is not connection.get_transaction()
            or ready.tenant_id != context.tenant.id
            or ready.actor_user_id != context.user.id
        ):
            raise ProductWorkError("基线应用须沿用同一办理事务中的完整复核")
        ready.consumed = True
        tenant_id, project_id, change_id = ready.tenant_id, ready.project_id, ready.change_id
        command, applications = ready.command, tables.baseline_change_applications
        fingerprint, request, decision, policy, baseline, scenario, snapshot, mapping, plan = (
            ready.values[k]
            for k in (
                "fingerprint",
                "request",
                "decision",
                "policy",
                "baseline",
                "scenario",
                "snapshot",
                "mapping",
                "plan",
            )
        )
        now = datetime.now(UTC)
        baseline_id = uuid4()
        application_id = uuid4()
        version = baseline["version"] + 1
        node_times = tuple(
            NodeTime(
                node_id=UUID(node["node_id"]),
                window=TimeWindow(start=node["start"], end=node["finish"]),
            )
            for node in snapshot["result"]["nodes"]
        )
        approval = ApprovalRef(
            approval_id=decision["id"],
            payload_digest=request["payload_digest"],
            policy_version=f"baseline-policy:{policy['id']}:{policy['version']}",
            approved_by_user_id=decision["actor_user_id"],
            approved_at=decision["created_at"],
        )
        record = TimeRecord(
            id=baseline_id,
            tenant_id=tenant_id,
            scope=ScopeRef(kind="project", ref_id=project_id),
            version=version,
            owner_user_id=context.user.id,
            sources=(
                SourceRef(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind="baseline_change_request",
                    ref_id=change_id,
                    digest=request["payload_digest"],
                ),
                SourceRef(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind="baseline_change_decision",
                    ref_id=decision["id"],
                ),
                SourceRef(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind="schedule_time_record",
                    ref_id=baseline["id"],
                    version=baseline["version"],
                ),
            ),
            time_kind="baseline",
            node_times=node_times,
            fact_kind="hypothesis",
            approval=approval,
            algorithm_version=snapshot["result"]["algorithm_version"],
            as_of=now,
        )
        connection.execute(
            tables.schedule_time_records.insert().values(
                id=baseline_id,
                tenant_id=tenant_id,
                project_id=project_id,
                time_kind="baseline",
                version=version,
                execution_request_id=None,
                contract=record.model_dump(mode="json"),
            )
        )
        connection.execute(
            tables.schedule_time_nodes.insert(),
            [
                dict(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    record_id=baseline_id,
                    node_id=item.node_id,
                    start=item.window.start,
                    end=item.window.end,
                )
                for item in node_times
            ],
        )
        tasks_by_node = dict(
            connection.execute(
                select(tables.schedule_nodes.c.id, tables.schedule_nodes.c.task_id).where(
                    tables.schedule_nodes.c.tenant_id == tenant_id,
                    tables.schedule_nodes.c.project_id == project_id,
                    tables.schedule_nodes.c.id.in_(mapping.values()),
                    tables.schedule_nodes.c.task_id.is_not(None),
                )
            )
            .tuples()
            .all()
        )
        for edge in plan["dependencies"]:
            child, parent = mapping[edge["successor"]], mapping[edge["predecessor"]]
            connection.execute(
                tables.schedule_plan_dependencies.insert().values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    baseline_id=baseline_id,
                    predecessor_node_id=parent,
                    successor_node_id=child,
                    relation=edge["relation"],
                    lag=Decimal(edge["lag"]),
                    lag_unit=edge["lag_unit"],
                )
            )
            if (
                edge["relation"] == "fs"
                and Decimal(edge["lag"]) >= 0
                and child in tasks_by_node
                and parent in tasks_by_node
            ):
                connection.execute(
                    tables.task_dependencies.insert().values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        baseline_id=baseline_id,
                        task_id=tasks_by_node[child],
                        depends_on_task_id=tasks_by_node[parent],
                    )
                )
        receipt = dict(
            id=str(application_id),
            status="applied",
            change_id=str(change_id),
            decision_id=str(decision["id"]),
            payload_digest=request["payload_digest"],
            baseline_id=str(baseline_id),
            baseline_version=version,
            previous_baseline_id=str(baseline["id"]),
            actor_user_id=str(context.user.id),
            reason=command.reason,
            applied_at=now.isoformat(),
            node_ids=[str(item.node_id) for item in node_times],
            responsibility_changes=snapshot["result"]["changes"].get("responsibility_changes", []),
        )
        applied = (
            connection.execute(
                applications.insert()
                .values(
                    id=application_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    change_id=change_id,
                    decision_id=decision["id"],
                    baseline_id=baseline_id,
                    previous_baseline_id=baseline["id"],
                    scenario_id=scenario["id"],
                    actor_user_id=context.user.id,
                    receipt=receipt,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                )
                .returning(applications)
            )
            .mappings()
            .one()
        )
        from app.domain.schedule_responsibility_changes import apply_task_responsibilities

        apply_task_responsibilities(connection, context, project_id, snapshot)
        _event(connection, context, project_id, change_id, "applied", receipt)
        if forecast:
            automatic_forecast(
                connection, tenant_id, project_id, context.user.id, "基线变更独立应用", now
            )
        return _plain(applied)
