"""Meeting references to immutable forecasts, with current-basis review context."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, or_, select

from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.schedule_forecasts import capture_basis


def sources(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    record_ids: list[UUID],
) -> tuple[dict[UUID, dict[str, Any]], dict[str, Any] | None]:
    """Read the latest and explicitly referenced versions in the caller's project scope.

    Only project result summaries leave this function; frozen network inputs are not
    meeting material. The review digest also changes when the current basis or latest
    forecast changes, while the referenced record itself stays fixed.
    """
    runs, records = tables.schedule_forecast_runs, tables.schedule_time_records
    query = (
        select(runs, records.c.version)
        .join(
            records,
            (records.c.tenant_id == runs.c.tenant_id)
            & (records.c.project_id == runs.c.project_id)
            & (records.c.id == runs.c.record_id),
        )
        .where(runs.c.tenant_id == tenant_id, runs.c.project_id == project_id)
    )
    latest_id = (
        query.with_only_columns(runs.c.record_id)
        .order_by(records.c.version.desc())
        .limit(1)
        .correlate(None)
        .scalar_subquery()
    )
    rows = list(
        connection.execute(
            query.where(
                or_(runs.c.record_id == latest_id, runs.c.record_id.in_(record_ids))
            ).order_by(records.c.version.desc())
        ).mappings()
    )
    if not rows:
        return {}, None
    current_basis: str | None = None
    basis_error: str | None = None
    try:
        current_basis = capture_basis(connection, tenant_id, project_id)["basis_digest"]
    except ProductWorkError as error:
        basis_error = str(error)
    latest = rows[0]
    values: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        result = row["result"]
        nodes = result["nodes"]
        current = current_basis is not None and row["basis_digest"] == current_basis
        is_latest = row["record_id"] == latest["record_id"]
        unknown = sum(bool(node.get("unknown_reasons")) for node in nodes)
        warnings = sum(bool(node.get("warnings")) for node in nodes)
        notes = [
            f"{node['node_key']}：{reason}"
            for node in nodes
            for reason in [*node.get("unknown_reasons", []), *node.get("warnings", [])]
        ]
        summary = [
            f"预测时点：{result['as_of']}；预计完成：{result.get('project_finish') or '未知'}",
            f"共 {len(nodes)} 个节点；{unknown} 个节点有待定项；{warnings} 个节点有提示；"
            f"{len(result.get('critical_node_keys', []))} 个关键节点。",
            "当前依据一致。" if current else "当前依据已变化或不可计算，需回到排程核对并更新预测。",
        ]
        if not is_latest:
            summary.append(f"本议题固定引用历史版本；最新预测为 v{latest['version']}。")
        if basis_error:
            summary.append(f"当前依据缺项：{basis_error}")
        summary.extend(notes[:8])
        if len(notes) > 8:
            summary.append(f"另有 {len(notes) - 8} 条待定项或提示，请打开原预测查看。")
        summary.append("预测用于讨论，容量需另行核对；不代表任务、关卡或议题已经完成。")
        value = {
            "kind": "forecast",
            "id": str(row["record_id"]),
            "title": f"正式排程预测 v{row['version']}",
            "status": "forecast_historical"
            if not is_latest
            else "forecast_stale"
            if not current
            else "forecast_unknown"
            if not result["complete"]
            else "forecast_current",
            "priority": "",
            "expertise": ["项目负责人", "相关节点负责人"],
            "owner_user_id": None,
            "href": f"/projects?project={project_id}&tab=overview&forecast={row['record_id']}"
            "#schedule-forecasts",
            "summary": summary,
        }
        values[row["record_id"]] = {
            **value,
            "digest": digest(
                _plain(
                    {
                        "source": value,
                        "result": result,
                        "original_basis": row["basis_digest"],
                        "current_basis": current_basis,
                        "latest_record_id": latest["record_id"],
                    }
                )
            ),
        }
    return values, values[latest["record_id"]]


def source_record(
    connection: Connection, tenant_id: UUID, project_id: UUID, record_id: UUID
) -> dict[str, Any] | None:
    values, _ = sources(connection, tenant_id, project_id, [record_id])
    return values.get(record_id)
