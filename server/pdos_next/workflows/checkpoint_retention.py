"""LangGraph checkpoint retention (D58; P78 item 3; D193): 30 days, purged daily.

One pass for one tenant:

1. Nothing is deleted unless the checkpoint database holds exactly the tables and
   columns the lifecycle catalog lists (CHECKPOINT_COVERED_COLUMNS).
2. Checkpoint addresses are grouped by owner, read from the server-built thread id:
   an agent Run or an embedding batch. Thread ids of any other shape are kept.
3. Owners whose newest checkpoint is newer than 30 days are kept.
4. For the older owners, the business database (dispatch role, open/closed flags
   only) says which are still open: queued, running or waiting Runs; queued,
   running or retryable batches. Open owners are kept, and so are owners the
   business database does not return.
5. Every checkpoint row of the remaining closed owners is deleted.

No model is called on any path.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
from sqlalchemy import text
from temporalio import activity

from pdos_next.core.database import tenant_session
from pdos_next.originals.lifecycle.catalog import (
    CHECKPOINT_COVERED_COLUMNS,
    CHECKPOINT_PURGED,
    CHECKPOINT_RETENTION_DAYS,
)

RETENTION = timedelta(days=CHECKPOINT_RETENTION_DAYS)
OWNER_PAGE = 200
_DIGEST = re.compile(r"[0-9a-f]{64}")


class CheckpointStoreNotCovered(RuntimeError):
    """The checkpoint database has a table or column the catalog does not list."""


def _uuid(value):
    try:
        parsed = UUID(value)
    except (TypeError, ValueError):
        return None
    return parsed if str(parsed) == value else None


def owner(thread_id, namespace, tenant_id):
    """(kind, id) of the Run or batch that wrote this address, or None if unknown.

    Thread ids, all built by the server:
    - ``xiaopai:embedding:{tenant}:{batch}``                  embedding batch
    - ``xiaopai:{tenant}:{session}`` + ns ``run:{run}[|...]``  session layout
    - ``xiaopai:{tenant}:{session}:{run}``                    main Run
    - ``xiaopai:{tenant}:{session}:{run}:{digest}``           isolated subtask
    - ``xiaopai:{tenant}:{run}:personal-summary:{epoch}``     personal summary
    """
    tenant = str(tenant_id)
    parts = thread_id.split(":")
    if len(parts) < 3 or parts[0] != "xiaopai":
        return None
    if parts[1] == "embedding":
        batch = _uuid(parts[3]) if len(parts) == 4 and parts[2] == tenant else None
        return ("embedding_batch", batch) if batch else None
    if parts[1] != tenant:
        return None
    rest = parts[2:]
    if len(rest) == 1:
        if _uuid(rest[0]) is None or not namespace.startswith("run:"):
            return None
        run = _uuid(namespace[4:].split("|", 1)[0])
    elif len(rest) == 3 and rest[1] == "personal-summary":
        run = _uuid(rest[0]) if rest[2].isdigit() else None
    elif len(rest) in {2, 3} and _uuid(rest[0]) is not None:
        run = _uuid(rest[1]) if len(rest) == 2 or _DIGEST.fullmatch(rest[2]) else None
    else:
        return None
    return ("run", run) if run else None


def _newest(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.utcoffset() is not None else None


def check_covered(connection):
    rows = connection.execute(
        "SELECT c.relname,a.attname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
        "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%' "
        "AND c.relkind IN ('r','p','v','m','f') AND a.attnum>0 AND NOT a.attisdropped"
    ).fetchall()
    actual = {}
    for table, column in rows:
        if table != "environment_guard":
            actual.setdefault(table, set()).add(column)
    expected = {name: set(columns) for name, columns in CHECKPOINT_COVERED_COLUMNS.items()}
    if actual != expected:
        raise CheckpointStoreNotCovered("Checkpoint store schema is not the catalogued one")


def _addresses(connection, tenant_id):
    tenant = str(tenant_id)
    return connection.execute(
        "SELECT thread_id,checkpoint_ns,max(checkpoint->>'ts') FROM checkpoints "
        "WHERE thread_id LIKE %s OR thread_id LIKE %s GROUP BY thread_id,checkpoint_ns",
        (f"xiaopai:{tenant}:%", f"xiaopai:embedding:{tenant}:%"),
    ).fetchall()


def _closed(dispatch_engine, tenant_id, owners):
    runs = [value for kind, value in owners if kind == "run"]
    batches = [value for kind, value in owners if kind == "embedding_batch"]
    with tenant_session(dispatch_engine, tenant_id) as session:
        rows = session.execute(
            text(
                "SELECT kind,owner_id,open FROM checkpoint_retention_owners("
                ":tenant,CAST(:runs AS uuid[]),CAST(:batches AS uuid[]))"
            ),
            {"tenant": tenant_id, "runs": runs, "batches": batches},
        ).all()
    return {(kind, value) for kind, value, open_ in rows if open_ is False}


def purge(
    dispatch_engine,
    checkpoint_url,
    tenant_id,
    *,
    now: datetime,
    heartbeat: Callable[[], None] = lambda: None,
):
    """Delete one tenant's closed owners' checkpoints older than the retention window."""
    tenant_id = UUID(str(tenant_id))
    cutoff = now - RETENTION
    counts = {"owners_deleted": 0, "addresses_deleted": 0, "rows_deleted": 0,
              "owners_open_or_unknown": 0, "addresses_recent": 0, "addresses_unrecognized": 0}
    with psycopg.connect(checkpoint_url, autocommit=True) as connection:
        check_covered(connection)
        groups, newest = {}, {}
        for thread_id, namespace, stamp in _addresses(connection, tenant_id):
            found = owner(thread_id, namespace, tenant_id)
            moment = _newest(stamp)
            if found is None or moment is None:
                counts["addresses_unrecognized"] += 1
                continue
            groups.setdefault(found, []).append((thread_id, namespace))
            newest[found] = max(newest.get(found, moment), moment)
        candidates = []
        for found, addresses in groups.items():
            if newest[found] >= cutoff:
                counts["addresses_recent"] += len(addresses)
            else:
                candidates.append(found)
        for start in range(0, len(candidates), OWNER_PAGE):
            page = candidates[start:start + OWNER_PAGE]
            closed = _closed(dispatch_engine, tenant_id, page)
            counts["owners_open_or_unknown"] += len(page) - len(closed)
            for found in page:
                if found not in closed:
                    continue
                with connection.transaction():
                    for thread_id, namespace in groups[found]:
                        for table in CHECKPOINT_PURGED:
                            counts["rows_deleted"] += connection.execute(
                                f"DELETE FROM {table} WHERE thread_id=%s AND checkpoint_ns=%s",
                                (thread_id, namespace),
                            ).rowcount
                counts["owners_deleted"] += 1
                counts["addresses_deleted"] += len(groups[found])
            heartbeat()
    return counts


class CheckpointRetention:
    def __init__(self, dispatch_engine, checkpoint_url):
        self.dispatch_engine, self.checkpoint_url = dispatch_engine, checkpoint_url

    @activity.defn(name="purge_checkpoint_retention")
    def purge(self, reference: dict) -> dict:
        from pdos_next.workflows.checkpoints import verified_checkpoint_url

        return purge(
            self.dispatch_engine,
            verified_checkpoint_url(self.checkpoint_url),
            UUID(reference["tenant_id"]),
            now=datetime.now(UTC),
            heartbeat=activity.heartbeat,
        )
