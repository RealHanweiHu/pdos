"""Independent named confirmation of scoped deadline commitments and four-time comparison."""

from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Digest,
    NodeTime,
    PlanCandidate,
    ScopeRef,
    SourceRef,
    Text,
    TimeRecord,
)
from app.db.schema import tables
from app.domain.forecast_capacity import _forecast, evaluate_current_forecast_capacity
from app.domain.plan_scheduling import NodeAllocation
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_capacity import CapacityCheckDraft
from app.domain.resource_reservations import _project
from app.domain.schedule_forecast_engine import calculate_forecast
from app.domain.schedule_forecasts import capture_basis
from app.domain.working_time import CalendarDefinition
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CommitmentPolicyDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    approver_user_id: UUID
    authority_basis: Text


class CommitmentConfirm(Contract):
    request_id: UUID
    policy_id: UUID
    forecast_record_id: UUID
    capacity_check_id: UUID
    expected_basis_digest: Digest
    expected_commitment_version: int = Field(ge=0)
    node_times: tuple[NodeTime, ...] = Field(min_length=1, max_length=1000)
    scope_label: Text
    reason: Text

    @model_validator(mode="after")
    def deadlines(self) -> Self:
        if len({item.node_id for item in self.node_times}) != len(self.node_times):
            raise ValueError("承诺节点不能重复")
        if any(item.window.end is None for item in self.node_times):
            raise ValueError("每个节点须明确承诺最晚完成时间")
        return self


