"""Feedback history and fresh native choices in the caller's current scope."""

from sqlalchemy import or_, select

from pdos_next.domain.build_execution.models import BuildLot
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.projects.models import Project
from pdos_next.models import Artifact
from pdos_next.service import require_access

from . import owner
from .models import FieldFeedbackCurrent, FieldFeedbackVersion, FieldResponseRecord


def workspace(s, ctx, pid, project_id=None):
    require_access(s, ctx, pid)
    if project_id is not None:
        owner.project(s, ctx, pid, project_id)
    query = select(FieldFeedbackCurrent).where(
        FieldFeedbackCurrent.tenant_id == ctx.tenant_id,
        FieldFeedbackCurrent.category_id == ctx.category_id,
        or_(FieldFeedbackCurrent.product_id == pid, FieldFeedbackCurrent.product_id.is_(None)),
    )
    if project_id:
        query = query.where(
            or_(
                FieldFeedbackCurrent.project_id == project_id,
                FieldFeedbackCurrent.project_id.is_(None),
            )
        )
    feedbacks = []
    for pointer in s.scalars(
        query.order_by(FieldFeedbackCurrent.created_at.desc(), FieldFeedbackCurrent.id).limit(50)
    ):
        row = owner.retained(s, ctx, s.get(FieldFeedbackVersion, pointer.version_id))
        value = owner.view(s, ctx, row)
        value["history"] = [
            {
                "version_id": str(version.id),
                "revision": version.revision,
                "receipt_id": str(version.receipt_id),
                "created_at": version.created_at.isoformat(),
            }
            for version in s.scalars(
                select(FieldFeedbackVersion)
                .where(
                    FieldFeedbackVersion.tenant_id == ctx.tenant_id,
                    FieldFeedbackVersion.category_id == ctx.category_id,
                    FieldFeedbackVersion.feedback_id == row.feedback_id,
                )
                .order_by(FieldFeedbackVersion.revision)
            )
        ]
        value["responses"] = [
            {
                **response.body,
                "id": str(response.id),
                "revision": response.revision,
                "receipt_id": str(response.receipt_id),
                "visibility": response.visibility,
                "created_at": response.created_at.isoformat(),
            }
            for response in s.scalars(
                select(FieldResponseRecord)
                .where(
                    FieldResponseRecord.tenant_id == ctx.tenant_id,
                    FieldResponseRecord.category_id == ctx.category_id,
                    FieldResponseRecord.feedback_id == row.feedback_id,
                )
                .order_by(FieldResponseRecord.created_at, FieldResponseRecord.id)
            )
        ]
        feedbacks.append(value)
    choices = {}
    for key, model, label in (
        ("engineering_configurations", EngineeringConfiguration, "name"),
        ("manufacturing_configurations", ProcessRevision, "name"),
        ("batches", BuildLot, "lot_label"),
        ("projects", Project, "name"),
    ):
        query = select(model).where(model.tenant_id == ctx.tenant_id, model.product_id == pid)
        choices[key] = (
            [
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    label: getattr(row, label),
                    **(
                        {"engineering_configuration_id": str(row.engineering_configuration_id)}
                        if key == "manufacturing_configurations"
                        else {}
                    ),
                }
                for row in s.scalars(query.order_by(model.created_at.desc(), model.id).limit(100))
            ]
            if pid
            else []
        )
    choices["sources"] = [
        {
            "id": str(row.id),
            "revision": row.revision,
            "title": row.title,
            "content": row.content,
            "visibility": row.visibility,
            "status": row.status,
        }
        for row in s.scalars(
            select(Artifact)
            .where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == ctx.category_id,
                or_(Artifact.product_id == pid, Artifact.product_id.is_(None)),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id)
            .limit(100)
        )
    ]
    return {"feedbacks": feedbacks, "options": choices}
