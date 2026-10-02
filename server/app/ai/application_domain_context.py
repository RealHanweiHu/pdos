"""Source adapters for actual risk, test-plan and upload-mapping model inputs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select

from app.ai.application_authorization import verify_application_authorization
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.observations import context_receipt_body, digest
from app.contracts.runtime_records import Observation
from app.db.schema import tables


def json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def contract(purpose: str, *, prompt_version: str | None = None) -> tuple[dict[str, Any], Any]:
    if purpose == "product_evaluation":
        from app.ai.product_matrix_preparation import PROMPT as MATRIX_PROMPT
        from app.ai.product_work_context import contract as product_contract
        from app.contracts.product_matrix_explanation import ProductMatrixExplanation

        if prompt_version == MATRIX_PROMPT.version:
            return MATRIX_PROMPT.model_dump(mode="json"), ProductMatrixExplanation
        if prompt_version is None:
            raise BudgetLedgerError("PRODUCT_EVALUATION_CONTRACT_REQUIRED")
        evaluation_prompt, evaluation_output = product_contract(prompt_version)
        return evaluation_prompt.model_dump(mode="json"), evaluation_output
    if purpose == "event_issue":
        from app.ai.issue_event_proposal import PROMPT as ISSUE_PROMPT
        from app.ai.issue_event_proposal import IssueEventProposal

        if prompt_version not in {None, ISSUE_PROMPT.version}:
            raise BudgetLedgerError("EVENT_ISSUE_CONTRACT_CHANGED")
        return ISSUE_PROMPT.model_dump(mode="json"), IssueEventProposal
    if purpose == "meeting_planning":
        from app.ai.meeting_planning_context import PROMPT as PLANNING_PROMPT
        from app.contracts.meeting_plan import MeetingAssessment

        if prompt_version not in {None, PLANNING_PROMPT.version}:
            raise BudgetLedgerError("MEETING_PLANNING_CONTRACT_CHANGED")
        return PLANNING_PROMPT.model_dump(mode="json"), MeetingAssessment
    if purpose == "intake_organization":
        from app.ai.intake_ai_context import PROMPT as INTAKE_PROMPT
        from app.contracts.intake_proposal import IntakeOrganization

        if prompt_version not in {None, INTAKE_PROMPT.version}:
            raise BudgetLedgerError("INTAKE_SOURCE_CONTRACT_CHANGED")
        return INTAKE_PROMPT.model_dump(mode="json"), IntakeOrganization
    if purpose == "process_template_configuration":
        from app.ai.process_template_context import prompt_data as template_prompt
        from app.contracts.process_template_proposal import output_type

        prompt = template_prompt(prompt_version)
        return prompt, output_type(prompt["version"])
    if purpose == "change_discussion":
        from app.ai.discussion_research_loop import PROMPT as RESEARCH_PROMPT
        from app.ai.discussion_research_loop import ResearchChoice

        if prompt_version == RESEARCH_PROMPT.version:
            return RESEARCH_PROMPT.model_dump(mode="json"), ResearchChoice
        from app.ai.discussion_initiation import PROMPT as INITIATION_PROMPT
        from app.ai.discussion_initiation import Initiation

        if prompt_version == INITIATION_PROMPT.version:
            return INITIATION_PROMPT.model_dump(mode="json"), Initiation
        from app.ai.change_discussion_contract import PROMPT as DISCUSSION_PROMPT
        from app.ai.change_discussion_contract import DiscussionTurn

        return DISCUSSION_PROMPT.model_dump(mode="json"), DiscussionTurn
    if purpose == "product_work":
        from app.ai.product_work_context import contract as product_contract

        product_prompt, product_output = product_contract(prompt_version)
        return product_prompt.model_dump(mode="json"), product_output
    if purpose == "product_matrix":
        from app.ai.product_matrix_preparation import PROMPT as MATRIX_PROMPT
        from app.contracts.product_matrix_explanation import ProductMatrixExplanation

        if prompt_version is not None and prompt_version != MATRIX_PROMPT.version:
            raise ValueError("Unknown product matrix prompt version")
        return MATRIX_PROMPT.model_dump(mode="json"), ProductMatrixExplanation
    if purpose == "executive_brief":
        from app.ai.executive_brief_preparation import PROMPT as EXECUTIVE_PROMPT
        from app.contracts.executive_brief import ExecutiveBrief

        if prompt_version not in {None, EXECUTIVE_PROMPT.version}:
            raise BudgetLedgerError("EXECUTIVE_BRIEF_CONTRACT_CHANGED")
        return EXECUTIVE_PROMPT.model_dump(mode="json"), ExecutiveBrief
    if purpose == "portfolio_explanation":
        from app.ai.portfolio_explanation_preparation import PROMPT as PORTFOLIO_PROMPT
        from app.contracts.portfolio_explanation import PortfolioExplanation

        if prompt_version not in {None, PORTFOLIO_PROMPT.version}:
            raise BudgetLedgerError("PORTFOLIO_EXPLANATION_CONTRACT_CHANGED")
        return PORTFOLIO_PROMPT.model_dump(mode="json"), PortfolioExplanation
    if purpose == "cost_reduction":
        from app.ai.cost_reduction_preparation import DISCUSSION_PROMPT as COST_DISCUSSION_PROMPT
        from app.ai.cost_reduction_preparation import PROMPT as COST_PROMPT
        from app.contracts.cost_reduction import CostAssessment

        if prompt_version not in {None, COST_PROMPT.version, COST_DISCUSSION_PROMPT.version}:
            raise BudgetLedgerError("COST_REDUCTION_CONTRACT_CHANGED")
        selected = (
            COST_DISCUSSION_PROMPT
            if prompt_version == COST_DISCUSSION_PROMPT.version
            else COST_PROMPT
        )
        return selected.model_dump(mode="json"), CostAssessment
    if purpose == "supplier_recovery":
        from app.ai.supplier_recovery_preparation import PROMPT as SUPPLY_PROMPT
        from app.contracts.supplier_recovery import SupplierRecoveryAssessment

        if prompt_version not in {None, SUPPLY_PROMPT.version}:
            raise BudgetLedgerError("SUPPLIER_RECOVERY_CONTRACT_CHANGED")
        return SUPPLY_PROMPT.model_dump(mode="json"), SupplierRecoveryAssessment
    if purpose == "quality_work_package":
        from app.ai.quality_preparation import PROMPT as QUALITY_PROMPT
        from app.contracts.quality_work_package import QualityAssessment

        return QUALITY_PROMPT.model_dump(mode="json"), QualityAssessment
    if purpose == "change_work_package" and prompt_version == "discussion-convene-v1":
        from app.ai.discussion_convene import PROMPT as CONVENE_PROMPT
        from app.ai.discussion_convene import ConvenePlan

        return CONVENE_PROMPT.model_dump(mode="json"), ConvenePlan
    if purpose == "change_work_package" and prompt_version == "change-work-package-v4":
        from app.ai.change_impact_preparation import ChangeImpactAssessment
        from app.ai.discussion_followup import PROMPT as FOLLOWUP_PROMPT

        return FOLLOWUP_PROMPT.model_dump(mode="json"), ChangeImpactAssessment
    if purpose == "change_work_package" and prompt_version == "change-work-package-v6":
        from app.ai.change_impact_preparation import ChangeImpactAssessment
        from app.ai.discussion_followup import NOTICE_PROMPT

        return NOTICE_PROMPT.model_dump(mode="json"), ChangeImpactAssessment
    if purpose == "change_work_package" and prompt_version == "change-work-package-v5":
        from app.ai.change_impact_preparation import ChangeImpactAssessment
        from app.ai.change_notice_preparation import PROMPT as NOTICE_BASE_PROMPT

        return NOTICE_BASE_PROMPT.model_dump(mode="json"), ChangeImpactAssessment
    if purpose == "change_work_package":
        from app.ai.change_impact_preparation import PROMPT, ChangeImpactAssessment

        return PROMPT.model_dump(mode="json"), ChangeImpactAssessment
    if purpose == "meeting_business":
        from app.domain.meeting_business_proposals import (
            MeetingBusinessAssessment,
        )
        from app.domain.meeting_business_proposals import (
            prompt_data as business_prompt,
        )

        return business_prompt(), MeetingBusinessAssessment
    if purpose == "meeting_decisions":
        from app.domain.meeting_decision_proposals import (
            MeetingDecisionAssessment,
        )
        from app.domain.meeting_decision_proposals import (
            prompt_data as decision_prompt,
        )

        return decision_prompt(), MeetingDecisionAssessment
    if purpose == "meeting_actions":
        from app.domain.meeting_action_proposals import MeetingActionAssessment, prompt_data

        return prompt_data(), MeetingActionAssessment
    if purpose in {"meeting_reading", "meeting_minutes"}:
        from app.ai.meeting_reading import PROMPT as MEETING_PROMPT
        from app.ai.meeting_reading import MeetingReading

        return MEETING_PROMPT.model_dump(mode="json"), MeetingReading
    if purpose == "risk_suggestion":
        from app.ai.executor import AgentAssessment
        from app.ai.risk_suggestions import RISK_PROMPT

        return RISK_PROMPT.model_dump(mode="json"), AgentAssessment
    if purpose in {"test_plan_suggestion", "event_issue"}:
        from app.ai.test_plan_versions import contract as version_contract

        return version_contract(prompt_version)
    if purpose == "report_mapping":
        from app.domain.test_report_import import IMPORT_PROMPT, ExcelImportMapping

        return IMPORT_PROMPT.model_dump(mode="json"), ExcelImportMapping
    raise BudgetLedgerError("APPLICATION_CONTEXT_PURPOSE_INVALID")


def bundle(purpose: str, *, prompt_version: str | None = None) -> dict[str, Any]:
    from app.ai.application_context import chat_bundle

    prompt, output_type = contract(purpose, prompt_version=prompt_version)
    base = chat_bundle()
    reader = purpose + "-source-adapter.v1"
    if purpose == "product_work":
        from app.ai.product_work_context import MODEL_CONTEXT_VERSION

        reader = MODEL_CONTEXT_VERSION
    service_tools = {}
    if purpose == "change_discussion" and prompt_version == "discussion-research-v1":
        from app.ai.discussion_research_loop import TOOLSET as RESEARCH_TOOLSET

        service_tools = {"service_toolset": RESEARCH_TOOLSET}
    if purpose == "quality_work_package":
        from app.ai.quality_application_tools import TOOLSET as QUALITY_TOOLSET

        service_tools = {"service_toolset": QUALITY_TOOLSET}
    if purpose == "change_work_package":
        from app.ai.change_application_tools import TOOLSET

        service_tools = {"service_toolset": TOOLSET}
    if purpose == "change_work_package" and prompt_version == "discussion-convene-v1":
        from app.ai.discussion_convene import TOOLSET as CONVENE_TOOLSET

        service_tools = {"service_toolset": CONVENE_TOOLSET}
    return {
        **base,
        "version": "application-domain-bundle.v1",
        "compiled": {
            **base["compiled"],
            "prompt": prompt,
            "schema": output_type.model_json_schema(),
            "reader": reader,
            "purpose": purpose,
            **service_tools,
        },
    }


def risk_payload(context: Any, concern: str) -> dict[str, Any]:
    event = context.trigger_events[-1].model_dump(mode="json")
    return dict(
        question=concern,
        project=context.project,
        execution=context.execution,
        trigger={k: event[k] for k in ("event_type", "entity", "entity_id", "timestamp")},
        references=[
            dict(
                reference_id=f"event:{e.id}",
                entity=e.entity,
                entity_id=str(e.entity_id),
                label=e.event_type,
            )
            for e in context.trigger_events
        ],
    )


def record(
    engine: Engine,
    *,
    tenant_id: UUID,
    project_id: UUID | None,
    run_id: UUID,
    model_call_id: UUID,
    purpose: str,
    context: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    with engine.connect() as c:
        auth = (
            c.execute(
                select(tables.application_authorizations).where(
                    tables.application_authorizations.c.tenant_id == tenant_id,
                    tables.application_authorizations.c.run_id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
    if auth is None:
        return
    from app.ai.test_plan_versions import version_from_run

    prompt_version = None
    if purpose == "product_evaluation":
        with engine.connect() as original_connection:
            prompt_version = original_connection.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.id == run_id,
                )
            ).scalar_one()["evaluation_prompt_version"]
    if purpose == "product_work":
        with engine.connect() as original_connection:
            prompt_version = original_connection.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.id == run_id,
                )
            ).scalar_one()["product_work_prompt_version"]
    if purpose == "product_matrix":
        from app.ai.product_matrix_preparation import version as matrix_version

        with engine.connect() as c:
            original_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = matrix_version(original_context, snapshot)
    if purpose == "executive_brief":
        from app.ai.executive_brief_preparation import version as executive_version

        with engine.connect() as c:
            original_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = executive_version(original_context, snapshot)
    if purpose == "portfolio_explanation":
        from app.ai.portfolio_explanation_preparation import version as portfolio_version

        with engine.connect() as c:
            original_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = portfolio_version(original_context, snapshot)
    if purpose == "cost_reduction":
        from app.ai.cost_reduction_preparation import version as cost_version

        with engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = cost_version(rc, snapshot)
    if purpose == "change_discussion":
        from app.ai.discussion_initiation import prompt_version as initiation_version

        with engine.connect() as c:
            original_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = initiation_version(original_context, snapshot)
    if (
        purpose == "change_work_package"
        and snapshot.get("context_version") == "change-work-package-context-v4"
    ):
        from app.ai.change_notice_preparation import require_enabled
        from app.ai.change_notice_preparation import version as notice_version

        require_enabled(snapshot)
        with engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.id == run_id,
                )
            ).scalar_one()
        prompt_version = notice_version(rc, snapshot)
    if purpose == "change_work_package" and snapshot.get("phase") == "discussion_convene":
        from app.ai.discussion_convene import version as convene_version

        with engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.id == run_id,
                )
            ).scalar_one()
        prompt_version = convene_version(rc, snapshot)
    if purpose == "change_work_package" and snapshot.get("discussion_input"):
        from app.ai.discussion_followup import version as followup_version

        with engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = followup_version(rc, snapshot)
    if purpose == "test_plan_suggestion":
        with engine.connect() as c:
            run_context = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = version_from_run(purpose, run_context)
    if purpose == "process_template_configuration":
        with engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
                )
            ).scalar_one()
        prompt_version = rc["process_template_prompt_version"]
    if auth["body"]["purpose"] != purpose:
        raise BudgetLedgerError("APPLICATION_CONTEXT_PURPOSE_INVALID")
    prompt, output_type = contract(purpose, prompt_version=prompt_version)
    verify_application_authorization(
        engine,
        tenant_id=tenant_id,
        run_id=run_id,
        project_id=project_id,
        agent_key=prompt["agent_key"],
    )
    snapshot = json_value(snapshot)
    body = context_receipt_body(
        context=context,
        prompt_version=prompt["version"],
        system_prompt=prompt["system_prompt"],
        instruction=prompt["instruction"],
        output_type=output_type,
    )
    current_bundle = bundle(purpose, prompt_version=prompt_version)
    with engine.begin() as c:
        c.execute(
            select(tables.agent_runs.c.id).where(tables.agent_runs.c.id == run_id).with_for_update()
        ).scalar_one()
        existing = (
            c.execute(
                select(tables.application_context_observations).where(
                    tables.application_context_observations.c.tenant_id == tenant_id,
                    tables.application_context_observations.c.run_id == run_id,
                    tables.application_context_observations.c.model_call_id == model_call_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if (
                existing["context_body"] != body
                or existing["output_body"] != snapshot
                or existing["bundle"] != current_bundle
            ):
                raise BudgetLedgerError("APPLICATION_CONTEXT_CONFLICT")
            return
        from app.ai.application_context import require_new_context_history

        require_new_context_history(
            c,
            tenant_id,
            run_id,
            call_id=model_call_id
            if purpose == "change_discussion" or snapshot.get("phase") == "discussion_convene"
            else None,
        )
        oid, stamp = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()

        def source(
            kind: str, ref: UUID | int, value: Any, locator: str | None = None
        ) -> dict[str, Any]:
            return dict(
                tenant_id=tenant_id,
                project_id=project_id,
                kind=kind,
                ref_id=ref,
                as_of=stamp,
                digest=digest(value),
                locator=locator,
            )

        if purpose == "meeting_planning":
            sources = [source("meeting_planning_brief", UUID(snapshot["brief_id"]), snapshot)]
            shown, total = len(context["references"]), len(context["references"])
            status = (
                "partial"
                if any(s.get("omitted_characters") for s in snapshot["sources"])
                else "complete"
            )
            continuation = "仅本次填写要求和明确选入的业务字段摘录；其余项目资料与日历可用性未知"
        elif purpose == "intake_organization":
            sources = [source("intake_ai_brief", UUID(snapshot["brief_id"]), snapshot)]
            shown = len(snapshot["fragments"])
            total = sum(item["fragment_count"] for item in snapshot["sources"].values())
            status = "partial" if shown < total else "complete"
            continuation = "仅处理本次明确选择的抽取片段，未选范围和未抽取内容保留未知"
        elif purpose == "process_template_configuration":
            sources = [source("process_template_brief", UUID(snapshot["id"]), snapshot)]
            shown, total, status, continuation = 1, 1, "complete", None
        elif purpose == "change_discussion":
            sources = [
                source(
                    "discussion_projection",
                    UUID(snapshot.get("topic_id") or snapshot["ecr_id"]),
                    snapshot,
                )
            ]
            tool_ids = set(snapshot.get("research_tool_ids", [])) | {
                item["id"]
                for item in snapshot.get("research_inputs", [])
                if item.get("origin") == "agent_research"
            }
            for tool_id in sorted(tool_ids):
                actual = c.execute(
                    select(tables.application_tool_observations.c.output_body).where(
                        tables.application_tool_observations.c.tenant_id == tenant_id,
                        tables.application_tool_observations.c.run_id == run_id,
                        tables.application_tool_observations.c.id == UUID(tool_id),
                    )
                ).scalar_one()
                sources.append(source("application_tool_observation", UUID(tool_id), actual))
            shown = total = len(snapshot["references"])
            status = "partial" if snapshot["projection"]["missing"] else "complete"
            continuation = "请核对本席位明确缺项" if status == "partial" else None
        elif purpose == "product_evaluation":
            sources = [source("market_space", UUID(snapshot["market_space_id"]), snapshot)]
            if "references" in snapshot:
                shown = total = len(snapshot["references"])
            else:
                shown = len(snapshot["model_context"]["references"])
                total = shown + len(snapshot["model_context"]["omitted_references"])
            status = "partial" if snapshot.get("warnings") or shown < total else "complete"
            continuation = "影子评测保留原来源缺项与覆盖限制" if status == "partial" else None
        elif purpose == "product_work":
            sources = [source("market_space", UUID(snapshot["market_space_id"]), snapshot)]
            shown = total = len(snapshot["references"])
            status = "partial" if snapshot["warnings"] else "complete"
            continuation = "请核对本次来源缺项与覆盖限制" if status == "partial" else None
        elif purpose == "product_matrix":
            sources = [
                source("product_matrix_record", UUID(snapshot["selection"]["record_id"]), snapshot)
            ]
            shown = len(snapshot["model_context"]["references"])
            total = shown + len(snapshot["model_context"]["omitted_references"])
            status = "partial" if shown < total else "complete"
            continuation = (
                "仅原对照及明确选入的路线图；省略范围与实际经营结果保持未知"
                if status == "partial"
                else None
            )
        elif purpose == "executive_brief":
            sources = [
                source(
                    "executive_management_snapshot",
                    UUID(snapshot["project_id"]),
                    snapshot,
                )
            ]
            shown = total = len(snapshot["model_context"]["references"])
            status = (
                "partial"
                if (
                    snapshot["model_context"]["omitted_references"]
                    or any(v["omitted_fields"] for v in snapshot["model_context"]["references"])
                )
                else "complete"
            )
            continuation = "核对原看板的缺数和省略明细" if status == "partial" else None
        elif purpose == "portfolio_explanation":
            sources = [
                source(
                    "portfolio_comparison_snapshot",
                    UUID(snapshot["selection"]["comparison_id"]),
                    snapshot,
                )
            ]
            shown = total = len(snapshot["model_context"]["references"])
            status = "complete"
            continuation = None
        elif purpose == "cost_reduction":
            sources = [source("cost_reduction_snapshot", UUID(snapshot["project_id"]), snapshot)]
            refs = snapshot["model_context"]["references"]
            shown = total = len(refs)
            status = "partial" if any(r["omitted_fields"] for r in refs) else "complete"
            continuation = (
                "原费用明细有省略或来源变化，须回原计算核对" if status == "partial" else None
            )
        elif purpose == "event_issue":
            sources = [source("event_issue_source", UUID(snapshot["entity_id"]), snapshot)]
            shown = total = len(snapshot["context"]["references"])
            status = "complete"
            continuation = None
        elif purpose == "supplier_recovery":
            sources = [source("supplier_recovery_snapshot", UUID(snapshot["project_id"]), snapshot)]
            refs = snapshot["model_context"]["references"]
            shown = len(refs)
            total = shown + len(snapshot["model_context"]["omitted_references"])
            status = (
                "partial" if shown < total or any(r["omitted_fields"] for r in refs) else "complete"
            )
            continuation = "请缩小选定资料范围后重新准备" if status == "partial" else None
        elif purpose == "quality_work_package":
            sources = [source("quality_snapshot", UUID(snapshot["ncr_id"]), snapshot)]
            refs = snapshot["model_context"]["references"]
            shown = len(refs)
            total = shown + len(snapshot["model_context"]["omitted_references"])
            status = (
                "partial" if shown < total or any(r["omitted_fields"] for r in refs) else "complete"
            )
            continuation = "请缩小选定资料范围后重新准备" if status == "partial" else None
        elif purpose == "change_work_package":
            sources = [source("change_impact_snapshot", UUID(snapshot["ecr_id"]), snapshot)]
            if snapshot.get("discussion_input"):
                from app.ai.discussion_followup import require_current as current_discussion

                current_discussion(c, tenant_id, snapshot)
                discussion_input = snapshot["discussion_input"]
                sources.append(
                    source(
                        "change_discussion_input", UUID(discussion_input["id"]), discussion_input
                    )
                )
            from app.ai.change_application_tools import TRACE

            trace = (
                c.execute(
                    select(tables.application_tool_observations)
                    .join(
                        tables.agent_tool_intents,
                        tables.agent_tool_intents.c.id
                        == tables.application_tool_observations.c.tool_intent_id,
                    )
                    .where(
                        tables.application_tool_observations.c.tenant_id == tenant_id,
                        tables.application_tool_observations.c.run_id == run_id,
                        tables.agent_tool_intents.c.tool_key == TRACE,
                    )
                )
                .mappings()
                .one()
            )
            if trace["metadata"]["status"] not in {"completed", "partial"}:
                raise BudgetLedgerError("APPLICATION_TOOL_CONTEXT_UNAVAILABLE")
            sources.append(
                source("application_tool_observation", trace["id"], trace["output_body"])
            )
            coverage = snapshot["model_context"]["coverage"]
            shown = len(snapshot["model_context"]["references"])
            total = shown + coverage["omitted_reference_count"]
            status = (
                "partial"
                if total > shown
                or coverage["partial_reference_count"]
                or trace["metadata"]["status"] == "partial"
                else "complete"
            )
            continuation = "请减少关联层数或缩小人工范围后重新准备资料" if shown < total else None
        elif purpose in {
            "meeting_reading",
            "meeting_minutes",
            "meeting_actions",
            "meeting_decisions",
            "meeting_business",
        }:
            sources = [
                source(
                    "meeting",
                    UUID(snapshot["meeting_id"]),
                    {"title": snapshot["meeting_title"], "status": snapshot["meeting_status"]},
                ),
                source("meeting_transcript", UUID(snapshot["transcript_id"]), snapshot),
            ]
            shown = total = len(snapshot["segments"])
            status, continuation = "complete", None
        elif purpose == "risk_suggestion":
            if project_id is None:
                raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
            sources = [
                source("project", project_id, {k: snapshot[k] for k in ("project", "execution")})
            ]
            sources += [source("event", int(e["id"]), e) for e in snapshot["trigger_events"]]
            shown, total, status, continuation = len(sources), len(sources), "complete", None
        elif purpose == "test_plan_suggestion":
            sources = [
                source("test_plan", UUID(snapshot["plan_id"]), snapshot["state"]),
                source("application_request", run_id, snapshot["messages"]),
            ]
            sources += [
                source(s["kind"], UUID(s["id"]), s, s["locator"])
                for s in snapshot["source_snapshots"]
            ]
            if snapshot["previous_finding_id"]:
                sources.append(
                    source(
                        "finding",
                        UUID(snapshot["previous_finding_id"]),
                        snapshot["previous_payload"],
                    )
                )
            shown, total, status, continuation = len(sources), len(sources), "complete", None
        else:
            sources = [
                source(
                    "report_input_snapshot",
                    oid,
                    snapshot,
                    "upload_sha256:" + snapshot["request"]["file_sha256"],
                )
            ]
            shown, total = len(snapshot["sample_rows"]), snapshot["total_rows"]
            status = "partial" if shown < total else "complete"
            continuation = (
                f"upload:{snapshot['request']['file_sha256']}:row:{shown + 1}"
                if shown < total
                else None
            )
        observed = Observation.model_validate(
            dict(
                id=oid,
                tenant_id=tenant_id,
                run_id=run_id,
                tool_call_id=uuid4(),
                parent_observation_id=None,
                sequence=1,
                tool_version=purpose + "-source-adapter.v1",
                status="completed" if status == "complete" else "partial",
                sources=sources,
                observed_at=stamp,
                as_of=stamp,
                fresh_until=None,
                acl_policy_version=auth["body"]["policy_version"],
                allowed_purpose=purpose,
                taint="internal" if purpose == "risk_suggestion" else "untrusted_external",
                input_digest=digest(context),
                output_digest=digest(snapshot),
                shown_count=shown,
                total_count=total,
                truncated=shown < total,
                continuation=continuation,
            )
        )
        c.execute(
            tables.application_context_observations.insert().values(
                id=oid,
                tenant_id=tenant_id,
                run_id=run_id,
                authorization_id=auth["id"],
                model_call_id=model_call_id,
                metadata=observed.model_dump(mode="json"),
                output_body=snapshot,
                context_body=body,
                bundle=current_bundle,
                created_at=stamp,
            )
        )


def sources_current(
    engine: Engine, invocation: Any, purpose: str, snapshot: dict[str, Any]
) -> bool:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == invocation.tenant_id,
                    tables.agent_runs.c.id == invocation.run_id,
                )
            )
            .mappings()
            .one()
        )
        if purpose == "meeting_planning":
            from app.ai.meeting_planning_context import bound_source as planning_source
            from app.ai.meeting_planning_context import model_context as planning_context

            original = planning_source(
                c,
                invocation.tenant_id,
                invocation.project_id,
                run["requested_by_user_id"],
                run["run_context"],
            )
            return (
                run["scope_kind"] == "project"
                and snapshot
                == {
                    "brief_id": str(original["id"]),
                    "source_digest": original["source_digest"],
                    **original["source_snapshot"],
                }
                and invocation.prompt_version
                == run["run_context"]["meeting_planning_prompt_version"]
                and invocation.context == planning_context(snapshot)
            )
        if purpose == "intake_organization":
            from app.ai.intake_ai_context import bound_source as intake_source
            from app.ai.intake_ai_context import model_context as intake_context

            original = intake_source(
                c,
                invocation.tenant_id,
                invocation.project_id,
                run["requested_by_user_id"],
                run["run_context"],
            )
            return (
                run["scope_kind"] == "project"
                and snapshot == {"brief_id": str(original["id"]), **original["source_snapshot"]}
                and invocation.prompt_version == run["run_context"]["intake_prompt_version"]
                and invocation.context == intake_context(snapshot)
            )
        if purpose == "process_template_configuration":
            from app.ai.process_template_context import bound_source, model_context

            original = bound_source(c, invocation.tenant_id, run["run_context"])
            return (
                invocation.project_id is None
                and run["scope_kind"] == "tenant"
                and snapshot == original["source_snapshot"]
                and invocation.prompt_version
                == run["run_context"]["process_template_prompt_version"]
                and invocation.context == model_context(snapshot, invocation.prompt_version)
            )
        if purpose == "change_discussion":
            from app.ai.discussion_research import current as research_current
            from app.ai.discussion_sources import current as discussion_source

            if not research_current(
                c,
                invocation.tenant_id,
                run["requested_by_user_id"],
                snapshot.get("research_inputs", []),
            ):
                return False

            from app.ai.change_notice_preparation import require_discussion_enabled

            require_discussion_enabled(snapshot["source"])
            discussion_current = discussion_source(
                c,
                invocation.tenant_id,
                invocation.project_id,
                {
                    "ecr_id": UUID(snapshot["ecr_id"]) if snapshot["ecr_id"] else None,
                    "source": snapshot["source"],
                    "config": {
                        "request": {
                            "depth": snapshot["source"]["model_context"]["coverage"]["depth"]
                        }
                    },
                },
            )
            return bool(discussion_current["digest"] == snapshot["source"]["digest"])
        if purpose == "product_evaluation":
            from app.ai.product_shadow_evaluation import current as shadow_current

            try:
                return bool(snapshot == run["run_context"]["evaluation_source"]
                            and shadow_current(c, run, invocation))
            except (ValueError, LookupError, PermissionError):
                return False
        if purpose == "product_work":
            from app.ai.product_work_context import contract as product_contract
            from app.ai.product_work_context import model_context as product_context
            from app.ai.product_work_context import rebuild as product_state
            from app.ai.product_work_runs import authorize as product_authorize
            from app.ai.project_discussion_sources import actor
            from app.contracts.product_work_ai import ProductWorkSelection

            try:
                selected = ProductWorkSelection.model_validate(snapshot["selection"])
                current_actor = actor(c, invocation.tenant_id, run["requested_by_user_id"])
                product_authorize(
                    c, current_actor, run["market_space_id"], selected.product_line_id, write=True
                )
                return bool(
                    run["scope_kind"] == "market_space"
                    and run["project_id"] is None
                    and invocation.project_id is None
                    and str(run["market_space_id"]) == snapshot["market_space_id"]
                    and snapshot == run["run_context"]["product_work_source"]
                    and invocation.prompt_version
                    == product_contract(run["run_context"]["product_work_prompt_version"])[
                        0
                    ].version
                    and product_state(c, invocation.tenant_id, snapshot)["digest"]
                    == snapshot["digest"]
                    and invocation.context
                    == product_context(
                        snapshot,
                        run["run_context"].get("product_work_user_instruction", ""),
                        prompt_version=invocation.prompt_version,
                        tenant_id=invocation.tenant_id,
                    )
                )
            except (ValueError, LookupError, PermissionError):
                return False
        if purpose == "product_matrix":
            from app.ai.product_matrix_preparation import (
                model_context as matrix_context,
            )
            from app.ai.product_matrix_preparation import (
                rebuild as matrix_state,
            )
            from app.ai.product_matrix_preparation import (
                version as matrix_version,
            )

            try:
                return bool(
                    run["scope_kind"] == "market_space"
                    and run["project_id"] is None
                    and invocation.project_id is None
                    and str(run["market_space_id"]) == snapshot["market_space_id"]
                    and snapshot == run["run_context"]["matrix_source"]
                    and invocation.prompt_version == matrix_version(run["run_context"], snapshot)
                    and matrix_state(c, invocation.tenant_id, snapshot)["digest"]
                    == snapshot["digest"]
                    and invocation.context
                    == matrix_context(
                        snapshot, run["run_context"].get("matrix_user_instruction", "")
                    )
                )
            except (ValueError, LookupError, PermissionError):
                return False
        if purpose == "executive_brief":
            from app.ai.executive_brief_preparation import rebuild as executive_state
            from app.ai.executive_brief_runs import model_context as executive_context

            try:
                current_executive = executive_state(
                    c, invocation.tenant_id, invocation.project_id, snapshot
                )
            except (ValueError, LookupError, PermissionError):
                return False
            return bool(
                current_executive["digest"] == snapshot["digest"]
                and invocation.context
                == executive_context(
                    snapshot, run["run_context"].get("executive_user_instruction", "")
                )
            )
        if purpose == "portfolio_explanation":
            from app.ai.portfolio_explanation_preparation import rebuild as portfolio_state
            from app.ai.portfolio_explanation_runs import model_context as portfolio_context

            try:
                current_portfolio = portfolio_state(
                    c, invocation.tenant_id, invocation.project_id, snapshot
                )
            except (ValueError, LookupError, PermissionError):
                return False
            return bool(
                current_portfolio["digest"] == snapshot["digest"]
                and invocation.context
                == portfolio_context(
                    snapshot, run["run_context"].get("portfolio_user_instruction", "")
                )
            )
        if purpose == "cost_reduction":
            from app.ai.cost_reduction_preparation import rebuild as cost_state

            try:
                current_cost = cost_state(
                    c,
                    invocation.tenant_id,
                    invocation.project_id,
                    snapshot,
                )
            except (ValueError, LookupError, PermissionError):
                return False
            return bool(current_cost["digest"] == snapshot["digest"])
        if purpose == "event_issue":
            from app.ai.issue_event_proposal import PROMPT as ISSUE_PROMPT
            from app.ai.issue_event_runs import RUN_VERSION, rebuild
            from app.ai.issue_event_runs import model_context as event_issue_model_context
            from app.ai.issue_event_trigger_runs import require_current as require_issue_event
            from app.ai.project_discussion_sources import actor

            try:
                if (
                    run["agent_key"] != "quality_intelligence"
                    or run["context_version"] != RUN_VERSION
                    or run["project_id"] != invocation.project_id
                    or snapshot != run["run_context"].get("issue_event_source")
                    or invocation.prompt_version != ISSUE_PROMPT.version
                ):
                    return False
                current_actor = actor(c, invocation.tenant_id, run["requested_by_user_id"])
                require_issue_event(c, run)
                rebuild(c, current_actor, invocation.project_id, snapshot, write=True)
                return bool(invocation.context == event_issue_model_context(snapshot))
            except (ValueError, LookupError, PermissionError):
                return False
        if purpose == "supplier_recovery":
            from app.ai.supplier_recovery_preparation import Selection
            from app.ai.supplier_recovery_preparation import source_state as supply_state

            try:
                current_supply = supply_state(
                    c,
                    invocation.tenant_id,
                    invocation.project_id,
                    Selection.model_validate(snapshot["selection"]),
                )
            except (ValueError, LookupError):
                return False
            return bool(current_supply["digest"] == snapshot["digest"])
        if purpose == "quality_work_package":
            from app.ai.quality_preparation import source_state as quality_source_state
            from app.domain.product_workspace import ProductWorkError
            from app.domain.quality_operations import Evidence

            try:
                quality_actual = quality_source_state(
                    c,
                    invocation.tenant_id,
                    invocation.project_id,
                    UUID(snapshot["ncr_id"]),
                    [
                        Evidence.model_validate(
                            {k: s[k] for k in ("kind", "reference", "expected_digest", "locator")}
                        )
                        for s in snapshot["source_values"]
                    ],
                )
            except ProductWorkError:
                return False
            return bool(quality_actual["digest"] == snapshot["digest"])
        if purpose == "change_work_package":
            from app.ai.change_notice_preparation import rebuild as change_source_state
            from app.ai.change_notice_preparation import require_enabled
            from app.domain.product_workspace import ProductWorkError

            try:
                from app.ai.discussion_followup import require_current as current_discussion

                current_discussion(c, invocation.tenant_id, snapshot)
                actual = change_source_state(
                    c,
                    invocation.tenant_id,
                    invocation.project_id,
                    snapshot,
                    run["requested_by_user_id"],
                )
                require_enabled(snapshot)
            except (ProductWorkError, PermissionError):
                return False
            return bool(actual["digest"] == snapshot["digest"])
        if purpose in {
            "meeting_reading",
            "meeting_minutes",
            "meeting_actions",
            "meeting_decisions",
            "meeting_business",
        }:
            from app.ai.meeting_event_runs import require_current as require_meeting_event
            from app.ai.meeting_reading import source_state
            from app.domain.meetings import MeetingNotFoundError, MeetingStateError

            try:
                require_meeting_event(c, run)
                current_source = source_state(
                    c,
                    invocation.tenant_id,
                    invocation.project_id,
                    UUID(snapshot["meeting_id"]),
                    UUID(snapshot["transcript_id"]),
                    include_minutes=purpose == "meeting_minutes",
                    include_actions=purpose == "meeting_actions",
                    include_decisions=purpose == "meeting_decisions",
                    include_business=purpose == "meeting_business",
                )
            except (MeetingNotFoundError, MeetingStateError, PermissionError):
                return False
            return current_source == snapshot
        if purpose == "risk_suggestion":
            from app.ai.context_builder import RunContextBuilder
            from app.ai.runtime_contract import FrozenRunContext

            current = RunContextBuilder().build(
                c, run=run, built_at=datetime.fromisoformat(snapshot["built_at"])
            )
            before = FrozenRunContext.model_validate(snapshot)

            # Runtime counters are frozen as-of facts; our own invocation changes them.
            def business(values: dict[str, object]) -> dict[str, object]:
                return {
                    k: v
                    for k, v in values.items()
                    if k not in {"remaining_tokens_today", "agent_runs_today"}
                }

            return (
                current.project == before.project
                and business(current.execution) == business(before.execution)
                and current.trigger_events == before.trigger_events
            )
        if purpose == "test_plan_suggestion":
            from app.domain.test_plan_changes import plan_state
            from app.domain.test_plan_sources import resolve_sources, selections_for

            state = plan_state(
                c,
                tenant_id=invocation.tenant_id,
                project_id=invocation.project_id,
                plan_id=UUID(snapshot["plan_id"]),
            )
            sources = resolve_sources(
                c,
                tenant_id=invocation.tenant_id,
                project_id=invocation.project_id,
                selections=selections_for(snapshot["source_snapshots"]),
            )
            if json_value(state) != snapshot["state"] or sources != snapshot["source_snapshots"]:
                return False
            if snapshot["previous_finding_id"]:
                previous = (
                    c.execute(
                        select(tables.findings).where(
                            tables.findings.c.tenant_id == invocation.tenant_id,
                            tables.findings.c.project_id == invocation.project_id,
                            tables.findings.c.id == UUID(snapshot["previous_finding_id"]),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous is None or previous["status"] not in {"pending_review", "accepted"}:
                    return False
                old = c.execute(
                    select(tables.agent_runs.c.run_context).where(
                        tables.agent_runs.c.id == previous["run_id"],
                        tables.agent_runs.c.tenant_id == invocation.tenant_id,
                    )
                ).scalar_one()
                if (
                    old.get("superseded_by")
                    or json_value(previous["accepted_payload"] or previous["proposed_payload"])
                    != snapshot["previous_payload"]
                ):
                    return False
            return True
        if purpose == "report_mapping":
            return (
                run["run_context"].get("mapping_request") == snapshot["request"]
                and c.execute(
                    select(tables.test_plans.c.id).where(
                        tables.test_plans.c.tenant_id == invocation.tenant_id,
                        tables.test_plans.c.project_id == invocation.project_id,
                        tables.test_plans.c.id == UUID(snapshot["request"]["plan_id"]),
                    )
                ).first()
                is not None
            )
    return False