def _policy(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.schedule_commitment_policies
    return (
        connection.execute(
            select(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
            .order_by(table.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def compare_times(
    connection: Connection, tenant_id: UUID, project_id: UUID, context: AuthContext
) -> list[dict[str, Any]]:
    records = tables.schedule_time_records
    times = tables.schedule_time_nodes
    ranked = (
        select(
            times.c.node_id,
            records.c.id.label("record_id"),
            records.c.time_kind,
            records.c.version,
            times.c.start,
            times.c.end,
            func.row_number()
            .over(
                partition_by=(times.c.node_id, records.c.time_kind),
                order_by=records.c.version.desc(),
            )
            .label("position"),
        )
        .join(
            records,
            (records.c.tenant_id == times.c.tenant_id)
            & (records.c.project_id == times.c.project_id)
            & (records.c.id == times.c.record_id),
        )
        .where(times.c.tenant_id == tenant_id, times.c.project_id == project_id)
        .subquery()
    )
    windows: dict[str, dict[str, Any]] = {}
    for row in connection.execute(select(ranked).where(ranked.c.position == 1)).mappings():
        windows.setdefault(str(row["node_id"]), {})[row["time_kind"]] = _plain(row)
    from app.domain.formal_schedule import current_plan, current_states

    formal = current_plan(connection, tenant_id, project_id)
    states, titles = (
        current_states(connection, tenant_id, project_id, formal) if formal else ([], {})
    )
    result = [
        {
            "node_id": row["node_id"],
            "node_key": row["node_key"],
            "task_id": row["task_id"],
            "title": titles[row["node_key"]],
            "status": row["status"],
            "times": windows.get(row["node_id"], {}),
        }
        for row in states
    ]

    from app.domain.schedule_nodes import list_nodes

    bound = {item["node_id"] for item in result}
    for item in result:
        item["eligible_for_commitment"] = item["status"] not in ("done", "skipped")
    for node in list_nodes(connection, context, project_id):
        if node["id"] not in bound:
            result.append(
                {
                    "node_id": node["id"],
                    "node_key": node["node_kind"],
                    "task_id": node["task_id"],
                    "title": node["title"],
                    "status": node["source_status"],
                    "times": windows.get(node["id"], {}),
                    "eligible_for_commitment": False,
                }
            )
    return result


class ScheduleCommitmentService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            policies = tables.schedule_commitment_policies
            records = tables.schedule_time_records
            confirmations = tables.schedule_commitment_confirmations
            policy_rows = list(
                connection.execute(
                    select(policies)
                    .where(
                        policies.c.tenant_id == context.tenant.id,
                        policies.c.project_id == project_id,
                    )
                    .order_by(policies.c.version.desc())
                ).mappings()
            )
            policy = policy_rows[0] if policy_rows else None
            users = tables.users
            members = select(tables.project_members.c.user_id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
            )
            people = list(
                connection.execute(
                    select(users.c.id, users.c.display_name)
                    .where(
                        users.c.tenant_id == context.tenant.id,
                        users.c.is_active.is_(True),
                        users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                        or_(users.c.role.in_(("owner", "admin")), users.c.id.in_(members)),
                    )
                    .order_by(users.c.display_name, users.c.id)
                    .limit(1000)
                ).mappings()
            )
            rows = list(
                connection.execute(
                    select(confirmations, records.c.version, records.c.contract)
                    .join(
                        records,
                        (records.c.tenant_id == confirmations.c.tenant_id)
                        & (records.c.id == confirmations.c.record_id),
                    )
                    .where(
                        confirmations.c.tenant_id == context.tenant.id,
                        confirmations.c.project_id == project_id,
                    )
                    .order_by(records.c.version.desc())
                    .limit(51)
                ).mappings()
            )
            forecast = (
                connection.execute(
                    select(tables.schedule_forecast_runs, records.c.version)
                    .join(
                        records,
                        (records.c.tenant_id == tables.schedule_forecast_runs.c.tenant_id)
                        & (records.c.id == tables.schedule_forecast_runs.c.record_id),
                    )
                    .where(
                        records.c.tenant_id == context.tenant.id, records.c.project_id == project_id
                    )
                    .order_by(records.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            checks = []
            basis_digest = None
            if forecast:
                basis_digest = capture_basis(connection, context.tenant.id, project_id)[
                    "basis_digest"
                ]
                checks = list(
                    connection.execute(
                        select(
                            tables.forecast_capacity_checks.c.id,
                            tables.forecast_capacity_checks.c.created_at,
                            tables.forecast_capacity_checks.c.result,
                        )
                        .where(
                            tables.forecast_capacity_checks.c.tenant_id == context.tenant.id,
                            tables.forecast_capacity_checks.c.forecast_record_id
                            == forecast["record_id"],
                        )
                        .order_by(tables.forecast_capacity_checks.c.created_at.desc())
                        .limit(50)
                    ).mappings()
                )
            return {
                "policy": _plain(policy) if policy else None,
                "policies": [_plain(row) for row in policy_rows],
                "people": [_plain(row) for row in people],
                "items": [_plain(row) for row in rows[:50]],
                "has_more": len(rows) > 50,
                "latest_commitment_version": rows[0]["version"] if rows else 0,
                "current_user_id": str(context.user.id),
                "can_configure": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "can_confirm": bool(policy and policy["approver_user_id"] == context.user.id),
                "forecast": {
                    "id": str(forecast["record_id"]),
                    "version": forecast["version"],
                    "basis_is_current": forecast["basis_digest"] == basis_digest,
                }
                if forecast
                else None,
                "basis_digest": basis_digest,
                "capacity_checks": [
                    {
                        "id": str(row["id"]),
                        "created_at": row["created_at"].isoformat(),
                        "status": row["result"]["status"],
                    }
                    for row in checks
                ],
                "nodes": compare_times(connection, context.tenant.id, project_id, context),
            }

    def publish_policy(
        self, context: AuthContext, project_id: UUID, draft: CommitmentPolicyDraft
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, draft.approver_user_id)
            table = tables.schedule_commitment_policies
            fingerprint = digest({"project_id": str(project_id), **draft.model_dump(mode="json")})
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
                    raise ProductWorkError("请求编号已用于另一项承诺政策")
                return _plain(prior)
            current = _policy(connection, context.tenant.id, project_id)
            if draft.expected_version != (current["version"] if current else 0):
                raise ProductWorkError("承诺政策已有新版本，请刷新")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        version=draft.expected_version + 1,
                        approver_user_id=draft.approver_user_id,
                        authority_basis=draft.authority_basis,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                row["id"],
                "policy_published",
                _plain(row),
                draft.authority_basis,
            )
            return _plain(row)

    def confirm(
        self, context: AuthContext, project_id: UUID, command: CommitmentConfirm
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            tenant_id = context.tenant.id
            table = tables.schedule_commitment_confirmations
            fingerprint = digest({"project_id": str(project_id), **command.model_dump(mode="json")})
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.approved_by_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于不同承诺")
                return _plain(prior)
            policy = _policy(connection, tenant_id, project_id)
            if policy is None or policy["id"] != command.policy_id:
                raise ProductWorkError("请按当前具名承诺政策办理")
            if policy["approver_user_id"] != context.user.id:
                raise ProductWorkAccessError("仅承诺政策中的具名批准人可确认")
            _person(connection, context, project_id, context.user.id)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能确认正式承诺")
            capture = capture_basis(connection, tenant_id, project_id)
            if capture["basis_digest"] != command.expected_basis_digest:
                raise ProductWorkError("实际进展已有变化，请刷新承诺草稿")
            forecast = _forecast(connection, context, project_id, command.forecast_record_id)
            check = (
                connection.execute(
                    select(tables.forecast_capacity_checks).where(
                        tables.forecast_capacity_checks.c.tenant_id == tenant_id,
                        tables.forecast_capacity_checks.c.project_id == project_id,
                        tables.forecast_capacity_checks.c.forecast_record_id
                        == command.forecast_record_id,
                        tables.forecast_capacity_checks.c.id == command.capacity_check_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if check is None:
                raise ProductWorkError("须选择该预测的实际容量检查")
            now = datetime.now(UTC)
            basis = capture["basis"]
            external = basis.get("external_dependencies", [])
            if capture.get("network"):
                from app.domain.schedule_network import project_sources

                external = project_sources(
                    capture["network"], basis, now, forecast["inputs"]["estimates"]
                )
            refreshed = calculate_forecast(
                PlanCandidate.model_validate(basis["plan"]),
                now,
                {
                    key: CalendarDefinition.model_validate(value)
                    for key, value in basis["calendars"].items()
                },
                {
                    key: NodeAllocation(
                        calendar_key=value["calendar_version_id"],
                        parallel_units=value["parallel_units"],
                        allocation_basis=value["allocation_basis"],
                        not_before=value.get("not_before"),
                    )
                    for key, value in basis["allocations"].items()
                },
                {item["node_key"]: item for item in basis["tasks"]},
                forecast["inputs"]["estimates"],
                external,
            )
            node_states = {UUID(item["node_id"]): item for item in basis["tasks"]}
            predictions = {item["node_key"]: item for item in refreshed["nodes"]}
            selected_keys = set()
            for node in command.node_times:
                state = node_states.get(node.node_id)
                if state is None or state["status"] in ("done", "skipped"):
                    raise ProductWorkError("须选择本项目未结束的实际节点")
                selected_keys.add(state["node_key"])
                predicted = predictions[state["node_key"]]
                if (
                    node.window.end is None
                    or not predicted["finish"]
                    or datetime.fromisoformat(predicted["finish"]) > node.window.end
                    or node.window.end <= now
                ):
                    raise ProductWorkError(
                        f"{state['node_key']}：承诺完成时间须可由当前预测支持，且不能追认过去期限"
                    )
                if node.window.start is not None and (
                    state["actual_start"]
                    or node.window.start <= now
                    or not predicted["start"]
                    or datetime.fromisoformat(predicted["start"]) > node.window.start
                ):
                    raise ProductWorkError(
                        f"{state['node_key']}：最晚开始期限须可兑现，已开工节点仅确认完成期限"
                    )
            capacity = evaluate_current_forecast_capacity(
                connection,
                context,
                project_id,
                {**forecast, "result": refreshed},
                CapacityCheckDraft.model_validate(check["inputs"]),
            )
            blockers = [
                item["reason"]
                for item in capacity["unknown"] + capacity["warnings"]
                if item["node_key"] == "资源盘点"
                or selected_keys.intersection(item["node_key"].split(", "))
            ]
            if any(selected_keys.intersection(item["node_keys"]) for item in capacity["conflicts"]):
                blockers.append("承诺节点仍有资源容量冲突")
            if any(
                item["node_key"] in selected_keys
                and item["disposition"] in ("additional_capacity_needed", "requirement_unknown")
                for item in capacity["reservation_differences"]
            ):
                blockers.append("承诺节点的资源尚未取得足够的正式预约覆盖")
            if blockers:
                raise ProductWorkError("承诺条件未就绪：" + "；".join(blockers[:8]))
            records = tables.schedule_time_records
            latest = (
                connection.execute(
                    select(func.max(records.c.version)).where(
                        records.c.tenant_id == tenant_id,
                        records.c.project_id == project_id,
                        records.c.time_kind == "commitment",
                    )
                ).scalar_one()
                or 0
            )
            if latest != command.expected_commitment_version:
                raise ProductWorkError("承诺已有新版本，请刷新后独立确认")
            confirmation_id = uuid4()
            record_id = uuid4()
            version = latest + 1
            payload = {
                "project_id": str(project_id),
                "policy": _plain(policy),
                "forecast_record_id": str(command.forecast_record_id),
                "capacity_check_id": str(command.capacity_check_id),
                "node_times": [item.model_dump(mode="json") for item in command.node_times],
                "scope_label": command.scope_label,
                "reason": command.reason,
                "basis_digest": capture["basis_digest"],
                "capacity": capacity,
                "confirmation_recheck": refreshed,
            }
            payload_digest = digest(payload)
            approval = ApprovalRef(
                approval_id=confirmation_id,
                payload_digest=payload_digest,
                policy_version=f"project_commitment.v{policy['version']}",
                approved_by_user_id=context.user.id,
                approved_at=now,
            )
            contract = TimeRecord(
                id=record_id,
                tenant_id=tenant_id,
                scope=ScopeRef(kind="project", ref_id=project_id),
                version=version,
                owner_user_id=context.user.id,
                sources=(
                    SourceRef(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        kind="schedule_forecast",
                        ref_id=command.forecast_record_id,
                        as_of=datetime.fromisoformat(forecast["result"]["as_of"]),
                        digest=digest(forecast["result"]),
                    ),
                    SourceRef(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        kind="forecast_capacity_check",
                        ref_id=command.capacity_check_id,
                        as_of=check["created_at"],
                        digest=check["result_digest"],
                    ),
                ),
                time_kind="commitment",
                node_times=command.node_times,
                fact_kind="hypothesis",
                approval=approval,
                as_of=now,
            )
            connection.execute(
                records.insert().values(
                    id=record_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    time_kind="commitment",
                    version=version,
                    contract=contract.model_dump(mode="json"),
                )
            )
            connection.execute(
                tables.schedule_time_nodes.insert(),
                [
                    {
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "record_id": record_id,
                        "node_id": item.node_id,
                        "start": item.window.start,
                        "end": item.window.end,
                    }
                    for item in command.node_times
                ],
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=confirmation_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        record_id=record_id,
                        policy_id=policy["id"],
                        forecast_record_id=command.forecast_record_id,
                        capacity_check_id=command.capacity_check_id,
                        scope_label=command.scope_label,
                        reason=command.reason,
                        snapshot=payload,
                        payload_digest=payload_digest,
                        approved_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                confirmation_id,
                "confirmed",
                {
                    "record_id": str(record_id),
                    "version": version,
                    "scope_label": command.scope_label,
                    "payload_digest": payload_digest,
                },
                command.reason,
            )
            return _plain(row)


def _event(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    record_id: UUID,
    action: str,
    snapshot: dict[str, Any],
    reason: str,
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=f"schedule-commitment:{record_id}",
            event_type="SCHEDULE_COMMITMENT_CHANGED",
            source="planning_service",
            entity_id=record_id,
            payload={"record_id": str(record_id), "action": action},
        ),
        AuditDraft(
            action="schedule_commitment." + action,
            after_snapshot=snapshot,
            context={"reason": reason},
        ),
    )
