"""Canonical supply-pool locks shared by capture, allocation and release."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Connection, text

PoolKey = tuple[str, str, str]


def lock_pools(connection: Connection, tenant_id: UUID, keys: Iterable[PoolKey]) -> None:
    for source, pool, item in sorted(set(keys)):
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array("
                "CAST(:tenant AS text), CAST(:source AS text), CAST(:pool AS text),"
                "CAST(:item AS text))::text,0))"
            ),
            {"tenant": str(tenant_id), "source": source, "pool": pool, "item": item},
        )
