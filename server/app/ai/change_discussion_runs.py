"""Queued professional discussion, with one fixed call per actual seat and round."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai import change_notice_preparation as notices
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.capability_contract import resolve_capability
from app.ai.change_discussion_contract import (
    KEY,
    PROMPT,
    PURPOSE,
    RUN_VERSION,
    DiscussionTurn,
    call_id,
    seat_input,
    validate,
)
from app.ai.change_impact_preparation import source_state
from app.ai.discussion_contributions import POLICY, analyze, fingerprint
from app.ai.discussion_sources import current as current_source
from app.ai.discussion_sources import require_disclosure
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.change_execution_results import _access
from app.domain.debates import DebateService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    include_supplier_notices: bool = False
    research_steps: int = Field(default=0, ge=0, le=3)
    participation_mode: Literal["selected", "agent_choose"] = "selected"
    parent_run_id: UUID | None = None
    followup_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    question: str = Field(min_length=1, max_length=4000)
    seats: list[str] = Field(min_length=2, max_length=9)
    depth: int = Field(default=3, ge=1, le=5)
    rounds: int = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def unique(self) -> Request:
        if bool(self.parent_run_id) != bool(self.followup_reason):
            raise ValueError("关联继续须同时选择原讨论并说明新增资料或问题")
        if len(set(self.seats)) != len(self.seats):
            raise ValueError("同一专业只选择一次")
        return self


def authorize(engine: Engine, context: AuthContext, project: UUID, *, edit: bool) -> None:
    _access(engine, context, project, Action.CHANGE_EDIT if edit else Action.CHANGE_VIEW)
    _access(engine, context, project, Action.QUALITY_VIEW)


def event(
    c: Connection, tenant: UUID, session: UUID, action: str, actor: UUID | None = None
) -> None:
    DebateService._emit(
        c,
        tenant_id=tenant,
        actor_user_id=actor,
        record=DebateService._get(c, tenant_id=tenant, session_id=session),
        action=action,
        before=None,
        occurred_at=c.execute(select(func.clock_timestamp())).scalar_one(),
    )


def binding(c: Connection, tenant: UUID, run_id: UUID) -> RowMapping:
    t = tables.debate_run_bindings
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.run_id == run_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原讨论运行不存在")
    return row


def transcript(c: Connection, tenant: UUID, session: UUID) -> list[dict[str, Any]]:
    t, s = tables.debate_turns, tables.debate_seats
    return [
        _plain(dict(r))
        for r in c.execute(
            select(t, s.c.seat_key)
            .outerjoin(s, (s.c.tenant_id == t.c.tenant_id) & (s.c.id == t.c.seat_id))
            .where(t.c.tenant_id == tenant, t.c.session_id == session)
            .order_by(t.c.sequence)
        ).mappings()
    ]


def result(c: Connection, row: Any) -> dict[str, Any]:
    b = binding(c, row["tenant_id"], row["id"])
    s = tables.debate_sessions
    session = (
        c.execute(select(s).where(s.c.tenant_id == row["tenant_id"], s.c.id == b["session_id"]))
        .mappings()
        .one()
    )
    receipts = tables.debate_turn_receipts
    records = [
        dict(r)
        for r in c.execute(
            select(receipts)
            .where(receipts.c.tenant_id == row["tenant_id"], receipts.c.run_id == row["id"])
            .order_by(receipts.c.created_at, receipts.c.id)
        ).mappings()
    ]
    saved_turns = transcript(c, row["tenant_id"], b["session_id"])
    actor_ids = {UUID(v["author_user_id"]) for v in saved_turns if v["author_user_id"]}
    users = tables.users
    names = (
        {
            str(u["id"]): u["display_name"]
            for u in c.execute(
                select(users.c.id, users.c.display_name).where(
                    users.c.tenant_id == row["tenant_id"], users.c.id.in_(actor_ids)
                )
            ).mappings()
        }
        if actor_ids
        else {}
    )
    for turn in saved_turns:
        turn["author_name"] = names.get(turn["author_user_id"])
    from app.ai.discussion_initiation import effective_config
    from app.ai.discussion_initiation import receipt as initiation_receipt

    initiation = initiation_receipt(c, row["tenant_id"], row["id"])
    from app.ai.discussion_research import current as research_current
    from app.ai.discussion_research import records as research_records

    research = research_records(c, row["tenant_id"], row["id"])
    from app.ai.discussion_research_loop import history as research_history
    from app.ai.discussion_research_tools import observations as research_observations

    origin_choice = None
    if b["origin_checkpoint_id"] is not None:
        origin_choice = c.execute(
            select(tables.application_result_checkpoints.c.body).where(
                tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
                tables.application_result_checkpoints.c.run_id == b["origin_run_id"],
                tables.application_result_checkpoints.c.id == b["origin_checkpoint_id"],
            )
        ).scalar_one()["output"]
    payload = _plain(
        {
            "run_id": row["id"],
            "ecr_id": b["ecr_id"],
            "origin_run_id": b["origin_run_id"],
            "include_supplier_notices": notices.is_notice(b["source"]),
            "origin_choice": origin_choice,
            "topic_kind": b["topic_kind"],
            "request_id": row["request_id"],
            "status": row["status"],
            "error_code": row["error_code"],
            "requested_by_user_id": row["requested_by_user_id"],
            "created_at": row["created_at"],
            "session": dict(session),
            "effective_status": "preparing"
            if b["config"].get("initiation")
            and initiation is None
            and row["status"] in {"queued", "running"}
            else "cancelled"
            if row["error_code"] == "APPLICATION_REQUEST_CANCELLED"
            else "interrupted"
            if row["status"] in {"failed", "degraded"}
            and session["status"] in {"convened", "arguing"}
            else session["status"],
            "config": effective_config(b["config"], initiation),
            "initiation": initiation,
            "research_inputs": research,
            "research_choices": research_history(c, row["tenant_id"], row["id"]),
            "research_tools": research_observations(c, row["tenant_id"], row["id"]),
            "research_current": research_current(
                c, row["tenant_id"], row["requested_by_user_id"], research
            ),
            "source_digest": b["source"]["digest"],
            "source_coverage": b["source"]["model_context"]["coverage"],
            "turns": saved_turns,
            "receipts": records,
            "reference_labels": {
                r["reference_id"]: r["label"]
                for r in [
                    *b["source"]["model_context"]["references"],
                    *(item["reference"] for item in research),
                ]
            },
            "recovery_requested": row["run_context"].get("discussion_recovery_requested", False),
        }
    )

    from app.ai.change_discussion_resume import state as resume_state
    from app.domain.change_discussion_briefs import assemble, history

    payload["contributions"] = analyze(
        payload["config"], saved_turns, payload["receipts"], research
    )
    from app.ai.discussion_lineage import cancellation

    payload["parent_run_id"] = str(b["parent_run_id"]) if b["parent_run_id"] else None
    payload["related_request_cancelled"] = cancellation(c, row["tenant_id"], row["id"])
    payload["resume"] = resume_state(c, row, b)
    payload["brief"] = {
        **assemble(payload),
        "reviews": history(c, row["tenant_id"], row["id"]),
    }
    return payload


class ChangeDiscussionRuns:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def submit(
        self,
        context: AuthContext,
        project: UUID,
        ecr_id: UUID | None,
        command: Request,
        *,
        origin_run_id: UUID | None = None,
        origin_checkpoint_id: UUID | None = None,
    ) -> dict[str, Any]:
        if bool(origin_run_id) != bool(origin_checkpoint_id):
            raise ProductWorkError("原发起运行和成功回执须同时提供")
        authorize(self.engine, context, project, edit=True)
        require_live_key(KEY)
        if command.include_supplier_notices:
            if ecr_id is None:
                raise ProductWorkError("厂商通告只用于已关联实际ECR的讨论")
            require_live_key(notices.KEY)
            require_live_key(notices.DISCUSSION_KEY)
        if command.participation_mode == "agent_choose":
            from app.ai.discussion_initiation import KEY as INITIATION_KEY

            require_live_key(INITIATION_KEY)
        if command.research_steps:
            from app.ai.discussion_research_loop import KEY as RESEARCH_KEY
            from app.domain.product_workspace import _role

            require_live_key(RESEARCH_KEY)
            _role(context, Action.EVIDENCE_VIEW)
            _role(context, Action.EVIDENCE_CAPTURE)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            c.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == context.tenant.id)
                .with_for_update()
            ).one()
            BudgetLedger._lock(c, context.tenant.id)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            t = tables.agent_runs
            config = command.model_dump(mode="json")
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.request_id == str(command.request_id),
                        t.c.agent_key == "engineering_intelligence",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                b = binding(c, context.tenant.id, prior["id"])
                if (
                    prior["requested_by_user_id"] != context.user.id
                    or b["origin_run_id"] != origin_run_id
                    or b["origin_checkpoint_id"] != origin_checkpoint_id
                    or b["ecr_id"] != ecr_id
                    or {
                        **b["config"]["request"],
                        "include_supplier_notices": b["config"]["request"].get(
                            "include_supplier_notices", False
                        ),
                        "research_steps": b["config"]["request"].get("research_steps", 0),
                        "parent_run_id": b["config"]["request"].get("parent_run_id"),
                        "followup_reason": b["config"]["request"].get("followup_reason"),
                        "participation_mode": b["config"]["request"].get(
                            "participation_mode", "selected"
                        ),
                    }
                    != config
                ):
                    raise ProductWorkError("原讨论请求已有不同内容")
                require_disclosure(c, context.tenant.id, context.user.id, b)
                return result(c, prior)
            origin_row = None
            origin_intent = None
            if origin_run_id is not None and origin_checkpoint_id is not None:
                from app.ai.discussion_convene import origin, prepare

                origin_row = origin(
                    c,
                    self.gateway,
                    context.tenant.id,
                    context.user.id,
                    project,
                    origin_run_id,
                    origin_checkpoint_id,
                    command,
                )
                origin_intent = prepare(c, self.gateway, origin_row, origin_checkpoint_id)
            if command.parent_run_id:
                from app.ai.discussion_lineage import parent

                parent(c, context, project, ecr_id, command.parent_run_id)
            if ecr_id is None:
                from app.ai.project_discussion_sources import state as topic_source

                source = topic_source(
                    c, context.tenant.id, project, context.user.id, config["selections"]
                )
            else:
                source = (
                    notices.source_state(c, context, project, ecr_id, command.depth)
                    if command.include_supplier_notices
                    else source_state(c, context.tenant.id, project, ecr_id, command.depth)
                )
            if source["digest"] != command.expected_digest:
                raise ProductWorkError("讨论来源已变化，请重新核对")
            if origin_row is not None and command.include_supplier_notices:
                # Current evidence matched; retain the exact original snapshot, including read time.
                source = origin_row["run_context"]["impact_source"]
            projections = {s["key"]: s for s in source["model_context"]["professional_projections"]}
            if any(
                key not in projections or not projections[key]["reference_ids"]
                for key in command.seats
            ):
                raise ProductWorkError("请选择本次有实际专业资料的席位，缺资料不能靠角色扮演补齐")
            sets = [set(projections[key]["reference_ids"]) for key in command.seats]
            if len({frozenset(v) for v in sets}) < 2:
                raise ProductWorkError("所选席位没有不同资料，应先使用单次工程分析或补齐专业证据")
            profile = getattr(self.gateway, "creation_budget_profile", None)
            if profile is None:
                raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            session_id, run_id = uuid4(), uuid4()
            c.execute(
                tables.debate_sessions.insert().values(
                    id=session_id,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    topic_entity="engineering_change_request" if ecr_id else "project",
                    topic_entity_id=ecr_id or project,
                    question=command.question,
                    initiated_by="agent"
                    if command.participation_mode == "agent_choose" or origin_run_id is not None
                    else "user",
                    initiator_ref=str(origin_run_id)
                    if origin_run_id is not None
                    else str(run_id)
                    if command.participation_mode == "agent_choose"
                    else str(context.user.id),
                    initiated_by_user_id=None
                    if command.participation_mode == "agent_choose" or origin_run_id is not None
                    else context.user.id,
                    status="preparing"
                    if command.participation_mode == "agent_choose"
                    else "convened",
                    budget_tokens=profile.lineage_token_limit,
                    spent_tokens=0,
                    round_count=0,
                    max_rounds=command.rounds,
                    created_at=now,
                    updated_at=now,
                )
            )
            selected = []
            for key in command.seats:
                seat_id = uuid4()
                projection = projections[key]
                selected.append({"id": str(seat_id), **projection})
                c.execute(
                    tables.debate_seats.insert().values(
                        id=seat_id,
                        tenant_id=context.tenant.id,
                        session_id=session_id,
                        seat_key=key,
                        agent_key="engineering_intelligence",
                        stance_projection={
                            "anchors": {
                                "source": projection["reference_ids"]
                                + projection["shared_reference_ids"]
                            },
                            "projection": projection,
                            "source_digest": source["digest"],
                        },
                        persona_version="project.v1" if ecr_id is None else "ecr.v1",
                        created_at=now,
                    )
                )
            initiation_config: dict[str, Any] = {}
            initiation_pins: dict[str, Any] = {}
            if command.participation_mode == "agent_choose":
                from app.ai.discussion_initiation import PROMPT as INITIATION_PROMPT
                from app.ai.discussion_initiation import Initiation

                initiation_config = {
                    "initiation": {
                        "id": str(uuid4()),
                        "key": "initiation",
                        "label": "是否召集及实际席位判断",
                        "missing": [],
                        "reference_ids": sorted(
                            {ref for s in selected for ref in s["reference_ids"]}
                        ),
                        "shared_reference_ids": sorted(
                            {ref for s in selected for ref in s["shared_reference_ids"]}
                        ),
                    }
                }
                initiation_pins = {
                    "discussion_initiation_version": INITIATION_PROMPT.version,
                    "discussion_initiation_schema": digest(Initiation.model_json_schema()),
                }
            research_pins: dict[str, Any] = {}
            if command.research_steps:
                from app.ai.discussion_research_loop import PROMPT as RESEARCH_PROMPT
                from app.ai.discussion_research_loop import VERSION as RESEARCH_TOOLS
                from app.ai.discussion_research_loop import ResearchChoice

                research_pins = {
                    "discussion_research_version": RESEARCH_PROMPT.version,
                    "discussion_research_schema": digest(ResearchChoice.model_json_schema()),
                    "discussion_toolset_version": RESEARCH_TOOLS,
                }
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=run_id,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        agent_key="engineering_intelligence",
                        request_id=str(command.request_id),
                        requested_by_user_id=context.user.id,
                        status="running",
                        event_count=0,
                        event_row_ids=[],
                        window_started_at=now,
                        window_ended_at=now,
                        context_version=RUN_VERSION,
                        started_at=now,
                        created_at=now,
                        updated_at=now,
                        run_context={
                            "debate_session_id": str(session_id),
                            "discussion_source_digest": source["digest"],
                            "discussion_ecr_id": str(ecr_id) if ecr_id else None,
                            "discussion_prompt_version": PROMPT.version,
                            "discussion_schema_digest": digest(DiscussionTurn.model_json_schema()),
                            "application_queue_version": "1",
                            **initiation_pins,
                            **research_pins,
                        },
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            c.execute(
                tables.debate_run_bindings.insert().values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    run_id=run_id,
                    session_id=session_id,
                    ecr_id=ecr_id,
                    parent_run_id=command.parent_run_id,
                    origin_run_id=origin_run_id,
                    origin_checkpoint_id=origin_checkpoint_id,
                    topic_kind="engineering_change_request" if ecr_id else "project",
                    source=source,
                    config={
                        "request": config,
                        "seats": selected,
                        "budget_profile": profile.model_dump(mode="json"),
                        "discussion_policy": POLICY,
                        **initiation_config,
                    },
                    created_at=now,
                )
            )
            freeze_created_application_run(
                c,
                self.gateway,
                tenant_id=context.tenant.id,
                run_id=run_id,
                parent_run_id=origin_run_id or command.parent_run_id,
                actor_user_id=context.user.id,
                auth_version=context.user.auth_version,
                purpose=PURPOSE,
                issue_lease=False,
            )
            row = (
                c.execute(t.update().where(t.c.id == run_id).values(status="queued").returning(t))
                .mappings()
                .one()
            )
            if (
                origin_row is not None
                and origin_intent is not None
                and origin_checkpoint_id is not None
            ):
                from app.ai.discussion_convene import record_child

                record_child(c, origin_row, origin_intent, row, origin_checkpoint_id)
            event(c, context.tenant.id, session_id, "queued", context.user.id)
            return result(c, row)

    def execute(self, row: RowMapping) -> None:
        from app.ai.application_domain_context import record, sources_current

        with self.engine.connect() as c:
            b = dict(binding(c, row["tenant_id"], row["id"]))
        notices.require_discussion_enabled(b["source"])
        if row["run_context"]["discussion_prompt_version"] != PROMPT.version or row["run_context"][
            "discussion_schema_digest"
        ] != digest(DiscussionTurn.model_json_schema()):
            raise ProductWorkError("原讨论运行版本不可用")
        if b["config"].get("initiation"):
            from app.ai.discussion_initiation import effective_config
            from app.ai.discussion_initiation import run as initiate

            initiation = initiate(self.engine, self.gateway, row, b)
            if initiation["output"]["action"] != "convene":
                self.finish(row, "completed", None)
                return
            b["config"] = effective_config(b["config"], initiation)
        for round_number in range(1, b["config"]["request"]["rounds"] + 1):
            if (
                round_number > 1
                and b["config"].get("discussion_policy") == POLICY
                and self.finish(row, "completed", None, only_if_stable=True)
            ):
                return
            for seat in b["config"]["seats"]:
                require_live_key(KEY)
                notices.require_discussion_enabled(b["source"])
                seat_id = UUID(seat["id"])
                call = call_id(row["id"], seat_id, round_number)
                with self.engine.connect() as c:
                    receipts = tables.debate_turn_receipts
                    if c.execute(
                        select(receipts.c.id).where(
                            receipts.c.tenant_id == row["tenant_id"],
                            receipts.c.session_id == b["session_id"],
                            receipts.c.seat_id == seat_id,
                            receipts.c.round_number == round_number,
                        )
                    ).first():
                        continue
                if b["config"]["request"].get("research_steps"):
                    with self.engine.connect() as c:
                        fixed = c.execute(
                            select(tables.application_context_observations.c.id).where(
                                tables.application_context_observations.c.tenant_id
                                == row["tenant_id"],
                                tables.application_context_observations.c.run_id == row["id"],
                                tables.application_context_observations.c.model_call_id == call,
                            )
                        ).first()
                    if fixed is None:
                        from app.ai.discussion_research_loop import run as research

                        research(self.engine, self.gateway, row, b, seat, round_number)
                with self.engine.connect() as c:
                    observed = (
                        c.execute(
                            select(tables.application_context_observations).where(
                                tables.application_context_observations.c.tenant_id
                                == row["tenant_id"],
                                tables.application_context_observations.c.run_id == row["id"],
                                tables.application_context_observations.c.model_call_id == call,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    snapshot = (
                        observed["output_body"]
                        if observed
                        else seat_input(
                            b["source"],
                            seat,
                            b["config"]["request"]["question"],
                            round_number,
                            transcript(c, row["tenant_id"], b["session_id"]),
                            followup_reason=b["config"]["request"].get("followup_reason"),
                        )
                    )
                    if observed is None:
                        from app.ai.discussion_research import augment

                        snapshot = augment(c, row, snapshot)
                context = snapshot["context"]
                record(
                    self.engine,
                    tenant_id=row["tenant_id"],
                    project_id=row["project_id"],
                    run_id=row["id"],
                    model_call_id=call,
                    purpose=PURPOSE,
                    context=context,
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
                    context=context,
                )
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("原业务资料已有变化，请重新准备讨论")
                response = self.gateway.invoke_structured(invocation, DiscussionTurn)
                if response.status != "succeeded" or response.output is None:
                    raise BudgetLedgerError(response.error_code or "DISCUSSION_MODEL_UNAVAILABLE")
                validate(response.output, snapshot)
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("讨论期间原业务资料已有变化")
                self._save_turn(row, b, seat_id, round_number, call, response.output)
        self.finish(row, "completed", None)

    def _save_turn(
        self,
        row: RowMapping,
        b: dict[str, Any],
        seat: UUID,
        round_number: int,
        call: UUID,
        output: DiscussionTurn,
    ) -> None:
        with self.engine.begin() as c:
            bind_write(c, self.gateway, row["tenant_id"], row["id"])
            s, t = tables.debate_sessions, tables.debate_turns
            session = (
                c.execute(
                    select(s)
                    .where(s.c.tenant_id == row["tenant_id"], s.c.id == b["session_id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if session["status"] not in {"convened", "arguing", "interrupted"}:
                raise ProductWorkError("讨论已停止")
            checkpoint = (
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
            if checkpoint["body"]["output"] != output.model_dump(mode="json"):
                raise ProductWorkError("发言未对应原模型回执")
            trace = (
                c.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.tenant_id == row["tenant_id"],
                        tables.model_invocations.c.id == checkpoint["invocation_id"],
                    )
                )
                .mappings()
                .one()
            )
            text_value = "\n".join(
                [
                    *(v.text for v in output.statements),
                    *(v.basis.text for v in output.responses),
                    *("待补：" + v for v in output.missing),
                ]
            )
            prior_receipts = c.execute(
                select(tables.debate_turn_receipts)
                .where(
                    tables.debate_turn_receipts.c.tenant_id == row["tenant_id"],
                    tables.debate_turn_receipts.c.session_id == b["session_id"],
                    tables.debate_turn_receipts.c.seat_id == seat,
                )
                .order_by(tables.debate_turn_receipts.c.round_number)
            ).mappings()
            output_fingerprint = fingerprint(output.model_dump(mode="json"))
            repeated = next(
                (
                    r["turn_id"]
                    for r in prior_receipts
                    if fingerprint(r["output"]) == output_fingerprint
                ),
                None,
            )
            turn_id = uuid4()
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            c.execute(
                t.insert().values(
                    id=turn_id,
                    tenant_id=row["tenant_id"],
                    session_id=b["session_id"],
                    round_number=round_number,
                    sequence=DebateService._next_sequence(
                        c, tenant_id=row["tenant_id"], session_id=b["session_id"]
                    ),
                    speaker_kind="seat",
                    seat_id=seat,
                    content=text_value,
                    citations=[
                        x.model_dump(mode="json")
                        for v in [*output.statements, *(r.basis for r in output.responses)]
                        for x in v.citations
                    ],
                    repetition_of_turn_id=repeated,
                    input_tokens=trace["input_tokens"] or 0,
                    output_tokens=trace["output_tokens"] or 0,
                    created_at=now,
                )
            )
            c.execute(
                tables.debate_turn_receipts.insert().values(
                    id=uuid4(),
                    tenant_id=row["tenant_id"],
                    run_id=row["id"],
                    session_id=b["session_id"],
                    seat_id=seat,
                    round_number=round_number,
                    turn_id=turn_id,
                    checkpoint_id=checkpoint["id"],
                    output=output.model_dump(mode="json"),
                    created_at=now,
                )
            )
            c.execute(
                s.update()
                .where(s.c.id == b["session_id"])
                .values(
                    status="arguing",
                    round_count=round_number,
                    spent_tokens=s.c.spent_tokens
                    + (trace["input_tokens"] or 0)
                    + (trace["output_tokens"] or 0),
                    updated_at=now,
                )
            )
            event(c, row["tenant_id"], b["session_id"], "model_turn_recorded")

    def finish(
        self, row: RowMapping, status: str, error: str | None, *, only_if_stable: bool = False
    ) -> bool:
        with self.engine.begin() as c:
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error is None)
            t = tables.agent_runs
            current = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == row["tenant_id"], t.c.id == row["id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if current["status"] != "running":
                return False
            b = binding(c, row["tenant_id"], row["id"])
            # Same run/session lock order as human input and cancellation. A late
            # human input either participates in this decision or sees a stopped run.
            c.execute(
                select(tables.debate_sessions.c.id)
                .where(
                    tables.debate_sessions.c.tenant_id == row["tenant_id"],
                    tables.debate_sessions.c.id == b["session_id"],
                )
                .with_for_update()
            ).one()
            stop_reason = error or "fixed_rounds_completed"
            from app.ai.discussion_initiation import effective_config
            from app.ai.discussion_initiation import receipt as initiation_receipt

            initiation = initiation_receipt(c, row["tenant_id"], row["id"])
            effective = effective_config(b["config"], initiation)
            if b["config"].get("initiation") and error is None:
                if initiation is None:
                    raise ProductWorkError("尚无发起判断回执，不能宣称讨论完成")
                if initiation["output"]["action"] != "convene":
                    stop_reason = "agent_" + initiation["output"]["action"]
            if error is None and b["config"].get("discussion_policy") == POLICY:
                receipt_table = tables.debate_turn_receipts
                receipts = [
                    _plain(dict(v))
                    for v in c.execute(
                        select(receipt_table).where(
                            receipt_table.c.tenant_id == row["tenant_id"],
                            receipt_table.c.run_id == row["id"],
                        )
                    ).mappings()
                ]
                from app.ai.discussion_research import records as research_records

                assessment = analyze(
                    effective,
                    transcript(c, row["tenant_id"], b["session_id"]),
                    receipts,
                    research_records(c, row["tenant_id"], row["id"]),
                )
                if assessment["can_stop_unchanged"]:
                    stop_reason = "unchanged_full_round"
                elif only_if_stable:
                    return False
            elif only_if_stable:
                return False
            c.execute(
                t.update()
                .where(t.c.id == row["id"])
                .values(
                    status="degraded" if error else "succeeded",
                    error_code=error,
                    completed_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                )
            )
            c.execute(
                tables.debate_sessions.update()
                .where(tables.debate_sessions.c.id == b["session_id"])
                .values(
                    status=status,
                    stop_reason=stop_reason,
                    updated_at=func.clock_timestamp(),
                )
            )
            event(c, row["tenant_id"], b["session_id"], "stopped_" + status)
            return True


def listing(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ecr_id: UUID | None,
    before_id: UUID | None = None,
    focused_run_id: UUID | None = None,
) -> dict[str, Any]:
    authorize(engine, context, project, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        t, b = tables.agent_runs, tables.debate_run_bindings
        query = (
            select(t)
            .join(b, (b.c.tenant_id == t.c.tenant_id) & (b.c.run_id == t.c.id))
            .where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, b.c.ecr_id == ecr_id
            )
        )
        if ecr_id is None:
            query = query.where(t.c.requested_by_user_id == context.user.id)
        if focused_run_id:
            query = query.where(t.c.id == focused_run_id)
            if c.execute(query).first() is None:
                raise ProductWorkError("原讨论不属于此变更或已不可用")
        if before_id:
            before = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
            if before is None:
                raise ProductWorkError("请从原讨论列表继续翻页")
            query = query.where(
                (t.c.created_at < before["created_at"])
                | ((t.c.created_at == before["created_at"]) & (t.c.id < before_id))
            )
        records = (
            c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
            .mappings()
            .all()
        )
        items = []
        for row in records[:20]:
            try:
                require_disclosure(
                    c, context.tenant.id, context.user.id, binding(c, context.tenant.id, row["id"])
                )
            except (ProductWorkError, PermissionError):
                if focused_run_id:
                    raise ProductWorkError("原讨论资料当前不可读取") from None
                continue
            items.append(result(c, row))
        return {
            "items": items,
            "next_before_id": str(records[19]["id"]) if len(records) > 20 else None,
            "can_request": is_allowed(context.user.role, Action.CHANGE_EDIT),
            "actor_id": str(context.user.id),
            "rollout": resolve_capability(KEY).rollout.value,
            "notice_discussion_available": notices.discussion_available(),
            "research_rollout": resolve_capability(
                "engineering_intelligence.discussion_research"
            ).rollout.value,
            "initiation_rollout": resolve_capability(
                "engineering_intelligence.discussion_initiation"
            ).rollout.value,
        }


def detail(engine: Engine, context: AuthContext, project: UUID, run_id: UUID) -> dict[str, Any]:
    authorize(engine, context, project, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        t = tables.agent_runs
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.id == run_id,
                    t.c.context_version == RUN_VERSION,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原讨论不存在或已不可用")
        bound = binding(c, context.tenant.id, run_id)
        require_disclosure(c, context.tenant.id, context.user.id, bound)
        prepared_source = None
        source_error = None
        try:
            prepared_source = current_source(c, context.tenant.id, project, bound)
        except ProductWorkError as error:
            source_error = str(error)
        return {"run": result(c, row), "source": prepared_source, "source_error": source_error}
