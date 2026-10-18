"""Transport ordering and failure boundaries; no Temporal or PostgreSQL service substitutes."""

import asyncio
from contextlib import contextmanager
from threading import get_ident
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.dispatch.outbox import Envelope
from pdos_next.domain.automations import transport
from pdos_next.errors import DomainError
from pdos_next.workflows.automation import AutomationRuleWork


class Handle:
    def __init__(self, identity, trace):
        self.identity, self.trace, self.failure = identity, trace, None

    async def signal(self, signal):
        assert signal is AutomationRuleWork.wake
        self.trace.append(("wake", self.identity))
        if self.failure is not None:
            raise self.failure


class Client:
    def __init__(self, trace):
        self.trace, self.starts, self.handles = trace, [], {}
        self.start_failure = None

    async def start_workflow(self, workflow, reference, **kwargs):
        assert workflow is AutomationRuleWork.run
        assert set(reference) == transport.REFERENCE_KEYS
        assert kwargs["id_conflict_policy"] is WorkflowIDConflictPolicy.USE_EXISTING
        assert kwargs["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE
        self.starts.append((dict(reference), kwargs))
        identity = kwargs["id"]
        self.trace.append(("start", identity))
        if self.start_failure is not None:
            raise self.start_failure
        self.handles.setdefault(identity, Handle(identity, self.trace))
        return self.handles[identity]

    def get_workflow_handle(self, identity):
        self.trace.append(("existing", identity))
        return self.handles.setdefault(identity, Handle(identity, self.trace))


@pytest.fixture
def case(monkeypatch):
    tenant, category, owner, writer = (uuid4() for _ in range(4))
    rows = [
        {
            "tenant_id": tenant,
            "category_id": category,
            "owner_id": owner,
            "writer_id": writer,
            "grant_id": uuid4(),
        }
        for _ in range(2)
    ]
    trace, queries, connections, queued = [], [], [], []
    app, dispatcher = object(), object()
    event = Envelope(
        event_id=str(uuid4()),
        tenant_id=str(tenant),
        category_id=str(category),
        product_id=str(uuid4()),
        subject_id=str(uuid4()),
        subject_revision=3,
        event_type="work.task_submitted",
        schema_version=1,
        correlation_id=str(uuid4()),
        lease_id=str(uuid4()),
        actor_id=str(uuid4()),
        requester_id=str(uuid4()),
    )
    value = SimpleNamespace(
        tenant=tenant,
        rows=rows,
        trace=trace,
        queries=queries,
        connections=connections,
        queued=queued,
        app=app,
        dispatcher=dispatcher,
        event=event,
        loop_thread=get_ident(),
        queue_values={str(row["grant_id"]): str(uuid4()) for row in rows},
    )

    class MetadataSQL:
        def execute(self, statement, params):
            queries.append((str(statement), params, get_ident()))
            assert "automation_active_grants" in str(
                statement
            ) or "automation_event_targets" in str(statement)
            assert get_ident() != value.loop_thread
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: list(value.rows)))

    @contextmanager
    def transaction(engine, actual_tenant, **kwargs):
        assert engine is dispatcher and actual_tenant == tenant and kwargs == {}
        thread = get_ident()
        connections.append(("enter", thread))
        try:
            yield MetadataSQL()
        finally:
            connections.append(("exit", get_ident()))
            assert thread == get_ident()

    def queue_event(engine, reference, actual_event):
        assert engine is app and actual_event is event
        assert get_ident() != value.loop_thread
        queued.append((dict(reference), actual_event))
        trace.append(("persist", reference["grant_id"]))
        result = value.queue_values[reference["grant_id"]]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(transport, "tenant_session", transaction)
    monkeypatch.setattr(transport.service_runtime, "queue_event", queue_event)
    value.client = Client(trace)
    value.sender = transport.ServiceAutomationSender(
        value.client, app, dispatcher, task_queue="synthetic-automation-v1"
    )
    return value


def test_discovery_reads_only_dispatch_metadata_and_caches_successful_fixed_workflow_starts(case):
    async def run():
        assert await case.sender.discover(case.tenant) == {"ensured": 2}
        assert await case.sender.discover(case.tenant) == {"ensured": 2}

    asyncio.run(run())
    assert len(case.client.starts) == 2 and case.queued == []
    assert len(case.queries) == 2
    for reference, options in case.client.starts:
        assert reference["tenant_id"] == str(case.tenant)
        assert options["id"] == f"pdos-next:automation:{case.tenant}:{reference['grant_id']}"
        assert options["task_queue"] == "synthetic-automation-v1"
    assert all(
        query == "SELECT * FROM automation_active_grants(:tenant)" for query, _, _ in case.queries
    )
    assert all(params == {"tenant": case.tenant} for _, params, _ in case.queries)
    assert not any(step[0] == "wake" for step in case.trace)
    assert [step[0] for step in case.connections] == ["enter", "exit", "enter", "exit"]


