"""Project discussions and object comments; every write is a named human's own (P34-2)."""

from typing import Literal
from uuid import UUID

from fastapi import Request

from pdos_next.core.database import category_transaction, tenant_session
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.baseline.api import _query
from pdos_next.errors import DomainError

from . import service

PROJECT = "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}"
TOPICS = PROJECT + "/discussions"
THREAD = TOPICS + "/{thread_id}"
COMMENTS = PROJECT + "/comments/{subject_type}/{subject_id}"
MENTIONABLE = PROJECT + "/mentionable"
SubjectType = Literal["work_task", "artifact"]


def _before(request):
    value = request.query_params.get("before")
    if value is None:
        return None
    if not value.isdigit() or int(value) < 1:
        raise DomainError("INVALID_PAYLOAD", "分页位置无效。", 422)
    return int(value)


def register_routes(app, engine, auth_dependency):
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
        return category_transaction(engine, ctx, action)

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
