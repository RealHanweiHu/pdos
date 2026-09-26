"""Current formal-plan evidence across the caller's complete project scope."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.milestone_designations import node_snapshot, records
from app.domain.organization import active_delegated_principals
from app.domain.portfolio_health_policy import HealthPolicy, latest
from app.domain.portfolio_milestones import commitments
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import _project
from app.domain.schedule_forecasts import capture_basis


class ProgressRead(Contract):
    search: str = Field(default="", max_length=200)
    project_status: (
        Literal["draft", "proposed", "approved", "active", "on_hold", "completed", "archived"]
        | None
    ) = None
    order: Literal["deviation", "blocked", "conditions", "coverage", "critical", "code"] = (
        "deviation"
    )
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ProgressDetail(Contract):
    project_id: UUID
    focus: Literal[
        "all", "milestones", "key_milestones", "critical", "gaps", "critical_unknown"
    ] = "all"
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ProgressForecastHistory(Contract):
    project_id: UUID
    before_version: int | None = Field(default=None, ge=1)


def forecast_history_query(tenant_id: UUID, project_id: UUID) -> Any:
    f, r = tables.schedule_forecast_runs, tables.schedule_time_records
    return (
        select(
            f.c.record_id,
            f.c.baseline_id,
            f.c.result,
            f.c.reason,
            f.c.basis_digest,
            f.c.created_by_user_id,
            f.c.inputs["trigger"].as_string().label("trigger"),
            r.c.version,
            r.c.created_at,
            func.lag(r.c.created_at).over(order_by=r.c.version).label("previous_saved_at"),
        )
        .join(
            r,
            (r.c.tenant_id == f.c.tenant_id)
            & (r.c.project_id == f.c.project_id)
            & (r.c.id == f.c.record_id),
        )
        .where(f.c.tenant_id == tenant_id, f.c.project_id == project_id)
    )


def policy(c: Connection, context: AuthContext, now: datetime) -> HealthPolicy | None:
    row = latest(c, context.tenant.id)
    value = HealthPolicy.model_validate(row["body"]) if row else None
    return (
        value
        if value and value.status == "active" and value.valid_from <= now < value.valid_until
        else None
    )


def capture(
    c: Connection,
    context: AuthContext,
    project: Any,
    now: datetime,
    age_policy: HealthPolicy | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    identity = project["id"]
    item: dict[str, Any] = {
        "project_id": str(identity),
        "code": project["code"],
        "name": project["name"],
        "project_status": project["status"],
        "target_date": _plain(project).get("target_date"),
        "baseline_id": None,
        "baseline_version": None,
        "baseline_finish": None,
        "forecast_id": None,
        "forecast_version": None,
        "forecast_finish": None,
        "forecast_as_of": None,
        "forecast_current": False,
        "delay_days": None,
        "node_count": None,
        "completed_count": None,
        "completion_percent": None,
        "blocked_count": None,
        "unknown_count": None,
        "unfinished_count": None,
        "covered_count": None,
        "coverage_percent": None,
        "forecast_gap_count": None,
        "critical_count": None,
        "critical_unknown_count": None,
        "float_status": None,
        "coverage_missing": [],
        "key_milestone_unfinished_count": None,
        "key_milestone_covered_count": None,
        "unclassified_milestone_count": None,
        "designation_recheck_count": None,
        "missing": [],
        "href": f"/projects?project={identity}&tab=overview#schedule-forecasts",
    }
    try:
        current = capture_basis(c, context.tenant.id, identity)
    except (ValueError, LookupError) as error:
        item["missing"] = [str(error)]
        return item, []
    basis = current["basis"]
    r, n, f = (
        tables.schedule_time_records,
        tables.schedule_time_nodes,
        tables.schedule_forecast_runs,
    )
    base = {
        str(v["node_id"]): v
        for v in c.execute(
            select(n).where(
                n.c.tenant_id == context.tenant.id,
                n.c.project_id == identity,
                n.c.record_id == UUID(basis["baseline_id"]),
            )
        ).mappings()
    }
    forecast = (
        c.execute(
            select(f, r.c.version)
            .join(
                r,
                (r.c.tenant_id == f.c.tenant_id)
                & (r.c.project_id == f.c.project_id)
                & (r.c.id == f.c.record_id),
            )
            .where(f.c.tenant_id == context.tenant.id, f.c.project_id == identity)
            .order_by(r.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    plan_keys = {v["node_id"] for v in basis["tasks"]}
    if set(base) != plan_keys or not base or any(v["end"] is None for v in base.values()):
        item["missing"].append("正式基线节点或日期不完整")
        finish = None
    else:
        finish = max(v["end"] for v in base.values())
    item.update(
        baseline_id=basis["baseline_id"],
        baseline_version=basis["baseline_version"],
        baseline_finish=finish.isoformat() if finish else None,
    )
    predicted: dict[str, Any] = {}
    if forecast:
        result = forecast["result"]
        item["forecast_href"] = (
            f"/projects?project={identity}&tab=overview&forecast={forecast['record_id']}"
            "#schedule-forecasts"
        )
        item.update(
            forecast_id=str(forecast["record_id"]),
            forecast_version=forecast["version"],
            forecast_finish=result.get("project_finish"),
            forecast_as_of=result.get("as_of"),
        )
        reasons = []
        if forecast["basis_digest"] != current["basis_digest"]:
            reasons.append("预测来源已变化，请沿原排程重算")
        if not result.get("complete") or not result.get("project_finish"):
            reasons.append("保存预测包含未知或阻塞日期")
        as_of = datetime.fromisoformat(result["as_of"])
        if as_of > now:
            reasons.append("预测基准时间晚于本次读取")
        if age_policy and as_of < now - timedelta(hours=age_policy.max_forecast_age_hours):
            reasons.append("预测超出当前健康政策允许账龄")
        item["missing"].extend(reasons)
        item["forecast_current"] = not reasons
        if not reasons and finish:
            delta = datetime.fromisoformat(result["project_finish"]) - finish
            item["delay_days"] = str(Decimal(str(delta.total_seconds())) / 86400)
        predicted = {v["node_key"]: v for v in result.get("nodes", [])}
        item["float_status"] = result.get("float_status")
    else:
        item["missing"].append("尚无保存预测")
    item["coverage_missing"] = list(item["missing"])
    if age_policy is None:
        item["coverage_missing"].append("缺少当前有效的预测账龄政策，当前覆盖率不可评估")
    coverage_usable = item["forecast_current"] and age_policy is not None
    ranked = (
        commitments(context.tenant.id, identity)
        .add_columns(
            func.row_number()
            .over(partition_by=n.c.node_id, order_by=r.c.version.desc())
            .label("position")
        )
        .subquery()
    )
    promises = {
        str(v["node_id"]): v
        for v in c.execute(select(ranked).where(ranked.c.position == 1)).mappings()
    }
    designations = records(c, context.tenant.id, identity)
    plan_nodes = {v["node_key"]: v for v in basis["plan"]["nodes"]}
    nodes = []
    for state in basis["tasks"]:
        node_id, key = state["node_id"], state["node_key"]
        baseline = base.get(node_id)
        actual = state.get("actual_finish")
        missing = state.get("input_unknown", [])
        completed = state.get("status") == "done" and bool(actual) and not missing
        value = predicted.get(key, {})
        coverage_missing = list(item["coverage_missing"])
        coverage_missing.extend(missing)
        if not value.get("finish") or not value.get("start"):
            coverage_missing.append("本节点缺少完整保存预测日期")
        covered = coverage_usable and not coverage_missing
        critical = (
            value.get("critical")
            if covered and item["float_status"] == "calculated" and not completed
            else None
        )
        promise = promises.get(node_id)
        designation = designations.get(UUID(node_id), [])
        comparison_missing = []
        promise_delay = None
        if promise is None or promise["end"] is None:
            comparison_missing.append("缺少本节点具名承诺或完成期限")
        elif promise["approved_at"] is None or promise["approved_at"] > now:
            comparison_missing.append("承诺确认时间缺失或晚于本次读取")
        elif covered:
            delta = datetime.fromisoformat(value["finish"]) - promise["end"]
            promise_delay = str(Decimal(str(delta.total_seconds())) / 86400)
        if not covered:
            comparison_missing.extend(coverage_missing)
        source_ref = {
            k: state.get(k)
            for k in (
                "actual_start_event",
                "actual_finish_event",
                "actual_observation",
                "actual_correction",
                "source_digest",
                "completion_basis",
            )
            if state.get(k) is not None
        }
        nodes.append(
            {
                "node_id": node_id,
                "node_key": key,
                "kind": state["node_kind"],
                "business_designation": _plain(designation[0]) if designation else None,
                "business_designation_source_current": (
                    designation[0]["snapshot"] == node_snapshot(plan_nodes.get(key, {}))
                )
                if designation
                else None,
                "title": current["titles"].get(key, key),
                "status": state["status"],
                "task_id": state.get("task_id"),
                "owner_user_id": state.get("assignee_user_id"),
                "baseline_start": baseline["start"].isoformat()
                if baseline and baseline["start"]
                else None,
                "baseline_finish": baseline["end"].isoformat()
                if baseline and baseline["end"]
                else None,
                "saved_forecast_start": value.get("start"),
                "saved_forecast_finish": value.get("finish"),
                "saved_critical": value.get("critical"),
                "saved_total_float_minutes": value.get("total_float_minutes"),
                "saved_working_float_minutes": value.get("working_float_minutes"),
                "float_dimension": value.get("float_dimension"),
                "critical": critical,
                "forecast_covered": covered if not completed and age_policy else None,
                "coverage_missing": coverage_missing if not completed else [],
                "commitment": _plain(promise) if promise else None,
                "commitment_delay_days": promise_delay if not completed else None,
                "commitment_comparison_missing": comparison_missing if not completed else [],
                "actual_start": state.get("actual_start"),
                "actual_finish": actual,
                "completed_with_evidence": completed,
                "missing": missing,
                "evidence": source_ref,
                "href": f"/projects?project={identity}&tab=tasks&entity_id={state['task_id']}"
                if state.get("task_id")
                else item["href"],
            }
        )
    nodes.sort(
        key=lambda v: (v["kind"] != "milestone", v["baseline_finish"] or "9999", v["node_id"])
    )
    completed_count = sum(v["completed_with_evidence"] for v in nodes)
    unfinished = [v for v in nodes if not v["completed_with_evidence"]]
    covered_count = sum(v["forecast_covered"] is True for v in unfinished)
    milestones = [v for v in unfinished if v["kind"] == "milestone"]
    key_milestones = [
        v
        for v in milestones
        if v["business_designation"] and v["business_designation"]["is_key"] is True
    ]
    item.update(
        node_count=len(nodes),
        completed_count=completed_count,
        completion_percent=str(Decimal(completed_count) * 100 / len(nodes)) if nodes else None,
        blocked_count=sum(v["status"] == "blocked" for v in nodes),
        unknown_count=sum(bool(v["missing"]) for v in nodes),
        unfinished_count=len(unfinished),
        covered_count=covered_count if age_policy else None,
        coverage_percent=str(Decimal(covered_count) * 100 / len(unfinished))
        if unfinished and age_policy
        else None,
        forecast_gap_count=sum(v["forecast_covered"] is not True for v in unfinished),
        key_milestone_unfinished_count=len(key_milestones),
        key_milestone_covered_count=sum(
            v["forecast_covered"] is True and v["business_designation_source_current"] is True
            for v in key_milestones
        )
        if age_policy
        else None,
        unclassified_milestone_count=sum(v["business_designation"] is None for v in milestones),
        designation_recheck_count=sum(
            v["business_designation_source_current"] is False for v in milestones
        ),
        critical_count=sum(v["critical"] is True for v in unfinished),
        critical_unknown_count=sum(v["critical"] is None for v in unfinished),
        evidence_digest=digest(nodes),
        basis_digest=current["basis_digest"],
    )
    return item, nodes


class PortfolioProgressService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: ProgressRead) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            p = tables.projects
            query = select(p).where(p.c.tenant_id == context.tenant.id)
            if context.user.role not in (Role.OWNER, Role.ADMIN):
                principals = active_delegated_principals(
                    c, tenant_id=context.tenant.id, delegate_user_id=context.user.id, moment=now
                )
                query = query.where(
                    p.c.id.in_(
                        select(tables.project_members.c.project_id).where(
                            tables.project_members.c.tenant_id == context.tenant.id,
                            tables.project_members.c.user_id.in_((context.user.id, *principals)),
                        )
                    )
                )
            if command.search:
                query = query.where(
                    (p.c.code.icontains(command.search, autoescape=True))
                    | (p.c.name.icontains(command.search, autoescape=True))
                )
            if command.project_status:
                query = query.where(p.c.status == command.project_status)
            projects = list(c.execute(query.order_by(p.c.id)).mappings())
            can_gates = is_allowed(context.user.role, Action.GATE_VIEW)
            t = tables.tasks
            conditions: dict[UUID, int] = (
                {
                    project_id: amount
                    for project_id, amount in c.execute(
                        select(t.c.project_id, func.count())
                        .where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.project_id.in_([p["id"] for p in projects]),
                            t.c.kind == "gate_action",
                            t.c.source_entity_type == "gate",
                            t.c.status != "done",
                        )
                        .group_by(t.c.project_id)
                    ).all()
                }
                if can_gates
                else {}
            )
            active_policy = policy(c, context, now)
            items = []
            for project in projects:
                item, _ = capture(c, context, project, now, active_policy)
                item["open_gate_conditions"] = (
                    conditions.get(project["id"], 0) if can_gates else None
                )
                items.append(item)

            def sort_key(v: dict[str, Any]) -> tuple[Any, ...]:
                key = {
                    "deviation": "delay_days",
                    "blocked": "blocked_count",
                    "conditions": "open_gate_conditions",
                    "coverage": "forecast_gap_count",
                    "critical": "critical_count",
                }.get(command.order)
                if key is None:
                    return (v["code"], v["project_id"])
                value = v[key]
                return (
                    value is None,
                    -Decimal(str(value)) if value is not None else Decimal(0),
                    v["code"],
                    v["project_id"],
                )

            items.sort(key=sort_key)
            revision = digest(
                {
                    "items": items,
                    "order": command.order,
                    "policy": active_policy.model_dump(mode="json") if active_policy else None,
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("项目进度、读取范围或政策已变化，请刷新第一页")
            missing_plan = sum(v["node_count"] is None for v in items)
            unfinished = sum(v["unfinished_count"] or 0 for v in items)
            covered = sum(v["covered_count"] or 0 for v in items)
            return {
                "items": items[command.offset : command.offset + 20],
                "total": len(items),
                "next_offset": command.offset + 20 if command.offset + 20 < len(items) else None,
                "revision": revision,
                "as_of": now.isoformat(),
                "coverage_summary": {
                    "projects_without_formal_basis": missing_plan,
                    "known_unfinished_count": unfinished,
                    "known_covered_count": covered if active_policy else None,
                    "coverage_percent": str(Decimal(covered) * 100 / unfinished)
                    if active_policy and not missing_plan and unfinished
                    else None,
                    "known_critical_count": sum(v["critical_count"] or 0 for v in items),
                    "critical_unknown_count": sum(v["critical_unknown_count"] or 0 for v in items),
                },
                "forecast_max_age_hours": active_policy.max_forecast_age_hours
                if active_policy
                else None,
                "scope": "all_visible_projects_matching_filters; current_formal_nodes_only",
                "formula": (
                    "evidence_completed_nodes / current_formal_nodes; equal_node_count_not_effort"
                ),
            }

    def detail(self, context: AuthContext, command: ProgressDetail) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            project = _project(c, context, command.project_id)
            item, nodes = capture(c, context, project, now, policy(c, context, now))
            selected = [
                v
                for v in nodes
                if (
                    command.focus == "all"
                    or (command.focus == "milestones" and v["kind"] == "milestone")
                    or (
                        command.focus == "key_milestones"
                        and v["business_designation"]
                        and v["business_designation"]["is_key"] is True
                    )
                    or (command.focus == "critical" and v["critical"] is True)
                    or (
                        command.focus == "gaps"
                        and not v["completed_with_evidence"]
                        and v["forecast_covered"] is not True
                    )
                    or (
                        command.focus == "critical_unknown"
                        and not v["completed_with_evidence"]
                        and v["critical"] is None
                    )
                )
            ]
            revision = digest({"item": item, "nodes": nodes, "focus": command.focus})
            if command.offset and command.revision != revision:
                raise ProductWorkError("节点依据或预测已变化，请重新读取项目进度")
            return {
                "summary": item,
                "items": selected[command.offset : command.offset + 30],
                "total": len(selected),
                "revision": revision,
                "as_of": now.isoformat(),
                "next_offset": command.offset + 30 if command.offset + 30 < len(selected) else None,
            }

    def history(self, context: AuthContext, command: ProgressForecastHistory) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _project(c, context, command.project_id)
            q = forecast_history_query(context.tenant.id, command.project_id).subquery()
            query = select(q)
            if command.before_version:
                query = query.where(q.c.version < command.before_version)
            records = list(c.execute(query.order_by(q.c.version.desc()).limit(31)).mappings())
            items = []
            for record in records[:30]:
                result = record["result"]
                nodes = result.get("nodes", [])
                previous = record["previous_saved_at"]
                interval = (record["created_at"] - previous).total_seconds() if previous else None
                items.append(
                    {
                        **_plain(
                            {
                                k: record[k]
                                for k in (
                                    "record_id",
                                    "version",
                                    "baseline_id",
                                    "created_at",
                                    "previous_saved_at",
                                    "reason",
                                    "trigger",
                                    "created_by_user_id",
                                    "basis_digest",
                                )
                            }
                        ),
                        "as_of": result.get("as_of"),
                        "project_finish": result.get("project_finish"),
                        "complete": result.get("complete"),
                        "float_status": result.get("float_status"),
                        "node_count": len(nodes),
                        "dated_node_count": sum(
                            bool(v.get("start") and v.get("finish")) for v in nodes
                        ),
                        "saved_critical_count": sum(v.get("critical") is True for v in nodes),
                        "saved_critical_unknown_count": sum(
                            v.get("critical") is None for v in nodes
                        ),
                        "save_interval_hours": str(Decimal(str(interval)) / 3600)
                        if interval is not None and interval >= 0
                        else None,
                        "href": (
                            f"/projects?project={command.project_id}&tab=overview"
                            f"&forecast={record['record_id']}#schedule-forecasts"
                        ),
                    }
                )
            return {
                "items": items,
                "next_before_version": records[29]["version"] if len(records) > 30 else None,
                "scope": "saved_project_forecasts; intervals_do_not_prove_continuous_validity",
            }
