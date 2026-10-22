"""G0 result projection over actual identities, the fixed definition and project."""

from sqlalchemy import select

from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.products.variant_models import Variant
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.models import Principal
from pdos_next.service import require_access

from .access import fail, proposal
from .models import ProjectOpenItem, ProposalDecision


def read(session, ctx, proposal_id):
    row = proposal(session, ctx, proposal_id)
    decision = session.scalar(
        select(ProposalDecision)
        .where(
            ProposalDecision.tenant_id == ctx.tenant_id,
            ProposalDecision.category_id == ctx.category_id,
            ProposalDecision.proposal_id == row.id,
        )
        .order_by(ProposalDecision.created_at.desc())
        .limit(1)
    )
    if not decision or decision.outcome != "approved":
        fail("VERSION_CONFLICT", "g0_not_approved", "当前提案尚无已批准的立项结果。")
    if any(
        value is None
        for value in (
            decision.created_product_id,
            decision.created_project_id,
            decision.created_definition_id,
            decision.receipt_id,
        )
    ):
        fail("SOURCE_UNAVAILABLE", "g0_result_incomplete", "立项结果记录不完整，请核对原回执。")
    product = require_access(session, ctx, decision.created_product_id)
    project = session.get(Project, decision.created_project_id)
    definition = session.get(DefinitionRevision, decision.created_definition_id)
    variant = (
        session.get(Variant, decision.created_variant_id) if decision.created_variant_id else None
    )
    if project is None or definition is None or (decision.created_variant_id and variant is None):
        fail("NOT_FOUND", "g0_result_unreadable", "立项结果不在当前可读范围。", 404)
    link = session.scalar(
        select(ProjectProductLink).where(
            ProjectProductLink.tenant_id == ctx.tenant_id,
            ProjectProductLink.category_id == ctx.category_id,
            ProjectProductLink.project_id == project.id,
            ProjectProductLink.product_id == product.id,
            ProjectProductLink.variant_id == decision.created_variant_id,
        )
    )
    if (
        project.tenant_id != ctx.tenant_id
        or project.category_id != ctx.category_id
        or project.product_id != product.id
        or project.g0_decision_id != decision.id
        or definition.tenant_id != ctx.tenant_id
        or definition.category_id != ctx.category_id
        or definition.product_id != product.id
        or definition.variant_id != decision.created_variant_id
        or definition.g0_decision_id != decision.id
        or definition.source_proposal_id != row.id
        or definition.source_submission_id != decision.submission_id
        or definition.revision != 1
        or not definition.sealed
        or link is None
        or link.definition_id != definition.id
        or link.definition_revision != 1
        or variant is not None
        and (variant.product_id != product.id or variant.g0_decision_id != decision.id)
    ):
        fail("SOURCE_UNAVAILABLE", "g0_result_binding_invalid", "立项结果关联尚未核对，请刷新。")
    items = list(
        session.scalars(
            select(ProjectOpenItem)
            .where(
                ProjectOpenItem.tenant_id == ctx.tenant_id,
                ProjectOpenItem.category_id == ctx.category_id,
                ProjectOpenItem.project_id == project.id,
                ProjectOpenItem.g0_decision_id == decision.id,
            )
            .order_by(ProjectOpenItem.due_date, ProjectOpenItem.id)
        )
    )
    people = {
        person.id: person.name
        for person in session.scalars(
            select(Principal).where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.id.in_(
                    {decision.decided_by, project.owner_id, *[item.owner_id for item in items]}
                ),
            )
        )
    }

    def person(identity):
        return {"id": str(identity), "name": people.get(identity)}

    return {
        "category_id": str(row.category_id),
        "proposal_id": str(row.id),
        "decision": {
            "id": str(decision.id),
            "outcome": decision.outcome,
            "receipt_id": str(decision.receipt_id),
            "signer": person(decision.decided_by),
            "decided_at": decision.created_at.isoformat(),
            "rationale": decision.rationale,
        },
        "identity": {
            "kind": "new_variant" if variant else "new_product",
            "product": {"id": str(product.id), "name": product.name},
            "variant": {"id": str(variant.id), "name": variant.name, "kind": variant.kind}
            if variant
            else None,
        },
        "definition": {
            "id": str(definition.id),
            "title": definition.title,
            "product_id": str(product.id),
            "variant_id": str(definition.variant_id) if definition.variant_id else None,
            "revision": definition.revision,
            "sealed": definition.sealed,
            "status": definition.status,
        },
        "project": {
            "id": str(project.id),
            "name": project.name,
            "owner": person(project.owner_id),
            "product_id": str(product.id),
            "definition_id": str(link.definition_id),
            "definition_revision": link.definition_revision,
        },
        "open_items": [
            {
                "id": str(item.id),
                "project_id": str(project.id),
                "g0_decision_id": str(item.g0_decision_id),
                "kind": item.kind,
                "title": item.title,
                "owner": person(item.owner_id),
                "due_date": item.due_date.isoformat(),
                "status": item.status,
            }
            for item in items
        ],
    }
