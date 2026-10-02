"""Actual issue/risk/decision sources and Task prerequisites for initialization work."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_state import historical_sources, source_states
from app.domain.decision_intake_targets import decision_snapshot
from app.domain.issue_intake_compensations import task_view
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.task_dependency_graph import active_dependencies


class TaskDependencyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class IntakeBusinessRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["issue", "risk", "decision"]
    id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def business_snapshot(row: Any, kind: str, c: Connection | None = None) -> dict[str, Any]:
    if kind == "decision":
        if c is None:
            raise ValueError("决策来源核对需要当前数据库连接")
        value = decision_snapshot(row)
        source_table = tables.decision_intake_rows
        origins = list(
            c.execute(
                select(source_table)
                .where(
                    source_table.c.tenant_id == row["tenant_id"],
                    source_table.c.project_id == row["project_id"],
                    source_table.c.id.in_(
                        historical_sources(row["tenant_id"], row["project_id"], decision=row["id"])
                    ),
                )
                .order_by(source_table.c.id)
            ).mappings()
        )
        states = source_states(c, row["tenant_id"], origins)
        value["intake_sources"] = [
            {
                "source_row_id": str(origin["id"]),
                "original_decision_id": str(origin["decision_id"]),
                "document_id": str(origin["document_id"]),
                "locator": origin["locator"],
                "source_digest": digest(origin["source_snapshot"]),
                **states[origin["id"]],
            }
            for origin in origins
        ]
        return value | {
            "kind": kind,
            "href": f"/projects?project={row['project_id']}&tab=decisions#decision-{row['id']}",
        }
    if kind == "issue":
        value = target_snapshot(row)
    else:
        value = _plain(
            {
                key: row[key]
                for key in (
                    "id",
                    "title",
                    "description",
                    "status",
                    "owner_user_id",
                    "likelihood",
                    "impact",
                    "score",
                    "mitigation_plan",
                    "contingency_plan",
                    "draft_state",
                    "target_date",
                    "closed_at",
                    "updated_at",
                )
            }
        )
    return value | {
        "kind": kind,
        "href": f"/projects?project={row['project_id']}&tab=work-items&entity_id={row['id']}",
    }


def task_dependency_snapshots(
    c: Connection, tenant: UUID, project: UUID, rows: list[Any]
) -> dict[UUID, dict[str, Any]]:
    if not rows:
        return {}
    d = tables.task_dependencies
    edges = (
        c.execute(
            select(d.c.task_id, d.c.depends_on_task_id, d.c.baseline_id)
            .where(
                d.c.tenant_id == tenant,
                d.c.project_id == project,
                d.c.task_id.in_([row["id"] for row in rows]),
                active_dependencies(tenant, project),
            )
            .order_by(d.c.task_id, d.c.depends_on_task_id, d.c.baseline_id)
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[dict[str, Any]]] = {}
    for edge in edges:
        grouped.setdefault(edge["task_id"], []).append(
            _plain(
                {
                    "depends_on_task_id": edge["depends_on_task_id"],
                    "baseline_id": edge["baseline_id"],
                }
            )
        )
    return {
        row["id"]: task_view(row)
        | {
            "kind": row["kind"],
            "source_entity": row["source_entity"],
            "source_entity_id": str(row["source_entity_id"]) if row["source_entity_id"] else None,
            "priority": row["priority"],
            "dependencies": grouped.get(row["id"], []),
        }
        for row in rows
    }


def freeze_context(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    source: IntakeBusinessRef | None,
    predecessors: list[TaskDependencyRef],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if source:
        t = {"issue": tables.issues, "risk": tables.risks, "decision": tables.decisions}[
            source.kind
        ]
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == source.id
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or (source.kind == "issue" and row.get("withdrawn_at") is not None)
            or source.kind == "risk"
            and row["draft_state"] != "confirmed"
        ):
            raise ConversationError("请选择本项目实际问题、已确认风险或决策")
        snapshot = business_snapshot(row, source.kind, c)
        if digest(snapshot) != source.expected_digest:
            raise ConversationError("所选业务记录或历史来源关联已变化，请重新读取后核对")
        value["source"] = snapshot
    if predecessors:
        t = tables.tasks
        rows = {
            row["id"]: row
            for row in c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.id.in_([item.id for item in predecessors]),
                )
            ).mappings()
        }
        current = task_dependency_snapshots(c, ctx.tenant.id, project, list(rows.values()))
        snapshots = []
        for ref in predecessors:
            row = rows.get(ref.id)
            if row is None:
                raise ConversationError("前置任务不属于本项目")
            snapshot = current[ref.id]
            if digest(snapshot) != ref.expected_digest:
                raise ConversationError("前置任务或其依赖已变化，请重新核对原任务")
            snapshots.append(snapshot)
        value["predecessors"] = snapshots
    return value


def work_order(work: dict[UUID, Any], selected: list[UUID]) -> list[UUID]:
    selected_set = set(selected)
    result: list[UUID] = []
    active: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(key: UUID) -> None:
        if key in active:
            raise ValueError("初始化工作之间存在循环依赖，请调整先后关系")
        if key in visited:
            return
        active.add(key)
        for predecessor in work[key].predecessor_work_keys:
            if predecessor not in work:
                raise ValueError("前置工作不属于本次现状版本")
            if predecessor in selected_set:
                visit(predecessor)
        active.remove(key)
        visited.add(key)
        result.append(key)

    for key in selected:
        visit(key)
    return result
