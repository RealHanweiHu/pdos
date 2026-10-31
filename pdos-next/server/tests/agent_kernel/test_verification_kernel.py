"""Actual graph provenance and Human-candidate composition without DB/provider IO."""

import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.enterprise_search import verification_kernel
from pdos_next.enterprise_search.verification_candidates import PREPARATION, resolve_draft
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import BuildRef
from tests.agent_kernel.test_bound_read_host import make_host
from tests.agent_kernel.test_graph import Host, final, scope


def ready():
    selected = BuildRef(
        id=uuid4(), revision=3, product_id=uuid4(), project_id=uuid4(),
        engineering_configuration={"id": uuid4(), "revision": 2},
        manufacturing_configuration={"id": uuid4(), "revision": 4},
    )
    draft = {
        "title": "核对密封措施", "purpose": "验证选择配置下的措施",
        "return_form": "逐项测量结果", "reason": "依据已核对讨论准备复验",
        "items": [{"id": "pressure", "feature": "压力保持", "sample_count": 5}],
        "sources": [{"artifact_id": str(uuid4()), "expected_revision": 1,
                     "line": 3, "quote": "登记的压力保持要求"}],
    }
    arguments = resolve_draft(draft, request_id=uuid4(), selection=selected)["arguments"]
    arguments.pop("confirmation_token")  # Provider tools never receive Human confirmation tokens.
    return selected, arguments


class CandidateHost(Host):
    def prepare(self, current, spec, arguments, intent, *, source=None):
        self.prepared.append((spec.name, intent, source))
        return {"state": "candidate", "requires_human": True}


def test_graph_preparation_uses_completed_model_id_and_previously_loaded_method():
    _selected, arguments = ready()
    model_id = uuid4()
    host = CandidateHost([ModelTurn(ledger_call_id=model_id, calls=(
        ToolCall(id="provider-label-is-not-authority", name=PREPARATION, arguments=arguments),
    )), final()])
    current = scope()
    result = AgentKernel(host, default_registry()).execute(
        current, goal="准备复验", preload=["test_verification"],
    )
    assert result["output"]["status"] == "completed"
    name, key, source = host.prepared[0]
    assert name == PREPARATION and isinstance(source, WriteSource)
    assert source.model_call_id == model_id and source.response_index == 0
    assert source.skill.key == "test_verification"
    assert key == execution_key(current.run_id, model_id, 0)
    assert any(event["type"] == "skill_loaded" for event in host.events)
    assert str(source.skill.load_event_id) in str(result["loaded"])
    assert not host.writes


@pytest.mark.parametrize("same_turn_load", [False, True])
def test_graph_never_fabricates_a_preparation_model_or_method_binding(same_turn_load):
    _selected, arguments = ready()
    calls = [ToolCall(id="prepare", name=PREPARATION, arguments=arguments)]
    if same_turn_load:
        calls.insert(0, ToolCall(id="load", name="skill.load",
                                 arguments={"name": "test_verification"}))
    host = CandidateHost([ModelTurn(ledger_call_id=uuid4() if same_turn_load else None,
                                    calls=tuple(calls)), final()])
    result = AgentKernel(host, default_registry()).execute(
        scope(), goal="准备复验", preload=[] if same_turn_load else ["test_verification"],
    )
    error = result["tool_results"][-1]["value"]["error"]
    assert error["code"] == ("FORBIDDEN_SCOPE" if same_turn_load else "SOURCE_UNAVAILABLE")
    assert not host.prepared and not host.writes


