"""Fail-closed validation for evidence references.

Single point of citation preflight for the whole system (V2-7). Every kind a
conclusion may cite is resolved here against the database; an unknown kind or
an unresolvable reference fails closed rather than passing through unchecked.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, func, select

from app.db.schema import tables

# Extended from {document, event} in V2-7 so agent conclusions can cite what
# they actually stand on. Adding a kind means adding a resolver below — an
# unlisted kind is refused, never assumed valid.
EVIDENCE_KINDS = frozenset({"document", "event", "evidence_snapshot", "test_run", "decision"})


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
        if kind not in EVIDENCE_KINDS:
            raise QualityEvidenceError
        if kind == "document":
            found = connection.execute(
                select(tables.documents.c.id).where(
                    tables.documents.c.tenant_id == tenant_id,
                    tables.documents.c.project_id == project_id,
                    tables.documents.c.id == _as_uuid(reference),
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
        elif kind == "evidence_snapshot":
            # Snapshots are tenant-scoped, not project-scoped: the point of the
            # shared evidence base is that one capture serves every project.
            found = connection.execute(
                select(tables.evidence_snapshots.c.id).where(
                    tables.evidence_snapshots.c.tenant_id == tenant_id,
                    tables.evidence_snapshots.c.id == _as_uuid(reference),
                )
            ).scalar_one_or_none()
        elif kind == "test_run":
            found = connection.execute(
                select(tables.test_runs.c.id).where(
                    tables.test_runs.c.tenant_id == tenant_id,
                    tables.test_runs.c.project_id == project_id,
                    tables.test_runs.c.id == _as_uuid(reference),
                )
            ).scalar_one_or_none()
        else:
            found = connection.execute(
                select(tables.decisions.c.id).where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.project_id == project_id,
                    tables.decisions.c.id == _as_uuid(reference),
                )
            ).scalar_one_or_none()
        if found is None:
            raise QualityEvidenceError


def _as_uuid(reference: str) -> UUID:
    try:
        return UUID(reference)
    except ValueError as error:
        raise QualityEvidenceError from error
