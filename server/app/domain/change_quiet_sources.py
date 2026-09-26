"""Original formal baseline anchors for immutable quiet policies."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.product_workspace import ProductWorkError, _plain, digest


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_id: UUID
    node_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def sources(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    formal = current_plan(c, tenant, project)
    if formal is None:
        return []
    t, points = tables.schedule_time_records, tables.schedule_time_nodes
    baseline = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == formal["baseline_id"]
            )
        )
        .mappings()
        .one()
    )
    times = {
        r["node_id"]: dict(r)
        for r in c.execute(
            select(points).where(
                points.c.tenant_id == tenant,
                points.c.project_id == project,
                points.c.record_id == formal["baseline_id"],
            )
        ).mappings()
    }
    specs = {n["node_key"]: n for n in formal["plan"]["nodes"]}
    values = []
    for node in formal["nodes"]:
        if node["id"] not in times:
            continue
        snapshot = _plain(
            {
                "baseline_id": baseline["id"],
                "baseline_version": baseline["version"],
                "approval": baseline["contract"]["approval"],
                "baseline_sources": baseline["contract"]["sources"],
                "node_id": node["id"],
                "node_kind": node["node_kind"],
                "plan_node": specs[node["node_key"]],
                "time": times[node["id"]],
            }
        )
        values.append({**snapshot, "digest": digest(snapshot)})
    return values


def resolve(values: list[dict[str, Any]], anchor: Anchor) -> dict[str, Any]:
    value = next(
        (
            v
            for v in values
            if v["node_id"] == str(anchor.node_id)
            and v["baseline_id"] == str(anchor.baseline_id)
            and v["digest"] == anchor.expected_digest
        ),
        None,
    )
    if value is None:
        raise ProductWorkError("正式基线或所选节点已变化，请重新核对冻结窗口依据")
    if value["time"]["start"] is None or value["time"]["end"] is None:
        raise ProductWorkError("所选正式节点缺少完整基线日期")
    return value


def bind(
    c: Connection,
    tenant: UUID,
    project: UUID,
    policy_id: UUID,
    window_key: str,
    anchor: Anchor,
    snapshot: dict[str, Any],
) -> None:
    c.execute(
        tables.change_quiet_policy_anchors.insert().values(
            id=uuid4(),
            tenant_id=tenant,
            project_id=project,
            policy_id=policy_id,
            window_key=window_key,
            baseline_id=anchor.baseline_id,
            node_id=anchor.node_id,
            source_digest=anchor.expected_digest,
            snapshot=snapshot,
        )
    )


def assess(
    c: Connection,
    tenant: UUID,
    project: UUID,
    policy_id: UUID,
    window_key: str,
    current: list[dict[str, Any]],
) -> dict[str, Any]:
    t = tables.change_quiet_policy_anchors
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.policy_id == policy_id,
                t.c.window_key == window_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return {
            "current": False,
            "reason": "原政策尚未绑定正式基线节点，请发布新版本并重新分析",
            "snapshot": None,
        }
    valid = any(
        v["node_id"] == str(row["node_id"])
        and v["baseline_id"] == str(row["baseline_id"])
        and v["digest"] == row["source_digest"]
        for v in current
    )
    return {
        "current": valid,
        "reason": None if valid else "正式基线或节点已变化，请发布新政策并重新分析",
        "snapshot": row["snapshot"],
    }


def available(
    c: Connection, tenant: UUID, project: UUID
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        values = sources(c, tenant, project)
        return values, None if values else "当前尚无可用正式计划节点"
    except ProductWorkError as error:
        return [], str(error)
