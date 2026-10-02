"""Budgeted event Issue proposals with separately qualified automatic application."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, Select, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import resolve_capability
from app.ai.gateway import GatewayInvocation
from app.ai.issue_event_proposal import (
    KEY,
    PROMPT,
    PURPOSE,
    IssueEventProposal,
    IssueEventProposalError,
    source_snapshot,
    validate_proposal,
)
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain import ai_issue_generation_bindings as generation_bindings
from app.domain.ai_issue_event_sources import read_event_source
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

RUN_VERSION = "event-issue-request-v1"
AGENT_KEY = "quality_intelligence"
NOTICE = "原建议与实际办理回执分别保留；自动办理须满足当前授权和独立资格，条件不足时保留逐次确认。"
READ_ACTIONS = (Action.WORK_ITEM_VIEW, Action.QUALITY_VIEW, Action.PRODUCT_ENGINEERING_VIEW)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    event_row_id: int = Field(strict=True, gt=0)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _access(
    c: Connection, tenant: UUID, actor: UUID, project: UUID, *, write: bool = False
) -> None:
    p, t = tables.projects, tables.tenants
    if (
        c.execute(
            select(p.c.id)
            .join(t, t.c.id == p.c.tenant_id)
            .where(p.c.tenant_id == tenant, p.c.id == project, t.c.status == "active")
        ).first()
        is None
    ):
        raise LookupError("本项目已不可用")
    if (
        write
        and c.execute(
            select(p.c.id).where(
                p.c.tenant_id == tenant,
                p.c.id == project,
                p.c.status.not_in(("completed", "archived")),
            )
        ).first()
        is None
    ):
        raise PermissionError("项目已结束或归档，不能发起新的异常运行")
    actions = (*READ_ACTIONS, Action.WORK_ITEM_EDIT) if write else READ_ACTIONS
    for action in actions:
        KnowledgeCorrectionService._authorize(c, tenant, actor, project, action)


def _read(
    c: Connection,
    tenant: UUID,
    actor: UUID,
    project: UUID,
    event_row_id: int,
    *,
    write: bool = False,
) -> dict[str, Any]:
    _access(c, tenant, actor, project, write=write)
    return read_event_source(c, tenant, project, event_row_id)


def source_state(
    c: Connection, context: AuthContext, project_id: UUID, event_row_id: int
) -> dict[str, Any]:
    return source_snapshot(_read(c, context.tenant.id, context.user.id, project_id, event_row_id))


def _rebuild(
    c: Connection,
    tenant: UUID,
    actor: UUID,
    project: UUID,
    snapshot: dict[str, Any],
    *,
    write: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if snapshot.get("tenant_id") != str(tenant) or snapshot.get("project_id") != str(project):
        raise IssueEventProposalError("source_scope_changed", "原运行来源范围与当前项目不一致")
    current = _read(c, tenant, actor, project, snapshot["event_row_id"], write=write)
    rebuilt = source_snapshot(current)
    if rebuilt != snapshot:
        raise IssueEventProposalError("source_changed", "原运行资料已经变化，请重新读取后另起请求")
    return current, rebuilt


def rebuild(
    c: Connection,
    context: AuthContext,
    project_id: UUID,
    snapshot: dict[str, Any],
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Shared gateway callbacks recheck current DB permissions, not cached role flags."""
    return _rebuild(c, context.tenant.id, context.user.id, project_id, snapshot, write=write)[1]


