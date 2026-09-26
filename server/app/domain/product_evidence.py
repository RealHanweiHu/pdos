"""Shared snapshot resolution for pre-project business observations."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import SourceRef
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _sources


def evidence_quality(
    connection: Connection, context: AuthContext, refs: list[dict[str, Any]]
) -> list[str]:
    problems: list[str] = []
    ids = {UUID(item["ref_id"]) for item in refs}
    snapshot = tables.evidence_snapshots
    rows = connection.execute(
        select(snapshot, tables.research_sources.c.status.label("source_status"))
        .outerjoin(
            tables.research_sources,
            (tables.research_sources.c.id == snapshot.c.source_id)
            & (tables.research_sources.c.tenant_id == snapshot.c.tenant_id),
        )
        .where(snapshot.c.tenant_id == context.tenant.id, snapshot.c.id.in_(ids))
    ).mappings()
    now = datetime.now(UTC)
    seen: set[UUID] = set()
    for row in rows:
        seen.add(row["id"])
        if row["source_status"] != "active":
            problems.append("部分来源已停用或不可访问")
        if row["freshness_expires_at"] is not None and row["freshness_expires_at"] <= now:
            problems.append("部分来源已到建议复查时间")
        if row["superseded_by_id"] is not None:
            problems.append("部分来源已有新版")
        if row["conflicts_with_id"] is not None:
            problems.append("部分来源存在未消解冲突")
    if seen != ids:
        problems.append("部分来源快照不可用")
    return list(dict.fromkeys(problems))


def resolve_evidence(
    connection: Connection, context: AuthContext, refs: tuple[SourceRef, ...]
) -> list[dict[str, Any]]:
    resolved = _sources(connection, context, refs)
    for ref in resolved:
        found = connection.execute(
            select(tables.evidence_contents.c.content_digest).where(
                tables.evidence_contents.c.tenant_id == context.tenant.id,
                tables.evidence_contents.c.content_digest == ref["digest"],
            )
        ).first()
        if found is None:
            raise ProductWorkError("所选历史快照未保存正文，请重新采集后引用")
    return resolved
