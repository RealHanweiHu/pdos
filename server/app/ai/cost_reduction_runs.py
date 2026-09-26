"""Persistent cost analysis with fixed model receipts; business adoption remains separate."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, RowMapping, func, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import resolve_capability
from app.ai.cost_reduction_preparation import (
    PROMPT,
    encoded,
    prompt_for,
    rebuild,
    source_state,
    validate_assessment,
)
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.cost_reduction import CostAssessment, Selection
from app.db.schema import tables
from app.domain.material_exceptions import _authorize
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

KEY = "engineering_intelligence.cost_reduction"
PURPOSE = "cost_reduction"
RUN_VERSION = "cost-reduction-request-v1"


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    with engine.connect() as c:
        _authorize(c, context, project_id, write=action == Action.PRODUCT_ENGINEERING_EDIT)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: Selection
    user_instruction: str = Field(default="", max_length=10000)
    discussion_run_id: UUID | None = None


def model_context(snapshot: dict[str, Any], instruction: str) -> dict[str, Any]:
    context = snapshot["model_context"]
    return {
        "question": context["question"]
        + "\n本次读取覆盖与限制："
        + encoded(
            {
                "coverage_limits": context["coverage_limits"],
                "omitted_references": context["omitted_references"],
            }
        )
        + ("\n本次用户要求：" + instruction if instruction else ""),
        "references": [
            {
                "reference_id": ref["reference_id"],
                "entity": ref["reference_id"].split(":", 1)[0],
                "label": ref["label"],
                "excerpt": encoded({k: ref[k] for k in ("digest", "fields", "omitted_fields")}),
            }
            for ref in context["references"]
        ],
    }


def receipt(row: Any) -> dict[str, Any]:
    output = row["run_context"].get("cost_result")
    reference_labels = {
        r["reference_id"]: r["label"]
        for r in row["run_context"]["cost_source"]["model_context"]["references"]
    }
    return _plain(
        {
            "run_id": row["id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "error_code": row["error_code"],
            "finding_id": row["run_context"].get("cost_finding_id"),
            "invocation_id": row["run_context"].get("cost_invocation_id"),
            "discussion_run_id": row["run_context"].get("cost_discussion_run_id"),
            "reference_labels": reference_labels,
            "assessment": output
            if output and row["run_context"].get("cost_invocation_id")
            else None,
            "missing": output.get("missing", []) if output else [],
            "disposition": output.get("disposition") if output else None,
            "source_digest": row["run_context"]["cost_source"]["digest"],
            "selection": row["run_context"]["cost_selection"],
            "user_instruction": row["run_context"].get("cost_user_instruction", ""),
        }
    )


class CostRuns:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @staticmethod
    def list_results(
        engine: Engine,
        *,
        context: AuthContext,
        project_id: UUID,
        before_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            t = tables.agent_runs
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.context_version == RUN_VERSION,
                t.c.requested_by_user_id == context.user.id,
            )
            if run_id:
                query = query.where(t.c.id == run_id)
            if before_id:
                before = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if before is None:
                    raise ProductWorkError("请从原运行记录继续翻页")
                query = query.where(
                    (t.c.created_at < before["created_at"])
                    | ((t.c.created_at == before["created_at"]) & (t.c.id < before["id"]))
                )
            values = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for row in values[:20]:
                try:
                    current_digest = rebuild(
                        c, context.tenant.id, project_id, row["run_context"]["cost_source"]
                    )["digest"]
                except (ProductWorkError, LookupError, ValueError):
                    current_digest = None
                items.append(
                    {
                        **receipt(row),
                        **(
                            {
                                "frozen_sources": row["run_context"]["cost_source"][
                                    "model_context"
                                ]["references"]
                            }
                            if run_id
                            else {}
                        ),
                        "sources_current": row["run_context"]["cost_source"]["digest"]
                        == current_digest,
                        "requested_by_me": row["requested_by_user_id"] == context.user.id,
                    }
                )
        return {
            "can_request": is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT),
            "rollout": resolve_capability(KEY).rollout.value,
            "prompt_version": PROMPT.version,
            "discussion_rollout": resolve_capability(
                "engineering_intelligence.cost_discussion_followup"
            ).rollout.value,
            "items": items,
            "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
        }

    def create(self, *, context: AuthContext, project_id: UUID, request: Request) -> dict[str, Any]:
        _access(self.engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
        require_live_key(KEY)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
                raise ProductWorkError("项目不可用")
            _access(self.engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
            t = tables.agent_runs
            existing = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.agent_key == "engineering_intelligence",
                        t.c.request_id == str(request.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            body = {
                "cost_selection": request.selection.model_dump(mode="json"),
                "cost_expected_digest": request.expected_digest,
                "cost_user_instruction": request.user_instruction,
                "cost_discussion_run_id": str(request.discussion_run_id)
                if request.discussion_run_id
                else None,
            }
            if existing is not None:
                if (
                    existing["context_version"] != RUN_VERSION
                    or existing["requested_by_user_id"] != context.user.id
                    or any(existing["run_context"].get(k) != v for k, v in body.items())
                ):
                    raise ProductWorkError("本请求已用于其他分析，不能改写原输入")
                if not try_resume(
                    c,
                    self.gateway,
                    existing,
                    actor=context.user.id,
                    auth_version=context.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(existing)
                row, snapshot = existing, existing["run_context"]["cost_source"]
            else:
                snapshot = source_state(
                    c,
                    context.tenant.id,
                    project_id,
                    request.selection,
                    context.user.id,
                    request.discussion_run_id,
                )
                if snapshot["digest"] != request.expected_digest:
                    raise ProductWorkError("分析资料已有变化，请重新读取核对")
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                if request.discussion_run_id is not None:
                    from app.ai.cost_discussion_input import KEY as DISCUSSION_KEY
                    from app.ai.discussion_lineage import parent

                    require_live_key(DISCUSSION_KEY)
                    parent(c, context, project_id, None, request.discussion_run_id)
                    prior_followup = c.execute(
                        select(tables.cost_discussion_inputs.c.run_id).where(
                            tables.cost_discussion_inputs.c.tenant_id == context.tenant.id,
                            tables.cost_discussion_inputs.c.discussion_run_id
                            == request.discussion_run_id,
                        )
                    ).scalar_one_or_none()
                    if prior_followup:
                        raise ProductWorkError(
                            f"此讨论已有成本后续运行，请读取原运行：{prior_followup}"
                        )
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            agent_key="engineering_intelligence",
                            request_id=str(request.request_id),
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
                                **body,
                                "cost_source": snapshot,
                                "cost_output_mode": "reviewable.v1",
                                "cost_prompt_version": prompt_for(snapshot).version,
                                "cost_schema_digest": digest(CostAssessment.model_json_schema()),
                            },
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                freeze_created_application_run(
                    c,
                    self.gateway,
                    tenant_id=context.tenant.id,
                    run_id=row["id"],
                    parent_run_id=request.discussion_run_id,
                    actor_user_id=context.user.id,
                    purpose=PURPOSE,
                    auth_version=context.user.auth_version,
                )
                if request.discussion_run_id is not None:
                    from app.ai.cost_discussion_input import persist

                    persist(
                        c, context.tenant.id, project_id, row["id"], snapshot["discussion_input"]
                    )
        return self._execute(row, snapshot)

    def _execute(self, row: RowMapping, snapshot: dict[str, Any]) -> dict[str, Any]:
        from app.ai.application_domain_context import record, sources_current

        call_id = model_call_id(row["id"], ModelCallSlot.COST_REDUCTION)
        prompt = prompt_for(snapshot)
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call_id,
            agent_key="engineering_intelligence",
            agent_tier=AgentTier.REASONING,
            prompt_version=prompt.version,
            system_prompt=prompt.system_prompt,
            instruction=prompt.instruction,
            context=model_context(snapshot, row["run_context"].get("cost_user_instruction", "")),
        )
        output = None
        invocation_id = None
        error_code = None
        try:
            require_live_key(KEY)
            if snapshot.get("discussion_input"):
                require_live_key("engineering_intelligence.cost_discussion_followup")
            if row["run_context"].get("cost_prompt_version") != prompt.version or row[
                "run_context"
            ].get("cost_schema_digest") != digest(CostAssessment.model_json_schema()):
                raise ProductWorkError("原运行版本已不可用")
            record(
                self.engine,
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                run_id=row["id"],
                model_call_id=call_id,
                purpose=PURPOSE,
                context=invocation.context,
                snapshot=snapshot,
            )
            result = self.gateway.invoke_structured(invocation, CostAssessment)
            if result.status == "degraded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            else:
                validate_assessment(result.output, snapshot)
                if result.invocation_id is None:
                    raise ProductWorkError("模型运行缺少原调用回执")
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("生成期间原资料已变化")
                output, invocation_id = result.output, result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except ProductWorkError:
            error_code = "COST_REDUCTION_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "COST_REDUCTION_EXECUTION_FAILED"
        with self.engine.begin() as c:
            if not lock_project_write_scope(
                c, tenant_id=row["tenant_id"], project_id=row["project_id"]
            ):
                raise ProductWorkError("项目已不可用")
            current = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                        tables.agent_runs.c.id == row["id"],
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if current["status"] != "running":
                return receipt(current)
            try:
                require_live_key(KEY)
                if snapshot.get("discussion_input"):
                    require_live_key("engineering_intelligence.cost_discussion_followup")
            except CapabilityUnavailableError as error:
                output, error_code = None, error.code
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error_code is None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            if output is not None and invocation_id is not None and error_code is None:
                invocation_row = c.execute(
                    select(tables.model_invocations.c.id).where(
                        tables.model_invocations.c.tenant_id == row["tenant_id"],
                        tables.model_invocations.c.project_id == row["project_id"],
                        tables.model_invocations.c.run_id == row["id"],
                        tables.model_invocations.c.id == invocation_id,
                        tables.model_invocations.c.status == "succeeded",
                    )
                ).first()
                if invocation_row is None:
                    output, error_code = None, "COST_REDUCTION_RECEIPT_MISSING"
            finding_id = None
            if (
                output is not None
                and invocation_id is not None
                and error_code is None
                and current["run_context"].get("cost_output_mode") == "reviewable.v1"
            ):
                try:
                    with c.begin_nested():
                        from app.domain.cost_reduction_findings import persist

                        finding_id = persist(
                            c,
                            row=current,
                            snapshot=snapshot,
                            output=output,
                            invocation_id=invocation_id,
                            created_at=now,
                        )
                except (ProductWorkError, ValueError):
                    error_code = "COST_REDUCTION_CANDIDATE_INVALID"
            # Preserve independently recorded run control and context history.
            current_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == row["tenant_id"],
                    tables.agent_runs.c.id == row["id"],
                )
            ).scalar_one()
            saved = (
                c.execute(
                    tables.agent_runs.update()
                    .where(
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                        tables.agent_runs.c.id == row["id"],
                    )
                    .values(
                        status="degraded" if error_code else "succeeded",
                        error_code=error_code,
                        completed_at=now,
                        updated_at=now,
                        run_context={
                            **current_context,
                            "cost_result": output.model_dump(mode="json") if output else None,
                            "cost_finding_id": str(finding_id) if finding_id else None,
                            "cost_invocation_id": str(invocation_id) if invocation_id else None,
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
