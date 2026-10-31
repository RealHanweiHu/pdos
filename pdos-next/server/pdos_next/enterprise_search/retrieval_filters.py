"""Shared pre-count authority predicates, extracted from approved explicit corrections."""

from uuid import UUID

from sqlalchemy import and_, or_, select, tuple_


def scoped_authority(
    authority,
    tenant_id,
    scope,
    *,
    include_history,
    graph=None,
    include_sources=None,
    focus_object=None,
    current_only=False,
    exclude_project=None,
    exclude_proposal=None,
    exclude_sources=(),
    allow_customer_private=True,
):
    scoped = select(authority).where(authority.c.tenant_id == tenant_id)
    explicit = None
    if include_sources is not None:
        explicit = tuple_(
            authority.c.source_type,
            authority.c.source_id,
            authority.c.source_revision,
            authority.c.content_hash,
        ).in_(
            [
                (kind, UUID(str(identity)), revision, sha)
                for kind, identity, revision, sha in include_sources
            ]
        )
        scoped = scoped.where(explicit)
    if focus_object is not None:
        focus = and_(
            authority.c.source_type == focus_object[0],
            authority.c.object_id == UUID(str(focus_object[1])),
        )
        scoped = scoped.where(focus)
        explicit = focus if explicit is None else and_(explicit, focus)
    if current_only:
        scoped = scoped.where(authority.c.is_current)
    for key, value in scope.items():
        if value is not None:
            predicate = getattr(authority.c, key) == value
            if key != "category_id" and explicit is not None:
                predicate = or_(predicate, explicit)
            scoped = scoped.where(predicate)
    if exclude_project is not None:
        scoped = scoped.where(authority.c.project_id.is_distinct_from(exclude_project))
    if exclude_proposal is not None:
        scoped = scoped.where(authority.c.proposal_id.is_distinct_from(exclude_proposal))
    if exclude_sources:
        scoped = scoped.where(
            ~tuple_(authority.c.source_type, authority.c.source_id).in_(
                [(kind, UUID(str(identity))) for kind, identity in exclude_sources]
            )
        )
    if not allow_customer_private:
        scoped = scoped.where(~and_(authority.c.private, authority.c.customer_original))
    if not include_history:
        current = authority.c.is_current
        if graph is not None:
            current = or_(
                current,
                and_(
                    authority.c.source_type.in_(["issue", "capa"]),
                    tuple_(authority.c.source_type, authority.c.source_id).in_(
                        select(graph.c.target_kind, graph.c.target_id)
                    ),
                ),
            )
        scoped = scoped.where(current)
    return scoped
