"""Fixed multi-project reservation changes and deterministic post-change capacity."""

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_execution import _person
from app.domain.resource_capacity import (
    CapacityCheckDraft,
    Demand,
    _compute,
    _intervals,
    capacity_sources,
)
from app.domain.resource_priorities import PREFIX, active, rank
from app.domain.resource_reservations import ReservationDraft
from app.domain.working_time import CalendarDefinition, WorkingTime


class ReallocationItem(Contract):
    reservation_id: UUID
    expected_digest: Digest
    target: ReservationDraft
    impact: Text


class ReallocationDraft(Contract):
    request_id: UUID
    title: Text
    reason: Text
    items: tuple[ReallocationItem, ...] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({item.reservation_id for item in self.items}) != len(self.items):
            raise ValueError("原预约不可重复选择")
        return self


class ReallocationSubmit(ReallocationDraft):
    expected_preview_digest: Digest


class ReallocationDecision(Contract):
    request_id: UUID
    allocation_id: UUID
    expected_digest: Digest
    action: Literal["approve", "reject", "withdraw"]
    reason: Text


class ReallocationApply(Contract):
    request_id: UUID
    allocation_id: UUID
    expected_digest: Digest
    reason: Text


class ReallocationReview(Contract):
    allocation_id: UUID
    expected_digest: Digest


