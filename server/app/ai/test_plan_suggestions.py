"""Explicit, bounded conversation requests producing typed Findings only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select, update

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import original_observation, try_resume
from app.ai.application_waits import resume_wait, save_test_plan_wait
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_finding
from app.ai.run_budget_creation import freeze_created_application_run
from app.ai.test_plan_versions import DEFAULT_VERSION, WORK_PACKAGE_VERSION, require_version_live
from app.ai.test_plan_versions import contract as version_contract
from app.db.schema import tables
from app.domain.test_plan_changes import (
    TestPlanChangeError,
    TestPlanChangePayload,
    digest,
    plan_state,
    proposal_items,
    proposal_references,
    validate_changes,
)
from app.domain.test_plan_sources import (
    PlanSourceError,
    SourceSelection,
    resolve_sources,
    selections_for,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

PROMPT = json.loads((Path(__file__).with_name("prompts") / "test_plan_change_v5.json").read_text())
AGENT = "quality_intelligence"
FINDING_TYPE = "test_plan_change"


class TestPlanSuggestionService:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway) -> None:
        self._engine = engine
        self._gateway = gateway

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        actor_user_id: UUID,
        message: str,
        request_id: UUID,
        previous_finding_id: UUID | None,
        sources: list[SourceSelection] | None = None,
        auth_version: int | None = None,
        enqueue: bool = False,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        require_live_finding(AGENT, FINDING_TYPE)
        selected_version = prompt_version or DEFAULT_VERSION
        require_version_live(selected_version)
        selected_prompt, output_type = version_contract(selected_version)
        if enqueue and getattr(self._gateway, "creation_budget_profile", None) is None:
            raise TestPlanChangeError("APPLICATION_QUEUE_BUDGET_REQUIRED")
        request: dict[str, Any] = {
            "request_id": str(request_id),
            "plan_id": str(plan_id),
            "message": message,
            "previous_finding_id": str(previous_finding_id) if previous_finding_id else None,
            "actor_user_id": str(actor_user_id),
        }
        if prompt_version is not None:
            request["prompt_version"] = selected_version
        if sources is not None:
            request["sources"] = [s.model_dump(mode="json") for s in sources]
        with self._engine.begin() as connection:
            # Serialize subscription/request creation without holding a lock during inference.
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            replay = (
                connection.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.agent_key == AGENT,
                        tables.agent_runs.c.run_context["test_plan_request"][
                            "request_id"
                        ].as_string()
                        == str(request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                replay
                and replay["run_context"].get("test_plan_prompt_version", DEFAULT_VERSION)
                != selected_version
            ):
                raise TestPlanChangeError(
                    "原请求已固定其他提示词版本，请查看原运行或显式发起新请求"
                )
            resuming = False
            queue_claimed = False
            if replay:
                if replay["run_context"]["test_plan_request"] != request:
                    raise TestPlanChangeError("请求编号已用于其他内容")
                if enqueue and replay["status"] in {"queued", "running"}:
                    return {
                        "status": replay["status"],
                        "run_id": str(replay["id"]),
                        "finding_id": None,
                        "error_code": None,
                    }
                try:
                    if (
                        not enqueue
                        and replay["status"] == "queued"
                        and replay["run_context"].get("application_queue_version") == 1
                    ):
                        from app.ai.application_queue_claim import claim_application_queue

                        replay = claim_application_queue(
                            connection,
                            self._gateway,
                            replay,
                            auth_version=auth_version,
                            purpose="test_plan_suggestion",
                        )
                        queue_claimed = True
                    elif not enqueue:
                        resuming = try_resume(
                            connection,
                            self._gateway,
                            replay,
                            actor=actor_user_id,
                            auth_version=auth_version,
                            purpose="test_plan_suggestion",
                        )
                except BudgetLedgerError as error:
                    raise TestPlanChangeError(error.code) from error
                if not resuming and not queue_claimed:
                    if replay["status"] == "running":
                        raise TestPlanChangeError("该请求仍在生成，请稍后查看候选")
                    replayed_result = dict(
                        replay["run_context"].get("result")
                        or {
                            "status": "unavailable",
                            "finding_id": None,
                            "error_code": replay["error_code"] or "TEST_PLAN_REQUEST_INCOMPLETE",
                        }
                    )
                    if enqueue:
                        replayed_result["run_id"] = str(replay["id"])
                    return replayed_result
            if resuming:
                assert replay is not None
                saved = original_observation(connection, replay)["output_body"]
                state = saved["state"]
                base_digest = replay["run_context"]["base_digest"]
                messages = saved["messages"]
                previous_payload = (
                    TestPlanChangePayload.model_validate(saved["previous_payload"])
                    if saved["previous_payload"]
                    else None
                )
                source_snapshots = saved["source_snapshots"]
                sources = selections_for(source_snapshots)
            else:
                state = plan_state(
                    connection, tenant_id=tenant_id, project_id=project_id, plan_id=plan_id
                )
                base_digest = digest(state)
                messages = []
                previous_payload = None
                parent_run_id = None
                if previous_finding_id:
                    previous = (
                        connection.execute(
                            select(tables.findings).where(
                                tables.findings.c.tenant_id == tenant_id,
                                tables.findings.c.project_id == project_id,
                                tables.findings.c.id == previous_finding_id,
                                tables.findings.c.finding_type == FINDING_TYPE,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if not previous or previous["status"] not in {"pending_review", "accepted"}:
                        raise TestPlanChangeError("原建议不可继续，请重新开始对话")
                    old_context = connection.execute(
                        select(tables.agent_runs.c.run_context).where(
                            tables.agent_runs.c.id == previous["run_id"],
                            tables.agent_runs.c.tenant_id == tenant_id,
                        )
                    ).scalar_one()
                    if (
                        old_context.get("superseded_by")
                        or old_context["base_digest"] != base_digest
                    ):
                        raise TestPlanChangeError("原计划或候选已变化，请在最新版本重新开始")
                    parent_run_id = previous["run_id"]
                    previous_payload = TestPlanChangePayload.model_validate(
                        previous["accepted_payload"] or previous["proposed_payload"]
                    )
                    if previous_payload.base_plan_id != plan_id:
                        raise TestPlanChangeError("原建议不属于当前计划")
                    messages = list(old_context["messages"])
                if len(messages) >= 12:
                    raise TestPlanChangeError("本轮已达 12 条，请整理要求后开启新对话")
                messages.append(message)
                if sources is None:
                    sources = (
                        selections_for(previous_payload.source_snapshots)
                        if previous_payload
                        else []
                    )
                source_snapshots = resolve_sources(
                    connection, tenant_id=tenant_id, project_id=project_id, selections=sources
                )
            if queue_claimed:
                assert replay is not None
                frozen = replay["run_context"]
                if (
                    frozen["base_digest"] != base_digest
                    or frozen["messages"] != messages
                    or frozen["source_snapshots"] != source_snapshots
                    or frozen.get("previous_payload_digest")
                    != (
                        digest(previous_payload.model_dump(mode="json"))
                        if previous_payload
                        else None
                    )
                ):
                    raise TestPlanChangeError("TEST_PLAN_QUEUED_INPUT_CHANGED")
            refs = proposal_references(state, messages, source_snapshots)
            source_labels = {
                s[
                    "reference_id"
                ]: f"{s['label']} · 版本 {s['version']} · {s['locator']} · {s['status']}"
                for s in source_snapshots
            }
            base_items = [
                {
                    k: item.get(k)
                    for k in (
                        "key",
                        "title",
                        "category",
                        "method",
                        "acceptance_criteria",
                        "required",
                        "applicable",
                        "exclusion_reason",
                        "applicability",
                        "evidence_requirements",
                    )
                }
                for item in proposal_items(state)
            ]
            if selected_version == WORK_PACKAGE_VERSION:
                prepared_items = {
                    item["key"]: item.get("execution_preparation") for item in proposal_items(state)
                }
                for item in base_items:
                    item["execution_preparation"] = prepared_items.get(item["key"])
            context: dict[str, Any] = {
                "question": message,
                "test_plan": {
                    "product_type": state["plan"]["template_snapshot"]["product_type"],
                    "items": base_items,
                    "previous_proposal": previous_payload.model_dump_json()
                    if previous_payload
                    else None,
                },
                "references": [
                    {"reference_id": key, "excerpt": value, "label": source_labels.get(key, key)}
                    for key, value in refs.items()
                ],
            }
            if len(json.dumps(context, ensure_ascii=False)) > 100_000:
                raise TestPlanChangeError("上下文超过本次处理范围，请拆分要求；未静默截断")
            if not FindingQualityService.is_output_allowed_connection(
                connection, tenant_id=tenant_id, agent_key=AGENT, finding_type=FINDING_TYPE
            ):
                raise TestPlanChangeError("此类建议因质量反馈已暂停，请使用人工路径")
            if resuming or queue_claimed:
                assert replay is not None
                run_id = replay["id"]
                run_context = replay["run_context"]
                event_row_id = replay["event_row_ids"][0]
            else:
                sub_id = connection.execute(
                    select(tables.agent_subscriptions.c.id).where(
                        tables.agent_subscriptions.c.tenant_id == tenant_id,
                        tables.agent_subscriptions.c.agent_key == AGENT,
                    )
                ).scalar_one_or_none()
                if sub_id is None:
                    sub_id = uuid4()
                    connection.execute(
                        tables.agent_subscriptions.insert().values(
                            id=sub_id, tenant_id=tenant_id, agent_key=AGENT
                        )
                    )
                now = datetime.now(UTC)
                run_id = uuid4()
                event = EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"test-plan-request:{run_id}",
                        event_type="NPI_RECORD_CHANGED",
                        source="npi_service",
                        entity_id=plan_id,
                        payload={"record_type": "test_plan", "action": "suggestion_requested"},
                        occurred_at=now,
                    ),
                    AuditDraft(
                        action="test_plan.suggestion_requested",
                        after_snapshot={"run_id": str(run_id), "request": request},
                    ),
                )
                run_context = {
                    "test_plan_request": request,
                    "test_plan_prompt_version": selected_version,
                    "base_digest": base_digest,
                    "messages": messages,
                    "source_snapshots": source_snapshots,
                    **(
                        {
                            "application_queue_version": 1,
                            "previous_payload_digest": digest(
                                previous_payload.model_dump(mode="json")
                            )
                            if previous_payload
                            else None,
                        }
                        if enqueue
                        else {}
                    ),
                }
                connection.execute(
                    tables.agent_runs.insert().values(
                        id=run_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        subscription_id=sub_id,
                        agent_key=AGENT,
                        status="running",
                        request_id=str(request_id),
                        requested_by_user_id=actor_user_id,
                        context_version="test-plan-request-v1",
                        window_started_at=now - timedelta(microseconds=1),
                        window_ended_at=now + timedelta(microseconds=1),
                        first_event_row_id=event.event_row_id,
                        last_event_row_id=event.event_row_id,
                        event_count=1,
                        event_row_ids=[event.event_row_id],
                        run_context=run_context,
                        started_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                try:
                    freeze_created_application_run(
                        connection,
                        self._gateway,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        parent_run_id=parent_run_id,
                        actor_user_id=actor_user_id,
                        purpose="test_plan_suggestion",
                        auth_version=auth_version,
                        issue_lease=not enqueue,
                    )
                    resume_wait(
                        connection,
                        self._gateway,
                        tenant=tenant_id,
                        parent_run=parent_run_id,
                        child_run=run_id,
                        queued_child=enqueue,
                    )
                except BudgetLedgerError as error:
                    raise TestPlanChangeError(error.code) from error
                event_row_id = event.event_row_id
                if enqueue:
                    connection.execute(
                        tables.agent_runs.update()
                        .where(tables.agent_runs.c.id == run_id)
                        .values(status="queued", started_at=None, updated_at=func.clock_timestamp())
                    )
        if enqueue:
            return {
                "status": "queued",
                "run_id": str(run_id),
                "finding_id": None,
                "error_code": None,
            }
        try:
            require_live_finding(AGENT, FINDING_TYPE)
            require_version_live(selected_version)
            from app.ai.application_domain_context import record

            record(
                self._engine,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                model_call_id=model_call_id(run_id, ModelCallSlot.TEST_PLAN_SUGGESTION),
                purpose="test_plan_suggestion",
                context=context,
                snapshot=dict(
                    plan_id=str(plan_id),
                    state=state,
                    source_snapshots=source_snapshots,
                    messages=messages,
                    previous_finding_id=str(previous_finding_id) if previous_finding_id else None,
                    previous_payload=previous_payload.model_dump(mode="json")
                    if previous_payload
                    else None,
                ),
            )
            result = self._gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    model_call_id=model_call_id(run_id, ModelCallSlot.TEST_PLAN_SUGGESTION),
                    agent_key=AGENT,
                    agent_tier=AgentTier.REASONING,
                    prompt_version=selected_prompt["version"],
                    system_prompt=selected_prompt["system_prompt"],
                    instruction=selected_prompt["instruction"],
                    context=context,
                ),
                output_type,
            )
            if result.status != "succeeded" or result.output is None:
                return self._finish(
                    run_id, tenant_id, run_context, None, result.error_code or "MODEL_UNAVAILABLE"
                )
            if result.invocation_id is None:
                raise TestPlanChangeError("模型调用缺少可追溯记录")
            assessment = result.output.bind_sources(refs)
            validate_changes(
                assessment,
                state=state,
                messages=messages,
                ready=False,
                source_snapshots=source_snapshots,
            )
            payload = TestPlanChangePayload(
                **assessment.model_dump(),
                base_plan_id=plan_id,
                base_digest=base_digest,
                messages=messages,
                base_items=base_items,
                source_snapshots=source_snapshots,
            )
            if len(payload.model_dump_json().encode()) > 200_000:
                raise TestPlanChangeError("建议内容超过审阅范围，请拆分要求后重试")
            with self._engine.begin() as connection:
                bind_write(connection, self._gateway, tenant_id, run_id)
                require_live_finding(AGENT, FINDING_TYPE)
                # Use the same finding→project lock order as review/apply.
                previous = None
                if previous_finding_id:
                    previous = (
                        connection.execute(
                            select(tables.findings)
                            .where(
                                tables.findings.c.tenant_id == tenant_id,
                                tables.findings.c.id == previous_finding_id,
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .one()
                    )
                    old_context = connection.execute(
                        select(tables.agent_runs.c.run_context).where(
                            tables.agent_runs.c.id == previous["run_id"],
                            tables.agent_runs.c.tenant_id == tenant_id,
                        )
                    ).scalar_one()
                    if previous["status"] not in {"pending_review", "accepted"} or old_context.get(
                        "superseded_by"
                    ):
                        raise TestPlanChangeError("原建议已处理或有更新，本次候选未写入")
                if (
                    digest(
                        plan_state(
                            connection, tenant_id=tenant_id, project_id=project_id, plan_id=plan_id
                        )
                    )
                    != base_digest
                ):
                    raise TestPlanChangeError("生成期间原计划已变化，请重新生成")
                if not FindingQualityService.is_output_allowed_connection(
                    connection, tenant_id=tenant_id, agent_key=AGENT, finding_type=FINDING_TYPE
                ):
                    raise TestPlanChangeError("建议输出已暂停")
                if (
                    resolve_sources(
                        connection, tenant_id=tenant_id, project_id=project_id, selections=sources
                    )
                    != source_snapshots
                ):
                    raise TestPlanChangeError("生成期间依据已变化，请刷新后重新选择")
                finding_id = uuid4()
                connection.execute(
                    tables.findings.insert().values(
                        id=finding_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        run_id=run_id,
                        model_invocation_id=result.invocation_id,
                        agent_key=AGENT,
                        finding_type=FINDING_TYPE,
                        origin_key=f"test-plan:{request_id}",
                        status="pending_review",
                        title="测试计划调整建议",
                        summary=payload.summary,
                        proposed_payload=payload.model_dump(mode="json"),
                        evidence_event_ids=[event_row_id],
                        confidence_basis_points=0,
                        preflight_version="test-plan-change-v1",
                    )
                )
                connection.execute(
                    tables.finding_actions.insert().values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        finding_id=finding_id,
                        action="created",
                        to_status="pending_review",
                        detail={"request_id": str(request_id)},
                    )
                )
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"ai-finding:{finding_id}:created",
                        event_type="AI_FINDING_CREATED",
                        source="ai_runtime",
                        entity_id=finding_id,
                        payload={"finding_id": str(finding_id), "agent_run_id": str(run_id)},
                    ),
                    AuditDraft(
                        action="finding.create_from_test_plan",
                        after_snapshot={
                            "finding_id": str(finding_id),
                            "payload": payload.model_dump(mode="json"),
                        },
                    ),
                )
                if previous:
                    connection.execute(
                        update(tables.agent_runs)
                        .where(
                            tables.agent_runs.c.id == previous["run_id"],
                            tables.agent_runs.c.tenant_id == tenant_id,
                        )
                        .values(run_context={**old_context, "superseded_by": str(finding_id)})
                    )
                waiting = save_test_plan_wait(
                    connection, tenant=tenant_id, run=run_id, finding=finding_id, payload=payload
                )
                response = {"status": "created", "finding_id": str(finding_id), "error_code": None}
                connection.execute(
                    update(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.id == run_id, tables.agent_runs.c.tenant_id == tenant_id
                    )
                    .values(
                        status="waiting_input" if waiting else "succeeded",
                        completed_at=None if waiting else datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        run_context={**run_context, "result": response},
                    )
                )
            return response
        except (CapabilityUnavailableError, BudgetLedgerError) as error:
            return self._finish(run_id, tenant_id, run_context, None, error.code)
        except (TestPlanChangeError, PlanSourceError) as error:
            self._finish(run_id, tenant_id, run_context, None, "TEST_PLAN_PREFLIGHT_FAILED")
            raise error
        except Exception:
            # Never expose provider details or retry into business writes.
            return self._finish(run_id, tenant_id, run_context, None, "TEST_PLAN_MODEL_FAILED")

    def _finish(
        self,
        run_id: UUID,
        tenant_id: UUID,
        context: dict[str, Any],
        finding_id: UUID | None,
        error: str,
    ) -> dict[str, Any]:
        response = {
            "status": "unavailable",
            "finding_id": str(finding_id) if finding_id else None,
            "error_code": error,
        }
        with self._engine.begin() as connection:
            status = connection.execute(
                select(tables.agent_runs.c.status)
                .where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.id == run_id,
                )
                .with_for_update()
            ).scalar_one()
            if status != "running":
                return response
            bind_write(connection, self._gateway, tenant_id, run_id, success=False)
            connection.execute(
                update(tables.agent_runs)
                .where(tables.agent_runs.c.id == run_id, tables.agent_runs.c.tenant_id == tenant_id)
                .values(
                    status="degraded",
                    error_code=error,
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    run_context={**context, "result": response},
                )
            )
        return response
