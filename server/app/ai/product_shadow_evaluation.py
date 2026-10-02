"""Admin-requested, source-bound product evaluation; no employee candidates or qualification.

The application gateway owns model admission, current authority, metering and
durable call fencing. Reference answers stay outside the provider execution path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai import product_matrix_preparation as matrix
from app.ai import product_work_context as work
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.capability_contract import CapabilityRollout, resolve_capability
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import PROVIDER_SPECS, AgentTier, ProviderName
from app.ai.product_evaluation import (
    Capability,
    LoadedProductSuite,
    ProductEvaluationBinding,
    ProductEvaluationRequest,
    ProductEvaluationResponse,
    ProductEvaluationSuite,
    canonical,
    digest,
    run_product_evaluation,
    runtime_contract,
    strict_object,
)
from app.ai.product_evidence_context import validate_refs
from app.ai.product_work_preparation import source_state as work_source
from app.ai.project_discussion_sources import actor
from app.ai.provider_adapters import ProviderRequestError, ProviderUsage
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.product_matrix_explanation import (
    MatrixExplanationSelection,
    ProductMatrixExplanation,
)
from app.contracts.product_work_ai import ProductWorkAssessment, ProductWorkSelection
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, _space

PURPOSE = "product_evaluation"
RUN_VERSION = "product-evaluation-request-v1"


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Capability
    work: ProductWorkSelection | None = None
    matrix: MatrixExplanationSelection | None = None

    @model_validator(mode="after")
    def supported(self) -> Selection:
        if self.capability == "product_matrix":
            if self.matrix is None or self.work is not None:
                raise ValueError("matrix evaluation requires a matrix selection")
        elif (
            self.work is None or self.matrix is not None or self.work.capability != self.capability
        ):
            raise ValueError("work evaluation requires its matching capability selection")
        return self


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    case_id: str = Field(min_length=1, max_length=128)
    suite_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: Selection
    binding: ProductEvaluationBinding
    user_instruction: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def model_route(self) -> Request:
        provider = ProviderName(self.binding.provider)
        if (
            next(s.protocol.value for s in PROVIDER_SPECS if s.name == provider)
            != self.binding.protocol
        ):
            raise ValueError("evaluation provider protocol mismatch")
        return self


def authorize(c: Connection, context: AuthContext, space_id: UUID) -> None:
    if not is_allowed(context.user.role, Action.MODEL_GOVERNANCE_MANAGE):
        raise ProductWorkAccessError("产品影子评测仅允许当前租户模型管理员办理")
    _space(c, context, space_id)


def require_enabled(capability: str) -> None:
    contract = resolve_capability(f"product_management_intelligence.{capability}")
    if contract.rollout is CapabilityRollout.DISABLED:
        raise CapabilityUnavailableError("CAPABILITY_DISABLED")


def source(
    c: Connection, context: AuthContext, space_id: UUID, selection: Selection
) -> dict[str, Any]:
    authorize(c, context, space_id)
    require_enabled(selection.capability)
    if selection.matrix is not None:
        return matrix.source_state(c, context, space_id, selection.matrix)
    assert selection.work is not None
    return work_source(c, context, space_id, selection.work)


def readable(
    c: Connection, context: AuthContext, snapshot: dict[str, Any], capability: str
) -> None:
    authorize(c, context, UUID(snapshot["market_space_id"]))
    if capability == "product_matrix":
        matrix.readable(c, context, snapshot)
    else:
        work.readable(c, context, snapshot)


def context_for(snapshot: dict[str, Any], body: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
    capability = body["selection"]["capability"]
    instruction = body["user_instruction"]
    if capability == "product_matrix":
        return matrix.model_context(snapshot, instruction)
    prompt, _ = work.contract(capability=capability)
    return work.model_context(
        snapshot, instruction, prompt_version=prompt.version, tenant_id=tenant_id
    )


def current(c: Connection, row: Any, invocation: Any | None = None) -> bool:
    body = row["run_context"]["evaluation_input"]
    capability = body["selection"]["capability"]
    snapshot = row["run_context"]["evaluation_source"]
    require_enabled(capability)
    context = actor(c, row["tenant_id"], row["requested_by_user_id"])
    readable(c, context, snapshot, capability)
    _, _, runtime = runtime_contract(capability)
    rebuild = matrix.rebuild if capability == "product_matrix" else work.rebuild
    return bool(
        row["context_version"] == RUN_VERSION
        and row["scope_kind"] == "market_space"
        and row["project_id"] is None
        and digest(runtime) == body["runtime_sha256"]
        and rebuild(c, row["tenant_id"], snapshot)["digest"] == body["expected_digest"]
        and digest(snapshot) == body["source_sha256"]
        and (
            invocation is None
            or (
                invocation.project_id is None
                and invocation.prompt_version == row["run_context"]["evaluation_prompt_version"]
                and invocation.context == context_for(snapshot, body, row["tenant_id"])
            )
        )
    )


def run_row(c: Connection, context: AuthContext, space_id: UUID, run_id: UUID) -> Any:
    authorize(c, context, space_id)
    row = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                tables.agent_runs.c.market_space_id == space_id,
                tables.agent_runs.c.context_version == RUN_VERSION,
                tables.agent_runs.c.requested_by_user_id == context.user.id,
                tables.agent_runs.c.id == run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("影子评测记录不存在或不属于当前发起人")
    readable(
        c,
        context,
        row["run_context"]["evaluation_source"],
        row["run_context"]["evaluation_input"]["selection"]["capability"],
    )
    return row


def receipt(row: Any) -> dict[str, Any]:
    rc = row["run_context"]
    return _plain(
        dict(
            run_id=row["id"],
            status=row["status"],
            error_code=row["error_code"],
            execution_plane="shadow_evaluation",
            input=rc["evaluation_input"],
            assessment=rc.get("evaluation_result"),
            invocation_id=rc.get("evaluation_invocation_id"),
            qualification_granted=False,
            business_actions_created=False,
        )
    )


class ProductShadowEvaluation:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway | None = None) -> None:
        self.engine, self.gateway = engine, gateway

    def prepare(self, context: AuthContext, space_id: UUID, selection: Selection) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            snapshot = source(c, context, space_id, selection)
            prompt, _, runtime = runtime_contract(selection.capability)
            return dict(
                source=snapshot,
                source_sha256=digest(snapshot),
                expected_digest=snapshot["digest"],
                runtime_sha256=digest(runtime),
                prompt_version=prompt.version,
                qualification_granted=False,
            )

    def read(self, context: AuthContext, space_id: UUID, run_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            row = run_row(c, context, space_id, run_id)
            return {**receipt(row), "frozen_source": row["run_context"]["evaluation_source"]}

    def evaluate(
        self,
        context: AuthContext,
        space_id: UUID,
        loaded: LoadedProductSuite,
        binding: ProductEvaluationBinding,
        evaluation_id: UUID,
    ) -> dict[str, Any]:
        import json
        from hashlib import sha256

        from app.ai.product_evaluation import MAX_SUITE_BYTES

        if (
            len(loaded.document) > MAX_SUITE_BYTES
            or sha256(loaded.document).hexdigest() != loaded.sha256
        ):
            raise ProductWorkError("评测原文件摘要不符或超过上限")
        suite = ProductEvaluationSuite.model_validate(
            json.loads(loaded.document, object_pairs_hook=strict_object)
        )
        # This mapping contains only execution inputs, never the reference answers.
        inputs: dict[str, Request] = {}
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            for case in suite.cases:
                if case.tenant_id != context.tenant.id:
                    raise ProductWorkAccessError("评测材料不属于当前租户")
                if case.source["market_space_id"] != str(space_id):
                    raise ProductWorkError("评测样例须全部属于本次市场空间")
                selected = Selection.model_validate(
                    dict(
                        capability=suite.capability,
                        **{
                            "matrix"
                            if suite.capability == "product_matrix"
                            else "work": case.source["selection"]
                        },
                    )
                )
                actual = source(c, context, UUID(case.source["market_space_id"]), selected)
                if actual != case.source or digest(actual) != case.source_sha256:
                    raise ProductWorkError("评测材料与当前授权来源不一致，请重新核对全部样例")
                inputs[case.case_id] = Request(
                    request_id=uuid5(evaluation_id, case.case_id),
                    case_id=case.case_id,
                    suite_sha256=loaded.sha256,
                    runtime_sha256=suite.runtime_sha256,
                    source_sha256=case.source_sha256,
                    expected_digest=actual["digest"],
                    selection=selected,
                    binding=binding,
                    user_instruction=case.user_instruction,
                )

        def execute(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
            body = inputs[request.case_id]
            saved = self.create(context, UUID(suite_case_space[request.case_id]), body)
            invocation = None
            if saved["invocation_id"]:
                with self.engine.connect() as c:
                    invocation = (
                        c.execute(
                            select(tables.model_invocations).where(
                                tables.model_invocations.c.tenant_id == context.tenant.id,
                                tables.model_invocations.c.run_id == UUID(saved["run_id"]),
                                tables.model_invocations.c.id == UUID(saved["invocation_id"]),
                            )
                        )
                        .mappings()
                        .one()
                    )
            if saved["status"] != "succeeded" or saved["assessment"] is None:
                raise ProviderRequestError(
                    saved["error_code"] or "evaluation_incomplete",
                    "Evaluation unavailable",
                    usage=ProviderUsage(
                        input_tokens=invocation["input_tokens"],
                        output_tokens=invocation["output_tokens"],
                    )
                    if invocation
                    else None,
                )
            assert invocation is not None
            return ProductEvaluationResponse(
                content=canonical(saved["assessment"]),
                input_tokens=invocation["input_tokens"],
                output_tokens=invocation["output_tokens"],
                execution_source="provider_claim",
                reported_model=invocation["model"],
                original_receipt_ref=f"/api/product-work/spaces/{suite_case_space[request.case_id]}/evaluation/runs/{saved['run_id']}",
            )

        suite_case_space = {case.case_id: case.source["market_space_id"] for case in suite.cases}
        report = run_product_evaluation(
            loaded, binding=binding, executor=execute, max_structured_attempts=1
        )
        report["execution_plane"] = "shadow_evaluation"
        report["evaluation_id"] = str(evaluation_id)
        report["output_origin"] = "normalized_gateway_result"
        report["configuration_binding_verified"] = False
        report.pop("report_sha256", None)
        report["report_sha256"] = digest(report)
        return report

    def create(self, context: AuthContext, space_id: UUID, request: Request) -> dict[str, Any]:
        assert self.gateway is not None
        body = request.model_dump(mode="json")
        prompt, output_type, runtime = runtime_contract(request.selection.capability)
        with self.engine.begin() as c:
            authorize(c, context, space_id)
            require_enabled(request.selection.capability)
            c.execute(
                select(tables.market_spaces.c.id)
                .where(
                    tables.market_spaces.c.tenant_id == context.tenant.id,
                    tables.market_spaces.c.id == space_id,
                )
                .with_for_update()
            ).scalar_one()
            t = tables.agent_runs
            row = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space_id,
                        t.c.agent_key == "product_management_intelligence",
                        t.c.request_id == "evaluation:" + str(request.request_id),
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                if (
                    row["context_version"] != RUN_VERSION
                    or row["requested_by_user_id"] != context.user.id
                    or row["run_context"]["evaluation_input"] != body
                ):
                    raise ProductWorkError("本评测请求已用于其他输入，不能改写")
                readable(
                    c,
                    context,
                    row["run_context"]["evaluation_source"],
                    request.selection.capability,
                )
                from app.ai.application_recovery import try_resume

                if not try_resume(
                    c,
                    self.gateway,
                    row,
                    actor=context.user.id,
                    auth_version=context.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(row)
            else:
                snapshot = source(c, context, space_id, request.selection)
                if (
                    snapshot["digest"] != request.expected_digest
                    or digest(snapshot) != request.source_sha256
                    or digest(runtime) != request.runtime_sha256
                ):
                    raise ProductWorkError("评测资料或执行合同已有变化，请重新核对")
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=None,
                            market_space_id=space_id,
                            scope_kind="market_space",
                            agent_key="product_management_intelligence",
                            request_id="evaluation:" + str(request.request_id),
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
                            run_context=dict(
                                evaluation_input=body,
                                evaluation_source=snapshot,
                                evaluation_prompt_version=prompt.version,
                                evaluation_schema_digest=digest(output_type.model_json_schema()),
                                evaluation_output_mode="shadow_evaluation.v1",
                            ),
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
                    actor_user_id=context.user.id,
                    purpose=PURPOSE,
                    auth_version=context.user.auth_version,
                )
        return self._execute(row)

    def _execute(self, row: RowMapping) -> dict[str, Any]:
        from app.ai.application_domain_context import record, sources_current
        from app.ai.call_identity import ModelCallSlot, model_call_id

        assert self.gateway is not None
        rc = row["run_context"]
        body, snapshot = rc["evaluation_input"], rc["evaluation_source"]
        capability = body["selection"]["capability"]
        prompt, output_type, _ = runtime_contract(capability)
        call_id = model_call_id(row["id"], ModelCallSlot.PRODUCT_EVALUATION)
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=None,
            run_id=row["id"],
            model_call_id=call_id,
            agent_key="product_management_intelligence",
            agent_tier=AgentTier.REASONING,
            prompt_version=prompt.version,
            system_prompt=prompt.system_prompt,
            instruction=prompt.instruction,
            context=context_for(snapshot, body, row["tenant_id"]),
            expected_provider=ProviderName(body["binding"]["provider"]),
            expected_model=body["binding"]["model"],
        )
        output, invocation_id, error_code = None, None, None
        try:
            record(
                self.engine,
                tenant_id=row["tenant_id"],
                project_id=None,
                run_id=row["id"],
                model_call_id=call_id,
                purpose=PURPOSE,
                context=invocation.context,
                snapshot=snapshot,
            )
            result = self.gateway.invoke_structured(invocation, output_type)
            invocation_id = result.invocation_id
            if result.status != "succeeded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            else:
                if capability == "product_matrix":
                    assert isinstance(result.output, ProductMatrixExplanation)
                    matrix.validate_assessment(result.output, snapshot)
                else:
                    assert isinstance(result.output, ProductWorkAssessment)
                    work.validate_assessment(result.output, snapshot)
                    validate_refs(result.output, snapshot, row["tenant_id"])
                if invocation_id is None:
                    raise ProductWorkError("评测缺少原调用回执")
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("评测期间来源或授权已变化")
                output = result.output.model_dump(mode="json")
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except (ValueError, LookupError, PermissionError):
            error_code = "PRODUCT_EVALUATION_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "PRODUCT_EVALUATION_EXECUTION_FAILED"
        with self.engine.begin() as c:
            saved = (
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
            if saved["status"] != "running":
                return receipt(saved)
            try:
                if not current(c, saved, invocation):
                    output, error_code = None, "PRODUCT_EVALUATION_SOURCE_CHANGED"
            except (ValueError, LookupError, PermissionError):
                output, error_code = None, "PRODUCT_EVALUATION_ACCESS_CHANGED"
            if output is not None and error_code is None:
                original = c.execute(
                    select(tables.model_invocations.c.id).where(
                        tables.model_invocations.c.tenant_id == row["tenant_id"],
                        tables.model_invocations.c.run_id == row["id"],
                        tables.model_invocations.c.id == invocation_id,
                        tables.model_invocations.c.status == "succeeded",
                        tables.model_invocations.c.budget_call_id == call_id,
                        tables.model_invocations.c.agent_key == "product_management_intelligence",
                    )
                ).first()
                if original is None:
                    output, error_code = None, "PRODUCT_EVALUATION_RECEIPT_MISSING"
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error_code is None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    tables.agent_runs.update()
                    .where(
                        tables.agent_runs.c.id == row["id"],
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                    )
                    .values(
                        status="degraded" if error_code else "succeeded",
                        error_code=error_code,
                        completed_at=now,
                        updated_at=now,
                        run_context={
                            **saved["run_context"],
                            "evaluation_result": output if error_code is None else None,
                            "evaluation_invocation_id": str(invocation_id)
                            if invocation_id
                            else None,
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
