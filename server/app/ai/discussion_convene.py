"""Model-backed discussion requests from an existing authorized application run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.discussion_initiation import Initiation, validate_choice
from app.ai.executor import PromptFile
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import require_live_key
from app.contracts.runtime_records import Observation
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, digest

KEY = "engineering_intelligence.discussion_convene"
VERSION = "discussion-convene.v1"
TOOL = "discussion.convene"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "discussion_convene_v1.json").read_text()
)
TOOLSET = {
    "version": VERSION,
    "dispatch": "model_selected",
    "tools": [
        {"name": TOOL, "version": VERSION, "effect": "record_observation"},
    ],
}


class ConvenePlan(Initiation):
    question: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def question_required(self) -> Self:
        if (self.action == "convene") != (self.question is not None):
            raise ValueError("仅召集时提供明确讨论问题")
        return self


def version(rc: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    if snapshot.get("phase") != "discussion_convene":
        return None
    if rc.get("discussion_convene_version") != PROMPT.version or rc.get(
        "discussion_convene_schema"
    ) != digest(ConvenePlan.model_json_schema()):
        raise BudgetLedgerError("APPLICATION_CONVENE_VERSION_CHANGED")
    return PROMPT.version


def call_id(run: UUID) -> UUID:
    return uuid5(run, VERSION)


def origin(
    c: Connection,
    gateway: object,
    tenant: UUID,
    actor: UUID,
    project: UUID,
    parent_run: UUID,
    checkpoint: UUID,
    command: Any,
) -> RowMapping:
    require_live_key(KEY)
    cp, o, r = (
        tables.application_result_checkpoints,
        tables.application_context_observations,
        tables.agent_runs,
    )
    row = (
        c.execute(
            select(r).where(
                r.c.tenant_id == tenant,
                r.c.id == parent_run,
                r.c.project_id == project,
                r.c.requested_by_user_id == actor,
            )
        )
        .mappings()
        .one()
    )
    bind_write(c, gateway, tenant, parent_run)
    saved = (
        c.execute(
            select(cp.c.body, o.c.output_body)
            .join(o, (o.c.tenant_id == cp.c.tenant_id) & (o.c.id == cp.c.observation_id))
            .where(
                cp.c.tenant_id == tenant,
                cp.c.run_id == parent_run,
                cp.c.id == checkpoint,
                cp.c.model_call_id == call_id(parent_run),
            )
        )
        .mappings()
        .one()
    )
    snapshot = saved["output_body"]
    version(row["run_context"], snapshot)
    if snapshot.get("phase") != "discussion_convene":
        raise ProductWorkError("讨论须来自原运行实际发起判断")
    plan = ConvenePlan.model_validate(saved["body"]["output"])
    validate_choice(
        plan,
        {"references": snapshot["model_context"]["references"], "transcript": []},
        {"seats": snapshot["model_context"]["professional_projections"]},
    )
    if (
        plan.action != "convene"
        or command.question != plan.question
        or command.seats != [seat.key for seat in plan.seats]
        or command.expected_digest != snapshot["digest"]
        or command.participation_mode != "selected"
        or command.parent_run_id is not None
        or command.rounds != 2
        or command.research_steps != 0
        or command.include_supplier_notices
        != row["run_context"].get("impact_include_supplier_notices", False)
    ):
        raise ProductWorkError("不能扩展原判断的讨论问题、候选专业或资料")
    return row


def prepare(c: Connection, gateway: object, row: RowMapping, checkpoint: UUID) -> UUID:
    # Caller holds tenant budget lock and original application lease in this transaction.
    token = bind_write(c, gateway, row["tenant_id"], row["id"])
    if token is None:
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
    identity = uuid5(checkpoint, TOOL)
    if c.execute(
        select(tables.agent_tool_intents.c.id).where(tables.agent_tool_intents.c.id == identity)
    ).first():
        raise ProductWorkError("原发起工具已有记录，请回原子讨论读取")
    link = BudgetLedger._link(c, row["tenant_id"], row["id"])
    if link is None:
        raise BudgetLedgerError("BUDGET_RUN_UNBOUND")
    try:
        c.execute(
            text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
            dict(t=row["tenant_id"], r=row["id"]),
        )
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
            raise BudgetLedgerError(code) from error
        raise
    used = c.execute(
        text("""SELECT cehub_ai.tool_intent_call_count(:t,:l) +
     (SELECT count(*) FROM (SELECT DISTINCT ON(attempt_id) reservation_status
      FROM cehub_ai.budget_journal WHERE tenant_id=:t AND lineage_id=:l AND call_kind='tool'
      ORDER BY attempt_id,revision DESC) latest
      WHERE reservation_status<>'cancelled_before_dispatch')"""),
        dict(t=row["tenant_id"], l=link["id"]),
    ).scalar_one()
    limit = link["profile"].get("tool_call_limit")
    if type(limit) is not int or limit < 1 or used >= limit:
        raise BudgetLedgerError("BUDGET_TOOL_CALL_COUNT_EXHAUSTED")
    stamp = c.execute(select(func.clock_timestamp())).scalar_one()
    c.execute(
        tables.agent_tool_intents.insert().values(
            id=identity,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            lineage_id=link["id"],
            call_key=VERSION,
            tool_key=TOOL,
            input_body={"version": VERSION, "checkpoint_id": str(checkpoint)},
            created_at=stamp,
        )
    )
    c.execute(
        tables.agent_tool_dispatches.insert().values(
            intent_id=identity,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            lease_token=token,
            created_at=stamp,
        )
    )
    return identity


def record_child(
    c: Connection, row: RowMapping, intent: UUID, child: RowMapping, checkpoint: UUID
) -> None:
    auth = (
        c.execute(
            select(tables.application_authorizations).where(
                tables.application_authorizations.c.tenant_id == row["tenant_id"],
                tables.application_authorizations.c.run_id == row["id"],
            )
        )
        .mappings()
        .one()
    )
    stamp = c.execute(select(func.clock_timestamp())).scalar_one()
    payload = {
        "run_id": str(child["id"]),
        "session_id": child["run_context"]["debate_session_id"],
        "status": "queued",
        "notice": "讨论已排队，尚无专业结论；请按原运行回看实际结果",
    }
    oid = uuid5(intent, "observation")
    observed = Observation.model_validate(
        dict(
            id=oid,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            tool_call_id=intent,
            parent_observation_id=None,
            sequence=1,
            tool_version=VERSION,
            status="completed",
            sources=[
                dict(
                    tenant_id=row["tenant_id"],
                    project_id=row["project_id"],
                    kind="discussion_run",
                    ref_id=child["id"],
                    as_of=stamp,
                    digest=digest(payload),
                )
            ],
            observed_at=stamp,
            as_of=stamp,
            fresh_until=None,
            acl_policy_version=auth["body"]["policy_version"],
            allowed_purpose=auth["body"]["purpose"],
            taint="internal",
            input_digest=digest({"version": VERSION, "checkpoint_id": str(checkpoint)}),
            output_digest=digest(payload),
            shown_count=1,
            total_count=1,
            truncated=False,
            continuation=None,
        )
    )
    c.execute(
        tables.application_tool_observations.insert().values(
            id=oid,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            authorization_id=auth["id"],
            tool_intent_id=intent,
            metadata=observed.model_dump(mode="json"),
            output_body=payload,
            created_at=stamp,
        )
    )
    rc = c.execute(
        select(tables.agent_runs.c.run_context).where(tables.agent_runs.c.id == row["id"])
    ).scalar_one()
    c.execute(
        tables.agent_runs.update()
        .where(tables.agent_runs.c.id == row["id"])
        .values(run_context={**rc, "convened_discussion": payload}, updated_at=stamp)
    )


def run(
    engine: Engine, gateway: ApplicationModelGateway, row: RowMapping, snapshot: dict[str, Any]
) -> None:
    from app.ai.application_domain_context import record, sources_current
    from app.ai.change_discussion_runs import ChangeDiscussionRuns, Request
    from app.ai.change_work_package_runs import model_context
    from app.ai.project_discussion_sources import actor

    require_live_key(KEY)
    from app.ai.change_notice_preparation import require_discussion_enabled

    require_discussion_enabled(snapshot)
    call = call_id(row["id"])
    with engine.connect() as c:
        old = c.execute(
            select(tables.application_context_observations.c.output_body).where(
                tables.application_context_observations.c.tenant_id == row["tenant_id"],
                tables.application_context_observations.c.run_id == row["id"],
                tables.application_context_observations.c.model_call_id == call,
            )
        ).scalar_one_or_none()
        cp = (
            c.execute(
                select(tables.application_result_checkpoints).where(
                    tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
                    tables.application_result_checkpoints.c.run_id == row["id"],
                    tables.application_result_checkpoints.c.model_call_id == call,
                )
            )
            .mappings()
            .one_or_none()
        )
    selected = old or {**snapshot, "phase": "discussion_convene"}
    version(row["run_context"], selected)
    if cp is None:
        context = model_context(selected, row["run_context"].get("impact_user_instruction", ""))
        record(
            engine,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call,
            purpose="change_work_package",
            context=context,
            snapshot=selected,
        )
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call,
            agent_key=row["agent_key"],
            agent_tier=AgentTier.REASONING,
            prompt_version=PROMPT.version,
            system_prompt=PROMPT.system_prompt,
            instruction=PROMPT.instruction,
            context=context,
        )
        if not sources_current(engine, invocation, "change_work_package", selected):
            raise ProductWorkError("原资料已有变化，不能据此发起讨论")
        answer = gateway.invoke_structured(invocation, ConvenePlan)
        if answer.status != "succeeded" or answer.output is None:
            raise BudgetLedgerError(answer.error_code or "DISCUSSION_CONVENE_UNAVAILABLE")
        with engine.connect() as c:
            cp = (
                c.execute(
                    select(tables.application_result_checkpoints).where(
                        tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
                        tables.application_result_checkpoints.c.run_id == row["id"],
                        tables.application_result_checkpoints.c.model_call_id == call,
                    )
                )
                .mappings()
                .one()
            )
    plan = ConvenePlan.model_validate(cp["body"]["output"])
    validate_choice(
        plan,
        {"references": selected["model_context"]["references"], "transcript": []},
        {"seats": selected["model_context"]["professional_projections"]},
    )
    with engine.begin() as c:
        bind_write(c, gateway, row["tenant_id"], row["id"])
        rc = c.execute(
            select(tables.agent_runs.c.run_context).where(tables.agent_runs.c.id == row["id"])
        ).scalar_one()
        c.execute(
            tables.agent_runs.update()
            .where(tables.agent_runs.c.id == row["id"])
            .values(run_context={**rc, "discussion_convene_choice": plan.model_dump(mode="json")})
        )
        if plan.action != "convene":
            return
        prior = c.execute(
            select(tables.debate_run_bindings.c.run_id).where(
                tables.debate_run_bindings.c.tenant_id == row["tenant_id"],
                tables.debate_run_bindings.c.origin_run_id == row["id"],
                tables.debate_run_bindings.c.origin_checkpoint_id == cp["id"],
            )
        ).scalar_one_or_none()
        if prior is not None:
            return
        owner = actor(c, row["tenant_id"], row["requested_by_user_id"])
    ChangeDiscussionRuns(engine, gateway=gateway).submit(
        owner,
        row["project_id"],
        UUID(selected["ecr_id"]),
        Request(
            request_id=uuid5(cp["id"], TOOL),
            question=plan.question or "",
            seats=[s.key for s in plan.seats],
            expected_digest=selected["digest"],
            depth=selected["model_context"]["coverage"]["depth"],
            rounds=2,
            participation_mode="selected",
            include_supplier_notices=row["run_context"].get(
                "impact_include_supplier_notices", False
            ),
        ),
        origin_run_id=row["id"],
        origin_checkpoint_id=cp["id"],
    )
