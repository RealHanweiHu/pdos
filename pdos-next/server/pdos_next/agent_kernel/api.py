"""Thin authenticated run API; no synchronous model path or model-supplied authority."""

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.orm import load_only

from pdos_next.contracts import SourceRead
from pdos_next.database import tenant_session
from pdos_next.enterprise_search.verification_actions import VerificationAction
from pdos_next.enterprise_search.work_followup_actions import WorkFollowupAction
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .models import AgentEvent, AgentRun, AgentSession
from .persistence import cancel_run, create_run, record_answers, run_revert_status
from .requested_skills import RequestedSkill
from .run_feedback import FeedbackInput
from .run_reconciliation import ReconcileInput
from .search_preferences import SearchPreferences


class StartInput(StrictModel):
    goal: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=160)
    session_id: UUID | None = None
    continue_from_run_id: UUID | None = None
    restart_from_run_id: UUID | None = None
    product_id: UUID | None = None
    proposal_id: UUID | None = None
    project_id: UUID | None = None
    sources: list[SourceRead] = Field(default_factory=list)
    requested_skills: list[RequestedSkill] = Field(default_factory=list, max_length=8)
    excluded_continued_skills: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list, max_length=2,
    )
    search_preferences: SearchPreferences | None = None
    verification_action: VerificationAction | None = None
    work_followup_action: WorkFollowupAction | None = None
    lookup_depth: Literal["deep"] | None = None
    context_revision: int | None = Field(default=None, ge=1, strict=True)


class AnswerInput(StrictModel):
    answers: dict
    idempotency_key: str = Field(min_length=8, max_length=160)


@dataclass(frozen=True)
class ApiPorts:
    writer_for: object
    binding_for: object
    start_workflow: object
    signal_workflow: object
    cancel_workflow: object
    recover_call: object | None = None


def reference(row, ctx):
    return {
        "tenant_id": str(row.tenant_id),
        "category_id": str(row.category_id or ""),
        "actor_id": str(ctx.actor_id),
        "requester_id": str(row.requester_id),
        "subject_id": str(row.id),
    }


