"""Persistent user requests for typed engineering candidates with the shared gateway."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, RowMapping, func, select

from app.ai import change_application_tools as application_tools
from app.ai import change_notice_preparation as notice_preparation
from app.ai import discussion_followup
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import resolve_capability
from app.ai.change_impact_preparation import (
    PROMPT,
    ChangeImpactAssessment,
    encoded,
    source_state,
    validate_assessment,
)
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.change_execution_results import _access
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

KEY = "engineering_intelligence.change_work_package"
PURPOSE = "change_work_package"
RUN_VERSION = "change-work-package-request-v1"


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    include_supplier_notices: bool = False
    allow_discussion: bool = False
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    depth: int = Field(default=3, ge=1, le=5)
    user_instruction: str = Field(default="", max_length=10000)


def model_context(snapshot: dict[str, Any], instruction: str) -> dict[str, Any]:
    context = snapshot["model_context"]
    discussion = snapshot.get("discussion_input")
    return {
        "question": context["question"]
        + "\n本次读取覆盖与限制："
        + encoded(context["coverage"])
        + "\n本次专业资料投影（资料归属及缺项，不代表专业已评审或多席位已发言）："
        + encoded(context.get("professional_projections", []))
        + ("\n本次用户要求：" + instruction if instruction else "")
        + (
            "\n固定讨论摘要（意见与缺项，不是已批准事实）："
            + encoded(discussion_followup.model_input(discussion))
            if discussion
            else ""
        ),
        "references": [
            {
                "reference_id": ref["reference_id"],
                "entity": ref["category"],
                "label": ref["label"],
                "excerpt": encoded({k: ref[k] for k in ("digest", "fields", "omitted_fields")}),
            }
            for ref in context["references"]
        ],
    }


def receipt(row: Any) -> dict[str, Any]:
    output = row["run_context"].get("impact_result")
    used_refs: set[str] = set()
    if output:
        for impact in output.get("impacts", []):
            used_refs.add(impact["target_reference_id"])
        statements = output.get("summary", []) + [i["basis"] for i in output.get("impacts", [])]
        statements += [w["basis"] for i in output.get("impacts", []) for w in i["proposed_work"]]
        used_refs.update(
            c["reference_id"] for statement in statements for c in statement["citations"]
        )
    reference_labels = {
        r["reference_id"]: r["label"]
        for r in row["run_context"]["impact_source"]["model_context"]["references"]
        if r["reference_id"] in used_refs
    }
    return _plain(
        {
            "run_id": row["id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "error_code": row["error_code"],
            "finding_id": row["run_context"].get("impact_finding_id"),
            "reference_labels": reference_labels,
            "assessment": output
            if output and row["run_context"].get("impact_finding_id")
            else None,
            "missing": output.get("missing", []) if output else [],
            "disposition": output.get("disposition") if output else None,
            "source_digest": row["run_context"]["impact_source"]["digest"],
            "depth": row["run_context"]["impact_depth"],
            "user_instruction": row["run_context"].get("impact_user_instruction", ""),
            "tool_receipts": row["run_context"].get("impact_tool_receipts", {}),
            "allow_discussion": row["run_context"].get("impact_allow_discussion", False),
            "include_supplier_notices": notice_preparation.is_notice(
                row["run_context"]["impact_source"]
            ),
            "prompt_version": row["run_context"].get("impact_prompt_version"),
            "discussion_choice": row["run_context"].get("discussion_convene_choice"),
            "discussion_reference_labels": {
                r["reference_id"]: r["label"]
                for r in row["run_context"]["impact_source"]["model_context"]["references"]
            }
            if row["run_context"].get("impact_allow_discussion")
            else {},
            "convened_discussion": row["run_context"].get("convened_discussion"),
            "discussion_followup_enabled": row["run_context"].get("discussion_followup_version")
            == discussion_followup.VERSION,
            "discussion_followup_error": row["run_context"].get("discussion_followup_error"),
            **discussion_followup.provenance(row["run_context"]["impact_source"]),
        }
    )


class ChangeWorkPackageRuns:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @staticmethod
    def list_results(
        engine: Engine,
        *,
        context: AuthContext,
        project_id: UUID,
        ecr_id: UUID,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        _access(engine, context, project_id, Action.CHANGE_VIEW)
        _access(engine, context, project_id, Action.QUALITY_VIEW)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            t = tables.agent_runs
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.context_version == RUN_VERSION,
                t.c.run_context["impact_ecr_id"].as_string() == str(ecr_id),
            )
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
                snapshot = row["run_context"]["impact_source"]
                try:
                    notice_preparation.require_disclosure(c, context, snapshot)
                except (ProductWorkError, PermissionError):
                    continue
                try:
                    actual_digest = notice_preparation.rebuild(
                        c, context.tenant.id, project_id, snapshot, context.user.id
                    )["digest"]
                except (ProductWorkError, PermissionError):
                    actual_digest = None
                discussion_current = True
                try:
                    discussion_followup.require_current(
                        c, context.tenant.id, row["run_context"]["impact_source"]
                    )
                except ProductWorkError:
                    discussion_current = False
                from app.ai.change_discussion_receipts import linked

                items.append(
                    {
                        **receipt(row),
                        "sources_current": row["run_context"]["impact_source"]["digest"]
                        == actual_digest
                        and discussion_current,
                        **linked(c, row, context.user.id),
                        "requested_by_me": row["requested_by_user_id"] == context.user.id,
                    }
                )
        return {
            "can_request": is_allowed(context.user.role, Action.CHANGE_EDIT),
            "rollout": resolve_capability(KEY).rollout.value,
            "notice_rollout": resolve_capability(notice_preparation.KEY).rollout.value,
            "notice_discussion_available": notice_preparation.discussion_available(),
            "followup_rollout": resolve_capability(discussion_followup.KEY).rollout.value,
            "discussion_available": all(
                resolve_capability(key).rollout.value == "live"
                for key in (
                    discussion_followup.KEY,
                    "engineering_intelligence.discussion_convene",
                    "engineering_intelligence.change_discussion",
                )
            ),
            "convene_rollout": resolve_capability(
                "engineering_intelligence.discussion_convene"
            ).rollout.value,
            "prompt_version": PROMPT.version,
            "items": items,
            "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
        }

    def create(
        self, *, context: AuthContext, project_id: UUID, ecr_id: UUID, request: Request
    ) -> dict[str, Any]:
        _access(self.engine, context, project_id, Action.CHANGE_EDIT)
        _access(self.engine, context, project_id, Action.QUALITY_VIEW)
        require_live_key(KEY)
        if request.include_supplier_notices:
            require_live_key(notice_preparation.KEY)
            if request.allow_discussion:
                require_live_key(notice_preparation.DISCUSSION_KEY)
        if request.allow_discussion:
            require_live_key("engineering_intelligence.discussion_convene")
            require_live_key("engineering_intelligence.change_discussion")
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
                raise ProductWorkError("项目不可用")
            _access(self.engine, context, project_id, Action.CHANGE_EDIT)
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
                "impact_ecr_id": str(ecr_id),
                "impact_allow_discussion": request.allow_discussion,
                "impact_include_supplier_notices": request.include_supplier_notices,
                "impact_depth": request.depth,
                "impact_expected_digest": request.expected_digest,
                "impact_user_instruction": request.user_instruction,
            }
            if existing is not None:
                if (
                    existing["context_version"] != RUN_VERSION
                    or existing["requested_by_user_id"] != context.user.id
                    or any(
                        existing["run_context"].get(
                            k,
                            False
                            if k in {"impact_allow_discussion", "impact_include_supplier_notices"}
                            else None,
                        )
                        != v
                        for k, v in body.items()
                    )
                ):
                    raise ProductWorkError("本请求已用于其他分析，不能改写原输入")
                notice_preparation.require_disclosure(
                    c, context, existing["run_context"]["impact_source"]
                )
                notice_preparation.require_enabled(existing["run_context"]["impact_source"])
                if not try_resume(
                    c,
                    self.gateway,
                    existing,
                    actor=context.user.id,
                    auth_version=context.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(existing)
                row, snapshot = existing, existing["run_context"]["impact_source"]
            else:
                snapshot = (
                    notice_preparation.source_state(c, context, project_id, ecr_id, request.depth)
                    if request.include_supplier_notices
                    else source_state(c, context.tenant.id, project_id, ecr_id, request.depth)
                )
                if snapshot["digest"] != request.expected_digest:
                    raise ProductWorkError("分析资料已有变化，请重新读取核对")
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                convene_pins: dict[str, Any] = {}
                if request.allow_discussion:
                    require_live_key(discussion_followup.KEY)
                    from app.ai.discussion_convene import PROMPT as CONVENE_PROMPT
                    from app.ai.discussion_convene import ConvenePlan

                    convene_pins = {
                        "discussion_followup_version": discussion_followup.VERSION,
                        "discussion_convene_version": CONVENE_PROMPT.version,
                        "discussion_convene_schema": digest(ConvenePlan.model_json_schema()),
                    }
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
                                **convene_pins,
                                "impact_source": snapshot,
                                "impact_prompt_version": notice_preparation.prompt_for(
                                    snapshot
                                ).version,
                                "impact_toolset_version": application_tools.VERSION,
                                "impact_schema_digest": digest(
                                    ChangeImpactAssessment.model_json_schema()
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

        prompt = (
            discussion_followup.prompt_for(snapshot)
            if discussion_followup.version(row["run_context"], snapshot)
            else notice_preparation.prompt_for(snapshot)
        )
        call_id = model_call_id(row["id"], ModelCallSlot.CHANGE_WORK_PACKAGE)
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
            context=model_context(snapshot, row["run_context"].get("impact_user_instruction", "")),
        )
        output = None
        invocation_id = None
        error_code = None
        prepare_intent = None
        try:
            require_live_key(KEY)
            notice_preparation.require_enabled(snapshot)
            if snapshot.get("discussion_input"):
                require_live_key(discussion_followup.KEY)
            if (
                row["run_context"].get("impact_toolset_version") != application_tools.VERSION
                or row["run_context"].get("impact_prompt_version") != prompt.version
                or row["run_context"].get("impact_schema_digest")
                != digest(ChangeImpactAssessment.model_json_schema())
            ):
                raise ProductWorkError("原运行版本已不可用")
            with self.engine.connect() as c:
                discussion_followup.require_current(c, row["tenant_id"], snapshot)
            trace_intent = application_tools.admit(
                self.engine,
                self.gateway,
                row,
                application_tools.TRACE,
                application_tools.arguments(row, application_tools.TRACE),
            )
            with self.engine.begin() as c:
                traced = application_tools.dispatch(c, self.gateway, row, trace_intent)
            if traced.get("error_code"):
                raise ProductWorkError("影响关系读取未完成")
            invocation.context["question"] = (
                str(invocation.context["question"])
                + "\n实际引用关系追踪回执："
                + application_tools.trace_context(traced)
            )
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
            result = self.gateway.invoke_structured(invocation, ChangeImpactAssessment)
            if result.status == "degraded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            else:
                validate_assessment(result.output, snapshot)
                if result.invocation_id is None:
                    raise ProductWorkError("模型运行缺少原调用回执")
                if not sources_current(self.engine, invocation, PURPOSE, snapshot):
                    raise ProductWorkError("生成期间原资料已变化")
                output, invocation_id = result.output, result.invocation_id
                if row["run_context"].get("impact_allow_discussion"):
                    from app.ai.discussion_convene import run as convene

                    convene(self.engine, self.gateway, row, snapshot)
                prepare_intent = application_tools.admit(
                    self.engine,
                    self.gateway,
                    row,
                    application_tools.PREPARE,
                    application_tools.arguments(
                        row, application_tools.PREPARE, output=output, invocation_id=invocation_id
                    ),
                )
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except ProductWorkError:
            error_code = "CHANGE_WORK_PACKAGE_SOURCE_OR_OUTPUT_INVALID"
        except Exception:
            error_code = "CHANGE_WORK_PACKAGE_EXECUTION_FAILED"
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
            if (
                output is not None
                and invocation_id is not None
                and error_code is None
                and prepare_intent is not None
            ):
                try:
                    with c.begin_nested():
                        prepared = application_tools.dispatch(
                            c, self.gateway, current, prepare_intent
                        )
                        if prepared.get("error_code"):
                            output, error_code = None, prepared["error_code"]
                        elif prepared.get("finding_id"):
                            finding_id = UUID(prepared["finding_id"])
                except (ProductWorkError, ValueError):
                    output, error_code = None, "CHANGE_WORK_PACKAGE_CANDIDATE_INVALID"
            # Tool dispatch appended receipts in this transaction; retain them.
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
                            "impact_result": output.model_dump(mode="json") if output else None,
                            "impact_finding_id": str(finding_id) if finding_id else None,
                            "impact_invocation_id": str(invocation_id) if invocation_id else None,
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return receipt(saved)
