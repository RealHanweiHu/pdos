"""Resolve explicit knowledge evidence choices to server-owned versions."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, or_, select

from app.auth.roles import Action, is_allowed
from app.db.schema import tables


class KnowledgeSourceBindingError(ValueError):
    pass


class KnowledgeSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["document", "specification", "evidence_snapshot"]
    id: UUID
    expected_version: str = Field(pattern=r"^(?:[0-9a-f]{64}|[1-9][0-9]{0,9})$")


def _can_read_evidence(connection: Connection, tenant_id: UUID, actor_id: UUID) -> bool:
    role = connection.execute(
        select(tables.users.c.role).where(
            tables.users.c.tenant_id == tenant_id,
            tables.users.c.id == actor_id,
            tables.users.c.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return role is not None and is_allowed(role, Action.EVIDENCE_VIEW)


def source_options(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, actor_id: UUID, query: str = ""
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    pattern = f"%{query.strip()}%"
    for row in connection.execute(
        select(tables.documents)
        .where(
            tables.documents.c.tenant_id == tenant_id,
            tables.documents.c.project_id == project_id,
            tables.documents.c.filename.ilike(pattern),
        )
        .order_by(tables.documents.c.created_at.desc())
        .limit(200)
    ).mappings():
        options.append(
            dict(
                kind="document",
                id=str(row["id"]),
                title=row["filename"],
                expected_version=row["sha256"],
                version_label=f"文件 {row['sha256'][:12]}",
                available=True,
                reason=None,
            )
        )
    for row in connection.execute(
        select(tables.specifications)
        .where(
            tables.specifications.c.tenant_id == tenant_id,
            tables.specifications.c.project_id == project_id,
            or_(
                tables.specifications.c.title.ilike(pattern),
                tables.specifications.c.code.ilike(pattern),
            ),
        )
        .order_by(tables.specifications.c.updated_at.desc())
        .limit(200)
    ).mappings():
        options.append(
            dict(
                kind="specification",
                id=str(row["id"]),
                title=row["title"],
                expected_version=str(row["version"]),
                version_label=f"规格 v{row['version']}",
                available=True,
                reason=None,
            )
        )
    if _can_read_evidence(connection, tenant_id, actor_id):
        for row in connection.execute(
            select(
                tables.evidence_snapshots,
                tables.research_sources.c.name.label("source_name"),
                select(tables.evidence_contents.c.content_digest)
                .where(
                    tables.evidence_contents.c.tenant_id == tables.evidence_snapshots.c.tenant_id,
                    tables.evidence_contents.c.content_digest
                    == tables.evidence_snapshots.c.content_digest,
                )
                .exists()
                .label("has_body"),
                tables.research_sources.c.status.label("source_status"),
            )
            .outerjoin(
                tables.research_sources,
                (tables.research_sources.c.tenant_id == tables.evidence_snapshots.c.tenant_id)
                & (tables.research_sources.c.id == tables.evidence_snapshots.c.source_id),
            )
            .where(
                tables.evidence_snapshots.c.tenant_id == tenant_id,
                or_(
                    tables.evidence_snapshots.c.content_ref.ilike(pattern),
                    tables.research_sources.c.name.ilike(pattern),
                    tables.evidence_snapshots.c.content_digest.ilike(pattern),
                ),
            )
            .order_by(tables.evidence_snapshots.c.captured_at.desc())
            .limit(200)
        ).mappings():
            reason = snapshot_problem(connection, tenant_id, row)
            options.append(
                dict(
                    kind="evidence_snapshot",
                    id=str(row["id"]),
                    title=row["source_name"] or row["content_ref"],
                    expected_version=row["content_digest"],
                    version_label=(
                        f"快照 {row['content_digest'][:12]} · {row['captured_at'].isoformat()}"
                    ),
                    available=reason is None,
                    reason=reason,
                )
            )
    return options


def snapshot_problem(connection: Connection, tenant_id: UUID, row: Any) -> str | None:
    if row["superseded_by_id"] is not None:
        return "已有替代快照"
    if row["conflicts_with_id"] is not None:
        return "存在未消解的来源冲突"
    if row["freshness_expires_at"] is not None and row["freshness_expires_at"] <= datetime.now(UTC):
        return "已到复查时间"
    if row["source_id"] is not None and row["source_status"] != "active":
        return "原始来源已停用"
    if "has_body" in row:
        return None if row["has_body"] else "未保存快照正文"
    if (
        connection.execute(
            select(tables.evidence_contents.c.content_digest).where(
                tables.evidence_contents.c.tenant_id == tenant_id,
                tables.evidence_contents.c.content_digest == row["content_digest"],
            )
        ).first()
        is None
    ):
        return "未保存快照正文"
    return None


def resolve_selections(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    selections: tuple[KnowledgeSourceSelection, ...],
) -> list[dict[str, Any]]:
    if len(selections) > 20 or len({(s.kind, s.id) for s in selections}) != len(selections):
        raise KnowledgeSourceBindingError("最多选择20个不重复的依据")
    resolved = []
    for selection in selections:
        if selection.kind == "evidence_snapshot":
            if not _can_read_evidence(connection, tenant_id, actor_id):
                raise KnowledgeSourceBindingError("当前不能引用共享证据快照")
            row = (
                connection.execute(
                    select(
                        tables.evidence_snapshots,
                        tables.research_sources.c.status.label("source_status"),
                    )
                    .outerjoin(
                        tables.research_sources,
                        (
                            tables.research_sources.c.tenant_id
                            == tables.evidence_snapshots.c.tenant_id
                        )
                        & (tables.research_sources.c.id == tables.evidence_snapshots.c.source_id),
                    )
                    .where(
                        tables.evidence_snapshots.c.tenant_id == tenant_id,
                        tables.evidence_snapshots.c.id == selection.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KnowledgeSourceBindingError("证据快照不存在或不能访问")
            problem = snapshot_problem(connection, tenant_id, row)
            if problem:
                raise KnowledgeSourceBindingError(problem)
            version = row["content_digest"]
            payload = {"digest": version, "title": row["content_ref"]}
        else:
            table = tables.documents if selection.kind == "document" else tables.specifications
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.id == selection.id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KnowledgeSourceBindingError("文档或规格不存在于当前项目")
            version = row["sha256"] if selection.kind == "document" else str(row["version"])
            payload = (
                {"digest": version, "title": row["filename"]}
                if selection.kind == "document"
                else {"version": row["version"], "title": row["title"]}
            )
        if version != selection.expected_version:
            raise KnowledgeSourceBindingError("所选依据的版本已变化，请刷新后重新选择")
        resolved.append({"kind": selection.kind, "reference": str(selection.id), **payload})
    return resolved
