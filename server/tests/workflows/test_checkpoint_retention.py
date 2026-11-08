"""Checkpoint retention without a database or Temporal service (D58)."""

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

from pdos_next.originals.lifecycle import catalog
from pdos_next.workflows import checkpoint_retention as retention
from pdos_next.workflows import maintenance

TENANT, SESSION, RUN, OTHER = (str(uuid4()) for _ in range(4))
DIGEST = "a" * 64


@pytest.mark.parametrize(
    ("thread_id", "namespace", "expected"),
    [
        (f"xiaopai:{TENANT}:{SESSION}:{RUN}", "", ("run", RUN)),
        (f"xiaopai:{TENANT}:{SESSION}:{RUN}", "tools:abc", ("run", RUN)),
        (f"xiaopai:{TENANT}:{SESSION}:{RUN}:{DIGEST}", "", ("run", RUN)),
        (f"xiaopai:{TENANT}:{SESSION}", f"run:{RUN}", ("run", RUN)),
        (f"xiaopai:{TENANT}:{SESSION}", f"run:{RUN}|tools:abc", ("run", RUN)),
        (f"xiaopai:{TENANT}:{RUN}:personal-summary:3", "", ("run", RUN)),
        (f"xiaopai:embedding:{TENANT}:{RUN}", "", ("embedding_batch", RUN)),
        # Unknown shapes are kept, never guessed.
        (f"xiaopai:{TENANT}:{SESSION}", "", None),
        (f"xiaopai:{TENANT}:{SESSION}", "run:not-a-uuid", None),
        (f"xiaopai:{TENANT}:{SESSION}:{RUN}:not-a-digest", "", None),
        (f"xiaopai:{TENANT}:{RUN}:personal-summary:x", "", None),
        (f"xiaopai:{TENANT}:{SESSION}:{RUN.upper()}", "", None),
        (f"xiaopai:{TENANT}:a:b:c:d", "", None),
        (f"xiaopai:{OTHER}:{SESSION}:{RUN}", "", None),
        (f"xiaopai:embedding:{OTHER}:{RUN}", "", None),
        (f"other:{TENANT}:{SESSION}:{RUN}", "", None),
    ],
)
def test_owner_is_read_only_from_server_built_thread_ids(thread_id, namespace, expected):
    found = retention.owner(thread_id, namespace, TENANT)
    assert (found and (found[0], str(found[1]))) == expected


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query):
        return self

    def fetchall(self):
        return self.rows


def catalogued(extra=()):
    rows = [
        (table, column)
        for table, columns in catalog.CHECKPOINT_COVERED_COLUMNS.items()
        for column in columns
    ]
    return [*rows, ("environment_guard", "marker"), *extra]


def test_catalog_covers_the_installed_langgraph_checkpoint_schema():
    from langgraph.checkpoint.postgres import PostgresSaver

    created = " ".join(PostgresSaver.MIGRATIONS)
    for table, columns in catalog.CHECKPOINT_COVERED_COLUMNS.items():
        assert table in created
        for column in columns:
            assert column in created
    assert set(catalog.CHECKPOINT_PURGED) == set(catalog.CHECKPOINT_COVERED_COLUMNS) - {
        "checkpoint_migrations"
    }
    assert catalog.CHECKPOINT_RETENTION_DAYS == 30
    retention.check_covered(FakeConnection(catalogued()))


@pytest.mark.parametrize(
    "extra", [[("checkpoints", "new_column")], [("checkpoint_archive", "thread_id")]]
)
def test_unknown_checkpoint_table_or_column_denies_the_purge(extra):
    with pytest.raises(retention.CheckpointStoreNotCovered):
        retention.check_covered(FakeConnection(catalogued(extra)))


def test_missing_catalogued_table_also_denies_the_purge():
    rows = [row for row in catalogued() if row[0] != "checkpoint_writes"]
    with pytest.raises(retention.CheckpointStoreNotCovered):
        retention.check_covered(FakeConnection(rows))


@pytest.mark.parametrize(
    "reference",
    [
        {"tenant_id": "not-a-uuid", "job": "checkpoint_retention"},
        {"tenant_id": TENANT, "job": "unknown"},
        {"tenant_id": TENANT},
        {"tenant_id": TENANT, "job": "checkpoint_retention", "run_id": RUN},
    ],
)
def test_maintenance_accepts_only_a_tenant_and_a_known_job(monkeypatch, reference):
    execute = AsyncMock()
    monkeypatch.setattr(maintenance.workflow, "execute_activity", execute)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(maintenance.TenantMaintenance().run(reference))
    assert error.value.type == "MAINTENANCE_REFERENCE_INVALID" and error.value.non_retryable
    execute.assert_not_awaited()


class ContinuedAsNew(Exception):
    pass


def test_daily_passes_survive_a_failed_pass_and_bound_their_history(monkeypatch):
    calls, sleeps = [], []

    async def execute(name, payload, **options):
        calls.append((name, payload))
        assert options["retry_policy"].maximum_attempts == 3
        if len(calls) == 2:
            raise ActivityError(
                "failed", scheduled_event_id=1, started_event_id=2, identity="x",
                activity_type=name, activity_id="1", retry_state=None,
            )
        return {"owners_deleted": 0}

    async def sleep(period):
        sleeps.append(period)

    def continue_as_new(value):
        raise ContinuedAsNew(value)

    monkeypatch.setattr(maintenance.workflow, "execute_activity", execute)
    monkeypatch.setattr(maintenance.workflow, "sleep", sleep)
    monkeypatch.setattr(maintenance.workflow, "continue_as_new", continue_as_new)
    monkeypatch.setattr(maintenance.workflow, "logger", logging.getLogger("maintenance-test"))
    reference = {"tenant_id": TENANT, "job": "checkpoint_retention"}
    with pytest.raises(ContinuedAsNew) as continued:
        asyncio.run(maintenance.TenantMaintenance().run(reference))
    assert continued.value.args[0] == reference
    assert len(calls) == len(sleeps) == maintenance.PASSES_PER_HISTORY
    assert set(calls[0][1]) == {"tenant_id"} and calls[0][0] == "purge_checkpoint_retention"
    assert set(sleeps) == {timedelta(days=1)}


def test_sender_starts_each_tenant_job_once_and_tolerates_existing_runs():
    client = AsyncMock()
    client.start_workflow.side_effect = [None, WorkflowAlreadyStartedError("x", "y"), None, None]
    sender = maintenance.MaintenanceSender(client, task_queue="q")
    other = str(uuid4())
    for tenant in (TENANT, TENANT, other, other):
        asyncio.run(sender.discover(tenant))
    assert client.start_workflow.await_count == 2 * len(maintenance.JOBS)
    started = {(call.args[1]["job"], call.args[1]["tenant_id"]): call.kwargs
               for call in client.start_workflow.await_args_list}
    assert set(started) == {(job, t) for job in maintenance.JOBS for t in (TENANT, other)}
    for (job, tenant), options in started.items():
        assert options["id"] == f"pdos-next:maintenance:{job}:{tenant}"
        assert options["task_queue"] == "q"


def test_jobs_and_periods_are_the_decided_ones():
    assert maintenance.JOBS == {
        "checkpoint_retention": ("purge_checkpoint_retention", timedelta(days=1)),
        "original_rescan": ("rescan_expired_originals", timedelta(hours=1)),
    }
