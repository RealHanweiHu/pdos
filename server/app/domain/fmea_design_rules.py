"""Explicit design-rule drafts from current published FMEA, with independent Memory review."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain import living_fmea as fmea
from app.domain.memories import MemoryDraft, MemoryService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    publication_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=20000)
    applicability: str = Field(min_length=1, max_length=5000)


def _authorize(c: Connection, context: AuthContext, project: UUID, action: Action) -> None:
    fmea.authorize(c, context, project, Action.QUALITY_VIEW)
    fmea.authorize(c, context, project, action)


def _state(c: Connection, tenant: UUID, project: UUID, entry: UUID) -> dict[str, Any]:
    if fmea.latest(c, tenant, project, entry) is None:
        raise ProductWorkError("原 FMEA 条目不存在")
    publication = fmea.publication(c, tenant, project, entry)
    if publication is None:
        return {
            "publication": None,
            "version": None,
            "sources": [],
            "basis": None,
            "source_gaps": [],
        }
    v = tables.fmea_versions
    version = (
        c.execute(
            select(v).where(
                v.c.tenant_id == tenant,
                v.c.project_id == project,
                v.c.id == publication["version_id"],
            )
        )
        .mappings()
        .one()
    )
    sources, gaps = fmea.current_sources(c, version)
    basis = c.execute(
        text("SELECT cehub_memory.fmea_knowledge_basis(:tenant,:project,:version)"),
        {"tenant": tenant, "project": project, "version": version["id"]},
    ).scalar_one()
    return _plain(
        {
            "publication": dict(publication),
            "version": dict(version),
            "sources": sources,
            "basis": basis,
            "source_gaps": gaps,
        }
    )


def _summary(record: Any) -> dict[str, Any]:
    value = {
        key: record[key]
        for key in (
            "id",
            "title",
            "status",
            "knowledge_kind",
            "created_at",
            "verified_by_user_id",
            "verified_at",
        )
    }
    value["publication_id"] = next(
        (
            ref["reference"]
            for ref in record["source_refs"]
            if ref.get("kind") == "fmea_publication"
        ),
        None,
    )
    return _plain(value)


def read(engine: Engine, context: AuthContext, project: UUID, entry: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        _authorize(c, context, project, Action.MEMORY_VIEW)
        current = _state(c, context.tenant.id, project, entry)
        m = tables.memories
        records = (
            c.execute(
                select(m)
                .where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.project_id == project,
                    m.c.source_refs.cast(JSONB).contains(
                        [{"kind": "fmea_publication", "entry_id": str(entry)}]
                    ),
                )
                .order_by(m.c.created_at.desc(), m.c.id.desc())
                .limit(21)
            )
            .mappings()
            .all()
        )
        return {
            **current,
            "digest": digest(current),
            "items": [_summary(r) for r in records[:20]],
            "has_more": len(records) > 20,
            "can_draft": is_allowed(context.user.role, Action.MEMORY_DRAFT),
        }


def create(
    engine: Engine, context: AuthContext, project: UUID, entry: UUID, request: Draft
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不存在")
        _authorize(c, context, project, Action.MEMORY_DRAFT)
        # One candidate per original publication; the project lock serializes retries and authors.
        fingerprint = digest({"entry_id": str(entry), **request.model_dump(mode="json")})
        m = tables.memories
        old = (
            c.execute(
                select(m)
                .where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.project_id == project,
                    m.c.source_refs.cast(JSONB).contains(
                        [
                            {
                                "kind": "fmea_publication",
                                "reference": str(request.publication_id),
                                "entry_id": str(entry),
                            }
                        ]
                    ),
                )
                .order_by(m.c.created_at)
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if old:
            ref = next(
                r
                for r in old["source_refs"]
                if r.get("kind") == "fmea_publication"
                and r.get("reference") == str(request.publication_id)
            )
            if ref.get("draft_digest") != fingerprint:
                raise ProductWorkError("此发布版本已有设计规则候选，请打开原候选编辑或审核")
            return {"memory": _summary(old), "replayed": True}
        current = _state(c, context.tenant.id, project, entry)
        pub, version = current["publication"], current["version"]
        if (
            pub is None
            or pub["id"] != str(request.publication_id)
            or digest(current) != request.expected_digest
        ):
            raise ProductWorkError("原 FMEA 发布或依据已变化，请重新读取核对")
        if current["source_gaps"] or not current["basis"]:
            raise ProductWorkError("原 FMEA 或其质量证据已变化或不可用，请先修订并发布")
        memory = MemoryService(engine).create(
            tenant_id=context.tenant.id,
            project_id=project,
            actor_user_id=context.user.id,
            draft=MemoryDraft(
                title=request.title,
                content=request.content,
                applicability=request.applicability,
                tags=("fmea",),
                knowledge_kind="design_rule",
            ),
            source_refs=(
                {
                    "kind": "fmea_publication",
                    "reference": pub["id"],
                    "entry_id": str(entry),
                    "version": version["version"],
                    "title": version["body"]["title"],
                    "basis": current["basis"],
                    "draft_digest": fingerprint,
                },
            ),
            connection=c,
        )
        return {"memory": _summary(asdict(memory)), "replayed": False}
