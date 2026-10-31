"""Only native predecessor, publication-document and physical-request Build edges."""

from sqlalchemy import and_, select

from pdos_next.domain.builds.models import Build
from pdos_next.domain.manufacturing_baseline.models import PreparationVersion
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingPublicationDocument,
)
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import VerificationHandoffFact

from .readable_sources import readable
from .role_native_sources import scope


def append_edges(edge, kinds):
    if "manufacturing_document" in kinds:
        doc, previous = readable(PreparationVersion), readable(PreparationVersion)
        from sqlalchemy.orm import aliased

        previous = aliased(previous, name="native_previous_manufacturing_document")
        pair = (
            select(doc)
            .join(
                previous,
                and_(
                    scope(doc, previous),
                    doc.previous_id == previous.id,
                    doc.previous_revision == previous.revision,
                    doc.kind == previous.kind,
                    doc.series_id == previous.series_id,
                ),
            )
            .where(doc.kind.in_(("work_instruction", "control_plan")))
        )
        edge(
            "manufacturing_document",
            doc.id,
            "manufacturing_document",
            previous.id,
            "document_previous",
            pair,
        )
        link = readable(ManufacturingPublicationDocument)
        fixed = select(link).join(
            doc,
            and_(
                scope(link, doc),
                link.document_id == doc.id,
                link.document_revision == doc.revision,
                link.document_kind == doc.kind,
                link.process_id == doc.process_id,
                link.process_revision == doc.process_revision,
                link.operation_key == doc.operation_key,
            ),
        )
        edge(
            "manufacturing_document",
            link.id,
            "manufacturing_document",
            doc.id,
            "published_document",
            fixed,
        )
        edge(
            "manufacturing_document",
            doc.id,
            "manufacturing_document",
            link.id,
            "document_publication",
            fixed,
        )
    if {"verification_handoff", "build"} <= kinds:
        handoff, request, build = map(
            readable,
            (
                VerificationHandoffFact,
                FormalVerificationRequest,
                Build,
            ),
        )
        fixed = (
            select(handoff)
            .join(
                request,
                and_(
                    scope(handoff, request),
                    handoff.next_request_version_id == request.id,
                    handoff.next_request_revision == request.revision,
                    handoff.request_id == request.request_id,
                ),
            )
            .join(
                build,
                and_(
                    scope(request, build),
                    request.build_id == build.id,
                    request.build_revision == build.revision,
                ),
            )
        )
        edge("verification_handoff", handoff.id, "build", build.id, "handoff_build", fixed)
        edge("build", build.id, "verification_handoff", handoff.id, "build_handoff", fixed)
