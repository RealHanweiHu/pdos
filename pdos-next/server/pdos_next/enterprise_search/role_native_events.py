"""Resolve native role projections from committed COMMON receipts and fixed subjects."""

from sqlalchemy import and_, select

from pdos_next.domain.manufacturing_baseline.models import PreparationVersion
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication,
    ManufacturingPublicationDocument,
)
from pdos_next.domain.verification_handoff.models import VerificationHandoffFact
from pdos_next.domain.work_management.models import ProjectStatusUpdate
from pdos_next.service import EVENTS

OPERATIONS = frozenset(
    {
        "work.status_update.create",
        "npi.work_instruction.record",
        "npi.control_plan.record",
        "npi.manufacturing_baseline.publish",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "verification.handoff.return",
    }
)


def targets(session, event, receipt):
    op = receipt.operation
    if op not in OPERATIONS or EVENTS[op] != event.type:
        return []
    if op == "work.status_update.create":
        model, family = ProjectStatusUpdate, "project_status"
        bound = (
            select(model)
            .where(
                model.tenant_id == event.tenant_id,
                model.category_id == event.category_id,
                model.product_id == receipt.product_id,
                model.id == event.subject_id,
                model.revision == event.subject_revision,
                model.receipt_id == receipt.id,
                model.command_id == receipt.command_id,
                model.operation == op,
            )
            .subquery()
        )
        query = select(model.id).join(
            bound,
            and_(
                model.tenant_id == bound.c.tenant_id,
                model.category_id == bound.c.category_id,
                model.product_id == bound.c.product_id,
                model.project_id == bound.c.project_id,
            ),
        )
    elif op == "npi.manufacturing_baseline.publish":
        model, family = ManufacturingPublicationDocument, "manufacturing_document"
        publication = ManufacturingBaselinePublication
        fixed = select(publication.series_id).where(
            publication.tenant_id == event.tenant_id,
            publication.category_id == event.category_id,
            publication.product_id == receipt.product_id,
            publication.id == event.subject_id,
            publication.revision == event.subject_revision,
            publication.receipt_id == receipt.id,
            publication.command_id == receipt.command_id,
        )
        query = (
            select(model.id)
            .join(
                publication,
                and_(
                    model.tenant_id == publication.tenant_id,
                    model.category_id == publication.category_id,
                    model.product_id == publication.product_id,
                    model.project_id == publication.project_id,
                    model.publication_id == publication.id,
                    model.publication_revision == publication.revision,
                ),
            )
            .where(
                publication.tenant_id == event.tenant_id,
                publication.category_id == event.category_id,
                publication.series_id.in_(fixed),
            )
        )
    elif op.startswith("npi."):
        model, family = PreparationVersion, "manufacturing_document"
        # Preparation's own immutable confirmation pin binds the real receipt;
        # its source row predates neither the saved command nor its subject.
        from pdos_next.models import Confirmation

        fixed = (
            select(model.series_id)
            .join(
                Confirmation,
                and_(
                    Confirmation.tenant_id == model.tenant_id,
                    Confirmation.id == model.shared_proof_id,
                    Confirmation.consumed.is_(True),
                ),
            )
            .where(
                model.tenant_id == event.tenant_id,
                model.category_id == event.category_id,
                model.product_id == receipt.product_id,
                model.id == event.subject_id,
                model.revision == event.subject_revision,
                model.operation == op,
                model.input_snapshot["command"]["command_id"].astext == str(receipt.command_id),
                model.intent_digest == receipt.intent_digest,
            )
        )
        query = select(model.id).where(
            model.tenant_id == event.tenant_id,
            model.category_id == event.category_id,
            model.product_id == receipt.product_id,
            model.series_id.in_(fixed),
        )
    else:
        model, family = VerificationHandoffFact, "verification_handoff"
        fixed = select(model.request_id).where(
            model.tenant_id == event.tenant_id,
            model.category_id == event.category_id,
            model.product_id == receipt.product_id,
            model.operation == op,
            model.next_request_version_id == event.subject_id,
            model.next_request_revision == event.subject_revision,
        )
        query = select(model.id).where(
            model.tenant_id == event.tenant_id,
            model.category_id == event.category_id,
            model.product_id == receipt.product_id,
            model.request_id.in_(fixed),
        )
    return [(family, value) for value in session.scalars(query)]
