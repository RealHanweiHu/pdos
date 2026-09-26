"""Budgeted private intake organization with immutable source and successful model receipts."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai.application_domain_context import record
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import CapabilityRollout, resolve_capability
from app.ai.gateway import GatewayInvocation
from app.ai.intake_ai_context import (
    CAPABILITY,
    FINDING_TYPE,
    PROMPT,
    PURPOSE,
    RUN_VERSION,
    bound_source,
    model_context,
)
from app.ai.model_catalog import AgentTier
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.contracts.intake_proposal import IntakeOrganization, materialize
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.intake_ai_sources import IntakeAiSources
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class IntakeRunRequest(BaseModel):
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
        "brief_id": row["run_context"]["intake_brief_id"],
        "source_digest": row["run_context"]["intake_source_digest"],
        "finding_id": row["run_context"].get("intake_finding_id"),
    }


def brief(c: Connection, ctx: AuthContext, conversation: UUID, identity: UUID) -> RowMapping:
    t = tables.intake_ai_briefs
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.conversation_id == conversation,
                t.c.id == identity,
                t.c.created_by_user_id == ctx.user.id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConversationError("整理要求不属于本人的当前会话")
    return row


def generation_state() -> dict[str, Any]:
    enabled = resolve_capability(CAPABILITY).rollout == CapabilityRollout.LIVE
    return {
        "generation_available": enabled,
        "generation_message": "可请求AI整理，建议须后续人工核对并独立应用。"
        if enabled
        else "AI整理尚未开放；保存要求不会排队或调用模型，已有来源及运行记录保留。",
    }


class IntakeAiRuns:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway | None = None):
        self.engine, self.gateway = engine, gateway
        self.scope = IntakeAiSources(engine).scope

    def list(self, ctx: AuthContext, conversation: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            original = brief(c, ctx, conversation, identity)
            r = tables.agent_runs
            runs = list(
                c.execute(
                    select(r)
                    .where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == original["project_id"],
                        r.c.requested_by_user_id == ctx.user.id,
                        r.c.context_version == RUN_VERSION,
                        r.c.run_context["intake_root_brief_id"].as_string()
                        == str(original["root_brief_id"]),
                    )
                    .order_by(r.c.created_at.desc(), r.c.id.desc())
                    .limit(31)
                ).mappings()
            )
            items = []
            enabled = generation_state()["generation_available"]
            for run in runs[:30]:
                current = True
                try:
                    bound_source(
                        c, ctx.tenant.id, run["project_id"], ctx.user.id, run["run_context"]
                    )
                except Exception:
                    current = False
                value = receipt(run) | {"source_current": current}
                fid = run["run_context"].get("intake_finding_id")
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
                if enabled and run["run_context"].get("intake_reading"):
                    value["reading"] = run["run_context"]["intake_reading"]
                items.append(value)
            return {"items": items, "truncated": len(runs) > 30, **generation_state()}

    def create(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: IntakeRunRequest
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        gateway = self.gateway
        if gateway is None:
            raise ConversationError("模型运行网关未配置")
        with self.engine.begin() as c:
            self.scope.scope(c, ctx, conversation, write=True)
            original = brief(c, ctx, conversation, identity)
            if original["source_digest"] != body.expected_source_digest:
                raise ConversationError("整理来源已变化，请重新核对")
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
                    or prior["run_context"].get("intake_brief_id") != str(identity)
                    or prior["run_context"].get("intake_source_digest")
                    != body.expected_source_digest
                ):
                    raise ConversationError("此运行请求已对应其他整理要求")
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
                rc = {
                    "intake_brief_id": str(identity),
                    "intake_root_brief_id": str(original["root_brief_id"]),
                    "intake_source_digest": original["source_digest"],
                    "intake_source": {"brief_id": str(identity), **original["source_snapshot"]},
                    "intake_prompt_version": PROMPT.version,
                    "intake_prompt_digest": digest(PROMPT.model_dump(mode="json")),
                    "intake_schema_digest": digest(IntakeOrganization.model_json_schema()),
                }
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
                            r.c.run_context["intake_root_brief_id"].as_string()
                            == str(original["root_brief_id"]),
                        )
                        .order_by(r.c.created_at.desc(), r.c.id.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if parent is not None:
                    if parent["status"] == "running":
                        raise ConversationError("原要求仍在运行，请查看已有运行或停止")
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
                        raise ConversationError("原要求尚有未结算或结果未知的调用，请先核对原运行")
                    if budget.remaining_tokens <= 0:
                        raise ConversationError("原要求累计额度已用尽，修订来源不会重置预算")
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
            raise ConversationError("模型运行网关未配置")
        source = run["run_context"]["intake_source"]
        call = model_call_id(run["id"], ModelCallSlot.INTAKE_ORGANIZATION)
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
                IntakeOrganization,
            )
            if (
                result.status != "succeeded"
                or result.output is None
                or result.invocation_id is None
            ):
                error_code = result.error_code or "INTAKE_MODEL_UNAVAILABLE"
            else:
                output = result.output.model_dump(mode="json")
                payload = materialize(source, result.output)
                invocation_id = result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except (ConversationError, ValueError):
            error_code = "INTAKE_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "INTAKE_EXECUTION_FAILED"
        with self.engine.begin() as c:
            # Source revoke/archive and publication share the original conversation lock.
            b = tables.intake_ai_briefs
            conversation = c.execute(
                select(b.c.conversation_id).where(
                    b.c.tenant_id == ctx.tenant.id,
                    b.c.id == UUID(source["brief_id"]),
                )
            ).scalar_one()
            c.execute(
                select(tables.conversations.c.id)
                .where(
                    tables.conversations.c.tenant_id == ctx.tenant.id,
                    tables.conversations.c.id == conversation,
                )
                .with_for_update()
            ).scalar_one()
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
                        if payload["proposals"]:
                            if not FindingQualityService.is_output_allowed_connection(
                                c,
                                tenant_id=ctx.tenant.id,
                                agent_key="knowledge_lite",
                                finding_type=FINDING_TYPE,
                            ):
                                raise BudgetLedgerError("INTAKE_OUTPUT_NARROWED")
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
                                    origin_key=f"intake:{source['brief_id']}",
                                    status="pending_review",
                                    title="导入资料整理建议",
                                    summary=f"整理出{len(payload['proposals'])}项待核对建议，原文及缺项保留。",
                                    proposed_payload={
                                        "brief_id": source["brief_id"],
                                        "assessment": output,
                                        **payload,
                                    },
                                    evidence_event_ids=[],
                                    confidence_basis_points=0,
                                    preflight_version="intake-preflight.v1",
                                )
                            )
                            EventAuditWriter(
                                c,
                                tenant_id=ctx.tenant.id,
                                actor_user_id=ctx.user.id,
                                project_id=run["project_id"],
                            ).record(
                                EventDraft(
                                    event_id=f"intake-finding:{finding_id}:created",
                                    event_type="INTAKE_AI_FINDING_RECORDED",
                                    source="intake_ai_service",
                                    entity_id=finding_id,
                                    payload={"finding_id": str(finding_id), "action": "created"},
                                ),
                                AuditDraft(
                                    action="intake_ai_finding.created",
                                    after_snapshot={
                                        "finding_id": str(finding_id),
                                        "run_id": str(run["id"]),
                                    },
                                ),
                            )
            except (BudgetLedgerError, CapabilityUnavailableError) as error:
                error_code, finding_id = error.code, None
            except Exception:
                error_code, finding_id = "INTAKE_RESULT_SAVE_FAILED", None
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
                            "intake_finding_id": str(finding_id) if finding_id else None,
                            "intake_reading": payload
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
