"""Real read binding and replay selection, with in-memory rows and no I/O."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, PublicWebSnapshot
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.read_execution import ReadBinding, ReadSource
from pdos_next.agent_kernel.registered_snapshot_reads import RegisteredSnapshotReads
from pdos_next.agent_kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal, Receipt
from pdos_next.service import digest


class MemorySession:
    def __init__(self):
        self.rows, self.call, self.snapshot_queries = {}, None, 0

    def put(self, model, row):
        self.rows[model, row.id] = row
        return row

    def get(self, model, identity):
        return self.rows.get((model, identity))

    def scalar(self, _statement):
        return self.call

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is PublicWebSnapshot:
            self.snapshot_queries += 1
        return ScalarRows([row for (model, _), row in self.rows.items() if model is entity])

    def add(self, call):
        call.id, call.state = uuid4(), "started"
        self.call = self.put(AgentToolCall, call)

    def flush(self):
        pass


class ScalarRows(list):
    def all(self):
        return self


class MemoryStore(KernelStore):
    def __init__(self, session, run):
        super().__init__(None)
        self.session, self.run, self.settled = session, run, 0
        self.released = []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        self.authority(self.session, scope)
        yield self.session, self.run

    def settle(self, *args, **kwargs):
        self.settled += 1
        return super().settle(*args, **kwargs)

    def release_call(self, scope, call_id, **kwargs):
        self.released.append((call_id, kwargs))


@pytest.fixture
def fixture():
    scope = RunScope(*(uuid4() for _ in range(6)), isolation="research")
    spec = ToolSpec(
        "research.read",
        "Synthetic snapshot reader",
        {"type": "object"},
        {"type": "object"},
        "read",
        "READ",
    )
    registry = ToolRegistry([spec])
    binding = ModelBinding(
        model_version="synthetic",
        model_route_digest="a" * 64,
        tool_definitions_digest=digest(registry.definitions("research")),
        prompt_digest="b" * 64,
        isolation="research",
        cancel_epoch=0,
    )
    data = asdict(scope)
    data["id"] = data.pop("run_id")
    for key in ("isolation", "artifact_ids", "trigger"):
        data.pop(key)
    data["data_categories"], data["customer_identities"] = ["public"], []
    session = MemorySession()
    run = session.put(
        AgentRun,
        AgentRun(
            **data,
            state="running",
            reverted_at=None,
            held_tokens=0,
            used_tokens=0,
            token_limit=100,
            versions={
                "model_version": binding.model_version,
                "model_route_digest": binding.model_route_digest,
                "tool_definitions": {"research": binding.tool_definitions_digest},
                "prompt_prefixes": {"research": binding.prompt_digest},
            },
        ),
    )
    for person in (scope.writer_id, scope.requester_id):
        session.put(
            Principal,
            NS(
                id=person,
                tenant_id=scope.tenant_id,
                active=True,
                kind="agent" if person == scope.writer_id else "human",
            ),
        )
        session.put(Grant, NS(id=uuid4(), principal_id=person, expires_at=None))
    session.put(Category, NS(id=scope.category_id))
    body = "First public page\nSecond public page\n"
    snapshot = session.put(
        PublicWebSnapshot,
        NS(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            category_id=scope.category_id,
            owner_id=scope.requester_id,
            visibility="category",
            registered_by_run_id=uuid4(),
            receipt_id=uuid4(),
            url="https://example.test/article",
            final_url="https://example.test/article",
            title="Synthetic article",
            summary="Synthetic",
            retrieved_at=datetime(2026, 10, 11, tzinfo=UTC),
            markdown=body,
            content_hash=sha256(body.encode()).hexdigest(),
            provider="synthetic",
            credibility="public_web",
            status="ok",
        ),
    )
    session.put(
        Receipt,
        NS(
            id=snapshot.receipt_id,
            tenant_id=scope.tenant_id,
            category_id=scope.category_id,
            requester_id=snapshot.owner_id,
            actor_id=scope.writer_id,
            subject_revision=1,
            run_id=None,
            agent_run_id=snapshot.registered_by_run_id,
            operation="research.snapshot.register",
            subject_type="public_web_snapshot",
            subject_id=snapshot.id,
            result={
                "proof_version": 1,
                "snapshot_id": str(snapshot.id),
                "content_hash": snapshot.content_hash,
                "registered_by_run_id": str(snapshot.registered_by_run_id),
            },
        ),
    )
    arguments = {"url": snapshot.url, "cursor": 0}
    model = session.put(
        AgentToolCall,
        AgentToolCall(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            run_id=run.id,
            tool="model",
            state="completed",
            error_code=None,
            receipt_id=None,
            execution_binding=binding.model_dump(mode="json"),
            result={"calls": [{"name": spec.name, "arguments": deepcopy(arguments)}]},
        ),
    )
    store = MemoryStore(session, run)
    route = NS(version=binding.model_version, digest=binding.model_route_digest)
    host = BoundHost(
        store,
        KernelAdapters(
            route_for=lambda _: route,
            project_context=None,
            verify_result=None,
            prepare_candidate=None,
            execute_command=None,
            provider_client=object(),
            tool_registry=registry,
        ),
    )
    child = NS(
        _scope=scope,
        pages={},
        reads=[],
        _service=NS(
            _lock=RLock(),
            limits=NS(page_chars=10),
            _allowlists={
                (scope.tenant_id, scope.requester_id, scope.session_id, scope.run_id): {
                    snapshot.url
                },
            },
        ),
    )
    return NS(
        session=session,
        scope=scope,
        run=run,
        snapshot=snapshot,
        model=model,
        store=store,
        host=host,
        child=child,
        spec=spec,
        arguments=arguments,
        route=route,
        port=RegisteredSnapshotReads(store),
        source=ReadSource(model_call_id=model.id, response_index=0),
        intent=execution_key(run.id, model.id, 0),
    )


def read(f):
    return f.port.read(f.host, f.child, f.spec, f.arguments, f.intent, source=f.source)


def test_registered_replay_pins_original_snapshot_and_page_size(fixture):
    f = fixture
    first = read(f)
    original_binding = deepcopy(f.session.call.execution_binding)
    f.session.put(PublicWebSnapshot, NS(**{**vars(f.snapshot), "id": uuid4()}))
    f.child._service.limits.page_chars = 20
    f.child._service._allowlists.clear()
    f.child.pages.clear()
    assert read(f) == first
    assert f.session.snapshot_queries == 1
    assert f.session.call.execution_binding == original_binding
    assert f.session.call.result["end"] == 10
    assert (f.snapshot.id, "chars:0:10") in f.child.pages
    assert f.store.settled == 1 and not f.store.released


def test_existing_ordinary_read_keeps_original_raw_restore_route(fixture):
    f = fixture
    f.host.read_callback(
        f.scope,
        f.spec,
        f.arguments,
        f.intent,
        source=f.source,
        callback=lambda *_: {"snapshot_id": str(uuid4()), "markdown": "retained original"},
    )
    f.session.put(PublicWebSnapshot, NS(**{**vars(f.snapshot), "id": uuid4()}))
    f.child._service._allowlists.clear()
    saved = deepcopy(f.session.call.result)
    assert read(f) is None
    assert f.session.snapshot_queries == 0
    assert f.session.call.result == saved and f.store.settled == 1
    assert ReadBinding.model_validate(f.session.call.execution_binding).read_kind == "ordinary/v1"


@pytest.mark.parametrize(
    "mutation",
    [
        "arguments",
        "model",
        "epoch",
        "source",
        "writer",
        "requester",
        "grant",
        "binding",
        "receipt",
        "private",
        "body",
        "missing_snapshot",
        "failed_call",
        "page_identity",
        "route",
    ],
)
def test_replay_still_checks_actual_model_authority_and_immutable_snapshot(fixture, mutation):
    f = fixture
    read(f)
    if mutation == "arguments":
        f.arguments["cursor"] = 1
    elif mutation == "model":
        f.model.result["calls"][0]["arguments"]["cursor"] = 1
    elif mutation == "epoch":
        f.run.cancel_epoch = 1
    elif mutation == "source":
        f.source = ReadSource(model_call_id=uuid4(), response_index=0)
    elif mutation in {"writer", "requester"}:
        identity = getattr(f.scope, mutation + "_id")
        f.session.get(Principal, identity).active = False
    elif mutation == "grant":
        f.session.rows = {
            key: row
            for key, row in f.session.rows.items()
            if key[0] is not Grant or row.principal_id != f.scope.writer_id
        }
    elif mutation == "binding":
        f.session.call.execution_binding["model_call_id"] = str(uuid4())
    elif mutation == "receipt":
        del f.session.rows[Receipt, f.snapshot.receipt_id]
    elif mutation == "private":
        f.snapshot.visibility = "private"
    elif mutation == "body":
        f.snapshot.markdown += "changed"
    elif mutation == "missing_snapshot":
        del f.session.rows[PublicWebSnapshot, f.snapshot.id]
    elif mutation == "failed_call":
        f.session.call.state = "failed"
    elif mutation == "page_identity":
        f.session.call.result["snapshot_id"] = str(uuid4())
    elif mutation == "route":
        f.route.digest = "f" * 64
    with pytest.raises(DomainError):
        read(f)
    assert f.store.settled == 1


def test_new_read_still_requires_observed_url(fixture):
    fixture.child._service._allowlists.clear()
    with pytest.raises(DomainError):
        read(fixture)
    assert fixture.store.settled == 0


def test_new_read_does_not_choose_between_multiple_snapshots(fixture):
    f = fixture
    f.session.put(PublicWebSnapshot, NS(**{**vars(f.snapshot), "id": uuid4()}))
    with pytest.raises(DomainError) as error:
        read(f)
    assert error.value.code == "VERSION_CONFLICT" and f.store.settled == 0


def test_new_read_without_registered_snapshot_uses_raw_adapter(fixture):
    del fixture.session.rows[PublicWebSnapshot, fixture.snapshot.id]
    assert read(fixture) is None
    assert fixture.session.call is None


@pytest.mark.parametrize("state", ["started", "failed", "unknown"])
@pytest.mark.parametrize("read_kind", ["ordinary/v1", "registered_snapshot/v1"])
def test_unfinished_read_keeps_unknown_exit_without_source_reselection(fixture, state, read_kind):
    f = fixture
    if read_kind == "ordinary/v1":
        f.host.read_callback(
            f.scope,
            f.spec,
            f.arguments,
            f.intent,
            source=f.source,
            callback=lambda *_: {"snapshot_id": str(uuid4()), "markdown": "ordinary"},
        )
    else:
        read(f)
    f.session.call.state = state
    f.session.call.result = None
    f.session.call.error_code = "SOURCE_UNAVAILABLE" if state == "failed" else None
    original_binding = deepcopy(f.session.call.execution_binding)
    f.session.put(PublicWebSnapshot, NS(**{**vars(f.snapshot), "id": uuid4()}))
    f.child._service._allowlists.clear()
    queries = f.session.snapshot_queries
    f.child.pages.clear()
    with pytest.raises(DomainError) as error:
        read(f)
    assert error.value.code == "EXTERNAL_OUTCOME_UNKNOWN"
    assert error.value.detail["call_id"] == str(f.session.call.id)
    assert f.session.call.execution_binding == original_binding
    assert f.session.call.result is None and f.session.call.state == state
    assert f.session.snapshot_queries == queries and not f.child.pages
    assert f.store.settled == 1


def test_unfinished_read_does_not_bypass_actual_model_validation(fixture):
    f = fixture
    read(f)
    f.session.call.state, f.session.call.result = "started", None
    f.model.result["calls"][0]["arguments"]["cursor"] = 1
    queries = f.session.snapshot_queries
    with pytest.raises(DomainError) as error:
        read(f)
    assert error.value.code != "EXTERNAL_OUTCOME_UNKNOWN"
    assert f.session.snapshot_queries == queries and f.store.settled == 1
