"""Project discussions and object comments; every write is a named human's own (P34-2)."""

from typing import Literal
from uuid import UUID

from fastapi import Request

from pdos_next.core.database import category_transaction, tenant_session
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.baseline.api import _query
from pdos_next.errors import DomainError

from . import agent, service

PROJECT = "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}"
TOPICS = PROJECT + "/discussions"
THREAD = TOPICS + "/{thread_id}"
COMMENTS = PROJECT + "/comments/{subject_type}/{subject_id}"
MENTIONABLE = PROJECT + "/mentionable"
AGENT_REQUEST = THREAD + "/agent-requests/{request_id}"
SubjectType = Literal["work_task", "artifact"]


def _before(request):
    value = request.query_params.get("before")
    if value is None:
        return None
    if not value.isdigit() or int(value) < 1:
        raise DomainError("INVALID_PAYLOAD", "分页位置无效。", 422)
    return int(value)


def _start_runs(ports, refs):
    """After commit: hand each new Run to the one 小Pai workflow (Temporal → LangGraph).

    An unavailable Temporal leaves the Run queued; the worker's pending-run dispatcher
    starts the same workflow ID later. There is never a local inference fallback.
    """
    import anyio

    for ref in refs:
        try:
            anyio.from_thread.run(ports.start_workflow, ref)
        except Exception:  # noqa: BLE001 - recovered by kernel_pending_run_references
            continue


def register_routes(app, engine, auth_dependency, agent_ports=None):
    def reading(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        )

    def write(ctx, action):
        def bound(s):
            s.info["agent_ports"] = agent_ports
            value = action(s)
            refs = list(s.info.pop("agent_runs", ()))
            return value, refs

        value, refs = category_transaction(engine, ctx, bound)
        if refs and agent_ports is not None:
            _start_runs(agent_ports, refs)
        return value

    @app.get(TOPICS)
    def project_topics(
        request: Request, product_id: UUID, project_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, set())
        with reading(ctx) as s:
            return service.topics(s, ctx, product_id, project_id)

    @app.post(TOPICS, status_code=201)
    def start_topic(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        data: service.NewTopic,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(ctx, lambda s: service.start_topic(s, ctx, product_id, project_id, data))

    @app.get(THREAD)
    def read_thread(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        ctx: Context = auth_dependency,
    ):
        _query(request, {"before"})
        with reading(ctx) as s:
            return service.thread(s, ctx, product_id, project_id, thread_id, _before(request))

    @app.post(THREAD + "/messages", status_code=201)
    def post_message(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        data: service.NewMessage,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(ctx, lambda s: service.post(s, ctx, product_id, project_id, thread_id, data))

    @app.post(THREAD + "/messages/{message_id}/edit")
    def edit_message(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        message_id: UUID,
        data: service.EditMessage,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(
            ctx,
            lambda s: service.edit(s, ctx, product_id, project_id, thread_id, message_id, data),
        )

    @app.post(THREAD + "/messages/{message_id}/retract")
    def retract_message(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        message_id: UUID,
        data: service.RetractMessage,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(
            ctx,
            lambda s: service.retract(s, ctx, product_id, project_id, thread_id, message_id, data),
        )

    @app.post(THREAD + "/follow")
    def follow_thread(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        data: service.FollowChange,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(
            ctx, lambda s: service.set_follow(s, ctx, product_id, project_id, thread_id, data)
        )

    @app.get(AGENT_REQUEST + "/reply")
    def agent_reply(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        request_id: UUID,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        with reading(ctx) as s:
            project = service._project(s, ctx, product_id, project_id)
            thread = service._thread(s, ctx, project, thread_id)
            return agent.reply(s, ctx, project, thread, request_id)

    @app.post(AGENT_REQUEST + "/share")
    def share_agent_reply(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        thread_id: UUID,
        request_id: UUID,
        data: agent.ShareRequest,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())

        def action(s):
            project = service._project(s, ctx, product_id, project_id, write=True)
            thread = service._thread(s, ctx, project, thread_id)
            agent.share(s, ctx, project, thread, request_id, data)
            return service._thread_view(
                s, ctx, project, thread, full=service._full(s, ctx, project)
            )

        return write(ctx, action)

    @app.get(COMMENTS)
    def object_comments(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        subject_type: SubjectType,
        subject_id: UUID,
        ctx: Context = auth_dependency,
    ):
        _query(request, {"before"})
        with reading(ctx) as s:
            return service.comments(
                s, ctx, product_id, project_id, subject_type, subject_id, _before(request)
            )

    @app.post(COMMENTS, status_code=201)
    def post_comment(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        subject_type: SubjectType,
        subject_id: UUID,
        data: service.NewMessage,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return write(
            ctx,
            lambda s: service.comment(
                s, ctx, product_id, project_id, subject_type, subject_id, data
            ),
        )

    @app.get(MENTIONABLE)
    def mentionable(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        ctx: Context = auth_dependency,
    ):
        _query(request, {"subject_type", "subject_id"})
        subject_type = request.query_params.get("subject_type", "project")
        if subject_type not in {"project", "work_task", "artifact"}:
            raise DomainError("INVALID_PAYLOAD", "对象类型无效。", 422)
        raw = request.query_params.get("subject_id")
        try:
            subject_id = UUID(raw) if raw else project_id
        except ValueError as error:
            raise DomainError("INVALID_PAYLOAD", "对象标识无效。", 422) from error
        with reading(ctx) as s:
            return service.mentionable(s, ctx, product_id, project_id, subject_type, subject_id)
