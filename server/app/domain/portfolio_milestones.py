"""Deadline cohorts of named milestone commitments, with original evidence retained."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import Connection, DateTime, Engine, cast, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.milestone_designations import at, records
from app.domain.organization import active_delegated_principals
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import _project
from app.domain.schedule_source_actuals import latest_observations

ZONE = ZoneInfo("Asia/Shanghai")
OUTCOMES = {
    "on_time": "按期完成",
    "late": "延期完成",
    "overdue_open": "已到期未完成",
    "pending": "尚未到期",
    "unknown": "实际或适用依据待核对",
    "uncommitted": "尚无具名承诺",
}


class MilestoneRead(Contract):
    start_date: date
    end_date: date
    project_id: UUID | None = None
    include_uncommitted: bool = True
    importance: Literal["all", "key", "routine", "unclassified"] = "all"
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def interval(self) -> "MilestoneRead":
        if not timedelta(0) <= self.end_date - self.start_date <= timedelta(days=3660):
            raise ValueError("请选择先后有序、最多十年的承诺到期区间")
        return self


class MilestoneHistory(Contract):
    project_id: UUID
    node_id: UUID
    before_version: int | None = Field(default=None, ge=1)


def commitments(tenant_id: UUID, project_id: UUID, node_id: UUID | None = None) -> Any:
    t, r, a = (
        tables.schedule_time_nodes,
        tables.schedule_time_records,
        tables.schedule_commitment_confirmations,
    )
    query = select(
        t.c.node_id,
        t.c.start,
        t.c.end,
        r.c.version,
        r.c.id.label("record_id"),
        a.c.id.label("confirmation_id"),
        a.c.created_at,
        cast(r.c.contract["approval"]["approved_at"].as_string(), DateTime(timezone=True)).label(
            "approved_at"
        ),
        a.c.approved_by_user_id,
        select(tables.users.c.display_name)
        .where(
            tables.users.c.tenant_id == tenant_id,
            tables.users.c.id == a.c.approved_by_user_id,
        )
        .correlate(a)
        .scalar_subquery()
        .label("approved_by_name"),
        a.c.forecast_record_id,
        a.c.scope_label,
        a.c.reason,
        a.c.policy_id,
    ).select_from(
        t.join(
            r,
            (t.c.tenant_id == r.c.tenant_id)
            & (t.c.project_id == r.c.project_id)
            & (t.c.record_id == r.c.id),
        ).join(
            a,
            (a.c.tenant_id == r.c.tenant_id)
            & (a.c.project_id == r.c.project_id)
            & (a.c.record_id == r.c.id),
        )
    )
    query = query.where(
        t.c.tenant_id == tenant_id, t.c.project_id == project_id, r.c.time_kind == "commitment"
    )
    return query.where(t.c.node_id == node_id) if node_id else query


def outcome(
    commitment: Any | None,
    observation: Any | None,
    completion: Any | None,
    in_plan: bool,
    now: datetime,
) -> tuple[str, list[str]]:
    if commitment is None:
        return "uncommitted", ["未用项目目标日或基线替代人工承诺"]
    due = commitment["end"]
    if due is None:
        return "unknown", ["原承诺缺少完成期限"]
    confirmed = commitment["approved_at"]
    if confirmed is None or confirmed > due:
        return "unknown", ["具名确认时间缺失或晚于原承诺期限"]
    if observation and observation.get("correction_conflict"):
        return "unknown", [observation["correction_conflict"]]
    actual = observation.get("finished_at") if observation else None
    if actual:
        if not completion or not observation or observation.get("successful") is not True:
            return "unknown", ["缺少正式完成回执或观察未表明完成有效"]
        if actual > now:
            return "unknown", ["实际完成时间晚于本次读取时间"]
        if confirmed > actual:
            return "unknown", ["承诺确认晚于实际完成或原期限，不能据此计算按期兑现"]
        return ("on_time" if actual <= due else "late"), []
    if completion or (observation and observation.get("source_status") == "completed"):
        return "unknown", ["原完成办理存在，但有效实际结束时间缺失"]
    if not in_plan:
        return "unknown", ["节点已不在当前正式计划，原承诺仍保留，须核对后续处置"]
    return ("overdue_open" if due <= now else "pending"), []


def project_items(
    c: Connection, context: AuthContext, project: Any, now: datetime
) -> list[dict[str, Any]]:
    tenant, identity = context.tenant.id, project["id"]
    n, r, t = tables.schedule_nodes, tables.schedule_time_records, tables.schedule_time_nodes
    nodes = list(
        c.execute(
            select(n).where(
                n.c.tenant_id == tenant, n.c.project_id == identity, n.c.node_kind == "milestone"
            )
        ).mappings()
    )
    if not nodes:
        return []
    ranked = (
        commitments(tenant, identity)
        .add_columns(
            func.row_number()
            .over(partition_by=t.c.node_id, order_by=r.c.version.desc())
            .label("position")
        )
        .subquery()
    )
    latest = {
        v["node_id"]: v for v in c.execute(select(ranked).where(ranked.c.position == 1)).mappings()
    }
    baseline = (
        select(r.c.id)
        .where(r.c.tenant_id == tenant, r.c.project_id == identity, r.c.time_kind == "baseline")
        .order_by(r.c.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    current = set(
        c.execute(
            select(t.c.node_id).where(
                t.c.tenant_id == tenant, t.c.project_id == identity, t.c.record_id == baseline
            )
        ).scalars()
    )
    observations = {v["node_id"]: v for v in latest_observations(c, tenant, identity)}
    complete = tables.schedule_milestone_completions
    completed = {
        v["node_id"]: v
        for v in c.execute(
            select(complete).where(
                complete.c.tenant_id == tenant, complete.c.project_id == identity
            )
        ).mappings()
    }
    designations = records(c, tenant, identity, latest_only=False)
    result = []
    for node in nodes:
        node_id = node["id"]
        promise, actual, done = (
            latest.get(node_id),
            observations.get(node_id),
            completed.get(node_id),
        )
        state, missing = outcome(promise, actual, done, node_id in current, now)
        due = promise["end"] if promise else None
        # Freeze the selection point before a result or deadline can be cherry-picked.
        occurred = [
            v
            for v in (due, actual.get("finished_at") if actual else None)
            if v is not None and v <= now
        ]
        frozen_at = min(occurred) if occurred else None
        selection_at = frozen_at or now
        history = designations.get(node_id, [])
        designation = at(history, selection_at)
        result.append(
            {
                "project_id": str(identity),
                "project_code": project["code"],
                "project_name": project["name"],
                "node_id": str(node_id),
                "title": node["title"],
                "importance": "key"
                if designation and designation["is_key"]
                else "routine"
                if designation
                else "unclassified",
                "designation": _plain(designation) if designation else None,
                "current_designation": _plain(history[0]) if history else None,
                "designation_selection_at": frozen_at.isoformat() if frozen_at else None,
                "in_current_plan": node_id in current,
                "commitment": _plain(promise) if promise else None,
                "due_at": due.isoformat() if due else None,
                "due_date": due.astimezone(ZONE).date().isoformat() if due else None,
                "matured": bool(due and due <= now),
                "outcome": state,
                "missing": missing,
                "actual_finish": actual["finished_at"].isoformat()
                if actual and actual["finished_at"]
                else None,
                "actual": _plain(
                    {
                        k: actual.get(k)
                        for k in (
                            "id",
                            "version",
                            "event_row_id",
                            "audit_row_id",
                            "actual_correction",
                            "source_status",
                            "successful",
                        )
                    }
                )
                if actual
                else None,
                "completion_id": str(done["id"]) if done else None,
                "href": f"/projects?project={identity}&tab=overview&commitment_node={node_id}"
                "#schedule-commitments",
            }
        )
    return result


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    due = [v for v in items if v["matured"]]
    counts = {key: sum(v["outcome"] == key for v in items) for key in OUTCOMES}
    unknown = sum(v["outcome"] == "unknown" for v in due)
    on_time = sum(v["outcome"] == "on_time" for v in due)
    return {
        "total": len(items),
        "matured": len(due),
        "on_time_matured": on_time,
        "unknown_matured": unknown,
        "counts": counts,
        "rate_percent": str(Decimal(on_time) * 100 / len(due)) if due and not unknown else None,
    }


class PortfolioMilestoneService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: MilestoneRead) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            p = tables.projects
            query = select(p).where(p.c.tenant_id == context.tenant.id)
            if command.project_id:
                _project(c, context, command.project_id)
                query = query.where(p.c.id == command.project_id)
            elif context.user.role not in (Role.OWNER, Role.ADMIN):
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
            projects = list(c.execute(query.order_by(p.c.id)).mappings())
            all_items = [
                item for project in projects for item in project_items(c, context, project, now)
            ]
            registered_count = len(all_items)
            importance_counts = {
                k: sum(v["importance"] == k for v in all_items)
                for k in ("key", "routine", "unclassified")
            }
            all_items = [
                v
                for v in all_items
                if command.importance == "all" or v["importance"] == command.importance
            ]
            selected = [
                v
                for v in all_items
                if v["due_date"]
                and command.start_date.isoformat() <= v["due_date"] <= command.end_date.isoformat()
            ]
            # Uncommitted/missing-deadline rows cannot be assigned to a date cohort.
            undated = [v for v in all_items if v["due_date"] is None]
            selected.sort(key=lambda v: (v["due_at"], v["project_code"], v["node_id"]))
            buckets = []
            month = command.start_date.replace(day=1)
            while month <= command.end_date:
                key = month.strftime("%Y-%m")
                buckets.append(
                    {
                        "month": key,
                        **summarize([v for v in selected if v["due_date"].startswith(key)]),
                    }
                )
                if (month.year, month.month) == (command.end_date.year, command.end_date.month):
                    break
                month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            items = (
                selected + sorted(undated, key=lambda v: (v["project_code"], v["node_id"]))
                if command.include_uncommitted
                else selected
            )
            revision = digest(
                {
                    "items": items,
                    "buckets": buckets,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and revision != command.revision:
                raise ProductWorkError("承诺、实际依据或读取范围已变化，请刷新第一页")
            page = []
            for v in items[command.offset : command.offset + 30]:
                due = datetime.fromisoformat(v["due_at"]) if v["due_at"] else None
                page.append(
                    {
                        **v,
                        "remaining_natural_days": str(
                            Decimal(str((due - now).total_seconds())) / 86400
                        )
                        if due
                        else None,
                    }
                )
            return {
                "items": page,
                "total": len(items),
                "next_offset": command.offset + 30 if command.offset + 30 < len(items) else None,
                "revision": revision,
                "as_of": now.isoformat(),
                "summary": summarize(selected),
                "buckets": buckets,
                "registered_milestones": registered_count,
                "importance_counts": importance_counts,
                "importance": command.importance,
                "undated_count": len(undated),
                "outside_window_count": len(all_items) - len(selected) - len(undated),
                "project_count": len(projects),
                "scope": "registered_independent_milestones; latest_named_commitment_per_node",
                "formula_version": "commitment_due_cohort.v1",
                "cohort_timezone": "Asia/Shanghai",
                "history_mode": (
                    "recomputed_from_latest_commitment_and_effective_actual; not_as_was_snapshot"
                ),
            }

    def history(self, context: AuthContext, command: MilestoneHistory) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _project(c, context, command.project_id)
            n = tables.schedule_nodes
            node = (
                c.execute(
                    select(n).where(
                        n.c.tenant_id == context.tenant.id,
                        n.c.project_id == command.project_id,
                        n.c.id == command.node_id,
                        n.c.node_kind == "milestone",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if node is None:
                raise ProductWorkError("里程碑不存在或不在本项目")
            r = tables.schedule_time_records
            query = commitments(context.tenant.id, command.project_id, command.node_id)
            if command.before_version:
                query = query.where(r.c.version < command.before_version)
            records = list(c.execute(query.order_by(r.c.version.desc()).limit(31)).mappings())
            return {
                "node_id": str(node["id"]),
                "title": node["title"],
                "items": [_plain(v) for v in records[:30]],
                "next_before_version": records[29]["version"] if len(records) > 30 else None,
            }
