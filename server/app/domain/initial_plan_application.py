"""Independently apply an approved manual initial plan in one project transaction."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Digest,
    NodeTime,
    ScheduleNode,
    ScheduleSource,
    ScopeRef,
    SourceRef,
    Text,
    TimeRecord,
    TimeWindow,
)
from app.contracts.object_operations import InitialPlanAppliedPayload
from app.contracts.planning_records import InitialPlanApplication
from app.contracts.runtime_records import OperationReceipt, TargetMapping
from app.db.schema import tables
from app.domain.plan_responsibilities import _candidate
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _policy, ensure_conversion, execution_snapshot
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

EXISTING_PLAN_NOTICE = "项目已有首版计划，本次仅生成差异；任务和批准基线保留，变更另行办理。"


class InitialPlanApply(Contract):
    request_id: UUID
    execution_request_id: UUID
    expected_digest: Digest
    reason: Text


def _existing(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.initial_plan_applications
    return (
        connection.execute(
            select(table).where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        )
        .mappings()
        .one_or_none()
    )


def _result(connection: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    _candidate(connection, context, row["candidate_id"])
    bindings = tables.task_plan_bindings
    nodes = list(
        connection.execute(
            select(bindings)
            .where(
                bindings.c.tenant_id == context.tenant.id, bindings.c.application_id == row["id"]
            )
            .order_by(bindings.c.node_key)
        ).mappings()
    )
    baseline = (
        connection.execute(
            select(tables.schedule_time_records).where(
                tables.schedule_time_records.c.tenant_id == context.tenant.id,
                tables.schedule_time_records.c.id == row["baseline_id"],
            )
        )
        .mappings()
        .one()
    )
    return {**_plain(row), "nodes": [_plain(node) for node in nodes], "baseline": _plain(baseline)}


class InitialPlanApplicationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            existing = _existing(connection, context.tenant.id, project_id)
            return {
                "application": _result(connection, context, existing) if existing else None,
                "can_apply": is_allowed(context.user.role, Action.PROJECT_EDIT),
            }

    def apply(
        self, context: AuthContext, project_id: UUID, command: InitialPlanApply
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            tenant_id = context.tenant.id
            execution = (
                connection.execute(
                    select(tables.project_execution_requests)
                    .where(
                        tables.project_execution_requests.c.tenant_id == tenant_id,
                        tables.project_execution_requests.c.project_id == project_id,
                        tables.project_execution_requests.c.id == command.execution_request_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if execution is None:
                raise ProductWorkAccessError("执行申请不存在或不属于当前项目")
            review = (
                connection.execute(
                    select(tables.initial_plan_reviews).where(
                        tables.initial_plan_reviews.c.tenant_id == tenant_id,
                        tables.initial_plan_reviews.c.id == execution["plan_review_id"],
                    )
                )
                .mappings()
                .one()
            )
            candidate = _candidate(connection, context, review["candidate_id"])
            table = tables.initial_plan_applications
            fingerprint = digest({"project_id": str(project_id), **command.model_dump(mode="json")})
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项计划应用")
                return {
                    "application": _result(connection, context, prior),
                    "already_applied": True,
                    "diff": None,
                }
            existing = _existing(connection, tenant_id, project_id)
            if existing:
                result = _result(connection, context, existing)
                if existing["execution_request_id"] == execution["id"]:
                    return {"application": result, "already_applied": True, "diff": None}
                old = {node["node_key"]: node["node_snapshot"] for node in result["nodes"]}
                new = {node["node_key"]: node for node in candidate["plan"]["nodes"]}
                return {
                    "application": result,
                    "already_applied": True,
                    "diff": {
                        "added": [new[key] for key in sorted(new.keys() - old.keys())],
                        "removed": [old[key] for key in sorted(old.keys() - new.keys())],
                        "changed": [
                            {"node_key": key, "before": old[key], "after": new[key]}
                            for key in sorted(old.keys() & new.keys())
                            if digest(old[key]) != digest(new[key])
                        ],
                        "dependencies": {
                            "before": existing["snapshot"]["plan_snapshot"]["candidate"]["plan"][
                                "dependencies"
                            ],
                            "after": candidate["plan"]["dependencies"],
                        },
                        "notice": EXISTING_PLAN_NOTICE,
                    },
                }
            if digest(_plain(execution)) != command.expected_digest:
                raise ProductWorkError("执行申请已变化，请刷新后应用")
            if execution["state"] != "approved" or project["status"] not in (
                "approved",
                "active",
                "on_hold",
            ):
                raise ProductWorkError(
                    "需要对应项目的有效执行批准，项目须处于已批准、执行中或暂停状态"
                )
            policy = _policy(connection, tenant_id, project_id)
            if (
                policy is None
                or policy["id"] != execution["policy_id"]
                or connection.execute(
                    select(tables.project_execution_requests.c.id)
                    .where(
                        tables.project_execution_requests.c.tenant_id == tenant_id,
                        tables.project_execution_requests.c.project_id == project_id,
                        tables.project_execution_requests.c.round_no > execution["round_no"],
                    )
                    .limit(1)
                ).first()
            ):
                raise ProductWorkError("政策或执行申请已有新版本，请办理最新一轮")
            conversion = ensure_conversion(connection, tenant_id, project_id)
            snapshot, basis_digest = execution_snapshot(
                connection, context, project, review, policy, conversion
            )
            if basis_digest != execution["basis_digest"]:
                raise ProductWorkError("执行批准的关键依据已变化，请重新申请")
            if snapshot["blockers"]:
                raise ProductWorkError("计划应用条件未就绪：" + "；".join(snapshot["blockers"][:8]))
            if connection.execute(
                select(tables.schedule_time_records.c.id)
                .where(
                    tables.schedule_time_records.c.tenant_id == tenant_id,
                    tables.schedule_time_records.c.project_id == project_id,
                    tables.schedule_time_records.c.time_kind == "baseline",
                )
                .limit(1)
            ).first():
                raise ProductWorkError("项目已有正式基线，须采用计划变更，不能覆盖为首版")
            plan_snapshot = snapshot["plan_snapshot"]
            candidate = plan_snapshot["candidate"]
            scenario = plan_snapshot["scenario"]
            plan = candidate["plan"]
            if any(len(node["title"]) > 512 for node in plan["nodes"]):
                raise ProductWorkError("正式任务标题不能超过512字，请先修订候选并重新确认")
            stages = {
                row["code"]: row["id"]
                for row in connection.execute(
                    select(tables.stages).where(
                        tables.stages.c.tenant_id == tenant_id,
                        tables.stages.c.workflow_id == project["workflow_id"],
                    )
                ).mappings()
            }
            times = {node["node_key"]: node for node in scenario["result"]["nodes"]}
            allocations = [
                scenario["inputs"]["default_allocation"],
                *scenario["inputs"]["node_allocations"].values(),
            ]
            calendar_versions = {
                UUID(allocation["calendar_version_id"]) for allocation in allocations
            }
            calendars = dict(
                connection.execute(
                    select(
                        tables.work_calendar_versions.c.id,
                        tables.work_calendar_versions.c.calendar_id,
                    ).where(
                        tables.work_calendar_versions.c.tenant_id == tenant_id,
                        tables.work_calendar_versions.c.id.in_(calendar_versions),
                    )
                )
                .tuples()
                .all()
            )
            if calendars.keys() != calendar_versions:
                raise ProductWorkError("计划固定的工作日历版本缺失，请重新核对排程")
            now = datetime.now(UTC)
            application_id = uuid4()
            baseline_id = uuid4()
            receipt_id = uuid4()
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=context.user.id,
                project_id=project_id,
            )
            bindings = []
            node_times = []
            targets = []
            event_ids = []
            audit_ids = []
            node_ids = {}
            for node in plan["nodes"]:
                key = node["node_key"]
                task_id = uuid4()
                schedule_id = uuid4()
                node_ids[key] = schedule_id
                allocation = scenario["inputs"]["node_allocations"].get(
                    key, scenario["inputs"]["default_allocation"]
                )
                calendar_version_id = UUID(allocation["calendar_version_id"])
                task = (
                    connection.execute(
                        tables.tasks.insert()
                        .values(
                            id=task_id,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            workflow_id=project["workflow_id"],
                            stage_id=stages[candidate["stage_assignments"][key]],
                            assignee_user_id=UUID(node["owner_user_id"]),
                            title=node["title"],
                            description=node["completion_criteria"],
                            kind="task",
                            source_entity="initial_plan_candidate",
                            source_entity_id=UUID(candidate["id"]),
                            expected_output=node["expected_output"],
                            status="todo",
                            priority="medium",
                            created_at=now,
                            updated_at=now,
                        )
                        .returning(tables.tasks)
                    )
                    .mappings()
                    .one()
                )
                source = ScheduleSource(
                    kind="task",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    ref_id=task_id,
                    as_of=now,
                    digest=digest(_plain(task)),
                )
                schedule = ScheduleNode(
                    id=schedule_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    node_kind="task",
                    source=source,
                    calendar_id=calendars[calendar_version_id],
                )
                connection.execute(
                    tables.schedule_nodes.insert().values(
                        id=schedule_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        task_id=task_id,
                        calendar_version_id=calendar_version_id,
                        contract=schedule.model_dump(mode="json"),
                    )
                )
                window = TimeWindow(start=times[key]["start"], end=times[key]["finish"])
                node_times.append(NodeTime(node_id=schedule_id, window=window))
                targets.append(
                    TargetMapping(
                        node_key=key,
                        target=SourceRef(
                            tenant_id=tenant_id,
                            project_id=project_id,
                            kind="task",
                            ref_id=task_id,
                            as_of=now,
                            digest=source.digest,
                        ),
                    )
                )
                bindings.append(
                    dict(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        application_id=application_id,
                        node_key=key,
                        task_id=task_id,
                        schedule_node_id=schedule_id,
                        receiver_user_id=UUID(node["receiver_user_id"]),
                        discipline=node["discipline"],
                        completion_criteria=node["completion_criteria"],
                        node_snapshot=node,
                    )
                )
                written = writer.record(
                    EventDraft(
                        event_id=f"task:{task_id}:created",
                        event_type="TASK_CREATED",
                        source="task_service",
                        entity_id=task_id,
                        payload={"task_id": str(task_id), "status": "todo", "priority": "medium"},
                        occurred_at=now,
                    ),
                    AuditDraft(
                        action="task.create",
                        after_snapshot=_plain(task),
                        context={
                            "application_id": str(application_id),
                            "node_key": key,
                            "reason": command.reason,
                        },
                    ),
                )
                event_ids.append(written.event_row_id)
                audit_ids.append(written.audit_row_id)
            approval = ApprovalRef.model_validate(execution["approval"])
            baseline = TimeRecord(
                id=baseline_id,
                tenant_id=tenant_id,
                scope=ScopeRef(kind="project", ref_id=project_id),
                version=1,
                owner_user_id=context.user.id,
                sources=(
                    SourceRef(
                        tenant_id=tenant_id,
                        kind="initial_plan_candidate",
                        ref_id=UUID(candidate["id"]),
                        version=candidate["version"],
                    ),
                    SourceRef(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        kind="project_execution_request",
                        ref_id=execution["id"],
                        version=execution["version"],
                    ),
                ),
                time_kind="baseline",
                node_times=tuple(node_times),
                fact_kind="hypothesis",
                approval=approval,
                algorithm_version=scenario["result"]["algorithm_version"],
                as_of=now,
            )
            connection.execute(
                tables.schedule_time_records.insert().values(
                    id=baseline_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    time_kind="baseline",
                    version=1,
                    execution_request_id=execution["id"],
                    contract=baseline.model_dump(mode="json"),
                )
            )
            connection.execute(
                tables.schedule_time_nodes.insert(),
                [
                    {
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "record_id": baseline_id,
                        "node_id": item.node_id,
                        "start": item.window.start,
                        "end": item.window.end,
                    }
                    for item in node_times
                ],
            )
            task_ids = {node["node_key"]: node["task_id"] for node in bindings}
            for edge in plan["dependencies"]:
                connection.execute(
                    tables.schedule_plan_dependencies.insert().values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        baseline_id=baseline_id,
                        predecessor_node_id=node_ids[edge["predecessor"]],
                        successor_node_id=node_ids[edge["successor"]],
                        relation=edge["relation"],
                        lag=Decimal(edge["lag"]),
                        lag_unit=edge["lag_unit"],
                    )
                )
                # Existing Task readiness means completion prerequisites, not every scheduling edge.
                if edge["relation"] == "fs" and Decimal(edge["lag"]) >= 0:
                    connection.execute(
                        tables.task_dependencies.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            baseline_id=baseline_id,
                            task_id=task_ids[edge["successor"]],
                            depends_on_task_id=task_ids[edge["predecessor"]],
                        )
                    )
            contract = InitialPlanApplication(
                id=application_id,
                tenant_id=tenant_id,
                project_id=project_id,
                conversion_id=conversion["id"],
                source_scope=ScopeRef.model_validate(plan["scope"]),
                finding_id=None,
                candidate_digest=execution["plan_digest"],
                execution_approval=approval,
                baseline_id=baseline_id,
                operation_receipt_id=receipt_id,
                work_transfers=(),
            )
            written = writer.record(
                EventDraft(
                    event_id=f"initial-plan-applied:{application_id}",
                    event_type="INITIAL_PLAN_APPLIED",
                    source="planning_service",
                    entity_id=application_id,
                    payload=InitialPlanAppliedPayload(
                        object_id=application_id,
                        object_version=1,
                        operation_id=command.request_id,
                        correlation_id=application_id,
                        causation_event_row_id=None,
                        project_id=project_id,
                        conversion_id=conversion["id"],
                        baseline_id=baseline_id,
                        candidate_digest=execution["plan_digest"],
                        receipt_id=receipt_id,
                    ).model_dump(mode="json"),
                    occurred_at=now,
                ),
                AuditDraft(
                    action="initial_plan.apply",
                    after_snapshot=contract.model_dump(mode="json"),
                    context={"reason": command.reason},
                ),
            )
            event_ids.append(written.event_row_id)
            audit_ids.append(written.audit_row_id)
            receipt = OperationReceipt(
                id=receipt_id,
                tenant_id=tenant_id,
                source_run_id=None,
                finding_id=None,
                candidate_digest=execution["plan_digest"],
                idempotency_key=str(command.request_id),
                reviewed_by_user_id=review["reviewer_user_id"],
                reviewed_at=review["approval"]["approved_at"],
                applied_by_user_id=context.user.id,
                applied_at=now,
                status="applied",
                targets=tuple(targets),
                event_row_ids=tuple(event_ids),
                audit_row_ids=tuple(audit_ids),
                execution_state="pending",
                execution_evidence=(),
            )
            application = (
                connection.execute(
                    table.insert()
                    .values(
                        id=application_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        execution_request_id=execution["id"],
                        candidate_id=UUID(candidate["id"]),
                        baseline_id=baseline_id,
                        operation_receipt_id=receipt_id,
                        contract=contract.model_dump(mode="json"),
                        receipt=receipt.model_dump(mode="json"),
                        snapshot=snapshot,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            connection.execute(tables.task_plan_bindings.insert(), bindings)
            from app.domain.schedule_forecasts import automatic_forecast

            automatic_forecast(
                connection, tenant_id, project_id, context.user.id, "首版计划应用后的初始预测", now
            )

            return {
                "application": _result(connection, context, application),
                "already_applied": False,
                "diff": None,
            }