def router(engine, *, context_dependency, ports: ApiPorts):
    result = APIRouter()

    auth_dependency = Depends(context_dependency)

    def scoped_context(request: Request, ctx=auth_dependency):
        category = request.path_params.get("category_id")
        if str(ctx.category_id or "") != str(category or ""):
            raise DomainError("FORBIDDEN_SCOPE", "入口品类与已鉴权范围不一致。")
        return ctx

    run_dependency = Depends(scoped_context)

    def transaction(ctx, *, read_snapshot=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=read_snapshot,
        )

    def visible_run(session, ctx, row):
        if row is None or row.requester_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "运行不在当前可读范围。", 403)
        if row.proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal

            proposal(session, ctx, row.proposal_id)
        from .project_scope import require_project

        require_project(session, ctx, row.project_id, row.product_id)
        return row

    from .session_views import router as session_router

    result.include_router(
        session_router(transaction=transaction, context_dependency=run_dependency)
    )

    from .session_presentation_api import router as presentation_router

    result.include_router(
        presentation_router(transaction=transaction, context_dependency=run_dependency)
    )

    from .source_views import router as source_router

    result.include_router(source_router(transaction=transaction, context_dependency=run_dependency))

    from .upload_views import router as upload_router

    result.include_router(upload_router(transaction=transaction, context_dependency=run_dependency))

    from .work_products import router as work_product_router

    result.include_router(
        work_product_router(transaction=transaction, context_dependency=run_dependency)
    )

    from pdos_next.enterprise_search.api import router as enterprise_search_router

    from .work_state import router as work_state_router

    result.include_router(
        enterprise_search_router(transaction=transaction, context_dependency=run_dependency,
                                 engine=engine)
    )

    result.include_router(
        work_state_router(transaction=transaction, context_dependency=run_dependency)
    )

    @result.get("/v1/personal/agent-skills")
    def personal_skills(ctx=run_dependency):
        from .requested_skills import reading

        with transaction(ctx, read_snapshot=True) as session:
            return reading(session, ctx)

    @result.post("/v1/categories/{category_id}/agent-runs", status_code=202)
    @result.post("/v1/personal/agent-runs", status_code=202)
    async def start(data: StartInput, ctx=run_dependency):
        if data.verification_action is not None and data.work_followup_action is not None:
            raise DomainError("INVALID_PAYLOAD", "一次续接只准备一个明确的行动。", 422)
        request_digest = digest(
            {
                "category_id": ctx.category_id,
                "request": data.model_dump(
                    exclude={"idempotency_key"}
                    | ({"project_id"} if data.project_id is None else set())
                    | ({"requested_skills"} if not data.requested_skills else set())
                    | ({"search_preferences"} if data.search_preferences is None else set())
                    | ({"verification_action"} if data.verification_action is None else set())
                    | ({"work_followup_action"} if data.work_followup_action is None else set())
                    | ({"lookup_depth"} if data.lookup_depth is None else set())
                    | ({"context_revision"} if data.context_revision is None else set())
                    | ({"restart_from_run_id"} if data.restart_from_run_id is None else set())
                    | ({"excluded_continued_skills"}
                       if not data.excluded_continued_skills else set())
                ),
            }
        )
        requested_for_event = data.requested_skills
        # This host callback binds proposal audience/source taint, not a boolean from the client.
        with transaction(ctx) as s:
            lock_key = f"xiaopai-start:{ctx.tenant_id}:{ctx.requester_id}:{data.idempotency_key}"
            s.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": lock_key}
            )
            row = s.scalar(
                select(AgentRun).where(
                    AgentRun.requester_id == ctx.requester_id,
                    AgentRun.intent_key == data.idempotency_key,
                )
            )
            if row is not None:
                if row.intent_digest != request_digest:
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同目标。")
                if ctx.category_id is not None:
                    require_access(s, ctx, row.product_id)
                visible_run(s, ctx, row)
            else:
                from .conversation import merge_binding, prepare

                restart = None
                if data.restart_from_run_id is not None:
                    from .context_restart import prepare as prepare_restart

                    effective, restart = prepare_restart(s, ctx, data)
                    parent = None
                else:
                    effective, parent = prepare(s, ctx, data)
                from pdos_next.enterprise_search.assistant_depth import starting_profile

                depth_profile = starting_profile(data.lookup_depth, parent)
                from .requested_skills import validate as validate_skills

                validate_skills(s, ctx, data.requested_skills)
                from pdos_next.enterprise_search.verification_actions import prepare_start

                effective, action, requested_for_event = prepare_start(
                    s, ctx, effective, parent, data.verification_action,
                )
                work_action = None
                if data.work_followup_action is not None:
                    from pdos_next.enterprise_search.work_followup_actions import prepare_start

                    effective, work_action, requested_for_event = prepare_start(
                        s, ctx, effective, parent, data.work_followup_action,
                    )
                from .requested_skills import validate_start

                merged_skills = validate_start(
                    s, ctx, requested_for_event, parent=restart.parent if restart else parent,
                    excluded=data.excluded_continued_skills,
                )
                if restart is not None:
                    requested_for_event = merged_skills
                binding = merge_binding(
                    ports.binding_for(s, ctx, effective), restart.parent if restart else parent,
                )
                row = create_run(
                    s,
                    ctx,
                    goal=data.goal,
                    writer_id=ports.writer_for(s, ctx),
                    intent_key=data.idempotency_key,
                    session_id=effective.session_id,
                    product_id=effective.product_id,
                    proposal_id=effective.proposal_id,
                    project_id=effective.project_id,
                    continued_from_id=parent.id if parent else None,
                    private_context=binding.private_context,
                    data_categories=binding.data_categories,
                    customer_identities=binding.customer_identities,
                    read_sources=binding.read_sources,
                    outbound_context=getattr(binding, "outbound_context", None),
                    token_limit=getattr(binding, "token_limit", 100000),
                    validation_budget_id=getattr(binding, "validation_budget_id", None),
                    request_digest=request_digest,
                )
                row.versions = {**row.versions, "assistant_depth": depth_profile}
                if action is not None:
                    row.versions = {**row.versions, "verification_action": action}
                if work_action is not None:
                    row.versions = {**row.versions, "work_followup_action": work_action}
                from .search_preferences import configure_start

                configure_start(s, ctx, row, data.search_preferences)
                from .context_corrections import configure_start as configure_context_start

                configure_context_start(s, ctx, row, data, effective, parent)
                if restart is not None:
                    from .context_restart import install

                    install(s, row, restart)
            ref = reference(row, ctx)
            value = {
                "run_id": str(row.id),
                "session_id": str(row.session_id),
                "status": row.state,
                "continued_from_id": (
                    str(row.continued_from_id) if row.continued_from_id else None
                ),
                **({"restarted_from_id": row.versions["work_state_restart"]["source_run_id"]}
                   if "work_state_restart" in row.versions else {}),
            }
            if not s.scalar(select(AgentEvent.id).where(AgentEvent.run_id == row.id)):
                s.add(
                    AgentEvent(
                        tenant_id=ctx.tenant_id,
                        run_id=row.id,
                        sequence=1,
                        body={
                            "type": "accepted",
                            "status": "queued",
                            **(
                                {
                                    "requested_skills": [
                                        item.model_dump(mode="json")
                                        for item in requested_for_event
                                    ]
                                }
                                if requested_for_event
                                else {}
                            ),
                            **({"excluded_continued_skills": data.excluded_continued_skills}
                               if data.excluded_continued_skills
                               and data.restart_from_run_id is None else {}),
                        },
                    )
                )
        # A crash here leaves a stable queued Run. Repeating the same request starts the same
        # workflow ID; unavailable Temporal never falls back to local inference.
        try:
            await ports.start_workflow(ref)
        except Exception:
            value["execution_state"] = "durable_runtime_unavailable"
        return value

    @result.post("/v1/categories/{category_id}/agent-runs/{run_id}/calls/{call_id}/recover")
    def recover(run_id: UUID, call_id: UUID, ctx=run_dependency):
        if ports.recover_call is None:
            raise DomainError("SOURCE_UNAVAILABLE", "领域回执恢复端口尚未配置。")
        return ports.recover_call(ctx, run_id, call_id)

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}")
    @result.get("/v1/personal/agent-runs/{run_id}")
    def read(run_id: UUID, ctx=run_dependency):
        from pdos_next.enterprise_search.assistant_answer import stored_answer

        from .conversation import links
        from .process_view import read_process
        from .run_reconciliation import completed_record
        from .session_bindings import current_proposal_id

        with transaction(ctx, read_snapshot=True) as s:
            actual = s.get(AgentRun, run_id)
            if actual is None:
                from .owner_history import goals, hidden_detail

                recorded = goals(s, ctx, run_id=run_id)
                if recorded:
                    return hidden_detail(recorded[0])
            row = visible_run(s, ctx, actual)
            from pdos_next.personal_summary_runtime import checked_result

            answer = checked_result(s, ctx, row)
            if answer is None:
                answer = stored_answer(s, row)
            from .project_current_context import checked_result as checked_project_result

            answer = checked_project_result(s, ctx, row, answer)
            conversation = s.get(AgentSession, row.session_id)
            if conversation is None:
                raise DomainError("FORBIDDEN_SCOPE", "原会话不在当前可读范围。", 403)
            session_proposal_id = current_proposal_id(s, conversation)
            if session_proposal_id is not None and session_proposal_id != row.proposal_id:
                from pdos_next.domain.preproject.access import proposal

                proposal(s, ctx, session_proposal_id)
            return {
                "run_id": str(row.id),
                "goal": row.goal,
                "session_id": str(row.session_id),
                "conversation": links(s, row),
                "product_id": str(row.product_id) if row.product_id else None,
                "proposal_id": str(row.proposal_id) if row.proposal_id else None,
                "session_proposal_id": str(session_proposal_id) if session_proposal_id else None,
                "project_id": str(row.project_id) if row.project_id else None,
                "status": row.state,
                "result": answer,
                "error_code": row.error_code,
                "reconciliation": completed_record(s, row),
                "process": read_process(s, row),
                "versions": row.versions,
                **run_revert_status(row),
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/process")
    @result.get("/v1/personal/agent-runs/{run_id}/process")
    def process(
        run_id: UUID,
        before: int | None = Query(default=None, ge=1),
        source_cursor: UUID | None = None,
        receipt_cursor: UUID | None = None,
        page_size: int = Query(default=25, ge=1, le=100),
        ctx=run_dependency,
    ):
        from .process_view import read_process

        with transaction(ctx, read_snapshot=True) as session:
            row = session.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id)
                .options(
                    load_only(
                        AgentRun.id,
                        AgentRun.tenant_id,
                        AgentRun.category_id,
                        AgentRun.proposal_id,
                        AgentRun.product_id,
                        AgentRun.project_id,
                        AgentRun.requester_id,
                        # Receipt visibility also validates fixed service-run bindings.
                        AgentRun.trigger,
                        AgentRun.writer_id,
                        AgentRun.intent_digest,
                        AgentRun.goal,
                        AgentRun.validation_budget_id,
                        AgentRun.token_limit,
                        AgentRun.state,
                        AgentRun.error_code,
                        AgentRun.created_at,
                        AgentRun.reverted_at,
                        AgentRun.read_sources,
                        raiseload=True,
                    )
                )
            )
            return read_process(
                session,
                visible_run(session, ctx, row),
                before=before,
                page_size=page_size,
                source_cursor=source_cursor,
                receipt_cursor=receipt_cursor,
            )

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/continuation")
    @result.get("/v1/personal/agent-runs/{run_id}/continuation")
    def continuation(run_id: UUID, ctx=run_dependency):
        from .run_reconciliation import owner

        with transaction(ctx, read_snapshot=True) as session:
            row = session.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id)
                .options(
                    load_only(
                        AgentRun.id,
                        AgentRun.tenant_id,
                        AgentRun.category_id,
                        AgentRun.proposal_id,
                        AgentRun.product_id,
                        AgentRun.project_id,
                        AgentRun.requester_id,
                        AgentRun.state,
                        AgentRun.reverted_at,
                        AgentRun.session_id,
                        AgentRun.versions,
                        raiseload=True,
                    )
                )
            )
            owner(session, ctx, visible_run(session, ctx, row))
            from .context_restart import recovery_view
            from .requested_skills import recent
            child = session.execute(
                select(AgentRun.id, AgentRun.goal, AgentRun.intent_key).where(
                    AgentRun.continued_from_id == row.id
                )
            ).one_or_none()
            return {
                "run_id": str(row.id),
                "owner_id": str(row.requester_id),
                "continued_skills": [
                    item.model_dump(mode="json") for item in recent(session, row.id)
                ],
                "context_restart": recovery_view(session, row),
                "can_continue": not row.reverted_at
                and row.state in {"completed", "partial", "failed", "cancelled"}
                and child is None,
                "existing": {
                    "run_id": str(child.id),
                    "goal": child.goal,
                    "idempotency_key": child.intent_key,
                }
                if child
                else None,
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/reconciliation")
    @result.get("/v1/personal/agent-runs/{run_id}/reconciliation")
    def inspect_reconciliation(
        run_id: UUID,
        call_cursor: UUID | None = None,
        receipt_cursor: UUID | None = None,
        page_size: int = Query(default=50, ge=1, le=100),
        ctx=run_dependency,
    ):
        from .run_reconciliation import inspect

        with transaction(ctx) as session:
            row = visible_run(session, ctx, session.get(AgentRun, run_id))
            return inspect(
                session,
                ctx,
                row,
                call_cursor=call_cursor,
                receipt_cursor=receipt_cursor,
                page_size=page_size,
            )

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/feedback")
    @result.get("/v1/personal/agent-runs/{run_id}/feedback")
    def feedback(
        run_id: UUID,
        before: int | None = Query(default=None, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        request_key: UUID | None = None,
        ctx=run_dependency,
    ):
        from .run_feedback import lookup, read

        with transaction(ctx, read_snapshot=True) as session:
            return read(
                session,
                ctx,
                visible_run(session, ctx, lookup(session, run_id)),
                before=before,
                page_size=page_size,
                request_key=request_key,
            )

    @result.post("/v1/categories/{category_id}/agent-runs/{run_id}/feedback")
    @result.post("/v1/personal/agent-runs/{run_id}/feedback")
    def save_feedback(run_id: UUID, data: FeedbackInput, ctx=run_dependency):
        from .run_feedback import lookup, record

        with transaction(ctx) as session:
            row = lookup(session, run_id, lock=True)
            return record(session, ctx, visible_run(session, ctx, row), data)

    @result.post("/v1/categories/{category_id}/agent-runs/{run_id}/reconciliation")
    @result.post("/v1/personal/agent-runs/{run_id}/reconciliation")
    async def finalize_reconciliation(run_id: UUID, data: ReconcileInput, ctx=run_dependency):
        from .run_reconciliation import finalize

        value = finalize(engine, ctx, run_id, expected_cancel_epoch=data.expected_cancel_epoch)
        if value["reconciliation"] is not None:
            with transaction(ctx) as session:
                visible_run(session, ctx, session.get(AgentRun, run_id))
            try:
                await ports.cancel_workflow(ctx.tenant_id, run_id)
            except Exception:
                value["workflow_cleanup_pending"] = True
        return value

    @result.get("/v1/categories/{category_id}/agent-runs")
    @result.get("/v1/personal/agent-runs")
    def history(
        cursor: UUID | None = None,
        page_size: int = 50,
        proposal_id: UUID | None = None,
        project_id: UUID | None = None,
        ctx=run_dependency,
    ):
        from .session_views import _after, _anchor, _head, _human, _runs, _sessions

        with transaction(ctx, read_snapshot=True) as s:
            _human(s, ctx, proposal_id, project_id)
            heads = _runs(_sessions(ctx, proposal_id, project_id))
            query = select(heads)
            if cursor is not None:
                anchor = _anchor(s, select(
                    heads.c.created_at, heads.c.run_id.label("identity"),
                ).where(heads.c.run_id == cursor))
                query = _after(query, heads.c.created_at, heads.c.run_id, anchor)
            limit = min(max(page_size, 1), 200)
            rows = s.execute(query.order_by(
                heads.c.created_at.desc(), heads.c.run_id.desc(),
            ).limit(limit + 1)).mappings().all()
            page = rows[:limit]
            readable = {row.id: row for row in s.scalars(select(AgentRun).where(
                AgentRun.id.in_([row["run_id"] for row in page if row["status"] != "hidden"]),
            ))} if page else {}
            items = []
            for head in page:
                if head["status"] == "hidden":
                    items.append({**_head(head),
                        "product_id": str(head["product_id"]) if head["product_id"] else None,
                        "proposal_id": None,
                        "project_id": str(head["project_id"]) if head["project_id"] else None})
                    continue
                row = readable[head["run_id"]]
                items.append({
                    "run_id": str(row.id), "goal": row.goal,
                    "product_id": str(row.product_id) if row.product_id else None,
                    "proposal_id": str(row.proposal_id) if row.proposal_id else None,
                    "project_id": str(row.project_id) if row.project_id else None,
                    "status": row.state, "error_code": row.error_code,
                    "created_at": row.created_at.isoformat(), **run_revert_status(row),
                })
            return {
                "items": items,
                "next_cursor": str(page[-1]["run_id"]) if len(rows) > limit else None,
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/events")
    @result.get("/v1/personal/agent-runs/{run_id}/events")
    def events(run_id: UUID, after: int = 0, page_size: int = 50, ctx=run_dependency):
        from pdos_next.enterprise_search.assistant_answer import checked_sources

        with transaction(ctx, read_snapshot=True) as s:
            row = visible_run(s, ctx, s.get(AgentRun, run_id))
            checked_sources(s, row)
            rows = s.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == row.id, AgentEvent.sequence > after)
                .order_by(AgentEvent.sequence)
                .limit(min(max(page_size, 1), 200))
            ).all()
            return {
                "items": [{"sequence": r.sequence, "event": r.body} for r in rows],
                "next_cursor": rows[-1].sequence if rows else after,
                "status": row.state,
                "reverted": row.reverted_at is not None,
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/candidates")
    def candidates(
        run_id: UUID,
        after: int = Query(default=0, ge=0),
        page_size: int = Query(default=50, ge=1, le=200),
        ctx=run_dependency,
    ):
        from .domain_candidates import read as read_candidates

        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            row = visible_run(s, ctx, s.get(AgentRun, run_id))
            return read_candidates(s, ctx, row, after=after, page_size=page_size)

    @result.post("/v1/categories/{category_id}/agent-runs/{run_id}/answers", status_code=202)
    @result.post("/v1/personal/agent-runs/{run_id}/answers", status_code=202)
    async def answer(run_id: UUID, data: AnswerInput, ctx=run_dependency):
        with transaction(ctx) as s:
            entry = record_answers(
                s, ctx, run_id, answers=data.answers, idempotency_key=data.idempotency_key
            )
            identity = str(entry.id)
        await ports.signal_workflow(ctx.tenant_id, run_id, identity)
        return {"run_id": str(run_id), "answer_ref": identity, "status": "resume_requested"}

    @result.post("/v1/categories/{category_id}/agent-runs/{run_id}/cancel")
    @result.post("/v1/personal/agent-runs/{run_id}/cancel")
    async def cancel(run_id: UUID, ctx=run_dependency):
        with transaction(ctx) as s:
            value = cancel_run(s, ctx, run_id)
        try:
            await ports.cancel_workflow(ctx.tenant_id, run_id)
        except Exception:
            value["workflow_cancel_pending"] = True
        return value

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/stream")
    @result.get("/v1/personal/agent-runs/{run_id}/stream")
    async def stream(run_id: UUID, request: Request, after: int = 0, ctx=run_dependency):
        # Authenticate before headers, and re-read RLS on every page. Disconnecting
        # the process panel leaves the durable workflow running.
        events(run_id, after, 1, ctx)

        async def generate():
            cursor = max(0, after)
            while not await request.is_disconnected():
                try:
                    page = events(run_id, cursor, 100, ctx)
                except DomainError:
                    yield 'event: unavailable\ndata: {"code":"FORBIDDEN_SCOPE"}\n\n'
                    return
                for item in page["items"]:
                    cursor = item["sequence"]
                    yield (
                        f"id: {cursor}\nevent: process\ndata: "
                        + json.dumps(item["event"], ensure_ascii=False)
                        + "\n\n"
                    )
                if page["reverted"] or page["status"] in {
                    "completed",
                    "partial",
                    "cancelled",
                    "failed",
                }:
                    yield (
                        "event: end\ndata: "
                        + json.dumps({"status": page["status"], "reverted": page["reverted"]})
                        + "\n\n"
                    )
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return result
