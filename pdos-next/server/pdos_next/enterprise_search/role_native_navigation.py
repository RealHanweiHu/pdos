"""Human destinations use actual native fixed records and existing project panels."""

from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import and_, select

from pdos_next.domain.builds.models import Build
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingPublicationDocument,
)
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import VerificationHandoffFact


def links(session, sources):
    published = {
        UUID(str(row["source_id"]))
        for row in sources.values()
        if row["source_type"] == "manufacturing_document"
    }
    if published:
        published = set(
            session.scalars(
                select(ManufacturingPublicationDocument.id).where(
                    ManufacturingPublicationDocument.id.in_(published)
                )
            )
        )
    ids = {
        UUID(str(row["source_id"]))
        for row in sources.values()
        if row["source_type"] == "verification_handoff"
    }
    handoff, request = VerificationHandoffFact, FormalVerificationRequest
    builds = (
        dict(
            session.execute(
                select(handoff.id, Build.id)
                .join(
                    request,
                    and_(
                        handoff.tenant_id == request.tenant_id,
                        handoff.category_id == request.category_id,
                        handoff.product_id == request.product_id,
                        handoff.project_id == request.project_id,
                        handoff.next_request_version_id == request.id,
                        handoff.next_request_revision == request.revision,
                    ),
                )
                .join(
                    Build,
                    and_(
                        Build.tenant_id == request.tenant_id,
                        Build.category_id == request.category_id,
                        Build.product_id == request.product_id,
                        Build.project_id == request.project_id,
                        Build.id == request.build_id,
                    ),
                )
                .where(handoff.id.in_(ids))
            ).all()
        )
        if ids
        else {}
    )
    result = {}
    for cid, row in sources.items():
        if not all(row.get(key) for key in ("category_id", "product_id", "project_id")):
            continue
        kind, identity = row["source_type"], UUID(str(row["source_id"]))
        selected = {}
        if kind == "project_status":
            view, panel, label = "now", "summary", "查看当前项目与具名状态"
        elif kind == "manufacturing_document":
            view, panel, label = (
                ("prep", "publication", "查看当前制造发布")
                if identity in published
                else ("prep", "manufacturing", "查看制造准备与草稿")
            )
        elif kind == "verification_handoff" and identity in builds:
            view, panel, label = "builds", "handoff", "查看当前交样与接收"
            selected = {"build": str(builds[identity])}
        else:
            continue
        result[cid] = {
            "object_url": "/?"
            + urlencode(
                {
                    "area": "cockpit",
                    "category": str(row["category_id"]),
                    "product": str(row["product_id"]),
                    "project": str(row["project_id"]),
                    "projectView": view,
                    "panel": panel,
                    **selected,
                }
            ),
            "object_label": label,
        }
    return result
