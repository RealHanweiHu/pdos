"""Read-only current resource ledger pressure, preserving private project boundaries."""

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.organization import active_delegated_principals
from app.domain.plan_scenarios import _calendar_access
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_priorities import PREFIX, latest
from app.domain.resource_reservations import legacy_inventory_missing
from app.domain.working_time import CalendarDefinition, WorkingTime


class ResourceWindow(Contract):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def window(self) -> Self:
        if not timedelta(0) < self.end - self.start <= timedelta(days=366):
            raise ValueError("请选择一年以内的正向资源观察区间")
        return self


class ResourceOverview(ResourceWindow):
    search: str = Field(default="", max_length=200)
    project_id: UUID | None = None
    focus: Literal["all", "attention", "conflict", "unknown"] = "attention"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


class ResourceDetail(ResourceWindow):
    resource_id: UUID
    expected_digest: Digest
    part: Literal["segments", "bookings"] = "segments"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


def projects(c: Connection, context: AuthContext, now: datetime) -> dict[UUID, Any]:
    p, m = tables.projects, tables.project_members
    q = select(p.c.id, p.c.code, p.c.name).where(p.c.tenant_id == context.tenant.id)
    if context.user.role not in (Role.OWNER, Role.ADMIN):
        principals = active_delegated_principals(
            c, tenant_id=context.tenant.id, delegate_user_id=context.user.id, moment=now
        )
        q = q.where(
            p.c.id.in_(
                select(m.c.project_id).where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.user_id.in_((context.user.id, *principals)),
                )
            )
        )
    return {v["id"]: v for v in c.execute(q.order_by(p.c.code, p.c.id)).mappings()}


