"""An actual model decision may convene seats inside an already authorized run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_contract import DiscussionTurn, call_id, seat_input, validate
from app.ai.executor import PromptFile
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import require_live_key
from app.contracts.change_work_package import Statement
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "discussion_initiation_v1.json").read_text()
)
KEY = "engineering_intelligence.discussion_initiation"


class SeatChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=64)
    contribution: Statement


class Initiation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["convene", "not_needed", "insufficient_evidence"]
    reason: Statement
    seats: tuple[SeatChoice, ...] = Field(max_length=9)
    missing: tuple[str, ...] = Field(max_length=30)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.action == "convene" and len(self.seats) < 2:
            raise ValueError("召集讨论须至少两个有实际不同依据的席位")
        if self.action != "convene" and self.seats:
            raise ValueError("未召集讨论时不能声明实际参与席位")
        if len({s.key for s in self.seats}) != len(self.seats):
            raise ValueError("实际席位不能重复")
        if self.action == "insufficient_evidence" and not self.missing:
            raise ValueError("资料不足须说明缺项")
        return self


def receipt(c: Connection, tenant: UUID, run_id: UUID) -> dict[str, Any] | None:
    table = tables.debate_initiations
    row = (
        c.execute(select(table).where(table.c.tenant_id == tenant, table.c.run_id == run_id))
        .mappings()
        .one_or_none()
    )
    return _plain(dict(row)) if row else None


def effective_config(config: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, Any]:
    if not config.get("initiation"):
        return config
    keys = {v["key"] for v in actual["output"]["seats"]} if actual else set()
    return {
        **config,
        "candidate_seats": config["seats"],
        "seats": [s for s in config["seats"] if s["key"] in keys],
    }


def prompt_version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    if snapshot.get("phase") != "discussion_initiation":
        from app.ai.discussion_research_loop import version

        return version(run_context, snapshot)
    if run_context.get("discussion_initiation_version") != PROMPT.version or run_context.get(
        "discussion_initiation_schema"
    ) != digest(Initiation.model_json_schema()):
        raise BudgetLedgerError("APPLICATION_DISCUSSION_INITIATION_VERSION_CHANGED")
    return PROMPT.version


def validate_choice(value: Initiation, snapshot: dict[str, Any], config: dict[str, Any]) -> None:
    validate(
        DiscussionTurn(
            disposition="position",
            statements=(value.reason, *(s.contribution for s in value.seats)),
            responses=(),
            missing=value.missing,
        ),
        snapshot,
    )
    allowed = {s["key"]: s for s in config["seats"]}
    cited: list[set[str]] = []
    for choice in value.seats:
        seat = allowed.get(choice.key)
        if seat is None:
            raise ProductWorkError("拟召集席位超出原运行固定范围")
        own = set(seat["reference_ids"])
        refs = {v.reference_id for v in choice.contribution.citations}
        if not refs or not refs <= own:
            raise ProductWorkError("席位的新增信息理由须引用其原专业资料")
        cited.append(refs)
    if cited and len({frozenset(v) for v in cited}) < 2:
        raise ProductWorkError("拟召集席位仅引用相同资料，尚无不同信息贡献")


def run(
    engine: Engine, gateway: ApplicationModelGateway, row: RowMapping, bound: dict[str, Any]
) -> dict[str, Any]:
    from app.ai.application_domain_context import record, sources_current
    from app.ai.change_discussion_runs import event, transcript

    require_live_key(KEY)

    with engine.connect() as c:
        prior = receipt(c, row["tenant_id"], row["id"])
        if prior:
            return prior
        planning = bound["config"]["initiation"]
        call = call_id(row["id"], UUID(planning["id"]), 1)
        observations = tables.application_context_observations
        existing = c.execute(
            select(observations.c.output_body).where(
                observations.c.tenant_id == row["tenant_id"],
                observations.c.run_id == row["id"],
                observations.c.model_call_id == call,
            )
        ).scalar_one_or_none()
        if existing is not None:
            snapshot = existing
        else:
            snapshot = seat_input(
                bound["source"],
                planning,
                bound["config"]["request"]["question"],
                1,
                transcript(c, row["tenant_id"], bound["session_id"]),
                followup_reason=bound["config"]["request"].get("followup_reason"),
            )
            snapshot["phase"] = "discussion_initiation"
            import json

            question = json.loads(snapshot["context"]["question"])
            question["candidate_seats"] = [
                {k: s[k] for k in ("key", "label", "reference_ids", "missing")}
                for s in bound["config"]["seats"]
            ]
            snapshot["context"]["question"] = json.dumps(
                question, ensure_ascii=False, sort_keys=True
            )
            from app.ai.discussion_research import augment

            snapshot = augment(c, row, snapshot)
    prompt_version(row["run_context"], snapshot)
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
        raise ProductWorkError("原资料已变化，不能按旧范围召集讨论")
    response = gateway.invoke_structured(invocation, Initiation)
    if response.status != "succeeded" or response.output is None:
        raise BudgetLedgerError(response.error_code or "DISCUSSION_INITIATION_UNAVAILABLE")
    validate_choice(response.output, snapshot, bound["config"])
    if not sources_current(engine, invocation, "change_discussion", snapshot):
        raise ProductWorkError("发起判断期间资料已变化")
    with engine.begin() as c:
        bind_write(c, gateway, row["tenant_id"], row["id"])
        cp = tables.application_result_checkpoints
        checkpoint = (
            c.execute(
                select(cp).where(
                    cp.c.tenant_id == row["tenant_id"],
                    cp.c.run_id == row["id"],
                    cp.c.model_call_id == call,
                )
            )
            .mappings()
            .one()
        )
        output = response.output.model_dump(mode="json")
        if checkpoint["body"]["output"] != output:
            raise ProductWorkError("发起判断未对应原成功模型回执")
        c.execute(
            tables.debate_initiations.insert().values(
                id=uuid4(),
                tenant_id=row["tenant_id"],
                run_id=row["id"],
                session_id=bound["session_id"],
                checkpoint_id=checkpoint["id"],
                output=output,
                created_at=func.clock_timestamp(),
            )
        )
        c.execute(
            tables.debate_sessions.update()
            .where(tables.debate_sessions.c.id == bound["session_id"])
            .values(
                status="arguing" if response.output.action == "convene" else "preparing",
                updated_at=func.clock_timestamp(),
            )
        )
        event(c, row["tenant_id"], bound["session_id"], "agent_" + response.output.action)
        saved = receipt(c, row["tenant_id"], row["id"])
        assert saved is not None
        return saved
