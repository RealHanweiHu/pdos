"""Exact ID feedback and delivery scope in ECR impact analysis."""

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, select

from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest

AXES = (
    "requirements",
    "mechanical",
    "hardware",
    "firmware",
    "verification",
    "supply",
    "cost",
    "schedule",
    "handoffs",
)


class ImpactAssessment(Contract):
    conclusion: Literal["affected", "unaffected", "unknown"]
    basis: Text
    next_action: Text | None = None


class IdImpactDraft(Contract):
    expected_basis_digest: Digest
    feedback_responses: dict[str, Text]
    assessments: dict[str, ImpactAssessment]


def impact_basis(
    connection: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID
) -> dict[str, Any] | None:
    links = list(
        connection.execute(
            select(tables.id_design_change_decisions)
            .where(
                tables.id_design_change_decisions.c.tenant_id == tenant_id,
                tables.id_design_change_decisions.c.project_id == project_id,
                tables.id_design_change_decisions.c.ecr_id == ecr_id,
            )
            .order_by(tables.id_design_change_decisions.c.id)
        ).mappings()
    )
    if not links:
        return None
    freezes = [UUID(row["snapshot"]["freeze"]["id"]) for row in links]
    h, i, r = (
        tables.id_design_handoffs,
        tables.id_design_handoff_items,
        tables.id_design_handoff_responses,
    )
    all_handoffs = list(
        connection.execute(
            select(h)
            .where(
                h.c.tenant_id == tenant_id, h.c.project_id == project_id, h.c.freeze_id.in_(freezes)
            )
            .order_by(h.c.id)
        ).mappings()
    )
    superseded = {row["previous_handoff_id"] for row in all_handoffs if row["previous_handoff_id"]}
    handoffs = [row for row in all_handoffs if row["id"] not in superseded]
    items = list(
        connection.execute(
            select(i)
            .where(
                i.c.tenant_id == tenant_id,
                i.c.project_id == project_id,
                i.c.handoff_id.in_([row["id"] for row in handoffs]),
            )
            .order_by(i.c.id)
        ).mappings()
    )
    responses = list(
        connection.execute(
            select(r)
            .where(
                r.c.tenant_id == tenant_id,
                r.c.project_id == project_id,
                r.c.item_id.in_([row["id"] for row in items]),
            )
            .order_by(r.c.id)
        ).mappings()
    )
    from app.domain.formal_schedule import current_plan
    from app.domain.id_handoff_runtime import target_basis

    formal = current_plan(connection, tenant_id, project_id)
    targets = []
    if formal:
        by_key = {node["node_key"]: node for node in formal["plan"]["nodes"]}
        wanted = {row["target_node_id"] for row in handoffs}
        targets = [
            target_basis(row["id"], by_key[row["node_key"]])
            for row in formal["nodes"]
            if row["id"] in wanted
        ]
    return {
        "version": "id_change_impact.v1",
        "links": [_plain(row) for row in links],
        "handoffs": [_plain(row) for row in handoffs],
        "items": [_plain(row) for row in items],
        "responses": [_plain(row) for row in responses],
        "current_targets": targets,
    }


def freeze_analysis(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    ecr_id: UUID,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    basis = impact_basis(connection, tenant_id, project_id, ecr_id)
    if basis is None:
        return analysis
    if not isinstance(analysis.get("summary"), str) or not analysis["summary"].strip():
        raise ProductWorkError("请填写实际变更影响分析")
    draft = IdImpactDraft.model_validate(analysis.get("id_design"))
    if draft.expected_basis_digest != digest(basis):
        raise ProductWorkError("ID反馈、交接或下游责任已变化，请刷新后重新分析")
    if set(draft.feedback_responses) != {str(row["candidate_id"]) for row in basis["links"]}:
        raise ProductWorkError("影响分析须逐条回应本次转入的全部ID反馈")
    if set(draft.assessments) != set(AXES):
        raise ProductWorkError("请完成需求、结构、硬件、FW、验证、供给、成本、日期和交接影响分析")
    if any(
        row.conclusion == "affected" and not row.next_action for row in draft.assessments.values()
    ):
        raise ProductWorkError("受影响领域须明确后续处理行动")
    return {**analysis, "id_design": {**draft.model_dump(mode="json"), "basis": basis}}


def require_current_impact(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    ecr_id: UUID,
    analysis: dict[str, Any] | None,
) -> None:
    basis = impact_basis(connection, tenant_id, project_id, ecr_id)
    if basis is None:
        return
    stored = (analysis or {}).get("id_design", {})
    if stored.get("expected_basis_digest") != digest(basis):
        raise ProductWorkError("批准所需的ID反馈或交接依据已变化，请退回重新分析")
    draft = IdImpactDraft.model_validate(
        {
            key: stored.get(key)
            for key in ("expected_basis_digest", "feedback_responses", "assessments")
        }
    )
    if set(draft.assessments) != set(AXES) or any(
        row.conclusion == "unknown" for row in draft.assessments.values()
    ):
        raise ProductWorkError("ID变更仍有未明确影响，请补齐后批准")
