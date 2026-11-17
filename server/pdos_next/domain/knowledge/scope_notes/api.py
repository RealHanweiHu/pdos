"""Read routes for scope notes (M2b); every write uses the common command path.

A person previews and confirms ``scope_note.save`` / ``scope_note.retire`` /
``scope_note.observation.record`` through ``POST …/commands/preview`` and
``POST …/commands`` like any T1 command, so the receipt, the one confirmation
and the audience shown before confirming are the same for a page action and
for a candidate 小Pai prefilled.
"""

from typing import Literal
from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context

from . import reads

AnchorKind = Literal["category", "product", "proposal", "project"]


def register_routes(app, engine, auth_dependency):
    def session(ctx):
        return tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
                              requester_id=ctx.requester_id, category_id=ctx.category_id)

    @app.get("/v1/categories/{category_id}/scope-notes/{anchor_kind}/{anchor_id}")
    def scope_notes(anchor_kind: AnchorKind, anchor_id: UUID, ctx: Context = auth_dependency):
        with session(ctx) as s:
            return reads.listing(s, ctx, anchor_kind, anchor_id)

    @app.get("/v1/categories/{category_id}/scope-notes/{anchor_kind}/{anchor_id}/all")
    def scope_notes_all(anchor_kind: AnchorKind, anchor_id: UUID,
                        ctx: Context = auth_dependency):
        with session(ctx) as s:
            return reads.listing(s, ctx, anchor_kind, anchor_id, include_history=True)

    @app.get("/v1/categories/{category_id}/scope-note-items/{note_id}")
    def scope_note(note_id: UUID, ctx: Context = auth_dependency):
        with session(ctx) as s:
            return reads.history(s, ctx, note_id)

    @app.get("/v1/categories/{category_id}/scope-note-sources/{anchor_kind}/{anchor_id}")
    def scope_note_sources(anchor_kind: AnchorKind, anchor_id: UUID,
                           ctx: Context = auth_dependency):
        # D509: what the page may offer as evidence or formal object; the command re-checks.
        from .sources import options

        with session(ctx) as s:
            return options(s, ctx, anchor_kind, anchor_id)

    @app.get("/v1/categories/{category_id}/scope-recent/{anchor_kind}/{anchor_id}")
    def scope_recent(anchor_kind: AnchorKind, anchor_id: UUID, ctx: Context = auth_dependency):
        from .recent import view

        with session(ctx) as s:
            return view(s, ctx, anchor_kind, anchor_id)
