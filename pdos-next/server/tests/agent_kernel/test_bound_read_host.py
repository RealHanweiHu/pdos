"""Real host/claim/settle decisions with in-memory ORM rows, no DB or provider."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.deterministic_proofs import ComputeEngine, canonical_hash
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.read_execution import ReadBinding, ReadSource
from pdos_next.agent_kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, RunScope, ToolCall
from pdos_next.errors import DomainError
from pdos_next.service import digest


class MemorySession:
    """The production claim and settle methods still make all state decisions."""

    def __init__(self, run, model):
        self.rows = {(AgentRun, run.id): run, (AgentToolCall, model.id): model}
        self.call = None

    def get(self, kind, identity):
        return self.rows.get((kind, identity))

    def scalar(self, statement):
        return self.call

    def add(self, call):
        call.id = uuid4()
        call.state = "started"
        self.call = call
        self.rows[AgentToolCall, call.id] = call

    def flush(self):
        pass


class MemoryStore(KernelStore):
    def __init__(self, run, model):
        super().__init__(None)
        self.run, self.session = run, MemorySession(run, model)
        self.revoked, self.settled = False, 0
        self.released, self.claimed_bindings = [], []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        if self.revoked:
            raise DomainError("FORBIDDEN_SCOPE", "Synthetic current authority revoked")
        yield self.session, self.run

    def claim(self, *args, **kwargs):
        self.claimed_bindings.append(deepcopy(kwargs["execution_binding"]))
        return super().claim(*args, **kwargs)

    def settle(self, *args, **kwargs):
        self.settled += 1
        return super().settle(*args, **kwargs)

    def release_call(self, scope, call_id, **kwargs):
        self.released.append((call_id, kwargs))


def make_host(*, isolation="main", engine=None):
    scope = RunScope(*(uuid4() for _ in range(6)), isolation=isolation)
    name = "calc.cost_subtotal" if engine else {
        "main": "category.read", "research": "research.read", "extract": "evidence.artifact.read",
    }[isolation]
    spec = ToolSpec(
        name, "Synthetic registered reader", {"type": "object"}, {"type": "object"},
        "compute" if engine else "read", "READ",
    )
    registry = ToolRegistry([spec])
    values = asdict(scope)
    for key in ("isolation", "artifact_ids", "trigger"):
        values.pop(key)
    values["id"] = values.pop("run_id")
    values["data_categories"] = list(values["data_categories"])
    values["customer_identities"] = list(values["customer_identities"])
    model_binding = ModelBinding(
        model_version="synthetic-model", model_route_digest="a" * 64,
        tool_definitions_digest=digest(registry.definitions(isolation)),
        prompt_digest="b" * 64, isolation=isolation, cancel_epoch=0,
    )
    run = AgentRun(
        **values, state="running", reverted_at=None, held_tokens=0, used_tokens=0,
        token_limit=100, versions={
            "model_version": model_binding.model_version,
            "model_route_digest": model_binding.model_route_digest,
            "tool_definitions": {isolation: model_binding.tool_definitions_digest},
            "prompt_prefixes": {isolation: model_binding.prompt_digest},
        },
    )
    arguments = {"query": "synthetic input"}
    model = AgentToolCall(
        id=uuid4(), tenant_id=scope.tenant_id, run_id=scope.run_id, tool="model",
        state="completed", error_code=None, receipt_id=None,
        execution_binding=model_binding.model_dump(mode="json"),
        result={"calls": [{"id": "provider-label", "name": name, "arguments": arguments}]},
    )
    f = NS(
        scope=scope, run=run, model=model, spec=spec, arguments=deepcopy(arguments),
        source=ReadSource(model_call_id=model.id, response_index=0),
        intent=execution_key(run.id, model.id, 0),
        result={"rows": [{"value": "source text"}]}, callbacks=0,
        route=NS(version=model_binding.model_version, digest=model_binding.model_route_digest),
    )
    f.store = MemoryStore(run, model)

    def callback(scope, arguments):
        f.callbacks += 1
        if hasattr(f, "callback_error"):
            raise f.callback_error
        return deepcopy(f.result)

    f.host = BoundHost(f.store, KernelAdapters(
        route_for=lambda _: f.route, project_context=None, verify_result=None,
        prepare_candidate=None, execute_command=None, provider_client=object(),
        tool_registry=registry, read_tools={name: callback},
        compute_engines={name: engine} if engine else {},
    ))
    return f


def read(f, *, source=True):
    return f.host.read(
        f.scope, f.spec, f.arguments, f.intent, source=f.source if source else None,
    )


@pytest.mark.parametrize("isolation", ["main", "research", "extract"])
def test_actual_host_binds_model_response_and_rechecks_ordinary_replay(isolation):
    f = make_host(isolation=isolation)
    first = read(f)
    call = f.store.session.call
    binding = ReadBinding.model_validate(call.execution_binding)
    assert binding.model_call_id == f.model.id and binding.response_index == 0
    assert binding.call_key == f.intent and binding.isolation == isolation
    assert call.input_digest == digest([f.spec.name, f.arguments])
    assert call.state == "completed" and call.result == f.result
    assert "execution_ref" not in call.result
    assert first["execution_ref"] == {"call_id": str(call.id), "read_kind": "ordinary/v1"}
    assert read(f) == first
    assert f.callbacks == 2 and f.store.settled == 1 and not f.store.released


def test_actual_host_rejects_changed_source_on_replay_without_rewriting_ledger():
    f = make_host()
    read(f)
    saved = deepcopy(f.store.session.call.result)
    f.result["rows"][0]["value"] = "changed source"
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value.code == "SOURCE_STALE"
    assert f.store.session.call.result == saved
    assert f.store.settled == 1 and not f.store.released


@pytest.mark.parametrize("replay", [False, True])
def test_actual_host_requires_current_authority_before_every_read(replay):
    f = make_host()
    if replay:
        read(f)
    f.store.revoked = True
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value.code == "FORBIDDEN_SCOPE"
    assert f.callbacks == int(replay) and len(f.store.claimed_bindings) == int(replay)


@pytest.mark.parametrize("state", ["completed", "partial", "failed", "cancelled", "cancelling"])
def test_actual_host_cannot_start_or_replay_a_read_after_run_ends(state):
    f = make_host()
    read(f)
    f.run.state = state
    with pytest.raises(DomainError):
        read(f)
    assert f.callbacks == 1 and f.store.settled == 1


@pytest.mark.parametrize("tamper", ["missing", "provider-key", "arguments", "model-error", "route"])
def test_actual_host_requires_real_successful_model_provenance_before_callback(tamper):
    f = make_host()
    if tamper == "provider-key":
        f.intent = "provider-label"
    elif tamper == "arguments":
        f.arguments["query"] = "replacement input"
    elif tamper == "model-error":
        f.model.error_code = "SOURCE_UNAVAILABLE"
    elif tamper == "route":
        f.route = NS(version="new-model", digest="a" * 64)
    with pytest.raises(DomainError):
        read(f, source=tamper != "missing")
    assert f.callbacks == 0 and not f.store.claimed_bindings


def test_compute_metadata_is_complete_at_claim_and_ordinary_adapter_is_not_used():
    calculated = []

    def calculate(arguments):
        calculated.append(deepcopy(arguments))
        return {"content": {"total": Decimal("1.20")}}

    engine = ComputeEngine("synthetic-cost-v1", calculate, (("content",),))
    f = make_host(engine=engine)
    result = read(f)
    binding = f.store.claimed_bindings[0]
    assert binding["read_kind"] == "compute/v1" and binding["engine_version"] == engine.version
    assert binding["result_digest"] == canonical_hash(f.store.session.call.result)
    assert f.store.session.call.execution_binding == binding
    assert result["execution_ref"]["read_kind"] == "compute/v1"
    assert read(f) == result
    assert len(calculated) == 2 and f.callbacks == 0 and f.store.settled == 1


def test_compute_replay_refuses_same_version_with_different_calculated_result():
    totals = iter([Decimal("1.20"), Decimal("1.21")])
    f = make_host(engine=ComputeEngine(
        "synthetic-cost-v1", lambda _: {"content": {"total": next(totals)}}, (("content",),),
    ))
    read(f)
    saved = deepcopy(f.store.session.call.execution_binding)
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value.code == "DUPLICATE_INTENT_CONFLICT"
    assert f.store.session.call.execution_binding == saved
    assert f.store.settled == 1 and not f.store.released


def test_callback_failure_releases_new_call_and_preserves_original_exception():
    f = make_host()
    f.callback_error = DomainError("FORBIDDEN_SCOPE", "Synthetic source access denied")
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value is f.callback_error
    assert f.store.released[0][0] == f.store.session.call.id and f.store.settled == 0


def test_replay_source_failure_does_not_release_or_rewrite_completed_call():
    f = make_host()
    read(f)
    f.callback_error = DomainError("FORBIDDEN_SCOPE", "Synthetic source access revoked")
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value is f.callback_error
    assert not f.store.released and f.store.settled == 1


@pytest.mark.parametrize("invalid,value", [
    ("error_code", "SOURCE_UNAVAILABLE"), ("receipt_id", uuid4()),
    ("result", None), ("result", []),
])
def test_completed_invalid_read_cannot_replay_as_success(invalid, value):
    f = make_host()
    read(f)
    setattr(f.store.session.call, invalid, value)
    with pytest.raises(DomainError):
        read(f)


@pytest.mark.parametrize("ledger", [True, False])
def test_actual_graph_passes_server_model_provenance_into_bound_host(monkeypatch, ledger):
    f = make_host()
    final = {"status": "completed", "summary": "Synthetic result", "result": {}}
    turns = iter([
        ModelTurn(
            calls=(ToolCall(id="provider-label", name=f.spec.name, arguments=f.arguments),),
            ledger_call_id=f.model.id if ledger else None,
        ),
        ModelTurn(structured=final),
    ])
    context_ref = str(uuid4())
    f.run.versions["context_snapshots"] = {"synthetic-read-host": {
        "event_id": context_ref, "content_digest": digest({}), "skills": [],
    }}
    monkeypatch.setattr(f.host, "skill_context", lambda *_, **__: {
        "context": {}, "context_ref": context_ref,
    })
    monkeypatch.setattr(f.host.gateway, "turn", lambda *_, **__: next(turns))
    monkeypatch.setattr(f.host, "emit", lambda *_: uuid4())
    monkeypatch.setattr(f.host, "finish", lambda *_: None)
    monkeypatch.setattr(f.host, "verify", lambda _, result, __: result)
    state = AgentKernel(f.host, f.host.adapters.tool_registry).execute(
        f.scope, goal="Synthetic read",
    )
    value = state["tool_results"][0]["value"]
    if ledger:
        assert value["execution_ref"]["call_id"] == str(f.store.session.call.id)
        assert f.store.session.call.call_key == f.intent
        assert f.callbacks == 1
    else:
        assert value["error"]["code"] == "FORBIDDEN_SCOPE"
        assert f.callbacks == 0 and not f.store.claimed_bindings


def test_category_scoped_baseline_selector_is_read_only_and_preserves_bound_scope():
    registry = default_registry()
    scope = RunScope(*(uuid4() for _ in range(6)))
    target = uuid4()
    selected = {"product_id": str(target)}
    assert registry.authorize(scope, "product.baseline.read", selected, {}, lambda *_: False)
    assert scope.product_id is None
    for write in ("product.definition.draft", "product.definition.item.patch",
                  "product.variant.derive", "product.variant.rebase"):
        with pytest.raises(DomainError) as failure:
            registry.authorize(scope, write, selected, {}, lambda *_: True)
        assert failure.value.code == "FORBIDDEN_SCOPE"
    for invalid_scope in (replace(scope, category_id=None), replace(scope, product_id=uuid4())):
        with pytest.raises(DomainError):
            registry.authorize(
                invalid_scope, "product.baseline.read", selected, {}, lambda *_: True,
            )
    with pytest.raises(DomainError):
        registry.authorize(scope, "category.read", selected, {}, lambda *_: True)
    for field in ("category_id", "proposal_id", "tenant_id", "execution_binding"):
        with pytest.raises(DomainError):
            registry.authorize(
                scope, "product.baseline.read", {**selected, field: str(uuid4())},
                {}, lambda *_: True,
            )
