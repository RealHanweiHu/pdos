"""Append-only schedule observations derived from actual non-Task business audits."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select

from app.db.schema import tables
from app.domain.product_workspace import _plain, digest

KINDS = {
    "build": "build_id",
    "test_run": "test_run_id",
    "gate": "gate_id",
    "certification": "certification_id",
    "tooling": "tooling_id",
    "milestone": None,
}
GATE_ACTIONS = {"gate.round.open", "gate.approve", "gate.conditional", "gate.hold", "gate.rejected"}


def audit_kind(audit: Any) -> str | None:
    action = audit["action"]
    if action == "milestone.complete":
        return "milestone"
    if action in GATE_ACTIONS:
        return "gate"
    if action in ("test_run.record", "test_run.complete"):
        return "test_run"
    if action.startswith("npi.tooling_round."):
        return "tooling"
    for kind in ("build", "certification"):
        if action.startswith(f"npi.{kind}."):
            return kind
    return None


def _time(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def projection(kind: str, audit: Any, previous: Any | None) -> dict[str, Any]:
    source = audit["after_snapshot"] or {}
    if kind == "tooling" and "status" not in source:
        source = source.get("payload") or {}
    status = source.get("status")
    start, finish = None, None
    note = None
    if kind == "milestone":
        start = finish = _time(source.get("completed_at"))
        note = source.get("evidence")
    elif kind == "build":
        start = _time(source.get("started_at"))
        finish = _time(source.get("completed_at")) if status == "completed" else None
    elif kind == "tooling":
        start = _time(source.get("started_at") or (source.get("started") or {}).get("at"))
        finish = (
            _time(source.get("completed_at") or (source.get("completed") or {}).get("at"))
            if status == "completed"
            else None
        )
        if status == "completed" and source.get("outcome") != "accepted":
            note = "本轮执行已结束，尚未无条件接受；原条件和后续轮次须继续办理"
    elif kind == "test_run":
        start = _time(source.get("started_at")) or (previous["started_at"] if previous else None)
        if start is None and audit["action"] == "test_run.record":
            # The established record handler starts the execution at the audit timestamp.
            start = audit["timestamp"]
        finish = (
            _time(source.get("executed_at")) if status in ("passed", "failed", "aborted") else None
        )
    elif kind == "gate":
        if audit["action"] == "gate.round.open":
            start = audit["timestamp"]
        else:
            start = previous["started_at"] if previous else None
            finish = _time(source.get("decided_at"))
        if status in ("conditional", "hold", "rejected"):
            note = "本轮评审已结束，但未取得无条件批准；后续批准条件仍需单独满足"
    else:
        start = _time(source.get("started_at"))
        finish = _time(source.get("completed_at"))
        note = (
            "认证有效期不代表实际办理时间；缺失的历史实际时间保留未知"
            if start is None or finish is None
            else None
        )
    if kind == "test_run" and status in ("failed", "aborted"):
        note = "本轮执行已结束，结果未通过；结束时间不代表验收通过"
    terminal = {
        "build": {"completed", "cancelled"},
        "test_run": {"passed", "failed", "aborted"},
        "gate": {"approved", "conditional", "hold", "rejected"},
        "certification": {"valid", "expired", "revoked"},
        "milestone": {"completed"},
        "tooling": {"completed", "cancelled"},
    }
    successful = (
        status in {"completed", "passed", "approved", "valid"} if status in terminal[kind] else None
    )
    if kind == "tooling" and status in terminal[kind]:
        successful = status == "completed" and source.get("outcome") == "accepted"
    return {
        "source_status": status,
        "started_at": start,
        "finished_at": finish,
        "successful": successful,
        "note": note,
    }


def observe_audit(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    audit_id: int,
    *,
    publish: bool = True,
) -> bool:
    audit = (
        connection.execute(
            select(tables.audit_log).where(
                tables.audit_log.c.tenant_id == tenant_id,
                tables.audit_log.c.project_id == project_id,
                tables.audit_log.c.id == audit_id,
            )
        )
        .mappings()
        .one()
    )
    kind = audit_kind(audit)
    source = audit["after_snapshot"] or {}
    if kind == "tooling":
        source = source if "status" in source else source.get("payload", {})
    if kind is None or not source.get("status"):
        return False
    column = KINDS[kind]
    if kind != "milestone" and column is None:
        return False
    assert column is not None or kind == "milestone"
    node = (
        connection.execute(
            select(tables.schedule_nodes).where(
                tables.schedule_nodes.c.tenant_id == tenant_id,
                tables.schedule_nodes.c.project_id == project_id,
                tables.schedule_nodes.c.node_kind == kind,
                (
                    tables.schedule_nodes.c.id
                    if kind == "milestone"
                    else tables.schedule_nodes.c[str(column)]
                )
                == audit["entity_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        return False
    # All source handlers already own this lock; registration/backfill takes it as well.
    connection.execute(
        select(tables.projects.c.id)
        .where(tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id)
        .with_for_update()
    ).scalar_one()
    table = tables.schedule_source_observations
    if connection.execute(
        select(table.c.id).where(
            table.c.tenant_id == tenant_id,
            table.c.node_id == node["id"],
            table.c.audit_row_id == audit_id,
        )
    ).first():
        return False
    previous = (
        connection.execute(
            select(table)
            .where(table.c.tenant_id == tenant_id, table.c.node_id == node["id"])
            .order_by(table.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    values = projection(kind, audit, previous)
    event_id = connection.execute(
        select(tables.events.c.id).where(
            tables.events.c.tenant_id == tenant_id,
            tables.events.c.project_id == project_id,
            tables.events.c.entity_id == audit["entity_id"],
            tables.events.c.event_id == audit["event_id"],
        )
    ).scalar_one_or_none()
    observation = (
        connection.execute(
            table.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                node_id=node["id"],
                node_kind=kind,
                version=(previous["version"] if previous else 0) + 1,
                audit_row_id=audit_id,
                event_row_id=event_id,
                observed_at=audit["timestamp"],
                **values,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    from app.domain.schedule_source_errors import record_source_errors

    record_source_errors(connection, observation, previous)
    if publish:
        from app.domain.schedule_execution import persist_actual_snapshot

        persist_actual_snapshot(
            connection, tenant_id, project_id, audit["actor_user_id"], datetime.now(UTC)
        )
        from app.domain.formal_schedule import current_plan
        from app.domain.schedule_forecasts import automatic_forecast

        formal = current_plan(connection, tenant_id, project_id)
        if formal and (
            kind == "tooling" or any(item["id"] == node["id"] for item in formal["nodes"])
        ):
            automatic_forecast(
                connection,
                tenant_id,
                project_id,
                audit["actor_user_id"],
                "正式业务节点进展更新后的预测传播",
                datetime.now(UTC),
            )
    return True


def replay_source(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    source_id: UUID,
    kind: str,
    actor_user_id: UUID,
) -> None:
    if kind not in KINDS:
        return
    audits = list(
        connection.execute(
            select(tables.audit_log)
            .where(
                tables.audit_log.c.tenant_id == tenant_id,
                tables.audit_log.c.project_id == project_id,
                tables.audit_log.c.entity_id == source_id,
            )
            .order_by(tables.audit_log.c.timestamp, tables.audit_log.c.id)
        ).mappings()
    )
    changed = False
    for audit in audits:
        if audit_kind(audit) == kind:
            changed = (
                observe_audit(connection, tenant_id, project_id, audit["id"], publish=False)
                or changed
            )
    if changed:
        from app.domain.schedule_execution import persist_actual_snapshot

        persist_actual_snapshot(connection, tenant_id, project_id, actor_user_id, datetime.now(UTC))


def latest_observations(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> list[dict[str, Any]]:
    table = tables.schedule_source_observations
    ranked = (
        select(
            table,
            func.row_number()
            .over(partition_by=table.c.node_id, order_by=table.c.version.desc())
            .label("position"),
        )
        .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        .subquery()
    )
    rows = [
        dict(row)
        for row in connection.execute(select(ranked).where(ranked.c.position == 1)).mappings()
    ]
    from app.domain.schedule_source_corrections import corrected_observations

    return corrected_observations(connection, tenant_id, project_id, rows)


def observation_source(row: Any) -> dict[str, Any]:
    row = row.get("raw_observation", row)
    return {
        "tenant_id": row["tenant_id"],
        "project_id": row["project_id"],
        "kind": "schedule_source_observation",
        "ref_id": row["id"],
        "version": row["version"],
        "as_of": row["observed_at"],
        "digest": digest(_plain(row)),
    }


def observation_sources(row: Any) -> list[dict[str, Any]]:
    sources = [observation_source(row)]
    if row.get("actual_correction"):
        correction = row["actual_correction"]
        sources.append(
            {
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "kind": "schedule_source_correction",
                "ref_id": UUID(correction["id"]),
                "version": correction["version"],
            }
        )
    return sources
