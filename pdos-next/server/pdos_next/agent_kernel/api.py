"""Thin authenticated run API; no synchronous model path or model-supplied authority."""

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import load_only

from pdos_next.contracts import SourceRead
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .models import AgentEvent, AgentRun
from .persistence import cancel_run, create_run, record_answers, run_revert_status
from .run_feedback import FeedbackInput
from .run_reconciliation import ReconcileInput


class StartInput(StrictModel):
    goal: str = Field(min_length=3, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=160)
    session_id: UUID | None = None
    continue_from_run_id: UUID | None = None
    product_id: UUID | None = None
    proposal_id: UUID | None = None
    project_id: UUID | None = None
    sources: list[SourceRead] = Field(default_factory=list)


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

    @result.post("/v1/categories/{category_id}/agent-runs", status_code=202)
    @result.post("/v1/personal/agent-runs", status_code=202)
    async def start(data: StartInput, ctx=run_dependency):
        request_digest = digest(
            {
                "category_id": ctx.category_id,
                "request": data.model_dump(exclude={"idempotency_key"} | (
                    {"project_id"} if data.project_id is None else set()
                )),
            }
        )
        # This host callback binds proposal audience/source taint, not a boolean from the client.
        with transaction(ctx) as s:
            lock_key = f"xiaopai-start:{ctx.tenant_id}:{ctx.requester_id}:{data.idempotency_key}"
            s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                      {"key": lock_key})
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
                effective, parent = prepare(s, ctx, data)
                binding = merge_binding(ports.binding_for(s, ctx, effective), parent)
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
            ref = reference(row, ctx)
            value = {"run_id": str(row.id), "session_id": str(row.session_id), "status": row.state,
                     "continued_from_id": (
                         str(row.continued_from_id) if row.continued_from_id else None)}
            if not s.scalar(select(AgentEvent.id).where(AgentEvent.run_id == row.id)):
                s.add(
                    AgentEvent(
                        tenant_id=ctx.tenant_id,
                        run_id=row.id,
                        sequence=1,
                        body={"type": "accepted", "status": "queued"},
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
        from .conversation import links
        from .process_view import read_process
        from .run_reconciliation import completed_record
        with transaction(ctx, read_snapshot=True) as s:
            row = visible_run(s, ctx, s.get(AgentRun, run_id))
            return {
                "run_id": str(row.id),
                "goal": row.goal,
                "session_id": str(row.session_id),
                "conversation": links(s, row),
                "product_id": str(row.product_id) if row.product_id else None,
                "proposal_id": str(row.proposal_id) if row.proposal_id else None,
                "project_id": str(row.project_id) if row.project_id else None,
                "status": row.state,
                "result": row.result,
                "error_code": row.error_code,
                "reconciliation": completed_record(s, row),
                "process": read_process(s, row),
                "versions": row.versions,
                **run_revert_status(row),
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/process")
    @result.get("/v1/personal/agent-runs/{run_id}/process")
    def process(
        run_id: UUID, before: int | None = Query(default=None, ge=1),
        source_cursor: UUID | None = None, receipt_cursor: UUID | None = None,
        page_size: int = Query(default=25, ge=1, le=100), ctx=run_dependency,
    ):
        from .process_view import read_process
        with transaction(ctx, read_snapshot=True) as session:
            row = session.scalar(select(AgentRun).where(AgentRun.id == run_id).options(load_only(
                AgentRun.id, AgentRun.tenant_id, AgentRun.category_id, AgentRun.proposal_id,
                AgentRun.product_id, AgentRun.project_id,
                AgentRun.requester_id, AgentRun.state, AgentRun.error_code, AgentRun.created_at,
                AgentRun.reverted_at, AgentRun.read_sources, raiseload=True,
            )))
            return read_process(session, visible_run(session, ctx, row),
                                before=before, page_size=page_size,
                                source_cursor=source_cursor, receipt_cursor=receipt_cursor)

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/continuation")
    @result.get("/v1/personal/agent-runs/{run_id}/continuation")
    def continuation(run_id: UUID, ctx=run_dependency):
        from .run_reconciliation import owner
        with transaction(ctx, read_snapshot=True) as session:
            row = session.scalar(select(AgentRun).where(AgentRun.id == run_id).options(load_only(
                AgentRun.id, AgentRun.tenant_id, AgentRun.category_id, AgentRun.proposal_id,
                AgentRun.product_id, AgentRun.project_id,
                AgentRun.requester_id, AgentRun.state, AgentRun.reverted_at, raiseload=True,
            )))
            owner(session, ctx, visible_run(session, ctx, row))
            child = session.execute(select(AgentRun.id, AgentRun.goal, AgentRun.intent_key).where(
                AgentRun.continued_from_id == row.id)).one_or_none()
            return {"run_id": str(row.id), "owner_id": str(row.requester_id),
                    "can_continue": not row.reverted_at and row.state in {
                        "completed", "partial", "failed", "cancelled"} and child is None,
                    "existing": {"run_id": str(child.id), "goal": child.goal,
                                 "idempotency_key": child.intent_key} if child else None}

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/reconciliation")
    @result.get("/v1/personal/agent-runs/{run_id}/reconciliation")
    def inspect_reconciliation(
        run_id: UUID, call_cursor: UUID | None = None, receipt_cursor: UUID | None = None,
        page_size: int = Query(default=50, ge=1, le=100), ctx=run_dependency,
    ):
        from .run_reconciliation import inspect
        with transaction(ctx) as session:
            row = visible_run(session, ctx, session.get(AgentRun, run_id))
            return inspect(session, ctx, row, call_cursor=call_cursor,
                           receipt_cursor=receipt_cursor, page_size=page_size)

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/feedback")
    @result.get("/v1/personal/agent-runs/{run_id}/feedback")
    def feedback(run_id: UUID, before: int | None = Query(default=None, ge=1),
                 page_size: int = Query(default=25, ge=1, le=100),
                 request_key: UUID | None = None, ctx=run_dependency):
        from .run_feedback import lookup, read
        with transaction(ctx, read_snapshot=True) as session:
            return read(session, ctx, visible_run(session, ctx, lookup(session, run_id)),
                        before=before, page_size=page_size, request_key=request_key)

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
        from pdos_next.domain.preproject.models import Proposal

        with transaction(ctx) as s:
            if proposal_id is not None:
                from pdos_next.domain.preproject.access import proposal

                if ctx.category_id is None:
                    raise DomainError("FORBIDDEN_SCOPE", "个人入口不能读取提案运行。", 403)
                proposal(s, ctx, proposal_id)
            query = select(AgentRun).where(
                AgentRun.requester_id == ctx.requester_id,
                AgentRun.category_id == ctx.category_id,
                or_(
                    AgentRun.proposal_id.is_(None),
                    AgentRun.proposal_id.in_(select(Proposal.id)),
                ),
            )
            if proposal_id is not None:
                query = query.where(AgentRun.proposal_id == proposal_id)
            if project_id is not None:
                from pdos_next.domain.projects.models import Project

                project = s.get(Project, project_id)
                if (
                    project is None or project.tenant_id != ctx.tenant_id
                    or project.category_id != ctx.category_id
                ):
                    raise DomainError("FORBIDDEN_SCOPE", "项目不在当前可读范围。", 403)
                query = query.where(AgentRun.project_id == project_id)
            if cursor is not None:
                anchor = s.get(AgentRun, cursor)
                if (
                    anchor is None
                    or anchor.requester_id != ctx.requester_id
                    or proposal_id is not None
                    and anchor.proposal_id != proposal_id
                    or project_id is not None
                    and anchor.project_id != project_id
                ):
                    raise DomainError("FORBIDDEN_SCOPE", "运行历史游标不在当前可读范围。", 403)
                visible_run(s, ctx, anchor)
                query = query.where(
                    or_(
                        AgentRun.created_at < anchor.created_at,
                        and_(AgentRun.created_at == anchor.created_at, AgentRun.id < anchor.id),
                    )
                )
            limit = min(max(page_size, 1), 200)
            rows = list(
                s.scalars(
                    query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(limit + 1)
                )
            )
            page = rows[:limit]
            return {
                "items": [
                    {
                        "run_id": str(row.id),
                        "goal": row.goal,
                        "product_id": str(row.product_id) if row.product_id else None,
                        "proposal_id": str(row.proposal_id) if row.proposal_id else None,
                        "project_id": str(row.project_id) if row.project_id else None,
                        "status": row.state,
                        "error_code": row.error_code,
                        "created_at": row.created_at.isoformat(),
                        **run_revert_status(row),
                    }
                    for row in page
                ],
                "next_cursor": str(page[-1].id) if len(rows) > limit else None,
            }

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/events")
    @result.get("/v1/personal/agent-runs/{run_id}/events")
    def events(run_id: UUID, after: int = 0, page_size: int = 50, ctx=run_dependency):
        with transaction(ctx) as s:
            row = visible_run(s, ctx, s.get(AgentRun, run_id))
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
