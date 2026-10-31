"""Planning demands and deterministic comparisons; never make a reservation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select, text

from pdos_next.domain.build_operational_facts.models import OperationalAsset
from pdos_next.domain.external_wait import calendar_owner
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.service import digest

from .models import ProjectTask


def catalog(s, ctx, pid, project_id):
    people = list(
        s.scalars(
            select(Principal)
            .join(
                Grant,
                (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.kind == "human",
                Grant.category_id == ctx.category_id,
                or_(Grant.expires_at.is_(None), Grant.expires_at > now()),
            )
            .distinct()
        )
    )
    items = [
        {
            "id": str(p.id),
            "kind": "person",
            "label": p.name,
            "capacity": "1",
            "revision": None,
            "availability": "unknown",
            "calendar": None,
        }
        for p in people
    ]
    resources = {}
    for value in calendar_owner.available(s, ctx, pid, project_id):
        if value["ref"]["kind"] != "build_resource":
            continue
        identity = UUID(value["ref"]["resource_id"])
        asset = s.get(OperationalAsset, identity)
        if asset is None or asset.tenant_id != ctx.tenant_id:
            continue
        physical = asset.data["value"]
        resources[str(identity)] = {
            "id": str(identity),
            "kind": "resource",
            "label": f"{asset.identity['kind']} · {str(identity)[:8]}",
            "capacity": physical.get("capacity"),
            "revision": asset.revision,
            "calendar": value["calendar"],
            "availability": "capacity_only",
            "fact": value["ref"],
            "nature": "source_bound",
        }
    return {
        "items": items + list(resources.values()),
        "coordinators": [{"id": str(p.id), "name": p.name} for p in people],
    }


def validate_demands(s, ctx, pid, project_id, demands):
    if not demands:
        return
    options = catalog(s, ctx, pid, project_id)
    keys = {(v["kind"], v["id"]) for v in options["items"]}
    people = {v["id"] for v in options["coordinators"]}
    if any(
        (d.kind, str(d.resource_id)) not in keys or str(d.coordinator_id) not in people
        for d in demands
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "资源或协调人不在当前可用范围，请刷新后重选。", 403)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def conflicts_for(demand, task, windows, capacity):
    """Half-open intervals; unknown finish never becomes a free slot."""
    start, finish = instant(task.get("earliest_start")), instant(task.get("latest_finish"))
    if start is None or finish is None or capacity is None:
        return {"state": "unknown", "conflicts": [], "peak_units": None}
    relevant = [w for w in windows if instant(w["start"]) < finish and instant(w["finish"]) > start]
    events = [(start, Decimal(demand["units"])), (finish, -Decimal(demand["units"]))]
    for w in relevant:
        events.extend(
            [
                (max(start, instant(w["start"])), Decimal(str(w["units"]))),
                (min(finish, instant(w["finish"])), -Decimal(str(w["units"]))),
            ]
        )
    usage = Decimal(0)
    peak = Decimal(0)
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        usage += delta
        peak = max(peak, usage)
    return {
        "state": "conflict" if peak > Decimal(str(capacity)) else "unreserved",
        "conflicts": relevant if peak > Decimal(str(capacity)) else [],
        "peak_units": str(peak),
    }


def compare_capacity(demand, task, occupied, same, capacity, *, incomplete=False):
    # Without a shared activity identity, mixing plans and reservations can
    # neither prove double counting nor prove independent use. Preserve doubt.
    planned = conflicts_for(
        demand, task, [w for w in occupied if w["source"] == "plan"] + same, capacity
    )
    actual = conflicts_for(
        demand, task, [w for w in occupied if w["source"] == "reservation"] + same, capacity
    )
    combined = conflicts_for(demand, task, occupied + same, capacity)
    definite = "conflict" in {planned["state"], actual["state"]}
    unknown = incomplete or combined["state"] in {"unknown", "conflict"}
    return {
        "state": "conflict" if definite else "unknown" if unknown else "unreserved",
        "conflicts": planned["conflicts"] + actual["conflicts"]
        if definite
        else combined["conflicts"],
        "peak_units": str(
            max(Decimal(planned["peak_units"] or "0"), Decimal(actual["peak_units"] or "0"))
        )
        if planned["peak_units"] is not None and actual["peak_units"] is not None
        else None,
        "potential_peak_units": combined["peak_units"],
        "reason": "计划与预约可能重合，需核对活动关系及合并容量"
        if unknown and not definite and combined["state"] == "conflict"
        else "存在日期、资源或容量待核对"
        if unknown and not definite
        else None,
    }


def sequential(tasks, first, second):
    """Precedence prevents simultaneous use, even when forecast ranges overlap."""

    def precedes(a, b):
        waiting, visited = list(tasks[b].get("depends_on", [])), set()
        while waiting:
            key = waiting.pop()
            if key == a:
                return True
            if key not in visited:
                visited.add(key)
                waiting.extend(tasks[key].get("depends_on", []))
        return False

    return precedes(first, second) or precedes(second, first)


def analyze(s, ctx, pid, project, forecast, demands):
    if not demands:
        return {
            "items": [],
            "conflict_count": 0,
            "unknown_count": 0,
            "digest": digest([]),
            "effect": "未声明资源需求；不能据此判定资源已就绪。",
        }
    options = catalog(s, ctx, pid, project.id)
    choices = {(r["kind"], r["id"]): r for r in options["items"]}
    windows = {}

    def add(kind, rid, window):
        windows.setdefault((kind, str(rid)), []).append(window)

    incomplete = set()
    for kind, rid in {(d["kind"], d["resource_id"]) for d in demands}:
        if (kind, rid) not in choices:
            incomplete.add((kind, rid))
            continue
        rows = s.execute(
            text("SELECT * FROM planning_resource_windows(:tenant,:project,:resource,:kind)"),
            {"tenant": ctx.tenant_id, "project": project.id, "resource": UUID(rid), "kind": kind},
        ).mappings()
        for row in rows:
            if row["window_start"] is None or row["window_finish"] is None:
                incomplete.add((kind, rid))
                continue
            add(
                kind,
                rid,
                {
                    "start": row["window_start"].isoformat(),
                    "finish": row["window_finish"].isoformat(),
                    "units": str(row["units"]),
                    "source": row["source_kind"],
                    "project_name": row["visible_project_name"],
                    "project_id": str(row["visible_project_id"])
                    if row["visible_project_id"]
                    else None,
                },
            )
    tasks = {t["key"]: t for t in forecast["tasks"]}
    items = []
    for index, d in enumerate(demands):
        resource = choices.get((d["kind"], d["resource_id"]))
        task = tasks[d["task_key"]]
        same = []
        for other_index, other in enumerate(demands):
            if other_index != index and (other["kind"], other["resource_id"]) == (
                d["kind"],
                d["resource_id"],
            ):
                if sequential(tasks, d["task_key"], other["task_key"]):
                    continue
                t = tasks[other["task_key"]]
                if t.get("earliest_start") and t.get("latest_finish"):
                    same.append(
                        {
                            "start": t["earliest_start"],
                            "finish": t["latest_finish"],
                            "units": other["units"],
                            "source": "candidate",
                            "project_name": project.name,
                            "task_title": t["title"],
                        }
                    )
                else:
                    incomplete.add((d["kind"], d["resource_id"]))
        occupied = windows.get((d["kind"], d["resource_id"]), [])
        capacity = resource.get("capacity") if resource else None
        result = compare_capacity(
            d,
            task,
            occupied,
            same,
            capacity,
            incomplete=(d["kind"], d["resource_id"]) in incomplete,
        )
        coordinator = next(
            (p["name"] for p in options["coordinators"] if p["id"] == d["coordinator_id"]),
            "协调人待核对",
        )
        items.append(
            {
                **d,
                "coordinator_name": coordinator,
                "label": resource["label"] if resource else "资源当前不可用",
                "task_title": task["title"],
                "start": task.get("earliest_start"),
                "finish": task.get("latest_finish"),
                **result,
            }
        )
    return {
        "items": items,
        "conflict_count": sum(i["state"] == "conflict" for i in items),
        "unknown_count": sum(i["state"] == "unknown" for i in items),
        "digest": digest(items),
        "effect": (
            "分别比较计划需求与实际占用；无已知冲突仍须核对完整日历、资格与预约。"
            "计划采用不改变实际预约。"
        ),
    }


def compare(before, after):
    old = {t["key"]: t for t in before["tasks"]} if before else {}
    new = {t["key"]: t for t in after["tasks"]}
    return [
        {
            "key": key,
            "title": new.get(key, old.get(key))["title"],
            "change": "added"
            if key not in old
            else "removed"
            if key not in new
            else "changed"
            if old[key] != new[key]
            else "unchanged",
            "before": old.get(key),
            "after": new.get(key),
        }
        for key in sorted(old.keys() | new.keys())
    ]


def lineage(s, project_id, tasks):
    """Immutable execution references remain original; group plan-task revisions by key."""
    keys = {t.key for t in tasks}
    result = {key: [] for key in keys}
    for t in s.scalars(
        select(ProjectTask).where(ProjectTask.project_id == project_id, ProjectTask.key.in_(keys))
    ):
        result[t.key].append(str(t.id))
    return result
