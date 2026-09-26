"""Explicit, version-pinned knowledge references in a human task handoff."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.knowledge_push import (
    ContextNotFoundError,
    KnowledgeAccessError,
    KnowledgePushService,
    KnowledgeVersionError,
    PushNotFoundError,
)
from app.domain.product_workspace import ProductWorkError


class KnowledgeReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    push_id: UUID
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str = Field(min_length=1, max_length=4000)


def reference(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    task: UUID,
    ref: KnowledgeReference,
    adopter: UUID,
    *,
    lock: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        push, memory = KnowledgePushService(c.engine)._authorized_push(
            c, ctx.tenant.id, ctx.user.id, ref.push_id, lock=lock
        )
    except (KnowledgeAccessError, KnowledgeVersionError, PushNotFoundError, ContextNotFoundError):
        raise ProductWorkError("关联经验当前不可读取或依据已变化，请退回补齐并重新选择") from None
    if (
        push["project_id"] != project
        or push["context_kind"] != "task_takeover"
        or push["context_entity_id"] != task
        or memory["content_sha256"] != ref.content_sha256
    ):
        raise ProductWorkError("关联经验必须对应本任务和原采用版本")
    f = tables.knowledge_push_feedback
    feedback = (
        c.execute(
            select(f).where(
                f.c.tenant_id == ctx.tenant.id,
                f.c.push_id == ref.push_id,
                f.c.actor_user_id == adopter,
                f.c.action == "adopted",
                f.c.memory_content_sha256 == ref.content_sha256,
            )
        )
        .mappings()
        .one_or_none()
    )
    if feedback is None:
        raise ProductWorkError("交付人须先在本任务的相关经验中记录采用依据")
    # Only identifiers and the explicitly shared applicability note are persisted.
    # Cross-project knowledge text is resolved under each reader's current permissions.
    frozen = ref.model_dump(mode="json") | {
        "memory_id": str(memory["id"]),
        "feedback_id": str(feedback["id"]),
        "adopter_user_id": str(adopter),
        "context_sha256": push["context_sha256"],
    }
    view = {
        "title": memory["title"],
        "applicability": memory["applicability"],
        "href": f"/knowledge?project={memory['project_id']}&memory={memory['id']}",
    }
    return frozen, view


def freeze(
    c: Connection, ctx: AuthContext, project: UUID, task: UUID, refs: list[KnowledgeReference]
) -> list[dict[str, Any]]:
    return [
        reference(c, ctx, project, task, ref, ctx.user.id, lock=True)[0]
        for ref in sorted(refs, key=lambda item: item.push_id)
    ]


def current(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    task: UUID,
    refs: list[dict[str, Any]],
    *,
    lock: bool = False,
) -> list[dict[str, Any]]:
    result = []
    for item in sorted(refs, key=lambda value: value["push_id"]):
        try:
            ref = KnowledgeReference.model_validate(
                {key: item[key] for key in ("push_id", "content_sha256", "note")}
            )
            frozen, view = reference(
                c, ctx, project, task, ref, UUID(item["adopter_user_id"]), lock=lock
            )
            if frozen != item:
                raise ProductWorkError("关联经验依据已变化")
            result.append(item | view | {"available": True})
        except ProductWorkError:
            if lock:
                raise
            result.append(item | {"available": False})
    return result


def options(c: Connection, ctx: AuthContext, project: UUID, task: UUID) -> dict[str, Any]:
    p, f = tables.knowledge_pushes, tables.knowledge_push_feedback
    candidates = (
        c.execute(
            select(p.c.id, f.c.memory_content_sha256)
            .join(f, (f.c.tenant_id == p.c.tenant_id) & (f.c.push_id == p.c.id))
            .where(
                p.c.tenant_id == ctx.tenant.id,
                p.c.project_id == project,
                p.c.context_kind == "task_takeover",
                p.c.context_entity_id == task,
                f.c.actor_user_id == ctx.user.id,
                f.c.action == "adopted",
            )
            .order_by(f.c.created_at.desc(), f.c.id.desc())
            .limit(51)
        )
        .mappings()
        .all()
    )
    items = []
    for candidate in candidates[:50]:
        ref = KnowledgeReference(
            push_id=candidate["id"],
            content_sha256=candidate["memory_content_sha256"],
            note="待填写",
        )
        try:
            _, view = reference(c, ctx, project, task, ref, ctx.user.id, lock=False)
            items.append(ref.model_dump(mode="json") | view | {"note": ""})
        except ProductWorkError:
            continue
    return {"items": items, "has_more": len(candidates) > 50}
