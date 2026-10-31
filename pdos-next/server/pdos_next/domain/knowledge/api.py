"""Knowledge inputs and reads; all effects use the common command boundary."""

from uuid import UUID

from fastapi import Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.service import Context

from .assistant_schemas import (
    AnswerDraftInput,
    AttributionInput,
    GapInput,
    GapPreviewInput,
    ReviewDraftInput,
)


def register_routes(app, engine, auth_dependency):
    def session(ctx, *, reading=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=reading,
        )

    @app.get("/v1/categories/{category_id}/experience")
    @app.get("/v1/categories/{category_id}/products/{product_id}/experience")
    def experience(
        request: Request,
        product_id: UUID | None = None,
        project_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from .views import workspace

        _query(request, {"project_id"})
        with session(ctx, reading=True) as s:
            return workspace(s, ctx, product_id, project_id)

    @app.post("/v1/categories/{category_id}/experience/inputs")
    @app.post("/v1/categories/{category_id}/products/{product_id}/experience/inputs")
    def experience_inputs(
        request: Request,
        data: Command,
        product_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import inputs

        _query(request, set())
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)

    @app.post("/v1/categories/{category_id}/experience/answer-draft")
    def answer_knowledge_draft(
        request: Request, data: AnswerDraftInput, ctx: Context = auth_dependency
    ):
        from .assistant_views import draft

        _query(request, set())
        with session(ctx, reading=True) as s:
            return draft(s, ctx, data)

    @app.post("/v1/categories/{category_id}/experience/review-draft")
    def answer_review_draft(
        request: Request, data: ReviewDraftInput, ctx: Context = auth_dependency
    ):
        from .assistant_views import review_draft

        _query(request, set())
        with session(ctx, reading=True) as s:
            return review_draft(s, ctx, data)

    @app.get("/v1/categories/{category_id}/experience/verified-answers")
    def answers(request: Request, ctx: Context = auth_dependency):
        from .assistant_views import verified_answers

        _query(request, set())
        with session(ctx, reading=True) as s:
            return verified_answers(s, ctx)

    @app.get("/v1/personal/knowledge-review-reminders")
    def review_reminders(request: Request, ctx: Context = auth_dependency):
        from pdos_next.domain.preproject.access import human

        from .assistant_views import reminders

        _query(request, set())
        with session(ctx, reading=True) as s:
            human(s, ctx)
            return reminders(s, ctx)

    @app.post("/v1/categories/{category_id}/experience/gaps/preview")
    def gap_preview(request: Request, data: GapPreviewInput, ctx: Context = auth_dependency):
        from .assistant_gaps import preview

        _query(request, set())
        with session(ctx, reading=True) as s:
            return preview(s, ctx, data, engine=engine)[0]

    @app.post("/v1/categories/{category_id}/experience/gaps")
    def gap_submit(request: Request, data: GapInput, ctx: Context = auth_dependency):
        from .assistant_gaps import submit

        _query(request, set())
        with session(ctx) as s:
            return submit(s, ctx, data, engine=engine)

    @app.post("/v1/categories/{category_id}/experience/gaps/recover")
    def gap_recover(request: Request, data: GapInput, ctx: Context = auth_dependency):
        from .assistant_gaps import recover

        _query(request, set())
        with session(ctx, reading=True) as s:
            return recover(s, ctx, data)

    @app.get("/v1/categories/{category_id}/experience/gaps/weekly")
    def gap_weekly(request: Request, week: str, ctx: Context = auth_dependency):
        from .assistant_gaps import weekly

        _query(request, {"week"})
        with session(ctx, reading=True) as s:
            return weekly(s, ctx, week)

    @app.post("/v1/categories/{category_id}/experience/gaps/attributions")
    def gap_attribute(request: Request, data: AttributionInput, ctx: Context = auth_dependency):
        from .assistant_gaps import attribute

        _query(request, set())
        with session(ctx) as s:
            return attribute(s, ctx, data)
