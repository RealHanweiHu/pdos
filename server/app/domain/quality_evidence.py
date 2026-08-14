"""Fail-closed validation for CAPA evidence references."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, func, select

from app.db.schema import tables


class QualityEvidenceError(ValueError):
    """Raised when evidence is malformed or outside the bound Project."""


def validate_evidence_refs(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    refs: list[dict[str, object]],
    required: bool,
) -> None:
    if required and not refs:
        raise QualityEvidenceError
    for ref in refs:
        if set(ref) != {"kind", "reference"}:
            raise QualityEvidenceError
        kind, reference = ref["kind"], ref["reference"]
        if not isinstance(kind, str) or not isinstance(reference, str) or not reference.strip():
            raise QualityEvidenceError
        if kind == "document":
            try:
                document_id = UUID(reference)
            except ValueError as error:
                raise QualityEvidenceError from error
            found = connection.execute(
                select(tables.documents.c.id).where(
                    tables.documents.c.tenant_id == tenant_id,
                    tables.documents.c.project_id == project_id,
                    tables.documents.c.id == document_id,
                )
            ).scalar_one_or_none()
        elif kind == "event":
            found = connection.execute(
                select(func.min(tables.events.c.id)).where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.project_id == project_id,
                    tables.events.c.event_id == reference,
                )
            ).scalar_one_or_none()
        else:
            raise QualityEvidenceError
        if found is None:
            raise QualityEvidenceError