def fixture(monkeypatch, *, action=True):
    selected, arguments = ready()
    current = scope(product_id=selected.product_id, project_id=selected.project_id)
    values = asdict(current)
    for key in ("isolation", "artifact_ids", "citation_ids"):
        values.pop(key)
    values["id"] = values.pop("run_id")
    run = SimpleNamespace(**values, versions={}, state="running", reverted_at=None)
    citations = [str(uuid4()), str(uuid4())]
    if action:
        run.versions["verification_action"] = {
            "selection": selected.model_dump(mode="json"), "citation_ids": citations,
            "request_id": arguments["request_id"],
            "source_run_id": str(uuid4()), "source_proof": {"frozen": True},
        }
    source = WriteSource(
        skill=SkillBinding(key="test_verification", version="1", digest="a" * 64,
                           load_event_id=uuid4()), model_call_id=uuid4(), response_index=2,
    )
    opened, recorded = [], []
    def get_run(kind, identity, *, with_for_update=False):
        assert kind.__name__ == "AgentRun" and identity == run.id and with_for_update
        return run

    session = SimpleNamespace(get=get_run)

    @contextmanager
    def human_transaction(engine, tenant_id, **kwargs):
        opened.append((engine, tenant_id, kwargs))
        session.info = {"scope": (tenant_id, kwargs["actor_id"], kwargs["requester_id"],
                                  kwargs["category_id"])}
        yield session

    def record(actual_session, ctx, run_id, **kwargs):
        assert actual_session is session and run_id == run.id
        assert ctx.actor_id == ctx.requester_id == current.requester_id
        assert ctx.agent_run_id is ctx.agent_call_id is ctx.run_id is None
        assert session.info["scope"][1] == current.requester_id != run.writer_id
        recorded.append(kwargs)
        return {"event_id": str(uuid4()), "state": "candidate", "requires_human": True}

    monkeypatch.setattr(verification_kernel, "tenant_session", human_transaction)
    monkeypatch.setattr(verification_kernel, "record", record)
    return SimpleNamespace(
        selected=selected, arguments=arguments, scope=current, run=run, citations=citations,
        source=source, intent=execution_key(run.id, source.model_call_id, source.response_index),
        opened=opened, recorded=recorded, owner=SimpleNamespace(engine=object()),
        spec=default_registry().get(PREPARATION),
    )


def prepare(f, **kwargs):
    return verification_kernel.prepare(
        f.owner, f.scope, f.spec, f.arguments, f.intent, source=kwargs.get("source", f.source),
    )


def test_kernel_adapter_uses_human_transaction_without_changing_run_writer(monkeypatch):
    f = fixture(monkeypatch)
    original_writer = f.run.writer_id
    result = prepare(f)
    assert result["state"] == "candidate" and result["write_tier"] == "T1"
    assert f.run.writer_id == original_writer and len(f.opened) == len(f.recorded) == 1
    assert f.opened[0][2] == {
        "actor_id": f.scope.requester_id, "requester_id": f.scope.requester_id,
        "category_id": f.scope.category_id,
    }
    actual = f.recorded[0]
    assert actual["selection"] == f.selected
    assert list(map(str, actual["citation_ids"])) == f.citations
    assert actual["arguments"] == f.arguments and actual["source"] == f.source


@pytest.mark.parametrize("change", [
    "source", "intent", "writer", "epoch", "selection", "citations",
    "request_identity", "missing_request_identity",
])
def test_kernel_adapter_rejects_unbound_or_changed_action_without_recording(monkeypatch, change):
    f = fixture(monkeypatch)
    kwargs = {}
    if change == "source":
        kwargs["source"] = None
    elif change == "intent":
        f.intent = "provider-supplied-id"
    elif change == "writer":
        f.scope = replace(f.scope, writer_id=uuid4())
    elif change == "epoch":
        f.run.cancel_epoch += 1
    elif change == "selection":
        f.run.versions["verification_action"]["selection"] = {}
    elif change == "request_identity":
        f.arguments["request_id"] = str(uuid4())
    elif change == "missing_request_identity":
        f.run.versions["verification_action"].pop("request_id")
    else:
        f.run.versions["verification_action"]["citation_ids"] = []
    with pytest.raises(DomainError) as failure:
        prepare(f, **kwargs)
    if change == "request_identity":
        assert failure.value.code == "FORBIDDEN_SCOPE"
    assert not f.recorded


def test_no_action_preserves_existing_generic_candidate_path(monkeypatch):
    f = fixture(monkeypatch, action=False)
    assert prepare(f, source=None) is None and not f.recorded


