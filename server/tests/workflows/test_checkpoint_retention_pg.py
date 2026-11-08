"""Real LangGraph checkpoints and real Run/batch states (D58): only closed owners go."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import text
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.persistence import create_run
from pdos_next.core.database import tenant_session
from pdos_next.workflows import checkpoint_retention as retention
from pdos_next.workflows.checkpoints import verified_checkpoint_url

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Requires the explicitly selected independent checkpoint store",
)
NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
OLD, RECENT = NOW - timedelta(days=31), NOW - timedelta(days=29)


@pytest.fixture
def store():
    url = verified_checkpoint_url(os.environ["PDOS_CHECKPOINT_DATABASE_URL"])
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
        yield url, saver


def put(saver, thread_id, namespace, at, *, write=True):
    checkpoint = empty_checkpoint()
    checkpoint["ts"] = at.isoformat()
    checkpoint["channel_values"] = {"messages": ["synthetic"]}
    checkpoint["channel_versions"] = {"messages": "1"}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace}}
    saved = saver.put(config, checkpoint, {"source": "loop", "step": 1}, {"messages": "1"})
    if write:
        saver.put_writes(saved, [("messages", "pending")], task_id=str(uuid4()))


def rows(url, thread_id, namespace):
    with psycopg.connect(url) as connection:
        return [
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE thread_id=%s AND checkpoint_ns=%s",
                (thread_id, namespace),
            ).fetchone()[0]
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
        ]


def run(setup, state):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        value = create_run(
            session, setup.ctx, goal="检查点保留", writer_id=setup.agent,
            intent_key="d58-retention:" + str(uuid4()),
        )
        identity, session_id = value.id, value.session_id
    with Session(setup.admin) as session, session.begin():
        session.execute(
            text("UPDATE agent_runs SET state=:state WHERE id=:id"),
            {"state": state, "id": identity},
        )
    return identity, session_id


def batch(setup, state):
    """Only the batch state matters here. Its profile chain needs receipts and budgets,
    so this isolated synthetic fixture inserts the batch row alone, without triggers."""
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.execute(
            text(
                "INSERT INTO enterprise_embedding_batches(id,tenant_id,created_at,"
                "profile_version_id,category_id,manifest,work_key,state,attempts) "
                "VALUES(:id,:t,now(),:profile,:c,'{}',:work,:state,0)"
            ),
            {
                "id": identity, "t": setup.tenant, "profile": uuid4(), "c": setup.category,
                "work": uuid4().hex + uuid4().hex, "state": state,
            },
        )
    return identity


def test_purge_removes_only_closed_owners_older_than_thirty_days(setup, store):
    url, saver = store
    t = setup.tenant
    completed, completed_session = run(setup, "completed")
    waiting, waiting_session = run(setup, "waiting_input")
    queued, queued_session = run(setup, "queued")
    running, running_session = run(setup, "running")
    failed_recent, failed_session = run(setup, "failed")
    shared_done, shared_session = run(setup, "cancelled")
    shared_open, _ = run(setup, "waiting_input")
    ready, retryable = batch(setup, "ready"), batch(setup, "retryable")
    missing, other_tenant = uuid4(), uuid4()
    gone = {
        "legacy completed": (f"xiaopai:{t}:{completed_session}:{completed}", ""),
        "subgraph of completed": (f"xiaopai:{t}:{completed_session}:{completed}", "tools:x"),
        "isolated child": (f"xiaopai:{t}:{completed_session}:{completed}:{'c' * 64}", ""),
        "summary": (f"xiaopai:{t}:{completed}:personal-summary:0", ""),
        "session ns closed": (f"xiaopai:{t}:{shared_session}", f"run:{shared_done}"),
        "session child closed": (f"xiaopai:{t}:{shared_session}", f"run:{shared_done}|tools:y"),
        "ready batch": (f"xiaopai:embedding:{t}:{ready}", ""),
    }
    kept = {
        "waiting": (f"xiaopai:{t}:{waiting_session}:{waiting}", ""),
        "queued": (f"xiaopai:{t}:{queued_session}:{queued}", ""),
        "running": (f"xiaopai:{t}:{running_session}:{running}", ""),
        "session ns open": (f"xiaopai:{t}:{shared_session}", f"run:{shared_open}"),
        "retryable batch": (f"xiaopai:embedding:{t}:{retryable}", ""),
        "unknown owner": (f"xiaopai:{t}:{uuid4()}:{missing}", ""),
        "unrecognized": (f"xiaopai:{t}:not-a-session", ""),
        "other tenant": (f"xiaopai:{other_tenant}:{uuid4()}:{completed}", ""),
    }
    try:
        for thread_id, namespace in [*gone.values(), *kept.values()]:
            put(saver, thread_id, namespace, OLD)
        # The newest checkpoint of an owner decides its age, not the oldest one.
        put(saver, f"xiaopai:{t}:{failed_session}:{failed_recent}", "", OLD)
        put(saver, f"xiaopai:{t}:{failed_session}:{failed_recent}", "", RECENT, write=False)
        kept["recent failed"] = (f"xiaopai:{t}:{failed_session}:{failed_recent}", "")
        before = {name: rows(url, *address) for name, address in gone.items()}
        assert all(count[0] and count[1] and count[2] for count in before.values())

        result = retention.purge(setup.dispatch, url, t, now=NOW)

        for name, address in gone.items():
            assert rows(url, *address) == [0, 0, 0], name
        for name, address in kept.items():
            assert rows(url, *address)[0] >= 1, name
        assert result["owners_deleted"] == 3  # completed Run, cancelled Run, ready batch
        assert result["addresses_deleted"] == len(gone)
        assert result["owners_open_or_unknown"] == 6
        assert result["addresses_unrecognized"] == 1
        assert result["addresses_recent"] == 1
        # A second pass finds nothing more to delete.
        again = retention.purge(setup.dispatch, url, t, now=NOW)
        assert again["owners_deleted"] == 0
    finally:
        with psycopg.connect(url) as connection:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                connection.execute(
                    f"DELETE FROM {table} WHERE thread_id LIKE %s OR thread_id LIKE %s "
                    "OR thread_id LIKE %s",
                    (f"xiaopai:{t}:%", f"xiaopai:embedding:{t}:%", f"xiaopai:{other_tenant}:%"),
                )


def test_uncatalogued_checkpoint_schema_denies_any_deletion(setup, store):
    url, saver = store
    completed, session_id = run(setup, "completed")
    address = (f"xiaopai:{setup.tenant}:{session_id}:{completed}", "")
    put(saver, *address, OLD)
    with psycopg.connect(url) as connection:
        connection.execute("ALTER TABLE checkpoints ADD COLUMN d58_probe text")
    try:
        with pytest.raises(retention.CheckpointStoreNotCovered):
            retention.purge(setup.dispatch, url, setup.tenant, now=NOW)
        assert rows(url, *address)[0] == 1
    finally:
        with psycopg.connect(url) as connection:
            connection.execute("ALTER TABLE checkpoints DROP COLUMN d58_probe")
    assert retention.purge(setup.dispatch, url, setup.tenant, now=NOW)["owners_deleted"] == 1
    assert rows(url, *address) == [0, 0, 0]


def test_owner_flags_need_the_matching_tenant_scope_and_the_dispatch_grant(setup, store):
    completed, _ = run(setup, "completed")
    queued = batch(setup, "queued")
    statement = text(
        "SELECT kind,owner_id,open FROM checkpoint_retention_owners("
        ":t,CAST(:runs AS uuid[]),CAST(:batches AS uuid[]))"
    )
    values = {"t": setup.tenant, "runs": [completed], "batches": [queued]}
    with tenant_session(setup.dispatch, setup.tenant) as session:
        assert sorted(session.execute(statement, values).all()) == [
            ("embedding_batch", queued, True), ("run", completed, False),
        ]
        # The dispatch role itself still reads neither table directly.
        for table in ("agent_runs", "enterprise_embedding_batches"):
            with pytest.raises(Exception, match="permission denied"), session.begin_nested():
                session.execute(text(f"SELECT state FROM {table} LIMIT 1"))
    # Another tenant's scope sees nothing, so nothing of this tenant can be deleted from it.
    with tenant_session(setup.dispatch, setup.other_tenant) as session:
        assert session.execute(statement, values).all() == []
    with Session(setup.admin) as session:
        for role in ("pdos_next_app", "pdos_agent", "pdos_next_auth"):
            assert not session.scalar(
                text(
                    "SELECT has_function_privilege(:role,"
                    "'public.checkpoint_retention_owners(uuid,uuid[],uuid[])','EXECUTE')"
                ),
                {"role": role},
            )
