"""Persistent read-only product work analyses with fixed inputs and actual model receipts."""

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
from app.ai.product_work_context import (
    contract,
    key,
    model_context,
    readable,
    rebuild,
    validate_assessment,
)
from app.ai.product_work_preparation import authorize as authorize_sources
from app.ai.product_work_preparation import source_for_request
from app.ai.project_discussion_sources import actor
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.product_work_ai import ProductCapability, ProductResearchAssessment
from app.contracts.product_work_ai import ProductWorkSelection as Selection
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkError,
    ProductWorkRunNotFoundError,
    _line,
    _plain,
    _role,
    _space,
    digest,
)

PURPOSE = "product_work"
RUN_VERSION = "product-work-request-v1"


def authorize(
    c: Any,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID | None,
    *,
    write: bool = False,
    lock: bool = False,
) -> Any:
    authorize_sources(c, context, space_id, line_id)
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE if write else Action.PRODUCT_WORK_VIEW)
    space = _space(c, context, space_id, access="contributor" if write else "viewer", lock=lock)
    if write and space["lifecycle"] == "archived":
        raise ProductWorkError("已归档市场空间只读")
    _line(
        c, context, space_id, line_id, access="contributor" if write else "viewer", writable=write
    )
    return space


def run_row(c: Any, context: AuthContext, space_id: UUID, run_id: UUID) -> Any:
    t = tables.agent_runs
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space_id,
                t.c.scope_kind == "market_space",
                t.c.context_version == RUN_VERSION,
                t.c.requested_by_user_id == context.user.id,
                t.c.id == run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkRunNotFoundError("产品工作运行不存在或不属于当前发起人")
    readable(c, context, row["run_context"]["product_work_source"])
    return row


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: Selection
    user_instruction: str = Field(default="", max_length=10000)


