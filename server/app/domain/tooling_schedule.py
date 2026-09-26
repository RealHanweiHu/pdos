"""Explicit tooling availability conditions for formal need nodes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.product_workspace import _plain, digest

POLICY = "tooling.availability.v1"


def assess(c: Connection, tenant: UUID, project: UUID, row: Any) -> dict[str, Any]:
    payload = row["payload"]
    sources = row["snapshot"]["sources"]
    evidence: dict[str, Any] = {}
    changed = False
    # Downstream execution changes its Build/Issue state; it does not change this
    # round's evidence of availability. Recheck the actual evidence, not those states.
    for key in ("evidence_id", "report_id", "available", "completed"):
        value = payload.get(key)
        identity = value.get("evidence_id") if isinstance(value, dict) else value
        if not identity:
            continue
        try:
            current = metadata(document_row(c, tenant, project, UUID(identity)))
            expected = sources.get(key)
            if isinstance(value, dict):
                expected = expected.get("document") if expected else None
            evidence[key] = current
            changed = changed or digest(current) != digest(expected)
        except (LookupError, ValueError):
            evidence[key] = None
            changed = True
    available = payload.get("available")
    estimate = payload.get("estimated_ready")
    accepted = payload["status"] == "completed" and payload["outcome"] == "accepted"
    state = "waiting"
    if changed:
        state = "source_changed"
    elif payload["status"] == "cancelled":
        state = "cancelled"
    elif available and accepted:
        state = "ready"
    elif estimate:
        # An estimated date also needs its own current original evidence.
        try:
            current = metadata(document_row(c, tenant, project, UUID(estimate["evidence_id"])))
            evidence["estimated_ready"] = current
            state = (
                "source_changed"
                if digest(current) != digest(sources["estimated_ready"]["document"])
                else "estimate"
                if datetime.fromisoformat(estimate["at"]) > datetime.now(UTC)
                else "estimate_expired"
            )
        except (LookupError, ValueError):
            state = "source_changed"
    return _plain(
        {
            "policy": POLICY,
            "round_id": row["id"],
            "round_version": row["version"],
            "title": f"{row['code']} · {row['round_label']} · {row['title']}",
            "target_point": payload.get("schedule_target_point"),
            "status": state,
            "ready_at": estimate["at"] if state == "estimate" else None,
            "available_at": available["at"] if state == "ready" else None,
            "source_digest": digest({"round": _plain(dict(row)), "current_evidence": evidence}),
        }
    )


def conditions(c: Connection, tenant: UUID, project: UUID) -> dict[UUID, list[dict[str, Any]]]:
    table = tables.tooling_rounds
    result: dict[UUID, list[dict[str, Any]]] = {}
    for row in c.execute(
        select(table).where(
            table.c.tenant_id == tenant,
            table.c.project_id == project,
            table.c.payload["schedule_target_point"].as_string().in_(("start", "finish")),
        )
    ).mappings():
        value = assess(c, tenant, project, row)
        for identity in row["payload"]["need_node_ids"]:
            result.setdefault(UUID(identity), []).append(value)
    return result


def execution_conditions(items: list[dict[str, Any]], at: datetime) -> list[dict[str, Any]]:
    result = []
    for item in items:
        available = datetime.fromisoformat(item["available_at"]) if item["available_at"] else None
        satisfied = item["status"] == "ready" and available is not None and available <= at
        result.append(
            {
                **item,
                "kind": "tooling_availability",
                "satisfied": satisfied,
                "not_before": item["available_at"],
                "reason": None
                if satisfied
                else f"工装 {item['title']}：须核对本轮接受及当时实际可用证据",
            }
        )
    return result
