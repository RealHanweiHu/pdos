"""Versioned discussion input for a separate analysis on the original request budget."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.executor import PromptFile
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, digest

KEY = "engineering_intelligence.discussion_followup"
VERSION = "discussion-followup.v1"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "change_work_package_v4.json").read_text()
)
NOTICE_PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "change_work_package_v6.json").read_text()
)


def prompt_for(snapshot: dict[str, Any]) -> PromptFile:
    from app.ai.change_notice_preparation import is_notice

    return NOTICE_PROMPT if is_notice(snapshot) else PROMPT


MAX_BRIEF_CHARS = 120_000


def version(rc: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    if not snapshot.get("discussion_input"):
        return None
    prompt = prompt_for(snapshot)
    if rc.get("impact_prompt_version") != prompt.version:
        raise ProductWorkError("原讨论后分析版本不可用")
    return prompt.version


def actual(
    c: Connection, tenant: UUID, discussion: UUID, *, require_active: bool = False
) -> dict[str, Any]:
    from app.ai.change_discussion_runs import result

    row = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == tenant, tables.agent_runs.c.id == discussion
            )
        )
        .mappings()
        .one()
    )
    value = result(c, row)
    if (
        row["status"] != "succeeded"
        or not value["brief"]["body"]["complete"]
        or (require_active and value["related_request_cancelled"])
        or not value["research_current"]
    ):
        raise ProductWorkError("讨论尚未完整结束、资料已失效或原请求已停止")
    return {"body": value["brief"]["body"], "digest": value["brief"]["digest"]}


def require_current(c: Connection, tenant: UUID, snapshot: dict[str, Any]) -> None:
    value = snapshot.get("discussion_input")
    if value is None:
        return
    bound = (
        c.execute(
            select(tables.change_discussion_inputs).where(
                tables.change_discussion_inputs.c.tenant_id == tenant,
                tables.change_discussion_inputs.c.id == UUID(value["id"]),
            )
        )
        .mappings()
        .one_or_none()
    )
    if bound is None or (
        str(bound["discussion_run_id"]) != value["discussion_run_id"]
        or str(bound["origin_run_id"]) != value["origin_run_id"]
        or bound["brief_digest"] != value["digest"]
        or bound["body"] != value["body"]
        or digest(value["body"]) != value["digest"]
        or actual(c, tenant, bound["discussion_run_id"])["digest"] != value["digest"]
    ):
        raise ProductWorkError("原讨论结果版本已有变化，请重新准备分析")


def provenance(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("discussion_input")
    if value is None:
        return {}
    return {
        "discussion_input": {
            k: value[k] for k in ("id", "origin_run_id", "discussion_run_id", "digest")
        }
    }


def model_input(value: dict[str, Any]) -> dict[str, Any]:
    """Expose actual opinions, without internal policy and research dispatch records."""
    body = value["body"]
    return {
        **{k: value[k] for k in ("id", "discussion_run_id", "digest")},
        "body": {
            k: body[k]
            for k in (
                "version",
                "question",
                "status",
                "stop_reason",
                "complete",
                "coverage",
                "positions",
                "responses",
                "missing",
                "human_inputs",
                "turn_ids",
            )
        },
        "notice": "讨论内的额外研究资料不扩展本次事实引用；业务判断仍须核对原references。",
    }