def test_bootstrap_records_action_before_entering_ai_command_transaction(monkeypatch):
    owner = Bootstrap.__new__(Bootstrap)
    owner.commands = SimpleNamespace(transaction=lambda _: pytest.fail("Entered AI command UOW"))
    candidate = {"state": "candidate", "event_id": str(uuid4()), "write_tier": "T1"}
    f = fixture(monkeypatch)
    calls = []

    def project(*args, **kwargs):
        calls.append((args, kwargs))
        return candidate

    monkeypatch.setattr(verification_kernel, "prepare", project)
    assert owner.prepare_candidate(f.scope, f.spec, f.arguments, f.intent,
                                   source=f.source) is candidate
    assert calls[0][0][0] is owner and calls[0][1] == {"source": f.source}


def test_host_only_adds_source_keyword_to_preparation_callback(monkeypatch):
    from pdos_next.domain.automations import runtime

    monkeypatch.setattr(runtime, "guard_tool", lambda *_args, **_kwargs: None)
    f = make_host()
    seen = []
    f.host.adapters = replace(f.host.adapters,
        prepare_candidate=lambda *args, **kwargs: seen.append((args, kwargs)))
    source = WriteSource(skill=SkillBinding(key="test_verification", version="1",
        digest="a" * 64, load_event_id=uuid4()), model_call_id=uuid4(), response_index=0)
    preparation = default_registry().get(PREPARATION)
    ordinary = default_registry().get("project.create")
    f.host.prepare(f.scope, preparation, {}, "intent", source=source)
    f.host.prepare(f.scope, ordinary, {}, "ordinary")
    assert seen[0][1] == {"source": source} and seen[1][1] == {}


def test_action_context_uses_frozen_server_value_and_no_action_adds_nothing(monkeypatch):
    from pdos_next.agent_kernel import context_projection

    f = make_host()
    frozen = {"selection": {"id": str(uuid4())}, "citation_ids": [str(uuid4())]}
    f.run.versions.update(personal_preferences_context={"revision": 1},
                          verification_action=deepcopy(frozen))
    module = ModuleType("pdos_next.enterprise_search.verification_actions")
    observed = []

    def context_value(value):
        observed.append(deepcopy(value))
        return {"target": value["selection"], "citation_ids": value["citation_ids"]}

    module.context_value = context_value
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(context_projection, "combine_contracts", lambda *_: {"properties": {}})
    monkeypatch.setattr(context_projection, "project", lambda value, _: (value, [], []))
    monkeypatch.setattr(context_projection, "snapshot", lambda *_args, **_kwargs: "snapshot")
    f.host.adapters = replace(f.host.adapters, project_context=lambda *_: {"goal": "prepare"})
    first = f.host.skill_context(f.scope, "prepare", bindings=())
    assert first["context"]["verification_action"] == context_value(frozen)
    assert observed[0] == frozen and f.run.versions["verification_action"] == frozen
    f.run.versions.pop("verification_action")
    second = f.host.skill_context(f.scope, "prepare", bindings=())
    assert "verification_action" not in second["context"]


@pytest.mark.parametrize("operation", [PREPARATION, "project.create"])
def test_bootstrap_no_action_and_ordinary_candidates_keep_original_ai_metadata_path(
    monkeypatch, operation,
):
    f = fixture(monkeypatch, action=False)
    owner = Bootstrap.__new__(Bootstrap)
    owner.engine = f.owner.engine
    spec = default_registry().get(operation)
    entered, checked = [], []
    session = object()

    @contextmanager
    def ai_transaction(current):
        assert current is f.scope
        entered.append(current.writer_id)
        yield session

    command = {"operation": operation, "payload": {"title": "native candidate"}}
    owner.commands = SimpleNamespace(
        transaction=ai_transaction,
        command=lambda *_: SimpleNamespace(model_dump=lambda **_: command),
    )
    owner.store = SimpleNamespace(authority=lambda actual, current: checked.append(
        (actual, current.writer_id),
    ))
    result = owner.prepare_candidate(f.scope, spec, {}, f.intent)
    assert result["command"] == command and result["state"] == "candidate"
    assert entered == [f.scope.writer_id] and checked == [(session, f.scope.writer_id)]
    assert not f.recorded
