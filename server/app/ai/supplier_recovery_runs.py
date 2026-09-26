"""Persistent user requests for typed supplier recovery candidates with the shared gateway."""

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
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.ai.supplier_recovery_preparation import (
    PROMPT,
    Selection,
    encoded,
    source_state,
    validate_assessment,
)
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.supplier_recovery import SupplierRecoveryAssessment
from app.db.schema import tables
from app.domain.material_exceptions import _authorize
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

KEY = "supplier_intelligence.supplier_recovery"
PURPOSE = "supplier_recovery"
RUN_VERSION = "supplier-recovery-request-v1"


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    with engine.connect() as c:
        _authorize(c, context, project_id, write=action == Action.PRODUCT_ENGINEERING_EDIT)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: Selection
    user_instruction: str = Field(default="", max_length=10000)


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
    output = row["run_context"].get("supply_result")
    reference_labels = {
        r["reference_id"]: r["label"]
        for r in row["run_context"]["supply_source"]["model_context"]["references"]
    }
    return _plain(
        {
            "run_id": row["id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "error_code": row["error_code"],
            "finding_id": row["run_context"].get("supply_finding_id"),
            "reference_labels": reference_labels,
            "assessment": output
            if output and row["run_context"].get("supply_finding_id")
            else None,
            "missing": output.get("missing", []) if output else [],
            "disposition": output.get("disposition") if output else None,
            "source_digest": row["run_context"]["supply_source"]["digest"],
            "selection": row["run_context"]["supply_selection"],
            "user_instruction": row["run_context"].get("supply_user_instruction", ""),
        }
    )


class SupplierRecoveryRuns:
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
                    current_digest = source_state(
                        c,
                        context.tenant.id,
                        project_id,
                        Selection.model_validate(row["run_context"]["supply_selection"]),
                    )["digest"]
                except (ProductWorkError, LookupError, ValueError):
                    current_digest = None
                items.append(
                    {
                        **receipt(row),
                        **(
                            {
                                "frozen_sources": row["run_context"]["supply_source"][
                                    "model_context"
                                ]["references"]
                            }
                            if run_id
                            else {}
                        ),
                        "sources_current": row["run_context"]["supply_source"]["digest"]
                        == current_digest,
                        "requested_by_me": row["requested_by_user_id"] == context.user.id,
                    }
                )
        return {
            "can_request": is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT),
            "rollout": resolve_capability(KEY).rollout.value,
            "prompt_version": PROMPT.version,
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
                        t.c.agent_key == "supplier_intelligence",
                        t.c.request_id == str(request.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            body = {
                "supply_selection": request.selection.model_dump(mode="json"),
                "supply_expected_digest": request.expected_digest,
                "supply_user_instruction": request.user_instruction,
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
                row, snapshot = existing, existing["run_context"]["supply_source"]
            else:
                snapshot = source_state(c, context.tenant.id, project_id, request.selection)
                if snapshot["digest"] != request.expected_digest:
                    raise ProductWorkError("分析资料已有变化，请重新读取核对")
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            agent_key="supplier_intelligence",
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
                                "supply_source": snapshot,
                                "supply_prompt_version": PROMPT.version,
                                "supply_schema_digest": digest(
                                    SupplierRecoveryAssessment.model_json_schema()
                                ),
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
                    actor_user_id=context.user.id,
                    purpose=PURPOSE,
                    auth_version=context.user.auth_version,
                )
        return self._execute(row, snapshot)

    def _execute(self, row: RowMapping, snapshot: dict[str, Any]) -> dict[str, Any]:
        from app.ai.application_domain_context import record, sources_current

        call_id = model_call_id(row["id"], ModelCallSlot.SUPPLIER_RECOVERY)
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call_id,
            agent_key="supplier_intelligence",
            agent_tier=AgentTier.REASONING,
            prompt_version=PROMPT.version,
            system_prompt=PROMPT.system_prompt,
            instruction=PROMPT.instruction,
            context=model_context(snapshot, row["run_context"].get("supply_user_instruction", "")),
        )
        output = None
        invocation_id = None
        error_code = None
        try:
            require_live_key(KEY)
            if row["run_context"].get("supply_prompt_version") != PROMPT.version or row[
                "run_context"
            ].get("supply_schema_digest") != digest(SupplierRecoveryAssessment.model_json_schema()):
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
            result = self.gateway.invoke_structured(invocation, SupplierRecoveryAssessment)
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
            error_code = "SUPPLIER_RECOVERY_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "SUPPLIER_RECOVERY_EXECUTION_FAILED"
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
            except CapabilityUnavailableError as error:
                output, error_code = None, error.code
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error_code is None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            finding_id = None
            if output is not None and invocation_id is not None and error_code is None:
                try:
                    with c.begin_nested():
                        from app.domain.supplier_recovery_findings import persist

                        finding_id = persist(
                            c,
                            row=current,
                            snapshot=snapshot,
                            output=output,
                            invocation_id=invocation_id,
                            created_at=now,
                        )
                except (ProductWorkError, ValueError):
                    output, error_code = None, "SUPPLIER_RECOVERY_CANDIDATE_INVALID"
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
                            "supply_result": output.model_dump(mode="json") if output else None,
                            "supply_finding_id": str(finding_id) if finding_id else None,
                            "supply_invocation_id": str(invocation_id) if invocation_id else None,
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
