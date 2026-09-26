"""Deterministic serial schedule generation; actual reservations are never moved."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select, text

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.resource_capacity import CapacityCheckDraft, _compute, capacity_sources
from app.domain.resource_priorities import latest, rank
from app.domain.working_time import WorkingTime

VERSION = "resource.serial_generation.v1"


def _union_existing(
    occupied: list[dict[str, Any]], proposed: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """Keep confirmed use outside the new window, union matching use inside it."""
    affected = {row["resource_id"] for row in proposed}
    selected = [
        r for r in occupied if r.get("covered_node_key") == key and r["resource_id"] in affected
    ]
    result = [
        r
        for r in occupied
        if not (r.get("covered_node_key") == key and r["resource_id"] in affected)
    ]
    for resource in sorted(affected):
        points: dict[datetime, list[tuple[int, Decimal]]] = {}
        for group, rows in enumerate((selected, proposed)):
            for row in rows:
                if row["resource_id"] != resource:
                    continue
                for field, sign in (("start", 1), ("end", -1)):
                    points.setdefault(datetime.fromisoformat(row[field]), []).append(
                        (group, sign * Decimal(row["units"]))
                    )
        active = [Decimal(0), Decimal(0)]
        ordered = sorted(points)
        for index, left in enumerate(ordered[:-1]):
            for group, delta in points[left]:
                active[group] += delta
            amount = max(active)
            if amount:
                result.append(
                    {
                        "resource_id": resource,
                        "start": left.isoformat(),
                        "end": ordered[index + 1].isoformat(),
                        "units": str(amount),
                        "covered_node_key": key,
                    }
                )
    return result


class ResourceSolver:
    def __init__(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        scenario: Any,
        draft: CapacityCheckDraft,
        as_of: datetime,
        horizon_days: int,
    ):
        self.scenario = scenario
        self.draft = draft
        mapping = {UUID(node["node_id"]): node["node_key"] for node in scenario["result"]["nodes"]}
        remaining = {
            n["node_key"] for n in scenario["result"]["nodes"] if not n.get("actual_finish")
        }
        if (set(draft.demands) | set(draft.no_resource_reasons)) - remaining:
            raise ProductWorkError("资源求解只接受此情景中尚未完成的节点")
        self.profiles, self.original, self.legacy = capacity_sources(
            connection,
            context,
            draft,
            covered_project_id=project_id,
            covered_node_keys=mapping,
        )
        as_of = connection.execute(select(func.clock_timestamp())).scalar_one()
        self.as_of = as_of
        self.horizon = as_of + timedelta(days=horizon_days)
        self.policies: list[dict[str, Any]] = []
        self.policy_errors: dict[UUID, str] = {}
        self.pending: list[dict[str, Any]] = []
        priority_identity: list[str] = []
        seen: dict[UUID, UUID] = {}
        for profile in self.profiles.values():
            resource = profile["resource_id"]
            if resource in seen and seen[resource] != profile["id"]:
                raise ProductWorkError("同一资源须使用同一容量版本")
            seen[resource] = profile["id"]
            policy = latest(connection, context.tenant.id, resource)
            if policy is None:
                self.policy_errors[resource] = "缺少资源优先级政策"
                continue
            current_rank = rank(policy, project_id)
            self.policies.append(
                {
                    "resource_id": str(resource),
                    "policy_id": str(policy["id"]),
                    "version": policy["version"],
                    "status": policy["status"],
                    "valid_from": policy["valid_from"].isoformat(),
                    "valid_until": policy["valid_until"].isoformat(),
                    "rank": current_rank,
                    "body_digest": digest(policy["body"]),
                }
            )
            if (
                policy["status"] != "active"
                or not policy["valid_from"] <= as_of < policy["valid_until"]
            ):
                self.policy_errors[resource] = "资源优先级政策已暂停、未生效或已过期"
                continue
            r, b, i, p = (
                tables.resource_reservations,
                tables.resource_priority_bindings,
                tables.resource_reservation_intervals,
                tables.projects,
            )
            # This new scenario follows all earlier requests with equal priority.
            rows = connection.execute(
                select(
                    i.c.start,
                    i.c.end,
                    r.c.parallel_units,
                    b.c.rank,
                    r.c.id,
                    r.c.contract,
                    r.c.created_at,
                )
                .select_from(
                    r.join(b, (b.c.tenant_id == r.c.tenant_id) & (b.c.reservation_id == r.c.id))
                    .join(i, (i.c.tenant_id == r.c.tenant_id) & (i.c.reservation_id == r.c.id))
                    .join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
                )
                .where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.resource_id == resource,
                    r.c.state == "proposed",
                    b.c.policy_id == policy["id"],
                    b.c.rank <= current_rank,
                    r.c.capacity_version_id == profile["id"],
                    p.c.status.in_(("approved", "active")),
                    r.c.window_end > as_of,
                    r.c.window_start >= profile["window_start"],
                    r.c.window_end <= profile["window_end"],
                    r.c.parallel_units <= profile["parallel_units"],
                )
                .order_by(i.c.start, i.c.end, r.c.id)
            ).mappings()
            for row in rows:
                priority_identity.append(digest(_plain(dict(row))))
                self.pending.append(
                    {
                        "resource_id": str(resource),
                        "start": row["start"].isoformat(),
                        "end": row["end"].isoformat(),
                        "units": str(row["parallel_units"]),
                        "rank": row["rank"],
                        "origin": "earlier_priority_request",
                    }
                )
                if len(self.pending) > 50000:
                    raise ProductWorkError("待确认预约区间超过求解上限，请先整理过期待办")
        resource_ids = sorted({p["resource_id"] for p in self.profiles.values()}, key=str)
        reserved = tables.resource_reservations
        reserved_identity = [
            digest(_plain(dict(row)))
            for row in connection.execute(
                select(reserved).where(
                    reserved.c.tenant_id == context.tenant.id,
                    reserved.c.resource_id.in_(resource_ids),
                    reserved.c.state == "reserved",
                )
            ).mappings()
        ]
        legacy_identity = (
            [
                digest(_plain(dict(row)))
                for row in connection.execute(
                    text(
                        "SELECT * FROM cehub_project.current_legacy_resource_allocations "
                        "WHERE tenant_id=:tenant AND resource_id=ANY(:resources)"
                    ),
                    {"tenant": context.tenant.id, "resources": resource_ids},
                ).mappings()
            ]
            if resource_ids
            else []
        )
        self.ledger_digest = digest(
            {
                "reserved": sorted(reserved_identity),
                "priority": sorted(priority_identity),
                "legacy": sorted(legacy_identity),
            }
        )
        self.occupied = [*self.original, *self.pending]
        self.attempts = 0
        self.decisions: list[dict[str, Any]] = []
        self.calendars: dict[str, Any] = {}
        self.nodes = {n["node_key"]: n for n in scenario["result"]["nodes"]}

    def place(
        self,
        key: str,
        engine: WorkingTime,
        earliest: datetime,
        duration: int,
        waiting: int,
        finish_floor: datetime | None,
    ) -> tuple[datetime | None, datetime | None, list[str]]:
        demands = self.draft.demands.get(key, ())
        profiles = {d.capacity_version_id: self.profiles[d.capacity_version_id] for d in demands}
        reasons: list[str] = []
        for profile in profiles.values():
            resource = profile["resource_id"]
            reason = self.policy_errors.get(resource)
            if reason:
                reasons.append(f"{profile['resource_name']}：{reason}")
            if not profile["is_current"]:
                reasons.append(f"{profile['resource_name']}：容量版本已替换，请重新选择")
        for demand in demands:
            profile = profiles[demand.capacity_version_id]
            if demand.units > profile["parallel_units"]:
                reasons.append(f"{profile['resource_name']}：所需并行单位超过此版本的最大容量")
        decision: dict[str, Any] = {
            "node_key": key,
            "earliest": earliest.isoformat(),
            "start": None,
            "finish": None,
            "attempts": 0,
            "delays": [],
            "reasons": reasons,
        }
        self.decisions.append(decision)
        if reasons:
            return None, None, reasons
        start = (
            max(earliest.astimezone(UTC), *(p["window_start"] for p in profiles.values()))
            if profiles
            else earliest
        )
        calendar_key = self.nodes[key]["allocation"]["calendar_key"]
        self.calendars[calendar_key] = {
            **_plain(asdict(engine.evidence)),
            "definition": engine.definition.model_dump(mode="json"),
        }
        # Serial generation is a bounded feasible-window heuristic, not an optimality proof.
        for _ in range(256):
            if self.attempts >= 5000:
                reasons.append("本次求解达到 5000 次窗口检查上限；尚未找到日期，不等于无解")
                break
            self.attempts += 1
            decision["attempts"] += 1
            start = engine.snap(start) if duration else start
            finish = engine.advance(start, duration) + timedelta(days=waiting)
            if finish_floor:
                finish = max(finish, finish_floor)
            if finish > self.horizon:
                reasons.append("剩余工作完成时间超过本次明确求解范围；可扩大范围后重新计算")
                break
            # working-only resources can end before a long calendar waiting period.
            if any(
                (
                    finish
                    if d.occupancy_policy == "through_waiting"
                    else engine.advance(start, duration)
                )
                > profiles[d.capacity_version_id]["window_end"]
                for d in demands
            ):
                reasons.append("工作或持续占用超出已声明容量窗口，需补充容量或另选资源")
                break
            node = {
                **self.nodes[key],
                "start": start.isoformat(),
                "finish": finish.isoformat(),
                "work_minutes": duration,
            }
            result = _compute(
                {
                    "id": self.scenario["id"],
                    "result_digest": self.scenario["result_digest"],
                    "result": {"nodes": [node], "calendars": self.calendars},
                },
                {key: demands} if demands else {},
                profiles,
                {key: self.draft.no_resource_reasons[key]}
                if key in self.draft.no_resource_reasons
                else {},
                self.occupied,
                self.legacy & {p["resource_id"] for p in profiles.values()},
                match_existing_reservations=True,
            )
            if result["unknown"]:
                reasons.extend(item["reason"] for item in result["unknown"])
                break
            if not result["conflicts"]:
                self.occupied = _union_existing(self.occupied, result["demand_intervals"], key)
                decision.update(
                    start=start.isoformat(),
                    finish=finish.isoformat(),
                    delay_minutes=int((start - earliest).total_seconds() // 60),
                )
                return start, finish, []
            conflict = min(
                result["conflicts"], key=lambda item: (item["start"], item["resource_id"])
            )
            if len(decision["delays"]) < 20:
                decision["delays"].append(conflict)
            start = max(start + timedelta(minutes=1), datetime.fromisoformat(conflict["end"]))
        if not reasons:
            reasons.append("节点达到 256 次窗口搜索上限；当前规则尚未找到日期，不等于无解")
        return None, None, reasons

    def evidence(self) -> dict[str, Any]:
        return {
            "algorithm_version": VERSION,
            "as_of": self.as_of.isoformat(),
            "horizon_end": self.horizon.isoformat(),
            "order": (
                "dependency_topology_then_node_key; fixed_reserved_and_legacy; "
                "earlier_rank_then_request"
            ),
            "policies": self.policies,
            "profiles": [_plain(p) for p in self.profiles.values()],
            "reserved_intervals": self.original,
            "priority_intervals": self.pending,
            "legacy_missing": sorted(map(str, self.legacy)),
            "ledger_identity_digest": self.ledger_digest,
            "decisions": self.decisions,
            "attempts": self.attempts,
            "optimality_proven": False,
            "reservations_changed": False,
            "baseline_changed": False,
            "ready_for_application": False,
        }
