"""Shared SQL syntax for native sources under the caller's ordinary live RLS."""

from functools import lru_cache

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import aliased


@lru_cache(maxsize=None)  # noqa: UP033 - retain alias identity for all cached catalogs
def readable(model):
    """Reuse one materialized table expression across catalog and graph branches.

    Only the model's SQL alias is cached. Rows, principals and permissions are
    never cached: PostgreSQL evaluates the session-bound tenant and the source
    table's ordinary RLS anew on each execution. Complete columns let all users
    of a native model share the exact same CTE object within one statement.
    """
    tenant = cast(func.nullif(func.current_setting("pdos.tenant_id", True), ""), UUID)
    rows = (
        select(model)
        .where(model.tenant_id == tenant)
        .cte("shared_enterprise_" + model.__tablename__)
        .prefix_with("MATERIALIZED")
    )
    return aliased(model, rows)
