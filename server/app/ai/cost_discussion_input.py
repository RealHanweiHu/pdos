"""Actual private project discussion receipts for same-budget cost follow-up."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select

from app.ai.discussion_followup import MAX_BRIEF_CHARS, actual, model_input
from app.ai.discussion_sources import current, require_disclosure
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain

KEY = "engineering_intelligence.cost_discussion_followup"
VERSION = "cost-discussion-input.v1"


def read(
    c: Connection, context: AuthContext, project: UUID, discussion_id: UUID, observation_id: UUID
) -> dict[str, Any]:
    from app.ai.change_discussion_runs import binding
    from app.ai.project_discussion_sources import json_encoded

    b = binding(c, context.tenant.id, discussion_id)
    if (
        b["project_id"] != project
        or b["topic_kind"] != "project"
        or b["source"].get("source_kind") != "project_discussion"
    ):
        raise ProductWorkError("请选择本项目的实际主题讨论")
    require_disclosure(c, context.tenant.id, context.user.id, b)
    if not any(
        v["kind"] == "cost_gap_observation" and v["id"] == str(observation_id)
        for v in b["source"]["selections"]
    ):
        raise ProductWorkError("讨论须实际包含当前所选Cost Gap观察")
    if current(c, context.tenant.id, project, b)["digest"] != b["source"]["digest"]:
        raise ProductWorkError("讨论原资料已变化，请先按当前依据继续讨论")
    brief = actual(c, context.tenant.id, discussion_id)
    value = {
        "version": VERSION,
        "discussion_run_id": str(discussion_id),
        "session_id": str(b["session_id"]),
        "actor_id": str(context.user.id),
        "source_digest": b["source"]["digest"],
        **brief,
    }
    if len(json_encoded(value)) > MAX_BRIEF_CHARS:
        raise ProductWorkError("讨论回执超过成本分析容量，请保留原回执并缩小讨论范围")
    return value


def model_fields(value: dict[str, Any]) -> dict[str, Any]:
    exposed = model_input({**value, "id": value["session_id"]})
    return {
        **exposed,
        "interpretation": (
            "这是真实讨论的意见、分歧、回应、人工补充与缺项回执；"
            "发言或多人同意不等于业务事实、批准、已实现降本或验证通过。"
            "引用只能证明原席位说过该内容；实际成本结论仍须核对本次成本原字段。"
        ),
    }


def options(
    c: Connection, context: AuthContext, project: UUID, observation_id: UUID, before: UUID | None
) -> dict[str, Any]:
    from app.ai.cost_discussion_sources import authorize
    from app.domain.cost_freezes import row

    authorize(c, context, project)
    row(c, context.tenant.id, project, tables.cost_gap_observations, observation_id)
    r, b, i = tables.agent_runs, tables.debate_run_bindings, tables.cost_discussion_inputs
    q = (
        select(r.c.id, r.c.created_at, b.c.config, i.c.run_id.label("followup_run_id"))
        .join(b, (b.c.tenant_id == r.c.tenant_id) & (b.c.run_id == r.c.id))
        .outerjoin(i, (i.c.tenant_id == r.c.tenant_id) & (i.c.discussion_run_id == r.c.id))
        .where(
            r.c.tenant_id == context.tenant.id,
            r.c.project_id == project,
            r.c.requested_by_user_id == context.user.id,
            r.c.status == "succeeded",
            b.c.topic_kind == "project",
            b.c.source["source_kind"].as_string() == "project_discussion",
            b.c.source["selections"].contains(
                [{"kind": "cost_gap_observation", "id": str(observation_id)}]
            ),
        )
    )
    if before:
        previous = row(c, context.tenant.id, project, r, before)
        if previous["requested_by_user_id"] != context.user.id:
            raise ProductWorkError("翻页位置不属于本人讨论")
        q = q.where(
            (r.c.created_at < previous["created_at"])
            | ((r.c.created_at == previous["created_at"]) & (r.c.id < before))
        )
    records = list(c.execute(q.order_by(r.c.created_at.desc(), r.c.id.desc()).limit(21)).mappings())
    from app.ai.change_discussion_runs import binding

    visible = []
    for v in records[:20]:
        try:
            require_disclosure(
                c, context.tenant.id, context.user.id, binding(c, context.tenant.id, v["id"])
            )
        except (ValueError, LookupError, PermissionError):
            continue
        visible.append(v)
    return {
        "items": [
            _plain(
                {
                    "id": v["id"],
                    "created_at": v["created_at"],
                    "question": v["config"]["request"]["question"],
                    "followup_run_id": v["followup_run_id"],
                }
            )
            for v in visible
        ],
        "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
    }


def persist(
    c: Connection, tenant: UUID, project: UUID, run_id: UUID, value: dict[str, Any]
) -> None:
    c.execute(
        tables.cost_discussion_inputs.insert().values(
            id=uuid4(),
            tenant_id=tenant,
            project_id=project,
            run_id=run_id,
            discussion_run_id=UUID(value["discussion_run_id"]),
            source_digest=value["source_digest"],
            brief_digest=value["digest"],
            body=value,
            created_at=func.clock_timestamp(),
        )
    )
