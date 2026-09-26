"""Named approval of fixed baseline-change proposals; application is a separate action."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.project_scenario_capacity import evaluate_scenario_capacity, get_scenario
from app.domain.project_schedule_scenarios import calculate_scenario_at
from app.domain.resource_capacity import CapacityCheckDraft
from app.domain.resource_reservations import _project
from app.domain.task_dependency_graph import dependency_graph_has_cycle
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class BaselinePolicyDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    approver_user_id: UUID
    authority_basis: Text
    four_eyes: bool


class BaselinePolicyRenewal(Contract):
    previous_change_id: UUID
    expected_digest: Digest


class BaselineChangeDraft(Contract):
    request_id: UUID
    scenario_id: UUID
    capacity_check_id: UUID
    policy_id: UUID
    expected_baseline_id: UUID
    reason: Text
    policy_renewal: BaselinePolicyRenewal | None = None


class BaselineDecision(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["approve", "reject", "withdraw"]
    reason: Text


def latest_policy(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.baseline_change_policies
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


def latest_baseline(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.schedule_time_records
    row = (
        connection.execute(
            select(table)
            .where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.time_kind == "baseline",
            )
            .order_by(table.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("当前项目尚无获批基线")
    return row


def _event(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    record_id: UUID,
    action: str,
    snapshot: dict[str, Any],
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=f"baseline-change:{record_id}:{action}:{uuid4()}",
            event_type="BASELINE_CHANGE_RECORDED",
            source="planning_service",
            entity_id=record_id,
            payload={"record_id": str(record_id), "action": action},
        ),
        AuditDraft(action=f"baseline_change.{action}", after_snapshot=snapshot),
    )


def responsibility_gaps(
    connection: Connection, context: AuthContext, project_id: UUID, plan: dict[str, Any]
) -> list[str]:
    gaps = []
    for node in plan["nodes"]:
        for field, label in (("owner_user_id", "负责人"), ("receiver_user_id", "接收人")):
            if not node.get(field):
                gaps.append(f"{node['title']}：缺少{label}")
            else:
                try:
                    _person(connection, context, project_id, UUID(node[field]))
                except ProductWorkError:
                    gaps.append(f"{node['title']}：{label}已不是有效项目成员")
    return gaps


def approval_blockers(
    result: dict[str, Any], capacity: dict[str, Any], people_gaps: list[str]
) -> list[str]:
    blockers = list(people_gaps)
    if not result["complete"]:
        blockers.append("节点日期仍有缺项，须补齐实际依据或剩余估计")
    if any(node["warnings"] for node in result["nodes"]):
        blockers.append("实际时间与依赖约束存在差异，请核对拟变更关系")
    if capacity["status"] != "capacity_clear" or capacity["unknown"] or capacity["warnings"]:
        blockers.append("容量存在冲突、缺项或投入假设差异")
    return blockers


def manual_dependency_gaps(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    plan: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    mapping = {node["node_key"]: UUID(node["node_id"]) for node in result["nodes"]}
    edges = tuple(
        (mapping[edge["successor"]], mapping[edge["predecessor"]]) for edge in plan["dependencies"]
    )
    return (
        ["拟变更排程与当前手工任务依赖构成循环"]
        if dependency_graph_has_cycle(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            formal_edges=edges,
        )
        else []
    )


class BaselineChangeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project_id: UUID, target_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            baseline = latest_baseline(connection, context.tenant.id, project_id)
            policy = latest_policy(connection, context.tenant.id, project_id)
            table = tables.baseline_change_requests
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(51)
                ).mappings()
            )
            has_more = len(rows) > 50
            visible = rows[:50]
            if target_id is not None and not any(row["id"] == target_id for row in visible):
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
                    raise ProductWorkAccessError("指定申请不存在或不属于当前项目")
                visible.append(target)
            decisions = tables.baseline_change_decisions
            concluded = {
                row["change_id"]: _plain(row)
                for row in connection.execute(
                    select(decisions).where(
                        decisions.c.tenant_id == context.tenant.id,
                        decisions.c.project_id == project_id,
                        decisions.c.change_id.in_([row["id"] for row in visible]),
                    )
                ).mappings()
            }
            applications = tables.baseline_change_applications
            applied = {
                item["change_id"]: _plain(item)
                for item in connection.execute(
                    select(applications).where(
                        applications.c.tenant_id == context.tenant.id,
                        applications.c.project_id == project_id,
                        applications.c.change_id.in_([row["id"] for row in visible]),
                    )
                ).mappings()
            }
            bindings = tables.portfolio_execution_projects
            portfolio_origins = {
                value["scenario_id"]: {
                    "preparation_id": str(value["preparation_id"]),
                    "selection_id": str(value["selection_id"]),
                    "change_id": str(value["change_id"]),
                }
                for value in connection.execute(
                    select(bindings).where(
                        bindings.c.tenant_id == context.tenant.id,
                        bindings.c.project_id == project_id,
                        bindings.c.scenario_id.in_([r["scenario_id"] for r in visible]),
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
                "baseline": {"id": str(baseline["id"]), "version": baseline["version"]},
                "policy": _plain(policy) if policy else None,
                "people": [_plain(row) for row in people],
                "current_user_id": str(context.user.id),
                "can_configure": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "can_prepare": is_allowed(context.user.role, Action.PROJECT_EDIT),
                "items": [
                    {
                        **_plain(row),
                        "portfolio_origin": portfolio_origins.get(row["scenario_id"]),
                        "decision": concluded.get(row["id"]),
                        "application": applied.get(row["id"]),
                        "is_current": row["base_baseline_id"] == baseline["id"]
                        and policy is not None
                        and row["policy_id"] == policy["id"],
                    }
                    for row in visible
                ],
                "has_more": has_more,
            }

    def publish_policy(
        self, context: AuthContext, project_id: UUID, draft: BaselinePolicyDraft
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, draft.approver_user_id)
            table = tables.baseline_change_policies
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
                    raise ProductWorkError("请求编号已用于另一项基线政策")
                return _plain(prior)
            policy = latest_policy(connection, context.tenant.id, project_id)
            if draft.expected_version != (policy["version"] if policy else 0):
                raise ProductWorkError("基线批准政策已有新版本，请刷新")
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
                        four_eyes=draft.four_eyes,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(connection, context, project_id, row["id"], "policy_published", _plain(row))
            return _plain(row)

    def prepare(
        self, context: AuthContext, project_id: UUID, draft: BaselineChangeDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as connection:
            return self.prepare_in_connection(connection, context, project_id, draft)

    def prepare_in_connection(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        draft: BaselineChangeDraft,
        *,
        calculation_as_of: datetime | None = None,
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        from app.domain.portfolio_execution_preparations import origin

        if origin(connection, context.tenant.id, project_id, draft.scenario_id) is not None:
            raise ProductWorkError("此情景已绑定组合执行，请沿原组合申请办理，变化后重新比较")
        project = _project(connection, context, project_id, write=True)
        table = tables.baseline_change_requests
        signing = draft.model_dump(mode="json")
        if "policy_renewal" not in draft.model_fields_set:
            signing.pop("policy_renewal")
        if calculation_as_of is not None:
            signing["fixed_calculation_as_of"] = calculation_as_of.isoformat()
        fingerprint = digest({"project_id": str(project_id), **signing})
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
                raise ProductWorkError("请求编号已用于另一项基线变更")
            return _plain(prior)
        if project["status"] not in ("approved", "active", "on_hold"):
            raise ProductWorkError("当前项目状态不允许准备基线变更")
        baseline = latest_baseline(connection, context.tenant.id, project_id)
        policy = latest_policy(connection, context.tenant.id, project_id)
        if (
            baseline["id"] != draft.expected_baseline_id
            or policy is None
            or policy["id"] != draft.policy_id
        ):
            raise ProductWorkError("当前基线或批准政策已变化，请刷新")
        original = None
        if draft.policy_renewal:
            renewal = draft.policy_renewal
            original = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.id == renewal.previous_change_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if original is None or original["created_by_user_id"] != context.user.id:
                raise ProductWorkAccessError("仅原提交人可撤回旧申请并按新政策续提")
            if original["payload_digest"] != renewal.expected_digest:
                raise ProductWorkError("原申请与核对版本不同，请刷新")
            if connection.execute(
                select(tables.baseline_change_decisions.c.id).where(
                    tables.baseline_change_decisions.c.tenant_id == context.tenant.id,
                    tables.baseline_change_decisions.c.change_id == original["id"],
                )
            ).first():
                raise ProductWorkError("原申请已有裁决，不能再按新政策续提")
            if (
                original["base_baseline_id"] != baseline["id"]
                or original["policy_id"] == policy["id"]
                or original["scenario_id"] != draft.scenario_id
                or original["capacity_check_id"] != draft.capacity_check_id
            ):
                raise ProductWorkError("续提须沿用当前基线、原情景和容量检查，并指定当前新政策")
            _person(connection, context, project_id, policy["approver_user_id"])
            if policy["four_eyes"] and policy["approver_user_id"] == context.user.id:
                raise ProductWorkError("新政策要求提交人与批准人分离，请先指定独立批准人")
        scenario = get_scenario(connection, context, project_id, draft.scenario_id)
        checks = tables.project_scenario_capacity_checks
        check = (
            connection.execute(
                select(checks).where(
                    checks.c.tenant_id == context.tenant.id,
                    checks.c.project_id == project_id,
                    checks.c.scenario_id == draft.scenario_id,
                    checks.c.id == draft.capacity_check_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if check is None:
            raise ProductWorkError("请选择此情景的实际容量检查记录")
        now = calculation_as_of if calculation_as_of is not None else datetime.now(UTC)
        result = (
            deepcopy(original["snapshot"]["result"])
            if original
            else calculate_scenario_at(scenario, now)
        )
        capacity = evaluate_scenario_capacity(
            connection,
            context,
            project_id,
            scenario,
            CapacityCheckDraft.model_validate(check["inputs"]),
            result_override=result,
        )
        gaps = responsibility_gaps(connection, context, project_id, scenario["plan"])
        gaps.extend(
            manual_dependency_gaps(
                connection, context.tenant.id, project_id, scenario["plan"], result
            )
        )
        # For unstarted nodes, the approved explicit remainder becomes the
        # new estimate. Started nodes still need fresh remaining estimates
        # in later forecasts; never reuse a stale running-work estimate.
        approved_plan = deepcopy(scenario["plan"])
        result_by_key = {node["node_key"]: node for node in result["nodes"]}
        for node in approved_plan["nodes"]:
            calculated = result_by_key[node["node_key"]]
            estimate = calculated.get("estimate")
            if (
                estimate
                and not calculated.get("actual_start")
                and not calculated.get("actual_finish")
            ):
                node["effort_hours"] = estimate["remaining_hours"]
                node["waiting_days"] = estimate["remaining_waiting_days"]
                node["estimate_basis"] = estimate["basis"]

        def window(values: dict[str, str | None]) -> dict[str, str | None]:
            return {
                key: datetime.fromisoformat(value).astimezone(UTC).isoformat() if value else None
                for key, value in values.items()
            }

        old = {
            node["node_id"]: window(node["window"]) for node in baseline["contract"]["node_times"]
        }
        changes = [
            {
                "node_id": node["node_id"],
                "node_key": node["node_key"],
                "previous": old.get(node["node_id"]),
                "proposed": {"start": node["start"], "end": node["finish"]},
            }
            for node in result["nodes"]
            if old.get(node["node_id"]) != window({"start": node["start"], "end": node["finish"]})
        ]
        snapshot = {
            "plan": approved_plan,
            "result": result,
            "capacity": capacity,
            "capacity_inputs": check["inputs"],
            "policy": _plain(policy),
            "baseline": _plain(baseline),
            "scenario_basis_digest": scenario["basis_digest"],
            "scenario_result_digest": scenario["result_digest"],
            "original_capacity_digest": check["result_digest"],
            "time_changes": changes,
            "blockers": approval_blockers(result, capacity, gaps),
        }
        if original is not None:
            fields = set(snapshot) - {"policy", "blockers"}
            if digest({k: snapshot[k] for k in fields}) != digest(
                {k: original["snapshot"][k] for k in fields}
            ):
                raise ProductWorkError("原计划、日期、容量或来源已变化，请重新准备完整变更申请")
            if snapshot["blockers"]:
                raise ProductWorkError("续提条件未就绪：" + "；".join(snapshot["blockers"][:8]))
            snapshot["policy_renewal"] = {
                "previous_change_id": str(original["id"]),
                "previous_payload_digest": original["payload_digest"],
                "previous_policy": original["snapshot"]["policy"],
                "previous_reason": original["reason"],
                "reason": draft.reason,
                "actor_user_id": str(context.user.id),
                "actor_name": context.user.display_name,
            }
        payload_digest = digest(snapshot)
        row = (
            connection.execute(
                table.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    scenario_id=draft.scenario_id,
                    capacity_check_id=draft.capacity_check_id,
                    policy_id=draft.policy_id,
                    base_baseline_id=baseline["id"],
                    reason=draft.reason,
                    snapshot=snapshot,
                    payload_digest=payload_digest,
                    created_by_user_id=context.user.id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        if original is not None:
            withdrawal = BaselineDecision(
                request_id=uuid5(draft.request_id, "baseline-policy-renewal-withdraw"),
                expected_digest=original["payload_digest"],
                action="withdraw",
                reason=draft.reason,
            )
            decision = (
                connection.execute(
                    tables.baseline_change_decisions.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        change_id=original["id"],
                        action="withdraw",
                        actor_user_id=context.user.id,
                        reason=draft.reason,
                        approved_payload_digest=original["payload_digest"],
                        request_id=withdrawal.request_id,
                        request_digest=digest(
                            {
                                "project_id": str(project_id),
                                "change_id": str(original["id"]),
                                **withdrawal.model_dump(mode="json"),
                            }
                        ),
                    )
                    .returning(tables.baseline_change_decisions)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                original["id"],
                "withdraw",
                {**_plain(decision), "renewed_change_id": str(row["id"])},
            )
        _event(
            connection,
            context,
            project_id,
            row["id"],
            "prepared",
            {
                "id": str(row["id"]),
                "payload_digest": payload_digest,
                "blockers": snapshot["blockers"],
            },
        )
        return _plain(row)

    def decide(
        self, context: AuthContext, project_id: UUID, change_id: UUID, command: BaselineDecision
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            table = tables.baseline_change_requests
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.id == change_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("基线变更不存在或不可访问")
            decisions = tables.baseline_change_decisions
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "change_id": str(change_id),
                    **command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(decisions).where(
                        decisions.c.tenant_id == context.tenant.id,
                        decisions.c.actor_user_id == context.user.id,
                        decisions.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项基线裁决")
                return _plain(prior)
            if connection.execute(
                select(decisions.c.id).where(
                    decisions.c.tenant_id == context.tenant.id, decisions.c.change_id == change_id
                )
            ).first():
                raise ProductWorkError("此变更已有结论，请保留历史并准备新申请")
            if command.expected_digest != row["payload_digest"]:
                raise ProductWorkError("申请内容与审阅版本不一致，请刷新")
            policy = latest_policy(connection, context.tenant.id, project_id)
            if command.action == "withdraw":
                if row["created_by_user_id"] != context.user.id:
                    raise ProductWorkAccessError("仅提交人可撤回尚未裁决的申请")
            else:
                if (
                    policy is None
                    or policy["id"] != row["policy_id"]
                    or policy["approver_user_id"] != context.user.id
                ):
                    raise ProductWorkAccessError("仅当前政策中的具名批准人可裁决")
                _person(connection, context, project_id, context.user.id)
                if policy["four_eyes"] and row["created_by_user_id"] == context.user.id:
                    raise ProductWorkAccessError("当前政策要求提交人与批准人分开")
            if command.action == "approve":
                from app.domain.portfolio_execution_preparations import verify_baseline_origin

                verify_baseline_origin(connection, context, project_id, row)
                if (
                    project["status"] not in ("approved", "active", "on_hold")
                    or latest_baseline(connection, context.tenant.id, project_id)["id"]
                    != row["base_baseline_id"]
                ):
                    raise ProductWorkError("项目状态或当前基线已变化，请重新准备")
                scenario = get_scenario(connection, context, project_id, row["scenario_id"])
                snap = row["snapshot"]
                capacity = evaluate_scenario_capacity(
                    connection,
                    context,
                    project_id,
                    scenario,
                    CapacityCheckDraft.model_validate(snap["capacity_inputs"]),
                    result_override=snap["result"],
                )
                if digest(capacity) != digest(snap["capacity"]):
                    raise ProductWorkError("容量版本或预约已变化，请重新准备并审阅最新影响")
                blockers = approval_blockers(
                    snap["result"],
                    capacity,
                    responsibility_gaps(connection, context, project_id, snap["plan"]),
                )
                blockers.extend(
                    manual_dependency_gaps(
                        connection, context.tenant.id, project_id, snap["plan"], snap["result"]
                    )
                )
                if blockers:
                    raise ProductWorkError("；".join(blockers[:12]))
            decision = (
                connection.execute(
                    decisions.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        change_id=change_id,
                        action=command.action,
                        actor_user_id=context.user.id,
                        reason=command.reason,
                        approved_payload_digest=row["payload_digest"],
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(decisions)
                )
                .mappings()
                .one()
            )
            _event(connection, context, project_id, change_id, command.action, _plain(decision))
            return _plain(decision)
