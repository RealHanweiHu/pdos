"""Model-selected public research inside each frozen professional projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_contract import call_id, seat_input
from app.ai.executor import PromptFile
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import require_live_key
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest

KEY = "engineering_intelligence.discussion_research"
VERSION = "discussion-research-tools.v1"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "discussion_research_v1.json").read_text()
)
TOOLSET = {
    "version": VERSION,
    "dispatch": "model_selected",
    "tools": [
        {
            "name": "research.search_public",
            "version": "research.search_public.v1",
            "effect": "read",
        },
        {
            "name": "research.capture_snapshot",
            "version": "research.capture_snapshot.v1",
            "effect": "record_observation",
        },
    ],
}


class ResearchChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    action: Literal["finish", "search", "read"]
    target: str | None = Field(default=None, min_length=1, max_length=1024)
    reason: str = Field(min_length=1, max_length=1500)
    offset: int = Field(default=0, ge=0, le=2_000_000)
    length: int = Field(default=4000, ge=1, le=6000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.action == "finish") != (self.target is None):
            raise ValueError("结束研究不带目标；搜索或读取必须指定目标")
        if self.action == "search" and self.target and len(self.target) > 512:
            raise ValueError("搜索词最多512字符")
        if self.action != "read" and (self.offset != 0 or self.length != 4000):
            raise ValueError("只有网页读取可选择正文片段")
        return self


def research_call(run: UUID, seat: UUID, round_number: int, step: int) -> UUID:
    if not 1 <= step <= 3:
        raise ProductWorkError("研究步骤超出固定上限")
    return uuid5(call_id(run, seat, round_number), f"research:{step}")


def version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    if snapshot.get("phase") != "discussion_research":
        return None
    if (
        run_context.get("discussion_research_version") != PROMPT.version
        or run_context.get("discussion_research_schema")
        != digest(ResearchChoice.model_json_schema())
        or run_context.get("discussion_toolset_version") != VERSION
    ):
        raise BudgetLedgerError("APPLICATION_DISCUSSION_RESEARCH_VERSION_CHANGED")
    return PROMPT.version


def history(c: Connection, tenant: UUID, run: UUID) -> list[dict[str, Any]]:
    cp, o = tables.application_result_checkpoints, tables.application_context_observations
    return [
        _plain(dict(v))
        for v in c.execute(
            select(
                cp.c.id,
                cp.c.model_call_id,
                cp.c.body,
                cp.c.created_at,
                o.c.output_body["projection"]["label"].as_string().label("seat_label"),
                o.c.output_body["round_number"].as_integer().label("round_number"),
                o.c.output_body["research_step"].as_integer().label("step"),
            )
            .join(o, (o.c.tenant_id == cp.c.tenant_id) & (o.c.id == cp.c.observation_id))
            .where(
                cp.c.tenant_id == tenant,
                cp.c.run_id == run,
                o.c.output_body["phase"].as_string() == "discussion_research",
            )
            .order_by(cp.c.created_at, cp.c.id)
        ).mappings()
    ]


def run(
    engine: Engine,
    gateway: ApplicationModelGateway,
    row: RowMapping,
    bound: dict[str, Any],
    seat: dict[str, Any],
    round_number: int,
) -> None:
    from app.ai.application_domain_context import record, sources_current
    from app.ai.change_discussion_runs import transcript
    from app.ai.discussion_research import augment
    from app.ai.discussion_research_tools import execute, observations

    steps = bound["config"]["request"].get("research_steps", 0)
    if not steps:
        return
    require_live_key(KEY)
    for step in range(1, steps + 1):
        call = research_call(row["id"], UUID(seat["id"]), round_number, step)
        with engine.connect() as c:
            cp = c.execute(
                select(tables.application_result_checkpoints.c.body).where(
                    tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
                    tables.application_result_checkpoints.c.run_id == row["id"],
                    tables.application_result_checkpoints.c.model_call_id == call,
                )
            ).scalar_one_or_none()
            choice = ResearchChoice.model_validate(cp["output"]) if cp is not None else None
            existing = c.execute(
                select(tables.application_context_observations.c.output_body).where(
                    tables.application_context_observations.c.tenant_id == row["tenant_id"],
                    tables.application_context_observations.c.run_id == row["id"],
                    tables.application_context_observations.c.model_call_id == call,
                )
            ).scalar_one_or_none()
            if existing is not None:
                snapshot = existing
            else:
                snapshot = augment(
                    c,
                    row,
                    seat_input(
                        bound["source"],
                        seat,
                        bound["config"]["request"]["question"],
                        round_number,
                        transcript(c, row["tenant_id"], bound["session_id"]),
                        followup_reason=bound["config"]["request"].get("followup_reason"),
                    ),
                )
                snapshot.update(phase="discussion_research", research_step=step)
                question = json.loads(snapshot["context"]["question"])
                # Search hits remain leads, not citable reference fields.
                actual_observations = observations(c, row["tenant_id"], row["id"])[-12:]
                snapshot["research_tool_ids"] = [v["id"] for v in actual_observations]
                question["research_observations"] = [
                    {
                        "tool": v["tool_key"],
                        "result": {
                            **{
                                k: value
                                for k, value in v["output_body"].items()
                                if k != "reference"
                            },
                            "reference_id": (v["output_body"].get("reference") or {}).get(
                                "reference_id"
                            ),
                        },
                    }
                    for v in actual_observations
                ]
                question["research_steps_remaining"] = steps - step + 1
                snapshot["context"]["question"] = json.dumps(
                    question, ensure_ascii=False, sort_keys=True
                )
        version(row["run_context"], snapshot)
        if choice is None:
            record(
                engine,
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                run_id=row["id"],
                model_call_id=call,
                purpose="change_discussion",
                context=snapshot["context"],
                snapshot=snapshot,
            )
            invocation = GatewayInvocation(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                run_id=row["id"],
                model_call_id=call,
                agent_key="engineering_intelligence",
                agent_tier=AgentTier.REASONING,
                prompt_version=PROMPT.version,
                system_prompt=PROMPT.system_prompt,
                instruction=PROMPT.instruction,
                context=snapshot["context"],
            )
            if not sources_current(engine, invocation, "change_discussion", snapshot):
                raise ProductWorkError("研究前原资料已变化")
            response = gateway.invoke_structured(invocation, ResearchChoice)
            if response.status != "succeeded" or response.output is None:
                raise BudgetLedgerError(response.error_code or "DISCUSSION_RESEARCH_UNAVAILABLE")
            if not sources_current(engine, invocation, "change_discussion", snapshot):
                raise ProductWorkError("研究判断期间原资料已变化")
            choice = response.output
        if choice.action == "finish":
            return
        execute(engine, gateway, row, call, choice)
