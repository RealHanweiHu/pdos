"""Append readable public snapshots without enlarging frozen internal object scope."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: UUID
    offset: int = Field(default=0, ge=0, le=2_000_000)
    length: int = Field(default=4000, ge=1, le=6000)


class Addition(Preview):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    note: str = Field(min_length=1, max_length=2000)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def records(c: Connection, tenant: UUID, run: UUID) -> list[dict[str, Any]]:
    t = tables.debate_research_inputs
    manual = [
        _plain(dict(r))
        for r in c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.run_id == run)
            .order_by(t.c.created_at, t.c.id)
        ).mappings()
    ]

    from app.ai.discussion_research_tools import additions

    return manual + additions(c, tenant, run)


def _source(c: Connection, tenant: UUID, snapshot: UUID) -> Any:
    s, r, body = tables.evidence_snapshots, tables.research_sources, tables.evidence_contents
    value = (
        c.execute(
            select(
                s,
                r.c.name.label("source_name"),
                r.c.allowed_use,
                r.c.license_note,
                r.c.status.label("source_status"),
                r.c.source_type,
            )
            .outerjoin(r, (r.c.tenant_id == s.c.tenant_id) & (r.c.id == s.c.source_id))
            .join(
                body,
                (body.c.tenant_id == s.c.tenant_id) & (body.c.content_digest == s.c.content_digest),
            )
            .where(s.c.tenant_id == tenant, s.c.id == snapshot)
        )
        .mappings()
        .one_or_none()
    )
    if (
        value is None
        or (value["source_id"] is not None and value["source_type"] not in {"web", "api"})
        or not value["url"]
        or value["taint"] != "untrusted_external"
    ):
        raise ProductWorkError("请选择已保存正文且标记为外部未核实材料的公开网页/API快照")
    if value["source_id"] is not None and value["source_status"] != "active":
        raise ProductWorkAccessError("研究来源已停用，不能继续读取或分发原文")
    if value["source_id"] is None:
        return {
            **value,
            "source_name": "公开网页快照",
            "allowed_use": "internal_analysis",
            "license_note": "未登记来源许可，保留原文仅供内部核对",
        }
    return value


def _reference(value: Any, request: Preview, excerpt: str, stale: bool) -> dict[str, Any]:
    fields = _plain(
        {
            k: value[k]
            for k in (
                "id",
                "source_id",
                "source_name",
                "url",
                "captured_at",
                "content_digest",
                "source_version",
                "taint",
                "trust_tier",
                "allowed_use",
                "license_note",
                "freshness_expires_at",
                "superseded_by_id",
                "conflicts_with_id",
                "conflict_note",
            )
        }
    )
    fields.update(excerpt=excerpt, excerpt_offset=request.offset, stale=stale)
    return {
        "reference_id": f"research:{request.snapshot_id}:{request.offset}:{len(excerpt)}",
        "category": "public_research_snapshot",
        "label": "公开来源（待核对） · " + value["source_name"],
        "fields": fields,
        "digest": digest(fields),
        "omitted_fields": ["仅包含所选原文片段，不代表已读取完整页面"],
    }


def preview(c: Connection, context: AuthContext, request: Preview) -> dict[str, Any]:
    _role(context, Action.EVIDENCE_VIEW)
    value = _source(c, context.tenant.id, request.snapshot_id)
    body = c.execute(
        select(tables.evidence_contents.c.body).where(
            tables.evidence_contents.c.tenant_id == context.tenant.id,
            tables.evidence_contents.c.content_digest == value["content_digest"],
        )
    ).scalar_one()
    excerpt = body[request.offset : request.offset + request.length]
    if not excerpt.strip():
        raise ProductWorkError("所选正文位置为空，请调整片段起点")
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    ref = _reference(
        value,
        request,
        excerpt,
        bool(value["freshness_expires_at"] and value["freshness_expires_at"] <= now),
    )
    return {"reference": ref, "digest": ref["digest"], "total_characters": len(body)}


def choices(c: Connection, context: AuthContext) -> dict[str, Any]:
    _role(context, Action.EVIDENCE_VIEW)
    s, r, body = tables.evidence_snapshots, tables.research_sources, tables.evidence_contents
    query = (
        select(
            s.c.id,
            s.c.url,
            s.c.captured_at,
            s.c.superseded_by_id,
            s.c.freshness_expires_at,
            func.coalesce(r.c.name, "公开网页快照").label("name"),
        )
        .outerjoin(r, (r.c.tenant_id == s.c.tenant_id) & (r.c.id == s.c.source_id))
        .join(
            body,
            (body.c.tenant_id == s.c.tenant_id) & (body.c.content_digest == s.c.content_digest),
        )
        .where(
            s.c.tenant_id == context.tenant.id,
            (
                s.c.source_id.is_(None)
                | ((r.c.status == "active") & r.c.source_type.in_(("web", "api")))
            ),
            s.c.taint == "untrusted_external",
            s.c.url.is_not(None),
        )
        .order_by(s.c.captured_at.desc(), s.c.id)
        .limit(100)
    )
    return {
        "items": [_plain(dict(v)) for v in c.execute(query).mappings()],
        "notice": (
            "仅列最近100项已有正文的公开来源快照；"
            "过期、冲突或已有新版会保留提示，原文不视为已核实事实。"
        ),
    }


def require_disclosure(c: Connection, tenant: UUID, actor_id: UUID, run: UUID) -> None:
    additions = records(c, tenant, run)
    if not additions:
        return
    from app.ai.project_discussion_sources import actor

    _role(actor(c, tenant, actor_id), Action.EVIDENCE_VIEW)
    for item in additions:
        _source(c, tenant, UUID(item["snapshot_id"]))


def current(c: Connection, tenant: UUID, actor_id: UUID, additions: list[dict[str, Any]]) -> bool:
    if not additions:
        return True
    from app.ai.project_discussion_sources import actor

    _role(actor(c, tenant, actor_id), Action.EVIDENCE_VIEW)
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    for item in additions:
        request = Preview.model_validate(
            {k: item["request"][k] for k in ("snapshot_id", "offset", "length")}
        )
        value = _source(c, tenant, request.snapshot_id)
        original = item["reference"]
        actual = _reference(
            value,
            request,
            original["fields"]["excerpt"],
            bool(value["freshness_expires_at"] and value["freshness_expires_at"] <= now),
        )
        if actual != original:
            return False
    return True


def augment(c: Connection, row: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    additions = records(c, row["tenant_id"], row["id"])
    from app.ai.discussion_research_tools import observations

    actual_tools = observations(c, row["tenant_id"], row["id"])[-12:]
    if not additions and not actual_tools:
        return snapshot
    if not current(c, row["tenant_id"], row["requested_by_user_id"], additions):
        raise ProductWorkError("追加研究资料的版本或有效性已变化，请重新核对")
    refs = snapshot["references"] + [a["reference"] for a in additions]
    if len(json.dumps(refs, ensure_ascii=False)) > 160000:
        raise ProductWorkError("本次输入已超过讨论容量，请缩小研究片段或关联新的讨论")
    context = dict(snapshot["context"])
    question = json.loads(context["question"])
    question["research_results"] = [
        {
            "tool": v["tool_key"],
            "status": v["output_body"]["status"],
            "notice": v["output_body"].get("notice"),
            "error_code": v["output_body"].get("error_code"),
            "reference_id": (v["output_body"].get("reference") or {}).get("reference_id"),
        }
        for v in actual_tools
    ]
    question["public_research_notes"] = [
        {
            "reference_id": a["reference"]["reference_id"],
            "note": a["request"]["note"],
            "origin": a.get("origin", "human"),
            "warning": "未核实外部原文；用户说明是意见，不能当作已核实事实",
        }
        for a in additions
    ]
    context["question"] = json.dumps(question, ensure_ascii=False, sort_keys=True)
    context["references"] = context["references"] + [
        {
            "reference_id": a["reference"]["reference_id"],
            "entity": "public_research_snapshot",
            "label": a["reference"]["label"],
            "excerpt": json.dumps(
                {k: a["reference"][k] for k in ("digest", "fields", "omitted_fields")},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for a in additions
    ]
    return {
        **snapshot,
        "references": refs,
        "research_inputs": additions,
        "context": context,
        "research_tool_ids": [v["id"] for v in actual_tools],
    }


def append(
    engine: Engine, context: AuthContext, project: UUID, run: UUID, request: Addition
) -> dict[str, Any]:
    from app.ai.change_discussion_runs import authorize, binding, event
    from app.ai.discussion_sources import require_disclosure as disclose
    from app.domain.debates import DebateService

    authorize(engine, context, project, edit=True)
    _role(context, Action.EVIDENCE_VIEW)
    with engine.begin() as c:
        t = tables.agent_runs
        row = (
            c.execute(
                select(t)
                .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == run)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原讨论不存在")
        bound = binding(c, context.tenant.id, run)
        disclose(c, context.tenant.id, context.user.id, bound)
        existing = records(c, context.tenant.id, run)
        command = request.model_dump(mode="json")
        prior = next(
            (
                v
                for v in existing
                if v.get("request_id") == str(request.request_id)
                and v["actor_user_id"] == str(context.user.id)
            ),
            None,
        )
        if prior:
            if prior["request"] != command:
                raise ProductWorkError("原追加请求已有不同内容")
            return prior
        if row["status"] not in {"queued", "running"}:
            raise ProductWorkError("本次已停止；新增资料请关联原讨论继续")
        if len(existing) >= 20:
            raise ProductWorkError("本场已有20份研究片段，请关联原讨论继续")
        reference = preview(c, context, request)["reference"]
        if reference["digest"] != request.expected_digest:
            raise ProductWorkError("研究资料已变化，请重新预览")
        if any(v["reference"]["reference_id"] == reference["reference_id"] for v in existing):
            raise ProductWorkError("该快照片段已追加，无需重复加入")
        if (
            len(
                json.dumps(
                    [
                        *bound["source"]["model_context"]["references"],
                        *(v["reference"] for v in existing),
                        reference,
                    ],
                    ensure_ascii=False,
                )
            )
            > 140000
        ):
            raise ProductWorkError("原资料与新增片段超过本场容量，请缩短片段或关联继续")
        from app.ai.project_discussion_sources import actor

        _role(actor(c, context.tenant.id, row["requested_by_user_id"]), Action.EVIDENCE_VIEW)
        session = (
            c.execute(
                select(tables.debate_sessions)
                .where(tables.debate_sessions.c.id == bound["session_id"])
                .with_for_update()
            )
            .mappings()
            .one()
        )
        turn = uuid5(run, f"research:{context.user.id}:{request.request_id}")
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        c.execute(
            tables.debate_turns.insert().values(
                id=turn,
                tenant_id=context.tenant.id,
                session_id=bound["session_id"],
                round_number=session["round_count"],
                sequence=DebateService._next_sequence(
                    c, tenant_id=context.tenant.id, session_id=bound["session_id"]
                ),
                speaker_kind="human",
                author_user_id=context.user.id,
                content="追加公开研究片段：" + reference["label"] + "。说明：" + request.note,
                citations=[],
                input_tokens=0,
                output_tokens=0,
                created_at=now,
            )
        )
        item = (
            c.execute(
                tables.debate_research_inputs.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    run_id=run,
                    session_id=bound["session_id"],
                    snapshot_id=request.snapshot_id,
                    turn_id=turn,
                    request_id=request.request_id,
                    actor_user_id=context.user.id,
                    request=command,
                    reference=reference,
                    created_at=now,
                )
                .returning(tables.debate_research_inputs)
            )
            .mappings()
            .one()
        )
        event(c, context.tenant.id, bound["session_id"], "public_research_added", context.user.id)
        return _plain(dict(item))
