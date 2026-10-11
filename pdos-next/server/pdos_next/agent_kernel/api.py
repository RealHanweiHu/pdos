"""Thin authenticated run API; no synchronous model path or model-supplied authority."""

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import and_, or_, select

from pdos_next.contracts import SourceRead
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, require_access

from .models import AgentEvent, AgentRun
from .persistence import cancel_run, create_run, record_answers, run_revert_status


class StartInput(StrictModel):
    goal: str = Field(min_length=3, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=160)
    session_id: UUID | None = None
    product_id: UUID | None = None
    proposal_id: UUID | None = None
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

    def transaction(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        )

    @result.post("/v1/categories/{category_id}/agent-runs", status_code=202)
    @result.post("/v1/personal/agent-runs", status_code=202)
    async def start(data: StartInput, ctx=run_dependency):
        request_digest = digest(
            {
                "category_id": ctx.category_id,
                "request": data.model_dump(exclude={"idempotency_key"}),
            }
        )
        # This host callback binds proposal audience/source taint, not a boolean from the client.
        with transaction(ctx) as s:
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
            else:
                binding = ports.binding_for(s, ctx, data)
                row = create_run(
                    s,
                    ctx,
                    goal=data.goal,
                    writer_id=ports.writer_for(s, ctx),
                    intent_key=data.idempotency_key,
                    session_id=data.session_id,
                    product_id=data.product_id,
                    proposal_id=data.proposal_id,
                    private_context=binding.private_context,
                    data_categories=binding.data_categories,
                    customer_identities=binding.customer_identities,
                    read_sources=binding.read_sources,
                    token_limit=getattr(binding, "token_limit", 100000),
                    validation_budget_id=getattr(binding, "validation_budget_id", None),
                    request_digest=request_digest,
                )
            ref = reference(row, ctx)
            value = {"run_id": str(row.id), "session_id": str(row.session_id), "status": row.state}
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
        with transaction(ctx) as s:
            row = s.get(AgentRun, run_id)
            if not row or row.requester_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "运行不在当前可读范围。")
            return {
                "run_id": str(row.id),
                "session_id": str(row.session_id),
                "product_id": str(row.product_id) if row.product_id else None,
                "status": row.state,
                "result": row.result,
                "error_code": row.error_code,
                "versions": row.versions,
                **run_revert_status(row),
            }

    @result.get("/v1/categories/{category_id}/agent-runs")
    @result.get("/v1/personal/agent-runs")
    def history(cursor: UUID | None = None, page_size: int = 50, ctx=run_dependency):
        with transaction(ctx) as s:
            query = select(AgentRun).where(
                AgentRun.requester_id == ctx.requester_id, AgentRun.category_id == ctx.category_id
            )
            if cursor is not None:
                anchor = s.get(AgentRun, cursor)
                if anchor is None or anchor.requester_id != ctx.requester_id:
                    raise DomainError("FORBIDDEN_SCOPE", "运行历史游标不在当前可读范围。", 403)
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
            row = s.get(AgentRun, run_id)
            if not row or row.requester_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "运行不在当前可读范围。")
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
