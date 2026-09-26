"""Live ID acceptance conditions for execution and deterministic forecast inputs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, or_, select

from app.db.schema import tables
from app.domain.product_workspace import digest


def target_basis(node_id: UUID, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(node_id),
        **{
            key: node[key]
            for key in (
                "node_key",
                "title",
                "discipline",
                "owner_user_id",
                "receiver_user_id",
                "expected_output",
                "completion_criteria",
            )
        },
    }


def acceptance_conditions(
    connection: Connection, tenant_id: UUID, project_id: UUID, formal: dict[str, Any] | None
) -> dict[UUID, list[dict[str, Any]]]:
    h, i, r = (
        tables.id_design_handoffs,
        tables.id_design_handoff_items,
        tables.id_design_handoff_responses,
    )
    handoffs = list(
        connection.execute(
            select(h)
            .where(h.c.tenant_id == tenant_id, h.c.project_id == project_id)
            .order_by(h.c.version.desc(), h.c.id)
        ).mappings()
    )
    superseded = {row["previous_handoff_id"] for row in handoffs if row["previous_handoff_id"]}
    from app.domain.id_design_activation import active_freeze_ids

    active = active_freeze_ids(connection, tenant_id, project_id)
    heads = [row for row in handoffs if row["id"] not in superseded and row["freeze_id"] in active]
    items = list(
        connection.execute(
            select(i).where(
                i.c.tenant_id == tenant_id,
                i.c.project_id == project_id,
                i.c.handoff_id.in_([row["id"] for row in heads]),
            )
        ).mappings()
    )
    responses = {
        row["item_id"]: row
        for row in connection.execute(
            select(r).where(
                r.c.tenant_id == tenant_id,
                r.c.project_id == project_id,
                r.c.item_id.in_([row["id"] for row in items]),
            )
        ).mappings()
    }
    documents = {
        row["id"]: row
        for row in connection.execute(
            select(tables.documents.c.id, tables.documents.c.sha256).where(
                tables.documents.c.tenant_id == tenant_id,
                tables.documents.c.project_id == project_id,
                tables.documents.c.id.in_([row["document_id"] for row in items]),
            )
        ).mappings()
    }
    members = select(tables.project_members.c.user_id).where(
        tables.project_members.c.tenant_id == tenant_id,
        tables.project_members.c.project_id == project_id,
    )
    valid_people = set(
        connection.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    ("owner", "admin", "project_manager", "engineer", "quality")
                ),
                or_(tables.users.c.id.in_(members), tables.users.c.role.in_(("owner", "admin"))),
            )
        ).scalars()
    )
    targets = {}
    if formal:
        plans = {row["node_key"]: row for row in formal["plan"]["nodes"]}
        targets = {
            row["id"]: digest(target_basis(row["id"], plans[row["node_key"]]))
            for row in formal["nodes"]
        }
    result: dict[UUID, list[dict[str, Any]]] = {}
    for handoff in heads:
        own = [row for row in items if row["handoff_id"] == handoff["id"]]
        reasons = []
        basis_reasons = []
        if targets.get(handoff["target_node_id"]) != handoff["snapshot"]["target"]["target_digest"]:
            basis_reasons.append("下游正式节点或责任已变化，须按当前安排重新交接")
        if handoff["receiver_user_id"] not in valid_people:
            basis_reasons.append("具名接收人不再是当前有效成员，须更新交接安排")
        if not own or len(own) != len(handoff["snapshot"]["items"]):
            reasons.append("交付条目不完整，须补齐后逐项验收")
        accepted_at = []
        for item in own:
            response = responses.get(item["id"])
            if response is None:
                reasons.append(f"{item['title']}：尚未接收")
            elif response["action"] == "return":
                reasons.append(f"{item['title']}：已退回补齐")
            elif (
                response["accepted_digest"] != handoff["payload_digest"]
                or response["created_by_user_id"] != handoff["receiver_user_id"]
            ):
                reasons.append(f"{item['title']}：缺少本轮有效接收依据")
            else:
                accepted_at.append(response["created_at"])
            document = documents.get(item["document_id"])
            if document is None or document["sha256"] != item["artifact_snapshot"]["sha256"]:
                basis_reasons.append(f"{item['title']}：交付文档依据已变化")
            if any(
                UUID(residual["owner_user_id"]) not in valid_people
                for residual in item["residuals"]
            ):
                basis_reasons.append(f"{item['title']}：遗留责任人已失效，须重新安排")
        reasons.extend(basis_reasons)
        result.setdefault(handoff["target_node_id"], []).append(
            {
                "kind": "id_handoff_acceptance",
                "handoff_id": str(handoff["id"]),
                "freeze_id": str(handoff["freeze_id"]),
                "version": handoff["version"],
                "target_point": "finish",
                "payload_digest": handoff["payload_digest"],
                "basis_current": not basis_reasons,
                "basis_reason": "；".join(basis_reasons) or None,
                "accepted": not reasons,
                "accepted_at": max(accepted_at).isoformat()
                if not reasons and accepted_at
                else None,
                "response_ids": [
                    str(responses[item["id"]]["id"]) for item in own if item["id"] in responses
                ],
                "reason": "；".join(reasons) if reasons else None,
            }
        )
    q = tables.id_design_reacceptance_requirements
    requirements = connection.execute(
        select(q).where(
            q.c.tenant_id == tenant_id, q.c.project_id == project_id, q.c.freeze_id.in_(active)
        )
    ).mappings()
    for requirement in requirements:
        if any(
            row["freeze_id"] == requirement["freeze_id"]
            and row["target_node_id"] == requirement["target_node_id"]
            for row in heads
        ):
            continue
        result.setdefault(requirement["target_node_id"], []).append(
            {
                "kind": "id_handoff_acceptance",
                "handoff_id": None,
                "requirement_id": str(requirement["id"]),
                "freeze_id": str(requirement["freeze_id"]),
                "version": 1,
                "target_point": "finish",
                "payload_digest": requirement["request_digest"],
                "basis_current": True,
                "basis_reason": None,
                "accepted": False,
                "accepted_at": None,
                "response_ids": [],
                "reason": "新冻结设计已启用，尚未提交本版本交接并取得逐项接收",
            }
        )
    from app.domain.id_design_checkpoints import checkpoint_conditions

    for node_id, entries in checkpoint_conditions(
        connection, tenant_id, project_id, formal
    ).items():
        result.setdefault(node_id, []).extend(entries)
    return result


def execution_conditions(conditions: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    result = []
    for entry in conditions:
        timestamp = datetime.fromisoformat(entry["accepted_at"]) if entry["accepted_at"] else None
        satisfied = entry["accepted"] and timestamp is not None and timestamp <= now
        result.append(
            {
                **entry,
                "not_before": entry["accepted_at"],
                "satisfied": satisfied,
                "reason": None
                if satisfied
                else entry["reason"] or "完成依据发生在该实际时间之后，不能倒填为已满足",
            }
        )
    return result