def receipt(row: Any) -> dict[str, Any]:
    output = row["run_context"].get("product_work_result")
    reference_labels = {
        r["reference_id"]: r["label"]
        for r in row["run_context"]["product_work_source"]["references"]
    }
    return _plain(
        {
            "run_id": row["id"],
            "market_space_id": row["market_space_id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "error_code": row["error_code"],
            "invocation_id": row["run_context"].get("product_work_invocation_id"),
            "reference_labels": reference_labels,
            "assessment": output
            if output and row["run_context"].get("product_work_invocation_id")
            else None,
            "missing": output.get("missing", []) if output else [],
            "disposition": output.get("disposition") if output else None,
            "source_digest": row["run_context"]["product_work_source"]["digest"],
            "selection": row["run_context"]["product_work_selection"],
            "user_instruction": row["run_context"].get("product_work_user_instruction", ""),
        }
    )


class ProductWorkRuns:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @staticmethod
    def list_results(
        engine: Engine,
        *,
        context: AuthContext,
        space_id: UUID,
        capability: ProductCapability | None = None,
        product_line_id: UUID | None = None,
        before_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            t = tables.agent_runs
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space_id,
                t.c.scope_kind == "market_space",
                t.c.project_id.is_(None),
                t.c.agent_key == "product_management_intelligence",
                t.c.context_version == RUN_VERSION,
                t.c.requested_by_user_id == context.user.id,
            )
            if capability is None:
                if run_id is None or before_id is not None:
                    raise ProductWorkError("产品工作运行不存在或不属于当前发起人")
                original_row = c.execute(query.where(t.c.id == run_id)).mappings().one_or_none()
                if original_row is None:
                    raise ProductWorkRunNotFoundError("产品工作运行不存在或不属于当前发起人")
                try:
                    saved_context = original_row["run_context"]
                    selected = Selection.model_validate(saved_context["product_work_selection"])
                    original = saved_context["product_work_source"]
                    if (
                        original["actor_id"] != str(context.user.id)
                        or original["market_space_id"] != str(space_id)
                        or original["selection"] != selected.model_dump(mode="json")
                        or original["digest"] != saved_context["product_work_expected_digest"]
                        or original["digest"]
                        != digest({k: v for k, v in original.items() if k != "digest"})
                    ):
                        raise ValueError("invalid fixed run binding")
                except (KeyError, TypeError, ValueError) as error:
                    raise ProductWorkRunNotFoundError(
                        "产品工作运行不存在或不属于当前发起人"
                    ) from error
                capability, product_line_id = selected.capability, selected.product_line_id
                authorize(c, context, space_id, product_line_id)
                values = [original_row]
            else:
                authorize(c, context, space_id, product_line_id)
                query = query.where(
                    t.c.run_context["product_work_selection"]["capability"].as_string()
                    == capability,
                    t.c.run_context["product_work_selection"]["product_line_id"].as_string()
                    == (str(product_line_id) if product_line_id else None),
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
                values = list(
                    c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                    .mappings()
                    .all()
                )
            can_request = False
            try:
                authorize(c, context, space_id, product_line_id, write=True)
                can_request = True
            except (ValueError, LookupError, PermissionError):
                pass
            items = []
            digest_cache: dict[str, str | None] = {}
            for row in values[:20]:
                original = row["run_context"]["product_work_source"]
                readable(c, context, original)
                selection_key = digest(
                    {
                        "selection": original["selection"],
                        "private_attachment_link_version": original.get(
                            "private_attachment_link_version", "legacy"
                        ),
                    }
                )
                if selection_key not in digest_cache:
                    try:
                        digest_cache[selection_key] = rebuild(c, context.tenant.id, original)[
                            "digest"
                        ]
                    except (ProductWorkError, LookupError, ValueError, PermissionError):
                        digest_cache[selection_key] = None
                current_digest = digest_cache[selection_key]
                items.append(
                    {
                        **receipt(row),
                        **(
                            {
                                "frozen_sources": row["run_context"]["product_work_source"][
                                    "references"
                                ]
                            }
                            if run_id
                            else {}
                        ),
                        "sources_current": row["run_context"]["product_work_source"]["digest"]
                        == current_digest,
                        "requested_by_me": row["requested_by_user_id"] == context.user.id,
                    }
                )
        return {
            "can_request": can_request,
            "rollout": resolve_capability(key(capability)).rollout.value,
            "prompt_version": contract(capability=capability)[0].version,
            "items": items,
            "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
        }

    def create(self, *, context: AuthContext, space_id: UUID, request: Request) -> dict[str, Any]:
        require_live_key(key(request.selection.capability))
        prompt, output_type = contract(capability=request.selection.capability)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(
                c, context, space_id, request.selection.product_line_id, write=True, lock=True
            )
            t = tables.agent_runs
            existing = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space_id,
                        t.c.scope_kind == "market_space",
                        t.c.agent_key == "product_management_intelligence",
                        t.c.request_id == str(request.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            body = {
                "product_work_selection": request.selection.model_dump(mode="json"),
                "product_work_expected_digest": request.expected_digest,
                "product_work_user_instruction": request.user_instruction,
            }
            if existing is not None:
                if (
                    existing["context_version"] != RUN_VERSION
                    or existing["requested_by_user_id"] != context.user.id
                    or any(existing["run_context"].get(k) != v for k, v in body.items())
                ):
                    raise ProductWorkError("本请求已用于其他分析，不能改写原输入")
                readable(c, context, existing["run_context"]["product_work_source"])
                if not try_resume(
                    c,
                    self.gateway,
                    existing,
                    actor=context.user.id,
                    auth_version=context.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(existing)
                row, snapshot = existing, existing["run_context"]["product_work_source"]
            else:
                snapshot = source_for_request(
                    c, context, space_id, request.selection, request.expected_digest
                )
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
                            project_id=None,
                            market_space_id=space_id,
                            scope_kind="market_space",
                            agent_key="product_management_intelligence",
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
                                "product_work_source": snapshot,
                                "product_work_output_mode": "read_only.v1",
                                "product_work_prompt_version": prompt.version,
                                "product_work_schema_digest": digest(
                                    output_type.model_json_schema()
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
                    parent_run_id=None,
                    actor_user_id=context.user.id,
                    purpose=PURPOSE,
                    auth_version=context.user.auth_version,
                )
        return self._execute(row, snapshot)

    def _execute(self, row: RowMapping, snapshot: dict[str, Any]) -> dict[str, Any]:
        from app.ai.application_domain_context import record, sources_current

        call_id = model_call_id(row["id"], ModelCallSlot.PRODUCT_WORK)
        prompt, output_type = contract(row["run_context"]["product_work_prompt_version"])
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call_id,
            agent_key="product_management_intelligence",
            agent_tier=AgentTier.REASONING,
            prompt_version=prompt.version,
            system_prompt=prompt.system_prompt,
            instruction=prompt.instruction,
            context=model_context(
                snapshot,
                row["run_context"].get("product_work_user_instruction", ""),
                prompt_version=prompt.version,
                tenant_id=row["tenant_id"],
            ),
        )
        output = None
        invocation_id = None
        error_code = None
        try:
            require_live_key(key(snapshot["selection"]["capability"]))
            if row["run_context"].get("product_work_prompt_version") != prompt.version or row[
                "run_context"
            ].get("product_work_schema_digest") != digest(output_type.model_json_schema()):
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
            result = self.gateway.invoke_structured(invocation, output_type)
            if result.status == "degraded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            else:
                validate_assessment(result.output, snapshot)
                from app.ai.product_evidence_context import validate_refs

                validate_refs(result.output, snapshot, row["tenant_id"])
                if result.invocation_id is None:
                    raise ProductWorkError("模型运行缺少原调用回执")
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("生成期间原资料已变化")
                output, invocation_id = result.output, result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except ProductWorkError:
            error_code = "PRODUCT_WORK_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "PRODUCT_WORK_EXECUTION_FAILED"
        with self.engine.begin() as c:
            c.execute(
                select(tables.market_spaces.c.id)
                .where(
                    tables.market_spaces.c.tenant_id == row["tenant_id"],
                    tables.market_spaces.c.id == row["market_space_id"],
                )
                .with_for_update()
            ).scalar_one()
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
                require_live_key(key(snapshot["selection"]["capability"]))
            except CapabilityUnavailableError as error:
                output, error_code = None, error.code
            if output is not None and error_code is None:
                try:
                    authorize(
                        c,
                        actor(c, row["tenant_id"], row["requested_by_user_id"]),
                        row["market_space_id"],
                        Selection.model_validate(snapshot["selection"]).product_line_id,
                        write=True,
                    )
                    if rebuild(c, row["tenant_id"], snapshot)["digest"] != snapshot["digest"]:
                        output, error_code = None, "PRODUCT_WORK_SOURCE_CHANGED"
                except (ValueError, LookupError, PermissionError):
                    output, error_code = None, "PRODUCT_WORK_ACCESS_CHANGED"
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            if output is not None and invocation_id is not None and error_code is None:
                invocation_row = c.execute(
                    select(tables.model_invocations.c.id).where(
                        tables.model_invocations.c.tenant_id == row["tenant_id"],
                        tables.model_invocations.c.project_id == row["project_id"],
                        tables.model_invocations.c.run_id == row["id"],
                        tables.model_invocations.c.id == invocation_id,
                        tables.model_invocations.c.status == "succeeded",
                        tables.model_invocations.c.budget_call_id == call_id,
                        tables.model_invocations.c.agent_key == "product_management_intelligence",
                    )
                ).first()
                if invocation_row is None:
                    output, error_code = None, "PRODUCT_WORK_RECEIPT_MISSING"
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error_code is None)
            # Preserve independently recorded run control and context history.
            current_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == row["tenant_id"],
                    tables.agent_runs.c.id == row["id"],
                )
            ).scalar_one()
            if (
                isinstance(output, ProductResearchAssessment)
                and output.research_plan is not None
                and error_code is None
            ):
                from app.domain.product_research_findings import create_finding

                create_finding(
                    c,
                    {
                        **current,
                        "run_context": {
                            **current_context,
                            "product_work_invocation_id": str(invocation_id),
                        },
                    },
                    output,
                )
            if (
                output is not None
                and error_code is None
                and prompt.version
                in (
                    "product-evidence-v3",
                    "product-discovery-v4",
                    "product-planning-v5",
                    "product-planning-v6",
                )
            ):
                from app.domain.product_evidence_findings import (
                    create_finding as create_evidence_finding,
                )

                create_evidence_finding(
                    c,
                    {
                        **current,
                        "run_context": {
                            **current_context,
                            "product_work_invocation_id": str(invocation_id),
                        },
                    },
                    output,
                )
            if output is not None and error_code is None and prompt.version == "product-rfq-v6":
                from app.domain.product_rfq_requirements import create_finding as create_rfq_finding

                create_rfq_finding(
                    c,
                    {
                        **current,
                        "run_context": {
                            **current_context,
                            "product_work_invocation_id": str(invocation_id),
                        },
                    },
                    output,
                )
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
                            "product_work_result": output.model_dump(mode="json")
                            if output and error_code is None
                            else None,
                            "product_work_invocation_id": str(invocation_id)
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
