"""Versioned evidence for root-cause and effectiveness knowledge candidates."""

from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.knowledge_sources import snapshot_problem
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope

QUALITY_LEARNING_KINDS = {"root_cause", "effectiveness_review"}


def learning_refs(c: Connection, job: Any) -> tuple[list[dict[str, object]] | None, str]:
    tenant, project = job["tenant_id"], job["project_id"]
    if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
        return None, "quality_source_unavailable"
    kind = job["source_kind"]
    table = tables.root_cause_analyses if kind == "root_cause" else tables.effectiveness_reviews
    row = (
        c.execute(
            select(table).where(
                table.c.tenant_id == tenant,
                table.c.project_id == project,
                table.c.id == job["source_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    original = job["source_snapshot"]
    if row is None or any(key not in row for key in original):
        return None, "quality_source_unavailable"
    if _plain({key: row[key] for key in original}) != original:
        return None, "quality_source_changed"
    if kind == "root_cause" and row["status"] != "approved":
        return None, "quality_source_changed"
    if kind == "effectiveness_review":
        latest = c.execute(
            select(table.c.id)
            .where(
                table.c.tenant_id == tenant,
                table.c.project_id == project,
                table.c.ncr_id == row["ncr_id"],
            )
            .order_by(table.c.review_number.desc())
            .limit(1)
        ).scalar_one()
        if latest != row["id"]:
            return None, "quality_source_changed"
    refs: list[dict[str, object]] = [
        {"kind": kind, "reference": str(row["id"]), "version": job["source_version"]}
    ]
    for ref in original.get("evidence_refs", []):
        evidence_kind, identity = ref.get("kind"), ref.get("reference")
        if not isinstance(identity, str):
            return None, "quality_evidence_unavailable"
        if evidence_kind == "event":
            t = tables.events
            exists = c.execute(
                select(t.c.id)
                .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.event_id == identity)
                .limit(1)
            ).first()
            if not exists:
                return None, "quality_evidence_unavailable"
            refs.append({"kind": "event", "reference": identity})
            continue
        try:
            uid = UUID(identity)
        except ValueError:
            return None, "quality_evidence_unavailable"
        source_table = {
            "document": tables.documents,
            "test_run": tables.test_runs,
            "decision": tables.decisions,
            "evidence_snapshot": tables.evidence_snapshots,
        }.get(evidence_kind)
        if source_table is None:
            return None, "quality_evidence_unavailable"
        q = select(source_table).where(source_table.c.tenant_id == tenant, source_table.c.id == uid)
        if evidence_kind == "evidence_snapshot":
            sources = tables.research_sources
            q = q.add_columns(sources.c.status.label("source_status")).outerjoin(
                sources,
                (sources.c.tenant_id == source_table.c.tenant_id)
                & (sources.c.id == source_table.c.source_id),
            )
        else:
            q = q.where(source_table.c.project_id == project)
        evidence = c.execute(q).mappings().one_or_none()
        if evidence is None:
            return None, "quality_evidence_unavailable"
        binding: dict[str, object] = {"kind": evidence_kind, "reference": identity}
        if evidence_kind == "document":
            binding["digest"] = evidence["sha256"]
        elif evidence_kind == "evidence_snapshot":
            if snapshot_problem(c, tenant, evidence):
                return None, "quality_evidence_unavailable"
            binding["digest"] = evidence["content_digest"]
        else:
            if evidence["updated_at"] > job["created_at"]:
                return None, "quality_evidence_changed"
            if evidence_kind == "test_run" and (
                evidence["draft_state"] != "confirmed"
                or evidence["status"] not in {"passed", "failed", "aborted"}
            ):
                return None, "quality_evidence_unavailable"
            binding["updated_at_utc"] = (
                evidence["updated_at"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
            )
        refs.append(binding)
    if not original.get("evidence_refs"):
        return None, "quality_evidence_unavailable"
    return refs, "ready"