def capture(
    c: Connection,
    context: AuthContext,
    resource: Any,
    window: ResourceWindow,
    now: datetime,
    visible: dict[UUID, Any],
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    tenant, identity = context.tenant.id, resource["id"]
    cap, cal = tables.resource_capacity_versions, tables.work_calendar_versions
    profile = (
        c.execute(
            select(
                cap,
                cal.c.definition.label("calendar_definition"),
                cal.c.name.label("calendar_name"),
            )
            .join(
                cal, (cal.c.tenant_id == cap.c.tenant_id) & (cal.c.id == cap.c.calendar_version_id)
            )
            .where(cap.c.tenant_id == tenant, cap.c.resource_id == identity)
            .order_by(cap.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    missing = []
    usable = profile is not None
    if profile is None:
        missing.append("尚无已发布容量")
    else:
        calendar = WorkingTime(CalendarDefinition.model_validate(profile["calendar_definition"]))
        if _plain(asdict(calendar.evidence)) != profile["calendar_evidence"]:
            missing.append("容量发布后的时区规则有变化，需重新发布")
            usable = False
    if resource["user_id"]:
        u = tables.users
        active = c.execute(
            select(u.c.id).where(
                u.c.tenant_id == tenant,
                u.c.id == resource["user_id"],
                u.c.is_active.is_(True),
                u.c.role.in_(("owner", "admin", "project_manager", "engineer", "quality")),
            )
        ).first()
        if active is None:
            missing.append("资源关联人员已不可用")
            usable = False
    legacy_missing = legacy_inventory_missing(c, context, resource)
    if legacy_missing:
        missing.append("仍有旧占用未完成资源归并，已知占用不能代表全部")
    intervals = tables.resource_capacity_intervals
    available = (
        list(
            c.execute(
                select(intervals.c.start, intervals.c.end).where(
                    intervals.c.tenant_id == tenant,
                    intervals.c.capacity_version_id == profile["id"],
                )
            ).mappings()
        )
        if profile
        else []
    )
    if profile and not available:
        missing.append("容量版本尚无可核对时段")
        usable = False
    policy = latest(c, tenant, identity)
    policy_current = bool(
        policy
        and policy["status"] == "active"
        and policy["valid_from"] <= now < policy["valid_until"]
    )
    r, i, p, binding, u = (
        tables.resource_reservations,
        tables.resource_reservation_intervals,
        tables.projects,
        tables.resource_priority_bindings,
        tables.users,
    )
    bookings = list(
        c.execute(
            select(
                r,
                p.c.status.label("project_status"),
                binding.c.policy_id.label("priority_id"),
                binding.c.rank,
                u.c.display_name.label("owner_name"),
            )
            .select_from(
                r.join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
                .outerjoin(
                    binding,
                    (binding.c.tenant_id == r.c.tenant_id) & (binding.c.reservation_id == r.c.id),
                )
                .outerjoin(u, (u.c.tenant_id == r.c.tenant_id) & (u.c.id == r.c.owner_user_id))
            )
            .where(
                r.c.tenant_id == tenant,
                r.c.resource_id == identity,
                r.c.state.in_(("reserved", "proposed")),
                r.c.window_start < window.end,
                r.c.window_end > window.start,
            )
            .order_by(r.c.created_at, r.c.id)
        ).mappings()
    )
    spans = list(
        c.execute(
            select(i.c.reservation_id, i.c.start, i.c.end).where(
                i.c.tenant_id == tenant,
                i.c.reservation_id.in_({v["id"] for v in bookings}),
                i.c.start < window.end,
                i.c.end > window.start,
            )
        ).mappings()
    )
    legacy = list(
        c.execute(
            text(
                'SELECT start,"end",parallel_units '
                "FROM cehub_project.current_legacy_resource_allocations "
                "WHERE tenant_id=:tenant AND resource_id=:resource "
                'AND start<:end AND "end">:start ORDER BY start,"end",parallel_units'
            ),
            {"tenant": tenant, "resource": identity, "start": window.start, "end": window.end},
        ).mappings()
    )
    if len(spans) + len(legacy) + len(available) > 100000:
        raise ProductWorkError("资源占用区间超过读取上限，请缩小观察时间范围")
    identities = {v["id"]: v for v in bookings}
    eligible: set[UUID] = set()
    booking_views = []
    blocked = 0
    interval_ids = {v["reservation_id"] for v in spans}
    for row in bookings:
        reasons = []
        if row["state"] == "proposed":
            if (
                not policy_current
                or row["priority_id"] != (policy["id"] if policy else None)
                or row["contract"]["priority_policy_version"]
                != PREFIX + str(policy["id"] if policy else "")
            ):
                reasons.append("优先级政策已变化或未生效")
            if not profile or row["capacity_version_id"] != profile["id"]:
                reasons.append("容量版本已变化或缺失")
            elif (
                row["window_start"] < profile["window_start"]
                or row["window_end"] > profile["window_end"]
                or row["parallel_units"] > profile["parallel_units"]
            ):
                reasons.append("原提案超出当前容量窗口或单位上限")
            if row["project_status"] not in ("approved", "active"):
                reasons.append("项目尚不满足执行状态")
            if row["window_end"] <= now:
                reasons.append("原提案窗口已结束")
            if not usable or legacy_missing:
                reasons.append("资源容量或原占用需重核")
            if (
                row["id"] not in interval_ids
                and c.execute(
                    select(i.c.start).where(
                        i.c.tenant_id == tenant, i.c.reservation_id == row["id"]
                    )
                ).first()
                is None
            ):
                reasons.append("原提案缺少占用时段")
            if reasons:
                blocked += 1
            elif row["id"] in interval_ids:
                eligible.add(row["id"])
        elif row["id"] not in interval_ids:
            # Working-only bookings can legitimately have no spans in an off-hours selection.
            has_spans = c.execute(
                select(i.c.start).where(i.c.tenant_id == tenant, i.c.reservation_id == row["id"])
            ).first()
            if has_spans is None:
                missing.append("已确认预约缺少实际占用时段")
        if row["project_id"] in visible:
            project = visible[row["project_id"]]
            booking_views.append(
                {
                    "id": str(row["id"]),
                    "project_id": str(row["project_id"]),
                    "project_code": project["code"],
                    "project_name": project["name"],
                    "owner_name": row["owner_name"],
                    "state": row["state"],
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    "parallel_units": row["parallel_units"],
                    "rank": row["rank"],
                    "created_at": row["created_at"],
                    "capacity_version_id": row["capacity_version_id"],
                    "reasons": reasons,
                    "priority_conflict": bool(
                        c.execute(
                            select(func.cehub_project.resource_priority_conflict(tenant, row["id"]))
                        ).scalar_one()
                    )
                    if row["id"] in eligible
                    else None,
                    "version": row["version"],
                    "owner_user_id": str(row["owner_user_id"]),
                    "window_has_intervals": row["id"] in interval_ids,
                    "href": (
                        f"/projects?project={row['project_id']}&tab=overview"
                        f"&resource_reservation_id={row['id']}#resource-reservations"
                    ),
                }
            )
    points: dict[datetime, list[tuple[str, Decimal]]] = {window.start: [], window.end: []}

    def add(start: datetime, end: datetime, kind: str, units: Decimal) -> None:
        left, right = max(start, window.start), min(end, window.end)
        if left < right:
            points.setdefault(left, []).append((kind, units))
            points.setdefault(right, []).append((kind, -units))

    for span in spans:
        row = identities[span["reservation_id"]]
        if row["state"] == "reserved":
            add(span["start"], span["end"], "confirmed", row["parallel_units"])
            if row["project_id"] not in visible:
                add(span["start"], span["end"], "private_confirmed", row["parallel_units"])
        elif row["id"] in eligible:
            add(span["start"], span["end"], "pending", row["parallel_units"])
    for span in legacy:
        add(span["start"], span["end"], "legacy", span["parallel_units"])
    if profile:
        for at in (profile["window_start"], profile["window_end"]):
            if window.start < at < window.end:
                points.setdefault(at, [])
        if usable:
            for span in available:
                add(span["start"], span["end"], "capacity", profile["parallel_units"])
    running = {
        key: Decimal(0)
        for key in ("confirmed", "private_confirmed", "pending", "legacy", "capacity")
    }
    segments: list[dict[str, Any]] = []
    ordered = sorted(points)
    for index, left in enumerate(ordered[:-1]):
        for key, delta in points[left]:
            running[key] += delta
        right = ordered[index + 1]
        known = bool(
            usable
            and profile
            and profile["window_start"] <= left
            and right <= profile["window_end"]
        )
        occupied = running["confirmed"] + running["legacy"]
        status = (
            "unknown"
            if not known
            else "conflict"
            if occupied > running["capacity"]
            else "contention"
            if occupied + running["pending"] > running["capacity"]
            else "unknown"
            if missing
            else "clear"
        )
        segment = {
            "start": left.isoformat(),
            "end": right.isoformat(),
            "status": status,
            "capacity": str(running["capacity"]) if known else None,
            **{
                key: str(running[key])
                for key in ("confirmed", "private_confirmed", "pending", "legacy")
            },
        }
        if (
            segments
            and segments[-1]["end"] == segment["start"]
            and all(segments[-1][k] == v for k, v in segment.items() if k not in ("start", "end"))
        ):
            segments[-1]["end"] = segment["end"]
        else:
            segments.append(segment)
    summary = {
        "id": str(identity),
        "name": resource["name"],
        "kind": resource["kind"],
        "capacity_version": profile["version"] if profile else None,
        "capacity_id": str(profile["id"]) if profile else None,
        "capacity_start": profile["window_start"] if profile else None,
        "capacity_end": profile["window_end"] if profile else None,
        "calendar_name": profile["calendar_name"] if profile else None,
        "policy_version": policy["version"] if policy else None,
        "policy_current": policy_current,
        "legacy_missing": legacy_missing,
        "missing": sorted(set(missing)),
        "visible_bookings": len(booking_views),
        "proposal_needs_review": blocked,
        "status": "conflict"
        if any(v["status"] == "conflict" for v in segments)
        else "contention"
        if any(v["status"] == "contention" for v in segments)
        else "unknown"
        if missing or any(v["status"] == "unknown" for v in segments)
        else "clear",
        "segments": len(segments),
        "attention_segments": sum(v["status"] != "clear" for v in segments),
        "peak_confirmed_units": str(
            max(
                (Decimal(v["confirmed"]) + Decimal(v["legacy"]) for v in segments),
                default=Decimal(0),
            )
        ),
    }
    views = [_plain(v) for v in booking_views]
    summary = _plain(summary)
    summary["source_digest"] = digest({"summary": summary, "segments": segments, "bookings": views})
    return summary, segments, views


class PortfolioResourceService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def authorize(context: AuthContext) -> None:
        _calendar_access(context)
        _role(context, Action.WORK_ITEM_VIEW)

    def read(self, context: AuthContext, command: ResourceOverview) -> dict[str, Any]:
        self.authorize(context)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 48
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            visible = projects(c, context, now)
            r, b = tables.planning_resources, tables.resource_reservations
            q = select(r).where(r.c.tenant_id == context.tenant.id)
            if command.search:
                q = q.where(r.c.name.icontains(command.search, autoescape=True))
            if command.project_id:
                if command.project_id not in visible:
                    raise ProductWorkError("所选项目当前不可读取")
                q = q.where(
                    r.c.id.in_(
                        select(b.c.resource_id).where(
                            b.c.tenant_id == context.tenant.id,
                            b.c.project_id == command.project_id,
                            b.c.state.in_(("reserved", "proposed")),
                            b.c.window_start < command.end,
                            b.c.window_end > command.start,
                        )
                    )
                )
            items = [
                capture(c, context, row, command, now, visible)[0]
                for row in c.execute(q.order_by(r.c.id)).mappings()
            ]
            counts = {
                key: sum(v["status"] == key for v in items)
                for key in ("conflict", "contention", "unknown", "clear")
            }
            if command.focus == "attention":
                items = [
                    v
                    for v in items
                    if v["status"] != "clear"
                    or v["proposal_needs_review"]
                    or not v["policy_current"]
                ]
            elif command.focus == "conflict":
                items = [v for v in items if v["status"] in ("conflict", "contention")]
            elif command.focus == "unknown":
                items = [v for v in items if v["status"] == "unknown" or v["missing"]]
            items.sort(
                key=lambda v: (
                    {"conflict": 0, "contention": 1, "unknown": 2, "clear": 3}[v["status"]],
                    v["name"],
                    v["id"],
                )
            )
            revision = digest(
                {
                    "items": items,
                    "counts": counts,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("资源容量、占用或权限已有变化，请刷新第一页")
            return {
                "items": items[command.offset : command.offset + 20],
                "counts": counts,
                "total": len(items),
                "revision": revision,
                "next_offset": command.offset + 20 if command.offset + 20 < len(items) else None,
                "as_of": now.isoformat(),
                "window": {"start": command.start.isoformat(), "end": command.end.isoformat()},
                "projects": [_plain(v) for v in visible.values()],
                "can_manage": is_allowed(context.user.role, Action.TENANT_MANAGE),
            }

    def detail(self, context: AuthContext, command: ResourceDetail) -> dict[str, Any]:
        self.authorize(context)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 48
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            r = tables.planning_resources
            resource = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == context.tenant.id, r.c.id == command.resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if resource is None:
                raise ProductWorkError("资源不存在或当前不可读取")
            summary, segments, bookings = capture(
                c, context, resource, command, now, projects(c, context, now)
            )
            revision = digest(
                {
                    "source": summary["source_digest"],
                    "part": command.part,
                    "window": {"start": command.start.isoformat(), "end": command.end.isoformat()},
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("资源依据已有变化，请重新读取明细第一页")
            items = segments if command.part == "segments" else bookings
            return {
                "summary": summary,
                "source_current": summary["source_digest"] == command.expected_digest,
                "items": items[command.offset : command.offset + 30],
                "total": len(items),
                "revision": revision,
                "next_offset": command.offset + 30 if command.offset + 30 < len(items) else None,
                "part": command.part,
                "as_of": now.isoformat(),
            }
