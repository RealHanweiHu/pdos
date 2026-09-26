"""Explicit project-scoped source snapshots for test-plan suggestions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Select, and_, func, or_, select

from app.db.schema import tables

SourceKind = Literal["document", "specification", "requirement"]


class PlanSourceError(ValueError):
    pass


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: SourceKind
    id: UUID
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _query(kind: SourceKind, tenant_id: UUID, project_id: UUID) -> Select[Any]:
    if kind == "document":
        d, f = tables.documents, tables.document_fragments
        return (
            select(
                f.c.id,
                f.c.document_id,
                f.c.ordinal,
                f.c.locator,
                f.c.text,
                d.c.filename,
                d.c.sha256,
                d.c.classification,
            )
            .select_from(f.join(d, and_(f.c.tenant_id == d.c.tenant_id, f.c.document_id == d.c.id)))
            .where(
                f.c.tenant_id == tenant_id,
                f.c.project_id == project_id,
                d.c.tenant_id == tenant_id,
                d.c.project_id == project_id,
                d.c.classification == "internal",
                d.c.extraction_status == "extracted",
            )
        )
    if kind == "specification":
        s = tables.specifications
        return select(s).where(s.c.tenant_id == tenant_id, s.c.project_id == project_id)
    r, s, p, c = (
        tables.requirements,
        tables.specifications,
        tables.projects,
        tables.development_cases,
    )
    via_spec = (
        select(s.c.id)
        .where(
            s.c.tenant_id == tenant_id,
            s.c.project_id == project_id,
            s.c.requirement_id == r.c.id,
        )
        .exists()
    )
    via_case = (
        select(p.c.id)
        .select_from(
            p.join(c, and_(p.c.tenant_id == c.c.tenant_id, p.c.development_case_id == c.c.id))
        )
        .where(
            p.c.tenant_id == tenant_id,
            p.c.id == project_id,
            c.c.requirement_id == r.c.id,
        )
        .exists()
    )
    return select(r).where(r.c.tenant_id == tenant_id, or_(via_spec, via_case))


def _snapshot(kind: SourceKind, row: Any, project_id: UUID) -> dict[str, Any]:
    if kind == "document":
        label, version, locator, excerpt = (
            row["filename"],
            row["sha256"],
            row["locator"],
            row["text"],
        )
        status = "内部资料，内容待人工核对"
        href = (
            f"/projects?project={project_id}&tab=documents"
            f"&document_id={row['document_id']}&fragment={row['ordinal']}"
        )
    elif kind == "specification":
        label, version, locator = f"{row['code']} · {row['title']}", str(row["version"]), "规格正文"
        excerpt = json.dumps(
            {k: row[k] for k in ("title", "verification_method", "acceptance_criteria", "content")},
            ensure_ascii=False,
            indent=2,
        )
        status = "项目规格，适用性待人工核对"
        href = f"/projects?project={project_id}&tab=engineering&entity_id={row['id']}"
    else:
        label, version, locator = (
            f"{row['code']} · {row['title']}",
            row["updated_at"].isoformat(),
            "需求正文",
        )
        excerpt = json.dumps(
            {k: row[k] for k in ("title", "description", "acceptance_criteria")},
            ensure_ascii=False,
            indent=2,
        )
        status = str(row["status"])
        href = f"/requirements?requirement={row['id']}"
    snapshot = {
        "kind": kind,
        "id": str(row["id"]),
        "reference_id": f"{kind}:{row['id']}",
        "label": label,
        "version": version,
        "locator": locator,
        "status": status,
        "excerpt": excerpt,
        "href": href,
    }
    snapshot["digest"] = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return snapshot


def list_sources(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, kind: SourceKind, offset: int
) -> dict[str, Any]:
    query = _query(kind, tenant_id, project_id)
    key = tables.document_fragments.c.id if kind == "document" else getattr(tables, kind + "s").c.id
    total = connection.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = connection.execute(query.order_by(key).offset(offset).limit(10)).mappings().all()
    items = []
    for row in rows:
        snapshot = _snapshot(kind, row, project_id)
        available = len(snapshot["excerpt"]) <= 20_000
        items.append(
            {
                **snapshot,
                "available": available,
                "excerpt": snapshot["excerpt"]
                if available
                else "内容过长，请在原资料中拆分为可单独核对的要求后使用。",
            }
        )
    return {
        "items": items,
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


def resolve_sources(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, selections: list[SourceSelection]
) -> list[dict[str, Any]]:
    if len(selections) > 8 or len({(s.kind, s.id) for s in selections}) != len(selections):
        raise PlanSourceError("最多选择 8 处依据，不能重复选择")
    snapshots = []
    for selection in sorted(selections, key=lambda s: (s.kind, str(s.id))):
        key = (
            tables.document_fragments.c.id
            if selection.kind == "document"
            else getattr(tables, selection.kind + "s").c.id
        )
        row = (
            connection.execute(
                _query(selection.kind, tenant_id, project_id)
                .where(key == selection.id)
                .with_for_update(read=True)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise PlanSourceError("所选依据不存在、不属于本项目或不允许供 AI 使用")
        snapshot = _snapshot(selection.kind, row, project_id)
        if snapshot["digest"] != selection.digest:
            raise PlanSourceError("所选依据内容或版本已变化，请刷新并重新选择")
        if len(snapshot["excerpt"]) > 20_000:
            raise PlanSourceError("所选依据过长，请拆分后使用；未静默截断")
        snapshots.append(snapshot)
    return snapshots


def selections_for(snapshots: list[dict[str, Any]]) -> list[SourceSelection]:
    return [
        SourceSelection(kind=s["kind"], id=UUID(s["id"]), digest=s["digest"]) for s in snapshots
    ]
