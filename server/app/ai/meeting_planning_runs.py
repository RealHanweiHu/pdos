"""Budgeted ad-hoc meeting planning with fixed source and successful model receipts."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, and_, func, or_, select

from app.ai.application_domain_context import record
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import CapabilityRollout, resolve_capability
from app.ai.gateway import GatewayInvocation
from app.ai.meeting_planning_context import (
    PROMPT,
    bound_source,
    fixed_context,
    model_context,
)
from app.ai.model_catalog import AgentTier
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.contracts.meeting_plan import (
    CAPABILITY,
    FINDING_TYPE,
    PURPOSE,
    RUN_VERSION,
    MeetingAssessment,
    materialize,
)
from app.db.schema import tables
from app.domain.meeting_planning import authorize_sources
from app.domain.meeting_recurrence_commands import authorize
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class MeetingPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def receipt(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "project_id",
                "status",
                "error_code",
                "request_id",
                "created_at",
                "completed_at",
            )
        }
    ) | {
        "brief_id": row["run_context"]["meeting_planning_brief_id"],
        "source_digest": row["run_context"]["meeting_planning_source_digest"],
        "finding_id": row["run_context"].get("meeting_planning_finding_id"),
    }


def brief(c: Connection, ctx: AuthContext, project: UUID, identity: UUID) -> RowMapping:
    t = tables.meeting_planning_briefs
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.id == identity,
                t.c.created_by_user_id == ctx.user.id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingStateError("会议起草要求不属于本人的当前项目")
    return row


def generation_state() -> dict[str, Any]:
    enabled = resolve_capability(CAPABILITY).rollout == CapabilityRollout.LIVE
    return {
        "generation_available": enabled,
        "generation_message": "可请求AI会议起草，建议须后续人工核对并独立应用。"
        if enabled
        else "AI起草尚未开放；保存要求不会排队或调用模型，已有来源及运行记录保留。",
    }


def run_view(c: Connection, ctx: AuthContext, run: Any) -> dict[str, Any]:
    enabled = generation_state()["generation_available"]
    current = True
    try:
        bound_source(c, ctx.tenant.id, run["project_id"], ctx.user.id, run["run_context"])
    except Exception:
        current = False
    value = receipt(run) | {
        "source_current": current,
        "source_people": {
            p["id"]: p["display_name"]
            for p in run["run_context"]["meeting_planning_source"]["participants"]
        },
    }
    fid = run["run_context"].get("meeting_planning_finding_id")
    if fid and enabled:
        f = (
            c.execute(
                select(tables.findings).where(
                    tables.findings.c.tenant_id == ctx.tenant.id,
                    tables.findings.c.id == UUID(fid),
                    tables.findings.c.run_id == run["id"],
                    tables.findings.c.finding_type == FINDING_TYPE,
                )
            )
            .mappings()
            .one_or_none()
        )
        if f is not None:
            value["finding"] = _plain(f)
    if enabled and run["run_context"].get("meeting_planning_reading"):
        value["reading"] = run["run_context"]["meeting_planning_reading"]
    return value


class MeetingPlanningRuns:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway | None = None):
        self.engine, self.gateway = engine, gateway

    def list(
        self, ctx: AuthContext, project: UUID, identity: UUID, before: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize_sources(c, ctx, project)
            original = brief(c, ctx, project, identity)
            r = tables.agent_runs
            q = select(r).where(
                r.c.tenant_id == ctx.tenant.id,
                r.c.project_id == project,
                r.c.requested_by_user_id == ctx.user.id,
                r.c.context_version == RUN_VERSION,
                r.c.run_context["meeting_planning_root_brief_id"].as_string()
                == str(original["root_id"]),
            )
            if before:
                anchor = c.execute(q.where(r.c.id == before)).mappings().one_or_none()
                if anchor is None:
                    raise MeetingStateError("原运行游标不可用，请重新读取")
                q = q.where(
                    or_(
                        r.c.created_at < anchor["created_at"],
                        and_(r.c.created_at == anchor["created_at"], r.c.id < anchor["id"]),
                    )
                )
            runs = list(
                c.execute(q.order_by(r.c.created_at.desc(), r.c.id.desc()).limit(31)).mappings()
            )
            items = []
            for run in runs[:30]:
                items.append(run_view(c, ctx, run))
            return {
                "items": items,
                "next_before": str(runs[29]["id"]) if len(runs) > 30 else None,
                **generation_state(),
            }

    def create(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: MeetingPlanningRequest
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        gateway = self.gateway
        if gateway is None:
            raise MeetingStateError("模型运行网关未配置")
        with self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise MeetingStateError("项目不存在")
            authorize(c, ctx, project, write=True)
            authorize_sources(c, ctx, project)
            original = brief(c, ctx, project, identity)
            if original["source_digest"] != body.expected_source_digest:
                raise MeetingStateError("会议起草来源已变化，请重新核对")
            r = tables.agent_runs
            prior = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == original["project_id"],
                        r.c.agent_key == "knowledge_lite",
                        r.c.request_id == str(body.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if (
                    prior["context_version"] != RUN_VERSION
                    or prior["requested_by_user_id"] != ctx.user.id
                    or prior["run_context"].get("meeting_planning_brief_id") != str(identity)
                    or prior["run_context"].get("meeting_planning_source_digest")
                    != body.expected_source_digest
                ):
                    raise MeetingStateError("此运行请求已对应其他会议起草要求")
                if not try_resume(
                    c,
                    gateway,
                    prior,
                    actor=ctx.user.id,
                    auth_version=ctx.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(prior)
                run = prior
            else:
                rc = fixed_context(original)
                bound_source(c, ctx.tenant.id, original["project_id"], ctx.user.id, rc)
                if getattr(gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                parent = (
                    c.execute(
                        select(r)
                        .where(
                            r.c.tenant_id == ctx.tenant.id,
                            r.c.project_id == original["project_id"],
                            r.c.context_version == RUN_VERSION,
                            r.c.requested_by_user_id == ctx.user.id,
                            r.c.run_context["meeting_planning_root_brief_id"].as_string()
                            == str(original["root_id"]),
                        )
                        .order_by(r.c.created_at.desc(), r.c.id.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if parent is not None:
                    if parent["status"] == "running":
                        raise MeetingStateError("原要求仍在运行，请查看已有运行或停止")
                    from app.ai.run_progress import _budget

                    budget = _budget(
                        c,
                        ctx.tenant.id,
                        parent["id"],
                        c.execute(select(func.clock_timestamp())).scalar_one(),
                    )
                    if budget is None:
                        raise BudgetLedgerError("BUDGET_PARENT_RUN_UNBOUND")
                    if budget.unresolved_calls:
                        raise MeetingStateError("原要求尚有未结算或结果未知的调用，请先核对原运行")
                    if budget.remaining_tokens <= 0:
                        raise MeetingStateError("原要求累计额度已用尽，修订来源不会重置预算")
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                run = (
                    c.execute(
                        r.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=ctx.tenant.id,
                            project_id=original["project_id"],
                            scope_kind="project",
                            agent_key="knowledge_lite",
                            request_id=str(body.request_id),
                            requested_by_user_id=ctx.user.id,
                            status="running",
                            event_count=0,
                            event_row_ids=[],
                            window_started_at=now,
                            window_ended_at=now,
                            context_version=RUN_VERSION,
                            run_context=rc,
                            started_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                        .returning(r)
                    )
                    .mappings()
                    .one()
                )
                freeze_created_application_run(
                    c,
                    gateway,
                    tenant_id=ctx.tenant.id,
                    run_id=run["id"],
                    parent_run_id=parent["id"] if parent else None,
                    actor_user_id=ctx.user.id,
                    purpose=PURPOSE,
                    auth_version=ctx.user.auth_version,
                )
        return self.execute(ctx, run)

    def execute(self, ctx: AuthContext, run: RowMapping) -> dict[str, Any]:
        gateway = self.gateway
        if gateway is None:
            raise MeetingStateError("模型运行网关未配置")
        source = run["run_context"]["meeting_planning_source"]
        call = model_call_id(run["id"], ModelCallSlot.MEETING_PLANNING)
        output, payload, invocation_id, error_code = None, None, None, None
        try:
            require_live_key(CAPABILITY)
            with self.engine.connect() as c:
                bound_source(c, ctx.tenant.id, run["project_id"], ctx.user.id, run["run_context"])
            context = model_context(source)
            record(
                self.engine,
                tenant_id=ctx.tenant.id,
                project_id=run["project_id"],
                run_id=run["id"],
                model_call_id=call,
                purpose=PURPOSE,
                context=context,
                snapshot=source,
            )
            result = gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=ctx.tenant.id,
                    project_id=run["project_id"],
                    run_id=run["id"],
                    model_call_id=call,
                    agent_key="knowledge_lite",
                    agent_tier=AgentTier.REASONING,
                    prompt_version=PROMPT.version,
                    system_prompt=PROMPT.system_prompt,
                    instruction=PROMPT.instruction,
                    context=context,
                ),
                MeetingAssessment,
            )
            if (
                result.status != "succeeded"
                or result.output is None
                or result.invocation_id is None
            ):
                error_code = result.error_code or "MEETING_PLANNING_MODEL_UNAVAILABLE"
            else:
                output = result.output.model_dump(mode="json")
                payload = materialize(source, result.output)
                invocation_id = result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except (MeetingStateError, ValueError):
            error_code = "MEETING_PLANNING_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "MEETING_PLANNING_EXECUTION_FAILED"
        with self.engine.begin() as c:
            lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=run["project_id"])
            r = tables.agent_runs
            current = (
                c.execute(
                    select(r)
                    .where(r.c.tenant_id == ctx.tenant.id, r.c.id == run["id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if current["status"] != "running":
                return receipt(current)
            finding_id = None
            try:
                with c.begin_nested():
                    if not error_code and payload is not None and invocation_id is not None:
                        require_live_key(CAPABILITY)
                        bound_source(
                            c, ctx.tenant.id, run["project_id"], ctx.user.id, current["run_context"]
                        )
                        bind_write(c, gateway, ctx.tenant.id, run["id"])
                        if payload["assessment"]["plan"] is not None:
                            if not FindingQualityService.is_output_allowed_connection(
                                c,
                                tenant_id=ctx.tenant.id,
                                agent_key="knowledge_lite",
                                finding_type=FINDING_TYPE,
                            ):
                                raise BudgetLedgerError("MEETING_PLANNING_OUTPUT_NARROWED")
                            finding_id = uuid4()
                            c.execute(
                                tables.findings.insert().values(
                                    id=finding_id,
                                    tenant_id=ctx.tenant.id,
                                    project_id=run["project_id"],
                                    run_id=run["id"],
                                    model_invocation_id=invocation_id,
                                    agent_key="knowledge_lite",
                                    finding_type=FINDING_TYPE,
                                    origin_key=f"meeting-plan:{run['run_context']['meeting_planning_root_brief_id']}",
                                    status="pending_review",
                                    title="临时会议起草建议",
                                    summary="议题、参会与产出均待人工核对，接受后另行确认创建会议。",
                                    proposed_payload={
                                        "brief_id": source["brief_id"],
                                        "assessment": output,
                                        **payload,
                                    },
                                    evidence_event_ids=[],
                                    confidence_basis_points=0,
                                    preflight_version="meeting-planning-preflight.v1",
                                )
                            )
                            EventAuditWriter(
                                c,
                                tenant_id=ctx.tenant.id,
                                actor_user_id=ctx.user.id,
                                project_id=run["project_id"],
                            ).record(
                                EventDraft(
                                    event_id=f"meeting-planning-finding:{finding_id}:created",
                                    event_type="MEETING_PLAN_FINDING_RECORDED",
                                    source="meeting_service",
                                    entity_id=finding_id,
                                    payload={"finding_id": str(finding_id), "action": "created"},
                                ),
                                AuditDraft(
                                    action="meeting_planning_ai_finding.created",
                                    after_snapshot={
                                        "finding_id": str(finding_id),
                                        "run_id": str(run["id"]),
                                    },
                                ),
                            )
            except (BudgetLedgerError, CapabilityUnavailableError) as error:
                error_code, finding_id = error.code, None
            except Exception:
                error_code, finding_id = "MEETING_PLANNING_RESULT_SAVE_FAILED", None
            bind_write(c, gateway, ctx.tenant.id, run["id"], success=error_code is None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    r.update()
                    .where(r.c.id == run["id"])
                    .values(
                        status="degraded" if error_code else "succeeded",
                        error_code=error_code,
                        completed_at=now,
                        updated_at=now,
                        run_context={
                            **current["run_context"],
                            "meeting_planning_finding_id": str(finding_id) if finding_id else None,
                            "meeting_planning_reading": payload
                            if not error_code and finding_id is None
                            else None,
                        },
                    )
                    .returning(r)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
