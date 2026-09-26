"""Project-scoped personal ID confirmations and outstanding receiver handoffs."""

from typing import Any
from uuid import UUID

from sqlalchemy import Table, exists, literal, or_, select, union_all
from sqlalchemy.sql import ColumnElement, Select

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables


def inbox_statement(tenant_id: UUID, user_id: UUID, role: Role) -> Select[Any] | None:
    p, q, d, v, f = (
        tables.projects,
        tables.id_design_freeze_requests,
        tables.id_design_freeze_decisions,
        tables.id_design_revisions,
        tables.id_design_freezes,
    )
    variants = tables.id_design_variants
    parts = []

    def fields(
        table: Table,
        kind: str,
        revision_id: ColumnElement[Any],
        freeze_id: ColumnElement[Any],
        title: ColumnElement[Any],
    ) -> tuple[ColumnElement[Any], ...]:
        return (
            table.c.id,
            literal(kind).label("kind"),
            revision_id.label("revision_id"),
            freeze_id.label("freeze_id"),
            title.label("title"),
            table.c.created_at,
            p.c.id.label("project_id"),
            p.c.code.label("project_code"),
            p.c.name.label("project_name"),
        )

    def scope(statement: Select[Any]) -> Select[Any]:
        statement = statement.where(
            p.c.tenant_id == tenant_id, p.c.status.in_(("approved", "active", "on_hold"))
        )
        if role not in (Role.OWNER, Role.ADMIN):
            statement = statement.where(
                exists(
                    select(tables.project_members.c.user_id).where(
                        tables.project_members.c.tenant_id == tenant_id,
                        tables.project_members.c.project_id == p.c.id,
                        tables.project_members.c.user_id == user_id,
                    )
                )
            )
        return statement

    if is_allowed(role, Action.PRODUCT_ENGINEERING_EDIT):
        newer = v.alias("newer_id_inbox_revision")
        successor = q.alias("successor_id_freeze_request")
        own = []
        for slot in ("product", "me", "hw"):
            own.append(
                (q.c[f"{slot}_user_id"] == user_id)
                & ~exists(
                    select(d.c.id).where(
                        d.c.tenant_id == tenant_id,
                        d.c.project_id == q.c.project_id,
                        d.c.freeze_request_id == q.c.id,
                        d.c.slot == slot,
                    )
                )
            )
        parts.append(
            scope(
                select(
                    *fields(
                        q,
                        "freeze",
                        q.c.revision_id,
                        literal(None, type_=f.c.id.type),
                        variants.c.title,
                    )
                )
                .select_from(q)
                .join(p, (p.c.tenant_id == q.c.tenant_id) & (p.c.id == q.c.project_id))
                .join(
                    v,
                    (v.c.tenant_id == q.c.tenant_id)
                    & (v.c.project_id == q.c.project_id)
                    & (v.c.id == q.c.revision_id),
                )
                .join(
                    variants,
                    (variants.c.tenant_id == v.c.tenant_id)
                    & (variants.c.project_id == v.c.project_id)
                    & (variants.c.id == v.c.variant_id),
                )
                .where(
                    q.c.tenant_id == tenant_id,
                    ~exists(
                        select(successor.c.id).where(
                            successor.c.tenant_id == q.c.tenant_id,
                            successor.c.project_id == q.c.project_id,
                            successor.c.previous_request_id == q.c.id,
                        )
                    ),
                    or_(*own),
                    ~exists(
                        select(d.c.id).where(
                            d.c.tenant_id == tenant_id,
                            d.c.project_id == q.c.project_id,
                            d.c.freeze_request_id == q.c.id,
                            d.c.action == "reject",
                        )
                    ),
                    ~exists(
                        select(f.c.id).where(
                            f.c.tenant_id == tenant_id,
                            f.c.project_id == q.c.project_id,
                            f.c.variant_id == v.c.variant_id,
                        )
                    ),
                    ~exists(
                        select(newer.c.id).where(
                            newer.c.tenant_id == tenant_id,
                            newer.c.project_id == v.c.project_id,
                            newer.c.variant_id == v.c.variant_id,
                            newer.c.version > v.c.version,
                        )
                    ),
                )
            )
        )
    if is_allowed(role, Action.WORK_ITEM_EDIT):
        h, i, r = (
            tables.id_design_handoffs,
            tables.id_design_handoff_items,
            tables.id_design_handoff_responses,
        )
        next_handoff = h.alias("newer_id_inbox_handoff")
        returned = exists(
            select(r.c.id)
            .join(
                i,
                (i.c.tenant_id == r.c.tenant_id)
                & (i.c.project_id == r.c.project_id)
                & (i.c.id == r.c.item_id),
            )
            .where(
                r.c.tenant_id == tenant_id,
                i.c.project_id == h.c.project_id,
                i.c.handoff_id == h.c.id,
                r.c.action == "return",
            )
        )
        missing = exists(
            select(i.c.id).where(
                i.c.tenant_id == tenant_id,
                i.c.project_id == h.c.project_id,
                i.c.handoff_id == h.c.id,
                ~exists(
                    select(r.c.id).where(
                        r.c.tenant_id == tenant_id,
                        r.c.project_id == i.c.project_id,
                        r.c.item_id == i.c.id,
                    )
                ),
            )
        )
        parts.append(
            scope(
                select(
                    *fields(
                        h,
                        "handoff",
                        f.c.revision_id,
                        h.c.freeze_id,
                        h.c.snapshot["target"]["title"].as_string(),
                    )
                )
                .select_from(h)
                .join(p, (p.c.tenant_id == h.c.tenant_id) & (p.c.id == h.c.project_id))
                .join(
                    f,
                    (f.c.tenant_id == h.c.tenant_id)
                    & (f.c.project_id == h.c.project_id)
                    & (f.c.id == h.c.freeze_id),
                )
                .where(
                    h.c.tenant_id == tenant_id,
                    h.c.receiver_user_id == user_id,
                    ~exists(
                        select(tables.id_design_activations.c.id).where(
                            tables.id_design_activations.c.tenant_id == tenant_id,
                            tables.id_design_activations.c.project_id == h.c.project_id,
                            tables.id_design_activations.c.old_freeze_id == h.c.freeze_id,
                        )
                    ),
                    ~returned,
                    missing,
                    ~exists(
                        select(next_handoff.c.id).where(
                            next_handoff.c.tenant_id == tenant_id,
                            next_handoff.c.project_id == h.c.project_id,
                            next_handoff.c.previous_handoff_id == h.c.id,
                        )
                    ),
                )
            )
        )
    if not parts:
        return None
    rows = union_all(*parts).subquery("id_design_inbox")
    return select(rows)