def capture(c: Connection, context: AuthContext, draft: ReallocationDraft) -> dict[str, Any]:
    r, p, users = tables.resource_reservations, tables.projects, tables.users
    ids = {item.reservation_id for item in draft.items}
    original = {
        row["id"]: row
        for row in c.execute(
            select(r).where(r.c.tenant_id == context.tenant.id, r.c.id.in_(ids))
        ).mappings()
    }
    if set(original) != ids:
        raise ProductWorkError("所选预约不存在或不属于本租户")
    projects = {
        row["id"]: row
        for row in c.execute(
            select(p)
            .where(
                p.c.tenant_id == context.tenant.id,
                p.c.id.in_({row["project_id"] for row in original.values()}),
            )
            .order_by(p.c.id)
            .with_for_update()
        ).mappings()
    }
    if len(projects) < 2:
        raise ProductWorkError("跨项目调整至少涉及两个实际项目")
    people = {
        row["id"]: row
        for row in c.execute(
            select(users).where(
                users.c.tenant_id == context.tenant.id,
                users.c.id.in_({row["owner_user_id"] for row in projects.values()}),
            )
        ).mappings()
    }
    project_views = []
    for project in projects.values():
        person = people.get(project["owner_user_id"])
        if (
            project["status"] not in ("approved", "active")
            or not person
            or not person["is_active"]
            or not is_allowed(person["role"], Action.PROJECT_EDIT)
        ):
            raise ProductWorkError(
                "各项目须处于已批准/执行状态，并指定有效且有项目管理权限的实际负责人"
            )
        try:
            _person(c, context, project["id"], person["id"])
        except ProductWorkError as error:
            raise ProductWorkError("受影响项目的负责人已不具备项目权限，请由管理员核对") from error
        project_views.append(
            {
                "id": str(project["id"]),
                "name": project["name"],
                "status": project["status"],
                "owner_user_id": str(person["id"]),
                "owner_name": person["display_name"],
                "owner_role": person["role"],
            }
        )
    demands: dict[str, tuple[Demand, ...]] = {
        str(item.reservation_id): (
            Demand(
                capacity_version_id=item.target.capacity_version_id,
                units=item.target.parallel_units,
                contributes_effort=True,
                occupancy_policy=item.target.occupancy_policy,
                basis=item.impact,
            ),
        )
        for item in draft.items
    }
    capacity_draft = CapacityCheckDraft(request_id=draft.request_id, demands=demands)
    profiles, occupied, legacy = capacity_sources(c, context, capacity_draft)
    resource_ids = {v["resource_id"] for v in profiles.values()}
    # Source reservations may change while waiting for the common inventory lock.
    original = {
        row["id"]: row
        for row in c.execute(
            select(r).where(r.c.tenant_id == context.tenant.id, r.c.id.in_(ids))
        ).mappings()
    }
    interval = tables.resource_reservation_intervals
    all_rows = list(
        c.execute(
            select(
                r.c.id,
                r.c.project_id,
                r.c.resource_id,
                r.c.capacity_version_id,
                r.c.state,
                r.c.contract,
                r.c.created_at,
                r.c.window_start,
                r.c.window_end,
                r.c.parallel_units,
                interval.c.start,
                interval.c.end,
                p.c.status.label("project_status"),
            )
            .join(
                interval,
                (interval.c.tenant_id == r.c.tenant_id) & (interval.c.reservation_id == r.c.id),
            )
            .join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
            .where(
                r.c.tenant_id == context.tenant.id,
                r.c.resource_id.in_(resource_ids),
                r.c.state.in_(("reserved", "proposed")),
            )
            .order_by(r.c.id, interval.c.start)
        ).mappings()
    )
    policies = {
        resource: active(c, context.tenant.id, resource)
        for resource in sorted(resource_ids, key=str)
    }
    bookings = [
        dict(
            resource_id=str(row["resource_id"]),
            start=row["start"].isoformat(),
            end=row["end"].isoformat(),
            units=str(row["parallel_units"]),
        )
        for row in all_rows
        if row["state"] == "reserved" and row["id"] not in ids
    ]
    bookings += [row for row in occupied if row.get("origin") == "legacy_inventory"]
    targets, spans, calendars = [], {}, {}
    for item in draft.items:
        old, target = original[item.reservation_id], item.target
        if (
            old["state"] not in ("reserved", "proposed")
            or digest(_plain(old)) != item.expected_digest
        ):
            raise ProductWorkError("原预约版本或状态已变化，请刷新并重做预览")
        if target.node_id != old["node_id"] or target.task_id is not None:
            raise ProductWorkError("调整须保留原实际节点")
        if target.window_end <= datetime.now(UTC):
            raise ProductWorkError("调整后的窗口已结束，请重选")
        try:
            _person(c, context, old["project_id"], old["owner_user_id"])
        except ProductWorkError as error:
            raise ProductWorkError("原预约负责人已失效或不在项目中，请先办理责任移交") from error
        profile = profiles[target.capacity_version_id]
        if not profile["is_current"] or not profile["person_active"]:
            raise ProductWorkError("目标容量或资源人员已变化，请重新选择")
        policy = policies[profile["resource_id"]]
        if old["state"] == "proposed":
            same = (
                target.capacity_version_id == old["capacity_version_id"]
                and target.window_start == old["window_start"]
                and target.window_end == old["window_end"]
                and target.parallel_units == old["parallel_units"]
                and target.occupancy_policy == old["occupancy_policy"]
                and target.basis == old["basis"]
            )
            if not same or old["contract"]["priority_policy_version"] != PREFIX + str(policy["id"]):
                raise ProductWorkError("待确认预约须保留原请求及当前政策；需要改动请先重提预约")
        engine = WorkingTime(CalendarDefinition.model_validate(profile["calendar_definition"]))
        if _plain(asdict(engine.evidence)) != profile["calendar_evidence"]:
            raise ProductWorkError("时区依据已变化，请发布新容量")
        key = str(item.reservation_id)
        calendars[str(target.capacity_version_id)] = {
            **_plain(asdict(engine.evidence)),
            "definition": profile["calendar_definition"],
        }
        intervals = (
            _intervals(engine, target.window_start, target.window_end)
            if target.occupancy_policy == "working_only"
            else [(target.window_start, target.window_end)]
        )
        if not intervals:
            raise ProductWorkError("目标窗口没有可占用时段")
        spans[key] = [
            dict(
                resource_id=str(profile["resource_id"]),
                start=left.isoformat(),
                end=right.isoformat(),
                units=str(target.parallel_units),
            )
            for left, right in intervals
        ]
        targets.append(
            {
                "reservation_id": key,
                "project_id": str(old["project_id"]),
                "original": _plain(old),
                "target": target.model_dump(mode="json"),
                "resource_id": str(profile["resource_id"]),
                "resource_name": profile["resource_name"],
                "rank": rank(policy, old["project_id"]),
                "policy_id": str(policy["id"]),
                "impact": item.impact,
                "node": {
                    "node_key": key,
                    "start": target.window_start.isoformat(),
                    "finish": target.window_end.isoformat(),
                    "work_minutes": engine.working_minutes(target.window_start, target.window_end),
                    "allocation": {
                        "parallel_units": str(target.parallel_units),
                        "calendar_key": str(target.capacity_version_id),
                    },
                },
            }
        )
    conflicts: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for item, target_view in zip(draft.items, targets, strict=True):
        profile = profiles[item.target.capacity_version_id]
        old = original[item.reservation_id]
        policy = policies[profile["resource_id"]]
        before = (old["created_at"], str(old["id"])) if old["state"] == "proposed" else None
        pending = []
        for row in all_rows:
            if (
                row["id"] in ids
                or row["state"] != "proposed"
                or row["resource_id"] != profile["resource_id"]
                or row["capacity_version_id"] != profile["id"]
                or row["contract"]["priority_policy_version"] != PREFIX + str(policy["id"])
            ):
                continue
            if (
                row["project_status"] not in ("approved", "active")
                or row["window_end"] <= datetime.now(UTC)
                or row["window_start"] < profile["window_start"]
                or row["window_end"] > profile["window_end"]
                or row["parallel_units"] > profile["parallel_units"]
            ):
                continue
            theirs = rank(policy, row["project_id"])
            if theirs > target_view["rank"] or (
                theirs == target_view["rank"]
                and before is not None
                and (row["created_at"], str(row["id"])) >= before
            ):
                continue
            pending.append(
                dict(
                    resource_id=str(row["resource_id"]),
                    start=row["start"].isoformat(),
                    end=row["end"].isoformat(),
                    units=str(row["parallel_units"]),
                )
            )
        with localcontext() as arithmetic:
            arithmetic.prec = 48
            result = _compute(
                {
                    "id": draft.request_id,
                    "result_digest": digest(target_view),
                    "result": {"nodes": [target_view["node"]], "calendars": calendars},
                },
                {target_view["reservation_id"]: demands[target_view["reservation_id"]]},
                {profile["id"]: profile},
                {},
                [
                    *bookings,
                    *pending,
                    *(
                        span
                        for key, values in spans.items()
                        if key != target_view["reservation_id"]
                        for span in values
                    ),
                ],
                legacy & {profile["resource_id"]},
            )
        conflicts.extend(
            {**value, "reservation_id": target_view["reservation_id"]}
            for value in result["conflicts"]
        )
        unknown.extend(
            {**value, "reservation_id": target_view["reservation_id"]}
            for value in result["unknown"]
        )
    legacy_rows = (
        list(
            c.execute(
                text(
                    "SELECT * FROM cehub_project.current_legacy_resource_allocations "
                    "WHERE tenant_id=:tenant AND resource_id=ANY(:resources)"
                ),
                {"tenant": context.tenant.id, "resources": list(resource_ids)},
            ).mappings()
        )
        if resource_ids
        else []
    )
    body = {
        "version": "resource.reallocation.v1",
        "title": draft.title,
        "reason": draft.reason,
        "projects": project_views,
        "items": [{k: v for k, v in item.items() if k != "node"} for item in targets],
        "profiles": [_plain(profiles[key]) for key in sorted(profiles, key=str)],
        "policies": [_plain(policies[key]) for key in sorted(policies, key=str)],
        "ledger_digest": digest(
            {
                "reservations": [_plain(dict(row)) for row in all_rows],
                "legacy": sorted(digest(_plain(dict(row))) for row in legacy_rows),
            }
        ),
        "conflicts": conflicts,
        "unknown": unknown,
        "capacity_clear": not conflicts and not unknown,
        "baseline_changed": False,
        "commitments_changed": False,
    }
    return {"snapshot": body, "preview_digest": digest(body)}
