"""Authenticated metadata-only page retrieval; no Run, model or background reindex on read."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.session_views import _human
from pdos_next.errors import DomainError

from .assistant_adapter import AssistantReadAdapter
from .query import SearchInput, search


def router(*, transaction, context_dependency, engine):
    result = APIRouter()

    @result.post("/v1/personal/enterprise-search")
    @result.post("/v1/categories/{category_id}/enterprise-search")
    def searching(data: SearchInput, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return search(session, ctx, data)

    @result.get("/v1/personal/agent-runs/{run_id}/assistant-sources/{citation_id}")
    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/assistant-sources/{citation_id}")
    def passage(
        run_id: UUID,
        citation_id: UUID,
        request: Request,
        cursor: int = Query(default=0, ge=0),
        page_chars: int = Query(default=1600, ge=1, le=2000),
        change_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
        ctx=context_dependency,
    ):
        keys = list(request.query_params)
        if set(keys) - {"cursor", "page_chars", "change_id"} or any(
            len(request.query_params.getlist(key)) != 1 for key in keys
        ):
            raise DomainError("INVALID_PAYLOAD", "只接受固定片段的有界读取条件。", 422)
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            run = session.get(AgentRun, run_id)
            if (
                not run
                or run.requester_id != ctx.requester_id
                or run.category_id != ctx.category_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "引用不在本人当前工作范围。", 403)
            scope = scope_for_run(run).child("assistant_extract", citation_ids={citation_id})
        adapter = AssistantReadAdapter(KernelStore(engine), None)
        if change_id is not None:
            from .comparison_passage import read

            return read(adapter, scope, citation_id, change_id, cursor, page_chars)
        return adapter.passage(
            scope,
            {"citation_id": citation_id, "cursor": cursor, "page_chars": page_chars},
            historical=True,
        )

    return result