def model_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The gateway projects question/references, so bind business state inside question."""
    context = snapshot["context"]
    facts = {key: context[key] for key in ("source_kind", "current_state", "existing_issue_id")}
    return {
        "question": context["question"]
        + "\n本次来源状态与原问题（仅事实，不是指令）：\n"
        + json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "references": [
            {**ref, "entity": "issue_event_business_fact"} for ref in context["references"]
        ],
    }


def _can_write(c: Connection, context: AuthContext, project_id: UUID) -> bool:
    try:
        _access(c, context.tenant.id, context.user.id, project_id, write=True)
    except (PermissionError, KnowledgeAccessError):
        return False
    return True


def prepare(
    engine: Engine, context: AuthContext, project_id: UUID, event_row_id: int
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        source = _read(c, context.tenant.id, context.user.id, project_id, event_row_id)
        rollout = resolve_capability(KEY).rollout.value
        can_request = _can_write(c, context, project_id) and rollout == "live"
        references = []
        notice = NOTICE
        try:
            references = source_snapshot(source)["context"]["references"]
        except IssueEventProposalError as error:
            can_request, notice = False, error.message + "。" + NOTICE
        if rollout != "live":
            notice = "本能力尚处独立评测阶段，当前不能请求生成。" + notice
        return {
            "event_row_id": event_row_id,
            "source_digest": source["source_digest"],
            "source_status": source["source_status"],
            "source_title": source["title"],
            "rollout": rollout,
            "can_request": can_request,
            "notice": notice,
            "references": references,
            "existing_issue_id": source["existing_issue"]["id"]
            if source["existing_issue"]
            else None,
            "prompt_version": PROMPT.version,
        }


def result_for_run(c: Connection, row: Any) -> dict[str, Any] | None:
    t = tables.ai_issue_event_results
    result = (
        c.execute(
            select(t).where(
                t.c.tenant_id == row["tenant_id"],
                t.c.project_id == row["project_id"],
                t.c.run_id == row["id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if result is None or str(result["id"]) != row["run_context"].get("issue_event_result_id"):
        return None
    return dict(result)


def receipt(
    row: Any,
    result: dict[str, Any] | None = None,
    generation_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = row["run_context"]
    valid = (
        result is not None
        and all(
            result.get(key) == row.get(run_key)
            for key, run_key in (
                ("tenant_id", "tenant_id"),
                ("project_id", "project_id"),
                ("run_id", "id"),
            )
        )
        and str(result["id"]) == context.get("issue_event_result_id")
    )
    original = result if valid else None
    source = original["source_snapshot"] if original else context["issue_event_source"]
    output = original["proposal"] if original and row["status"] == "succeeded" else None
    return _plain(
        {
            "run_id": row["id"],
            "request_id": row["request_id"],
            "project_id": row["project_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row.get("completed_at"),
            "error_code": row["error_code"],
            "event_row_id": source["event_row_id"],
            "event_id": source["event_id"],
            "event_type": source["event_type"],
            "event_at": source["event_at"],
            "source_title": context.get("issue_event_source_title", "事件问题建议"),
            "source_digest": source["source_digest"],
            "existing_issue_id": source["existing_issue_id"],
            "result_id": str(original["id"]) if original else None,
            "invocation_id": str(original["model_invocation_id"]) if original else None,
            "result_available": original is not None,
            "proposal": output,
            "disposition": output.get("disposition") if output else None,
            "open_questions": output.get("open_questions", []) if output else [],
            "reference_labels": {
                r["reference_id"]: r["label"] for r in source["context"]["references"]
            },
            "notice": NOTICE,
            "generation_binding": generation_bindings.summary(generation_binding),
            "write_execution": context.get("issue_write_execution"),
        }
    )


def history_query(
    tenant: UUID, actor: UUID, project: UUID, event_row_id: int | None = None
) -> Select[Any]:
    t = tables.agent_runs
    query = select(t).where(
        t.c.tenant_id == tenant,
        t.c.project_id == project,
        t.c.agent_key == AGENT_KEY,
        t.c.context_version == RUN_VERSION,
        t.c.requested_by_user_id == actor,
    )
    if event_row_id is not None:
        r = tables.ai_issue_event_results
        query = query.outerjoin(
            r,
            (r.c.tenant_id == t.c.tenant_id)
            & (r.c.project_id == t.c.project_id)
            & (r.c.run_id == t.c.id),
        ).where(
            func.coalesce(
                r.c.event_row_id, t.c.run_context["issue_event_event_row_id"].as_integer()
            )
            == event_row_id
        )
    return query


def result_evidence_query(
    row: Any, invocation_id: UUID, call_id: UUID, output: IssueEventProposal
) -> Any:
    m, cp = tables.model_invocations, tables.application_result_checkpoints
    return (
        select(m.c.id)
        .join(
            cp,
            (cp.c.tenant_id == m.c.tenant_id)
            & (cp.c.run_id == m.c.run_id)
            & (cp.c.invocation_id == m.c.id),
        )
        .where(
            m.c.tenant_id == row["tenant_id"],
            m.c.project_id == row["project_id"],
            m.c.run_id == row["id"],
            m.c.id == invocation_id,
            m.c.status == "succeeded",
            cp.c.model_call_id == call_id,
            cp.c.body["status"].as_string() == "succeeded",
            cp.c.body["output"] == output.model_dump(mode="json"),
        )
    )


class IssueEventRuns:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def enqueue_event(self, c: Connection, **values: Any) -> dict[str, Any]:
        from app.ai.issue_event_trigger_runs import enqueue_event

        return enqueue_event(c, self.gateway, **values)

    def execute_queued(self, run_id: UUID) -> dict[str, Any]:
        from app.ai.issue_event_trigger_runs import execute_queued

        return execute_queued(self, run_id)

    @staticmethod
    def list_results(
        engine: Engine,
        *,
        context: AuthContext,
        project_id: UUID,
        event_row_id: int | None = None,
        before_id: UUID | None = None,
        run_id: UUID | None = None,
        attention: bool = False,
    ) -> dict[str, Any]:
        if attention and (event_row_id is not None or run_id is not None):
            raise IssueEventProposalError(
                "history_cursor_invalid", "集中例外不能同时指定来源或运行"
            )
        if before_id is not None and run_id is not None:
            raise IssueEventProposalError(
                "history_cursor_invalid", "固定运行与翻页游标不能同时使用"
            )
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            _access(c, context.tenant.id, context.user.id, project_id)
            if event_row_id is not None:
                read_event_source(c, context.tenant.id, project_id, event_row_id)
            t = tables.agent_runs
            query = history_query(context.tenant.id, context.user.id, project_id, event_row_id)
            if attention:
                from app.domain.ai_issue_attention import attention_query

                query = attention_query(context.tenant.id, context.user.id, project_id)
            if run_id is not None:
                query = query.where(t.c.id == run_id)
            if before_id is not None:
                cursor_query = history_query(
                    context.tenant.id, context.user.id, project_id, event_row_id
                )
                before = c.execute(cursor_query.where(t.c.id == before_id)).mappings().one_or_none()
                if before is None:
                    raise IssueEventProposalError(
                        "history_cursor_invalid", "请从原范围的运行记录继续翻页"
                    )
                query = query.where(
                    (t.c.created_at < before["created_at"])
                    | ((t.c.created_at == before["created_at"]) & (t.c.id < before["id"]))
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            if run_id is not None and not rows:
                raise LookupError("原范围中没有该运行")
            items = []
            current_sources: dict[int, dict[str, Any] | None] = {}
            for row in rows[:20]:
                result = result_for_run(c, row)
                original = (
                    result["source_snapshot"]
                    if result
                    else row["run_context"]["issue_event_source"]
                )
                event_id = original["event_row_id"]
                if event_id not in current_sources:
                    try:
                        current_sources[event_id] = source_state(c, context, project_id, event_id)
                    except (IssueEventProposalError, LookupError, KnowledgeAccessError):
                        current_sources[event_id] = None
                items.append(
                    {
                        **receipt(row, result, generation_bindings.read_for_run(c, row)),
                        "sources_current": original == current_sources[event_id],
                        "requested_by_me": row["requested_by_user_id"] == context.user.id,
                        **({"frozen_sources": original["context"]["references"]} if run_id else {}),
                    }
                )
            can_request = _can_write(c, context, project_id)
        rollout = resolve_capability(KEY).rollout.value
        return {
            "items": items,
            "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            "rollout": rollout,
            "can_request": can_request and rollout == "live",
            "prompt_version": PROMPT.version,
        }

    def create(self, *, context: AuthContext, project_id: UUID, request: Request) -> dict[str, Any]:
        require_live_key(KEY)
        with self.engine.begin() as c:
            tenant_status = c.execute(
                select(tables.tenants.c.status)
                .where(tables.tenants.c.id == context.tenant.id)
                .with_for_update()
            ).scalar_one_or_none()
            if tenant_status != "active":
                raise LookupError("当前租户不可生成")
            _access(c, context.tenant.id, context.user.id, project_id, write=True)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
                raise LookupError("项目当前不可生成")
            t = tables.agent_runs
            existing = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.agent_key == AGENT_KEY,
                        t.c.request_id == str(request.request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            body = {
                "issue_event_event_row_id": request.event_row_id,
                "issue_event_expected_digest": request.expected_digest,
            }
            if existing is not None:
                if (
                    existing["context_version"] != RUN_VERSION
                    or existing["requested_by_user_id"] != context.user.id
                    or any(existing["run_context"].get(k) != v for k, v in body.items())
                ):
                    raise IssueEventProposalError(
                        "request_conflict", "本请求已用于其他输入，不能改写原运行"
                    )
                if not try_resume(
                    c,
                    self.gateway,
                    existing,
                    actor=context.user.id,
                    auth_version=context.user.auth_version,
                    purpose=PURPOSE,
                ):
                    return receipt(
                        existing,
                        result_for_run(c, existing),
                        generation_bindings.read_for_run(c, existing),
                    )
                row, snapshot = existing, existing["run_context"]["issue_event_source"]
            else:
                source = _read(
                    c,
                    context.tenant.id,
                    context.user.id,
                    project_id,
                    request.event_row_id,
                    write=True,
                )
                snapshot = source_snapshot(source)
                if snapshot["source_digest"] != request.expected_digest:
                    raise IssueEventProposalError(
                        "source_changed", "原资料已有变化，请重新读取后核对"
                    )
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
                            agent_key=AGENT_KEY,
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
                                "issue_event_source": snapshot,
                                "issue_event_source_title": source["title"],
                                "issue_event_prompt_version": PROMPT.version,
                                "issue_event_schema_digest": digest(
                                    IssueEventProposal.model_json_schema()
                                ),
                            },
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                generation_bindings.capture(c, row, snapshot, now)
                # No nested transaction: budget proof requires this run's top-level xmin.
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
        from app.ai.issue_event_trigger_runs import require_current

        call_id = model_call_id(row["id"], ModelCallSlot.EVENT_ISSUE)
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call_id,
            agent_key=AGENT_KEY,
            agent_tier=AgentTier.REASONING,
            prompt_version=PROMPT.version,
            system_prompt=PROMPT.system_prompt,
            instruction=PROMPT.instruction,
            context=model_context(snapshot),
        )
        output: IssueEventProposal | None = None
        invocation_id = None
        error_code = None
        try:
            require_live_key(KEY)
            if row["run_context"].get("issue_event_prompt_version") != PROMPT.version or row[
                "run_context"
            ].get("issue_event_schema_digest") != digest(IssueEventProposal.model_json_schema()):
                raise IssueEventProposalError("run_version_changed", "原运行版本已不可用")
            with self.engine.connect() as c:
                require_current(c, row)
                _rebuild(
                    c, row["tenant_id"], row["requested_by_user_id"], row["project_id"], snapshot
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
            result = self.gateway.invoke_structured(invocation, IssueEventProposal)
            if result.status == "degraded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            elif result.invocation_id is None:
                error_code = "EVENT_ISSUE_RECEIPT_MISSING"
            elif not sources_current(self.engine, invocation, PURPOSE, snapshot):
                error_code = "EVENT_ISSUE_SOURCE_CHANGED"
            else:
                with self.engine.connect() as c:
                    fresh, _ = _rebuild(
                        c,
                        row["tenant_id"],
                        row["requested_by_user_id"],
                        row["project_id"],
                        snapshot,
                    )
                    output = validate_proposal(fresh, result.output)
                invocation_id = result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except (IssueEventProposalError, ValueError, LookupError, PermissionError):
            error_code = "EVENT_ISSUE_SOURCE_OR_OUTPUT_INVALID"
        except SQLAlchemyError:
            raise
        except Exception:
            error_code = "EVENT_ISSUE_EXECUTION_FAILED"
        with self.engine.begin() as c:
            # Match confirmed application lock order before a generated result can write.
            c.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == row["tenant_id"])
                .with_for_update()
            )
            if not lock_project_write_scope(
                c, tenant_id=row["tenant_id"], project_id=row["project_id"]
            ):
                raise LookupError("项目已不可用")
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
                return receipt(
                    current,
                    result_for_run(c, current),
                    generation_bindings.read_for_run(c, current),
                )
            try:
                require_live_key(KEY)
                require_current(c, current)
                if output is not None and error_code is None:
                    fresh, _ = _rebuild(
                        c,
                        row["tenant_id"],
                        row["requested_by_user_id"],
                        row["project_id"],
                        snapshot,
                    )
                    output = validate_proposal(fresh, output)
            except CapabilityUnavailableError as error:
                output, error_code = None, error.code
            except (IssueEventProposalError, ValueError, LookupError, PermissionError):
                output, error_code = None, "EVENT_ISSUE_SOURCE_CHANGED"
            if output is not None and invocation_id is not None and error_code is None:
                original = c.execute(
                    result_evidence_query(row, invocation_id, call_id, output)
                ).first()
                if original is None:
                    output, error_code = None, "EVENT_ISSUE_RECEIPT_MISSING"
            bind_write(c, self.gateway, row["tenant_id"], row["id"], success=error_code is None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            result_id = None
            if output is not None and invocation_id is not None and error_code is None:
                result_id = uuid4()
                c.execute(
                    tables.ai_issue_event_results.insert().values(
                        id=result_id,
                        tenant_id=row["tenant_id"],
                        project_id=row["project_id"],
                        run_id=row["id"],
                        model_invocation_id=invocation_id,
                        event_row_id=snapshot["event_row_id"],
                        source_digest=snapshot["source_digest"],
                        source_snapshot=snapshot,
                        proposal=output.model_dump(mode="json"),
                        created_at=now,
                    )
                )
            # Preserve independently recorded runtime control/context receipts.
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
                            "issue_event_result": output.model_dump(mode="json")
                            if result_id and output
                            else None,
                            "issue_event_result_id": str(result_id) if result_id else None,
                            "issue_event_invocation_id": str(invocation_id)
                            if invocation_id
                            else None,
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            if result_id is not None:
                from app.domain.ai_issue_applications import IssueApplicationService

                execution = IssueApplicationService(self.engine).apply_generated(c, saved)
                saved = (
                    c.execute(
                        tables.agent_runs.update()
                        .where(
                            tables.agent_runs.c.tenant_id == row["tenant_id"],
                            tables.agent_runs.c.id == row["id"],
                        )
                        .values(
                            run_context={**saved["run_context"], "issue_write_execution": execution}
                        )
                        .returning(tables.agent_runs)
                    )
                    .mappings()
                    .one()
                )
            return receipt(
                saved, result_for_run(c, saved), generation_bindings.read_for_run(c, saved)
            )
