"""Frozen management requirements and their organization-template source anchors.

Saving a brief does not start a model run. Generation is a separate action
and remains closed until the organization capability is qualified for live use.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, RowMapping, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.process_template_configuration import Input
from app.domain.process_templates import authorize, head, lock
from app.domain.product_workspace import _plain, digest
from app.domain.project_templates import ProjectTemplateError, catalog
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class TemplateBriefInput(Input):
    request_id: UUID
    template_id: str = Field(pattern=r"^org-[a-z0-9][a-z0-9-]{0,119}$")
    base_template_id: str = Field(min_length=1, max_length=128)
    base_version: int = Field(gt=0)
    base_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_release_id: UUID | None = None
    previous_brief_id: UUID | None = None
    instruction: str = Field(min_length=1, max_length=16000)
    acceptance_criteria: str = Field(min_length=1, max_length=8000)


def generation_state() -> dict[str, Any]:
    from app.ai.capability_contract import CapabilityRollout, resolve_capability

    available = (
        resolve_capability("knowledge_lite.process_template_configuration").rollout
        == CapabilityRollout.LIVE
    )
    return {
        "generation_available": available,
        "generation_message": "可请求智能配置建议，随后独立审阅和应用。"
        if available
        else "智能配置建议尚未开放，保存要求不会自动排队或调用模型。",
    }


def brief(c: Connection, ctx: AuthContext, identity: UUID) -> RowMapping:
    authorize(c, ctx)
    t = tables.process_template_briefs
    row = (
        c.execute(select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProjectTemplateError("流程要求记录不存在")
    return row


def source_status(c: Connection, tenant: UUID, row: Any) -> dict[str, Any]:
    h = head(c, tenant, row["template_id"])
    base = next(
        (
            item
            for item in catalog(connection=c, tenant_id=tenant)
            if item["id"] == row["base_template_id"]
        ),
        None,
    )
    base_current = (
        base is not None
        and base["version"] == row["base_version"]
        and digest(base) == row["base_digest"]
    )
    release_current = row["base_release_id"] == (h["id"] if h else None)
    return {
        "base_current": base_current,
        "release_current": release_current,
        "source_current": base_current and release_current,
        "current_base_version": base["version"] if base else None,
        "current_release_id": str(h["id"]) if h else None,
    }


def require_revision_source(
    c: Connection,
    ctx: AuthContext,
    identity: UUID,
    *,
    template_id: str,
    base_template_id: str,
    base_version: int,
    base_digest: str,
    base_release_id: UUID | None,
) -> RowMapping:
    row = brief(c, ctx, identity)
    if any(
        row[key] != value
        for key, value in {
            "template_id": template_id,
            "base_template_id": base_template_id,
            "base_version": base_version,
            "base_digest": base_digest,
            "base_release_id": base_release_id,
        }.items()
    ):
        raise ProjectTemplateError("配置候选须与原管理要求使用同一模板及来源版本")
    if not source_status(c, ctx.tenant.id, row)["source_current"]:
        raise ProjectTemplateError("管理要求的模板依据已变化，请基于当前版保存新要求")
    return row


class ProcessTemplateBriefService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, ctx: AuthContext, body: TemplateBriefInput) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json"))
        with self.engine.begin() as c:
            lock(c, ctx, body.template_id)
            t = tables.process_template_briefs
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id, t.c.request_id == body.request_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if (
                    prior["request_digest"] != signature
                    or prior["created_by_user_id"] != ctx.user.id
                ):
                    raise ProjectTemplateError("此保存请求已对应另一份管理要求")
                return _plain(prior)
            h = head(c, ctx.tenant.id, body.template_id)
            if body.expected_release_id != (h["id"] if h else None):
                raise ProjectTemplateError("目标模板已发布新版本，请读取当前版后继续")
            if h and body.base_template_id != body.template_id:
                raise ProjectTemplateError("修订须基于此组织模板当前发布版")
            base = next(
                (
                    item
                    for item in catalog(connection=c, tenant_id=ctx.tenant.id)
                    if item["id"] == body.base_template_id
                ),
                None,
            )
            if (
                base is None
                or base["version"] != body.base_version
                or digest(base) != body.base_digest
            ):
                raise ProjectTemplateError("配置依据已变化，请重新读取模板")
            previous = brief(c, ctx, body.previous_brief_id) if body.previous_brief_id else None
            if previous is not None and previous["template_id"] != body.template_id:
                raise ProjectTemplateError("补充要求须沿用同一目标模板")
            identity = uuid4()
            content = {
                "schema_version": 1,
                "id": str(identity),
                "tenant_id": str(ctx.tenant.id),
                "scope": {"kind": "tenant", "ref_id": str(ctx.tenant.id)},
                "template_id": body.template_id,
                "base_template_id": body.base_template_id,
                "base_version": body.base_version,
                "base_digest": body.base_digest,
                "base_release_id": str(body.expected_release_id)
                if body.expected_release_id
                else None,
                "previous_brief_id": str(body.previous_brief_id)
                if body.previous_brief_id
                else None,
                "instruction": body.instruction,
                "acceptance_criteria": body.acceptance_criteria,
                "base_snapshot": base,
            }
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        template_id=body.template_id,
                        request_id=body.request_id,
                        request_digest=signature,
                        base_template_id=body.base_template_id,
                        base_version=body.base_version,
                        base_digest=body.base_digest,
                        base_release_id=body.expected_release_id,
                        previous_brief_id=body.previous_brief_id,
                        instruction=body.instruction,
                        acceptance_criteria=body.acceptance_criteria,
                        source_snapshot=content,
                        source_digest=digest(content),
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id).record(
                EventDraft(
                    event_id=f"process-template-brief:{identity}",
                    event_type="PROCESS_TEMPLATE_BRIEF_CREATED",
                    source="process_template_service",
                    entity_id=identity,
                    payload={
                        "template_id": body.template_id,
                        "brief_id": str(identity),
                        "source_digest": row["source_digest"],
                    },
                ),
                AuditDraft(
                    action="process_template.brief_created",
                    after_snapshot={
                        "brief_id": str(identity),
                        "source_digest": row["source_digest"],
                        "previous_brief_id": content["previous_brief_id"],
                    },
                ),
            )
            return _plain(row)

    def list(self, ctx: AuthContext, before_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx)
            t = tables.process_template_briefs
            query = select(t).where(t.c.tenant_id == ctx.tenant.id)
            if before_id is not None:
                anchor = brief(c, ctx, before_id)
                query = query.where(
                    (t.c.created_at < anchor["created_at"])
                    | ((t.c.created_at == anchor["created_at"]) & (t.c.id < before_id))
                )
            records = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [
                    _plain(
                        {
                            key: row[key]
                            for key in (
                                "id",
                                "template_id",
                                "base_template_id",
                                "base_version",
                                "created_at",
                                "created_by_user_id",
                                "previous_brief_id",
                            )
                        }
                    )
                    for row in records[:20]
                ],
                "next_before_id": str(records[19]["id"]) if len(records) > 20 else None,
                **generation_state(),
            }

    def get(self, ctx: AuthContext, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = brief(c, ctx, identity)
            from app.ai.process_template_context import RUN_VERSION
            from app.ai.process_template_runs import receipt

            r = tables.agent_runs
            runs = (
                c.execute(
                    select(r)
                    .where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.scope_kind == "tenant",
                        r.c.context_version == RUN_VERSION,
                        r.c.run_context["process_template_brief_id"].as_string() == str(identity),
                    )
                    .order_by(r.c.created_at.desc(), r.c.id.desc())
                    .limit(21)
                )
                .mappings()
                .all()
            )
            v = tables.process_template_revisions
            candidates = (
                c.execute(
                    select(v.c.id, v.c.version, v.c.created_at, v.c.created_by_user_id, v.c.reason)
                    .where(v.c.tenant_id == ctx.tenant.id, v.c.source_brief_id == identity)
                    .order_by(v.c.version.desc())
                    .limit(51)
                )
                .mappings()
                .all()
            )
            return {
                "brief": _plain(row),
                **source_status(c, ctx.tenant.id, row),
                "revisions": [_plain(item) for item in candidates[:50]],
                "revisions_truncated": len(candidates) > 50,
                "runs": [
                    receipt(item)
                    | {
                        "can_control": item["requested_by_user_id"] == ctx.user.id,
                    }
                    for item in runs[:20]
                ],
                "runs_truncated": len(runs) > 20,
                **generation_state(),
            }
