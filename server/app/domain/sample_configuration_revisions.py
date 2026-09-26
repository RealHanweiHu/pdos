"""Immutable observed configurations; no current-state backfill of past tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Select, String, func, select

from app.db.schema import tables
from app.domain.product_workspace import _plain, digest


def create_revision(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    sample_id: UUID,
    actor_user_id: UUID,
    source: str,
    snapshot: dict[str, Any],
    source_document_id: UUID | None,
    occurred_at: datetime,
) -> UUID:
    # All callers hold the project write lock. A revision describes one actual
    # observation; report rows must never merge into the sample's current state.
    t = tables.sample_configuration_revisions
    number = c.execute(
        select(func.coalesce(func.max(t.c.revision_number), 0) + 1).where(
            t.c.tenant_id == tenant_id,
            t.c.sample_id == sample_id,
        )
    ).scalar_one()
    value = _plain(snapshot)
    revision_id = uuid4()
    c.execute(
        t.insert().values(
            id=revision_id,
            tenant_id=tenant_id,
            project_id=project_id,
            sample_id=sample_id,
            revision_number=number,
            source=source,
            source_document_id=source_document_id,
            created_by_user_id=actor_user_id,
            snapshot=value,
            content_digest=digest(value),
            created_at=occurred_at,
        )
    )
    return revision_id


def pin_current_configuration(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    sample_id: UUID | None,
    actor_user_id: UUID,
    occurred_at: datetime,
    source: str = "current_observation",
) -> UUID | None:
    """Observe current confirmed facts for a newly started test or manual edit."""
    if sample_id is None:
        return None
    t = tables.sample_build_configurations
    row = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.sample_id == sample_id,
                t.c.draft_state == "confirmed",
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    fields = (
        "pcb_version",
        "structure_version",
        "fw_release_id",
        "development_bom_id",
        "key_component_suppliers",
        "build_date",
    )
    snapshot = {key: row[key] for key in fields}
    snapshot["fw_version"] = (
        c.execute(
            select(tables.fw_releases.c.version).where(
                tables.fw_releases.c.tenant_id == tenant_id,
                tables.fw_releases.c.project_id == project_id,
                tables.fw_releases.c.id == row["fw_release_id"],
            )
        ).scalar_one_or_none()
        if row["fw_release_id"]
        else None
    )
    # BOM versions carry immutable identities; retain its human-readable version too.
    bom = (
        c.execute(
            select(tables.development_boms.c.code, tables.development_boms.c.version).where(
                tables.development_boms.c.tenant_id == tenant_id,
                tables.development_boms.c.project_id == project_id,
                tables.development_boms.c.id == row["development_bom_id"],
            )
        )
        .mappings()
        .one_or_none()
        if row["development_bom_id"]
        else None
    )
    snapshot["bom_code"] = bom["code"] if bom else None
    snapshot["bom_version"] = bom["version"] if bom else None
    r = tables.sample_configuration_revisions
    previous = (
        c.execute(
            select(r).where(
                r.c.tenant_id == tenant_id,
                r.c.project_id == project_id,
                r.c.sample_id == sample_id,
                r.c.id == row["current_revision_id"],
            )
        )
        .mappings()
        .one_or_none()
        if row["current_revision_id"]
        else None
    )
    if previous and previous["content_digest"] == digest(_plain(snapshot)):
        return UUID(str(previous["id"]))
    revision_id = create_revision(
        c,
        tenant_id=tenant_id,
        project_id=project_id,
        sample_id=sample_id,
        actor_user_id=actor_user_id,
        source=source,
        snapshot=snapshot,
        source_document_id=row["source_document_id"],
        occurred_at=occurred_at,
    )
    c.execute(
        t.update()
        .where(t.c.tenant_id == tenant_id, t.c.id == row["id"])
        .values(
            current_revision_id=revision_id,
        )
    )
    return revision_id


def run_selection() -> Select[Any]:
    r, t = tables.sample_configuration_revisions, tables.test_runs
    b = tables.test_report_import_batches
    u, case = tables.users, tables.test_cases
    preparation = tables.test_execution_preparations
    successor = (
        select(b.c.superseded_by_batch_id)
        .where(
            b.c.tenant_id == t.c.tenant_id,
            b.c.project_id == t.c.project_id,
            b.c.superseded_by_batch_id.is_not(None),
            b.c.created_run_ids.op("?")(t.c.id.cast(String)),
        )
        .correlate(t)
        .limit(1)
        .scalar_subquery()
    )
    return (
        select(
            t,
            select(b.c.id)
            .where(
                b.c.tenant_id == t.c.tenant_id,
                b.c.project_id == t.c.project_id,
                b.c.created_run_ids.op("?")(t.c.id.cast(String)),
            )
            .correlate(t)
            .order_by(b.c.created_at, b.c.id)
            .limit(1)
            .scalar_subquery()
            .label("import_batch_id"),
            successor.label("import_successor_batch_id"),
            select(tables.field_captures.c.id)
            .where(
                tables.field_captures.c.tenant_id == t.c.tenant_id,
                tables.field_captures.c.project_id == t.c.project_id,
                tables.field_captures.c.test_run_id == t.c.id,
            )
            .correlate(t)
            .scalar_subquery()
            .label("source_field_capture_id"),
            preparation.c.revision_number.label("preparation_revision"),
            preparation.c.snapshot.label("preparation_snapshot"),
            u.c.display_name.label("operator_name"),
            case.c.related_issue_id.label("case_related_issue_id"),
            r.c.id.label("configuration_id"),
            r.c.revision_number,
            r.c.source.label("configuration_source"),
            r.c.snapshot,
            r.c.source_document_id.label("configuration_document_id"),
            r.c.content_digest,
        )
        .outerjoin(
            r,
            (r.c.tenant_id == t.c.tenant_id)
            & (r.c.project_id == t.c.project_id)
            & (r.c.sample_id == t.c.sample_id)
            & (r.c.id == t.c.sample_configuration_revision_id),
        )
        .outerjoin(
            preparation,
            (preparation.c.tenant_id == t.c.tenant_id)
            & (preparation.c.project_id == t.c.project_id)
            & (preparation.c.id == t.c.test_preparation_id),
        )
        .outerjoin(
            u,
            (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.operator_user_id),
        )
        .outerjoin(
            case,
            (case.c.tenant_id == t.c.tenant_id)
            & (case.c.project_id == t.c.project_id)
            & (case.c.id == t.c.test_case_id),
        )
    )
