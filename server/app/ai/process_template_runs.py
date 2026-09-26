"""Budgeted organization configuration suggestions; model output creates only a Finding."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai.application_domain_context import record
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.process_template_context import (
    PROMPT_VERSION,
    PURPOSE,
    RUN_VERSION,
    bound_source,
    model_context,
    prompt_data,
    root_brief_id,
)
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.contracts.process_template_proposal import output_type
from app.db.schema import tables
from app.domain.process_template_briefs import brief
from app.domain.process_template_configuration import Input
from app.domain.process_template_findings import CAPABILITY, FINDING_TYPE, event, payload
from app.domain.process_templates import authorize, lock
from app.domain.product_workspace import _plain, digest
from app.domain.project_templates import ProjectTemplateError


class Request(Input):
    request_id: UUID
    expected_source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def receipt(row: RowMapping) -> dict[str, Any]:
    return _plain(
        {
            "id": row["id"],
            "status": row["status"],
            "error_code": row["error_code"],
            "request_id": row["request_id"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "requested_by_user_id": row["requested_by_user_id"],
            "brief_id": row["run_context"]["process_template_brief_id"],
            "finding_id": row["run_context"].get("process_template_finding_id"),
        }
    )


def run_row(c: Connection, ctx: AuthContext, identity: UUID) -> RowMapping:
    authorize(c, ctx)
    r = tables.agent_runs
    row = (
        c.execute(
            select(r).where(
                r.c.tenant_id == ctx.tenant.id,
                r.c.id == identity,
                r.c.scope_kind == "tenant",
                r.c.context_version == RUN_VERSION,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProjectTemplateError("组织配置生成记录不存在")
    return row


class ProcessTemplateRunService:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def create(self, ctx: AuthContext, identity: UUID, body: Request) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            original = brief(c, ctx, identity)
            lock(c, ctx, original["template_id"])
            if body.expected_source_digest != original["source_digest"]:
                raise ProjectTemplateError("原管理要求已变化，请重新读取")
            source = {
                "process_template_brief_id": str(identity),
                "process_template_root_brief_id": str(root_brief_id(c, ctx.tenant.id, identity)),
                "process_template_source_digest": original["source_digest"],
                "process_template_source": original["source_snapshot"],
                "process_template_prompt_version": PROMPT_VERSION,
                "process_template_schema_digest": digest(
                    output_type(PROMPT_VERSION).model_json_schema()
                ),
            }
            r = tables.agent_runs
            prior = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.scope_kind == "tenant",
                        r.c.agent_key == "knowledge_lite",
                        r.c.request_id == str(body.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["requested_by_user_id"] != ctx.user.id or any(
                    prior["run_context"].get(key) != value
                    for key, value in source.items()
                    if key
                    not in {"process_template_prompt_version", "process_template_schema_digest"}
                ):
                    raise ProjectTemplateError("此生成请求已对应其他原始要求或版本")
                if not try_resume(
                    c,
                    self.gateway,
                    prior,
                    actor=ctx.user.id,
                    auth_version=ctx.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(prior)
                row = prior
            else:
                bound_source(c, ctx.tenant.id, source)
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                parent = (
                    c.execute(
                        select(r)
                        .where(
                            r.c.tenant_id == ctx.tenant.id,
                            r.c.scope_kind == "tenant",
                            r.c.context_version == RUN_VERSION,
                            r.c.run_context["process_template_root_brief_id"].as_string()
                            == source["process_template_root_brief_id"],
                        )
                        .order_by(r.c.created_at.desc(), r.c.id.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if parent is not None and parent["status"] == "running":
                    raise ProjectTemplateError("原要求仍在生成，请先查看已有运行记录")
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    c.execute(
                        r.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=ctx.tenant.id,
                            project_id=None,
                            scope_kind="tenant",
                            agent_key="knowledge_lite",
                            request_id=str(body.request_id),
                            requested_by_user_id=ctx.user.id,
                            status="running",
                            event_count=0,
                            event_row_ids=[],
                            window_started_at=now,
                            window_ended_at=now,
                            context_version=RUN_VERSION,
                            started_at=now,
                            created_at=now,
                            updated_at=now,
                            run_context=source,
                        )
                        .returning(r)
                    )
                    .mappings()
                    .one()
                )
                freeze_created_application_run(
                    c,
                    self.gateway,
                    tenant_id=ctx.tenant.id,
                    run_id=row["id"],
                    parent_run_id=parent["id"] if parent else None,
                    actor_user_id=ctx.user.id,
                    purpose=PURPOSE,
                    auth_version=ctx.user.auth_version,
                )
        return self.execute(ctx, row)

    def execute(self, ctx: AuthContext, run: RowMapping) -> dict[str, Any]:
        source = run["run_context"]["process_template_source"]
        call = model_call_id(run["id"], ModelCallSlot.PROCESS_TEMPLATE)
        output, invocation_id, error_code = None, None, None
        try:
            require_live_key(CAPABILITY)
            version = run["run_context"]["process_template_prompt_version"]
            prompt = prompt_data(version)
            schema = output_type(version)
            if run["run_context"].get("process_template_schema_digest") != digest(
                schema.model_json_schema()
            ):
                raise BudgetLedgerError("PROCESS_TEMPLATE_CONTRACT_CHANGED")
            context = model_context(source, version)
            record(
                self.engine,
                tenant_id=ctx.tenant.id,
                project_id=None,
                run_id=run["id"],
                model_call_id=call,
                purpose=PURPOSE,
                context=context,
                snapshot=source,
            )
            result = self.gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=ctx.tenant.id,
                    project_id=None,
                    run_id=run["id"],
                    model_call_id=call,
                    agent_key="knowledge_lite",
                    agent_tier=AgentTier.REASONING,
                    prompt_version=version,
                    system_prompt=prompt["system_prompt"],
                    instruction=prompt["instruction"],
                    context=context,
                ),
                schema,
            )
            if (
                result.status != "succeeded"
                or result.output is None
                or result.invocation_id is None
            ):
                error_code = result.error_code or "PROCESS_TEMPLATE_MODEL_UNAVAILABLE"
            else:
                output = payload(source, result.output)
                invocation_id = result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except (ProjectTemplateError, ValueError):
            error_code = "PROCESS_TEMPLATE_OUTPUT_INVALID"
        except Exception:
            error_code = "PROCESS_TEMPLATE_EXECUTION_FAILED"
        with self.engine.begin() as c:
            lock(c, ctx, source["template_id"])
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
                    if not error_code and output is not None and invocation_id is not None:
                        require_live_key(CAPABILITY)
                        bound_source(c, ctx.tenant.id, current["run_context"])
                        bind_write(c, self.gateway, ctx.tenant.id, run["id"])
                        if not FindingQualityService.is_output_allowed_connection(
                            c,
                            tenant_id=ctx.tenant.id,
                            agent_key="knowledge_lite",
                            finding_type=FINDING_TYPE,
                        ):
                            raise BudgetLedgerError("PROCESS_TEMPLATE_OUTPUT_NARROWED")
                        finding_id = uuid4()
                        f = (
                            c.execute(
                                tables.findings.insert()
                                .values(
                                    id=finding_id,
                                    tenant_id=ctx.tenant.id,
                                    project_id=None,
                                    scope_kind="tenant",
                                    run_id=run["id"],
                                    model_invocation_id=invocation_id,
                                    agent_key="knowledge_lite",
                                    finding_type=FINDING_TYPE,
                                    origin_key=f"process-template:{source['id']}",
                                    status="pending_review",
                                    title="组织流程配置建议",
                                    summary=output["assessment"]["summary"],
                                    proposed_payload=output,
                                    evidence_event_ids=[],
                                    confidence_basis_points=0,
                                    preflight_version="process-template-preflight.v1",
                                )
                                .returning(tables.findings)
                            )
                            .mappings()
                            .one()
                        )
                        event(c, ctx, f, "created")
            except (BudgetLedgerError, CapabilityUnavailableError) as error:
                error_code, finding_id = error.code, None
            except Exception:
                error_code, finding_id = "PROCESS_TEMPLATE_PUBLICATION_FAILED", None
            bind_write(c, self.gateway, ctx.tenant.id, run["id"], success=error_code is None)
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
                            "process_template_finding_id": str(finding_id) if finding_id else None,
                        },
                    )
                    .returning(r)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