def test_uncertain_start_is_not_cached_and_retry_uses_the_same_workflow_identity(case):
    case.rows = case.rows[:1]
    failure = RuntimeError("synthetic uncertain start")
    case.client.start_failure = failure

    async def run():
        with pytest.raises(RuntimeError) as error:
            await case.sender.discover(case.tenant)
        assert error.value is failure
        case.client.start_failure = None
        assert await case.sender.discover(case.tenant) == {"ensured": 1}

    asyncio.run(run())
    assert len(case.client.starts) == 2
    assert case.client.starts[0] == case.client.starts[1]


def test_already_started_reuses_handle_and_event_wakes_only_after_all_target_queues(case):
    case.client.start_failure = WorkflowAlreadyStartedError(
        "synthetic-existing", "AutomationRuleWork"
    )
    result = asyncio.run(case.sender.event(case.event))
    assert result == {"persisted": 2, "ignored": 0, "skipped": []}
    assert [step[0] for step in case.trace] == [
        "persist",
        "persist",
        "start",
        "existing",
        "wake",
        "start",
        "existing",
        "wake",
    ]
    query, params, _ = case.queries[0]
    assert query == "SELECT * FROM automation_event_targets(:tenant,:event,:lease)"
    assert params == {
        "tenant": case.tenant,
        "event": UUID(case.event.event_id),
        "lease": UUID(case.event.lease_id),
    }
    assert all(item[0]["owner_id"] != case.event.requester_id for item in case.queued)


def test_event_does_not_wake_a_partially_persisted_fanout_after_an_infrastructure_failure(case):
    second = str(case.rows[1]["grant_id"])
    failure = RuntimeError("synthetic second target database failure")
    case.queue_values[second] = failure

    async def run():
        with pytest.raises(RuntimeError) as error:
            await case.sender.event(case.event)
        assert error.value is failure
        assert case.client.starts == []
        case.queue_values[second] = str(uuid4())
        return await case.sender.event(case.event)

    assert asyncio.run(run()) == {"persisted": 2, "ignored": 0, "skipped": []}
    assert [step[0] for step in case.trace[:4]] == ["persist"] * 4
    assert len(case.client.starts) == 2


@pytest.mark.parametrize("code,status", [("FORBIDDEN_SCOPE", 403), ("SOURCE_UNAVAILABLE", 403)])
def test_actual_source_acl_loss_skips_only_that_target_with_a_fixed_reason(
    case, code, status, caplog
):
    first = str(case.rows[0]["grant_id"])
    case.queue_values[first] = DomainError(code, "actual owner ACL denied", status)
    with caplog.at_level("INFO", logger=transport.__name__):
        result = asyncio.run(case.sender.event(case.event))
    assert result == {
        "persisted": 1,
        "ignored": 0,
        "skipped": [{"grant_id": first, "reason": transport.SCOPE_SKIP_REASON}],
    }
    assert transport.SCOPE_SKIP_REASON in caplog.text
    assert len(case.client.starts) == 1 and len(case.queued) == 2


@pytest.mark.parametrize(
    "error",
    [
        DomainError("SOURCE_UNAVAILABLE", "infra", 503),
        DomainError("VERSION_CONFLICT", "owner state changed"),
        DomainError("DUPLICATE_INTENT_CONFLICT", "changed source"),
    ],
)
def test_non_acl_owner_errors_propagate_without_starts_or_acknowledgement(case, error):
    case.queue_values[str(case.rows[0]["grant_id"])] = error

    async def run():
        with pytest.raises(DomainError) as raised:
            await case.sender.event(case.event)
        assert raised.value is error

    asyncio.run(run())
    assert case.client.starts == []


def test_null_owner_result_is_ignored_without_starting_a_workflow(case):
    case.queue_values = {str(row["grant_id"]): None for row in case.rows}
    assert asyncio.run(case.sender.event(case.event)) == {
        "persisted": 0,
        "ignored": 2,
        "skipped": [],
    }
    assert case.client.starts == [] and len(case.queued) == 2


def test_signal_failure_propagates_after_persistence_and_redelivery_keeps_successful_start(case):
    case.rows = case.rows[:1]
    identity = transport.workflow_id(case.tenant, case.rows[0]["grant_id"])
    failure = RuntimeError("synthetic wake delivery unknown")
    handle = case.client.handles.setdefault(identity, Handle(identity, case.trace))
    handle.failure = failure

    async def run():
        with pytest.raises(RuntimeError) as raised:
            await case.sender.event(case.event)
        assert raised.value is failure
        handle.failure = None
        return await case.sender.event(case.event)

    assert asyncio.run(run())["persisted"] == 1
    assert len(case.client.starts) == 1 and len(case.queued) == 2
    assert [step[0] for step in case.trace] == ["persist", "start", "wake", "persist", "wake"]


@pytest.mark.parametrize(
    "change", [{"tenant_id": uuid4()}, {"grant_id": "invalid"}, {"payload": {"authorized": True}}]
)
def test_bad_dispatch_reference_is_not_misclassified_as_source_acl_loss(case, change):
    case.rows = [case.rows[0] | change]

    async def run():
        with pytest.raises((ValueError, DomainError)):
            await case.sender.event(case.event)

    asyncio.run(run())
    assert case.client.starts == [] and case.queued == []
