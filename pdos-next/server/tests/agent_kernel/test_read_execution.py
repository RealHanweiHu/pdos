"""Actual ORM-shaped model/read provenance, without DB or provider access."""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.read_execution import (
    ReadBinding,
    ReadSource,
    build_read_binding,
    verify_read_source,
)
from pdos_next.agent_kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError
from pdos_next.service import digest


class MemorySession:
    def __init__(self, *rows):
        self.rows = {(type(row), row.id): row for row in rows}

    def get(self, model, identity):
        return self.rows.get((model, identity))


def fixture(isolation="main", *, compute=False):
    scope = RunScope(*(uuid4() for _ in range(6)), proposal_id=uuid4(), isolation=isolation)
    name = "calc.cost_subtotal" if compute else {
        "main": "category.read", "research": "research.read", "extract": "evidence.artifact.read",
    }[isolation]
    spec = ToolSpec(
        name, "Synthetic registered reader", {"type": "object", "properties": {
            "query": {"type": "string"},
        }}, {"type": "object"}, "compute" if compute else "read", "READ",
    )
    registry = ToolRegistry([spec])
    values = asdict(scope)
    for key in ("isolation", "artifact_ids", "trigger"):
        values.pop(key)
    values["id"] = values.pop("run_id")
    values["data_categories"] = list(values["data_categories"])
    values["customer_identities"] = list(values["customer_identities"])
    run = AgentRun(
        **values, state="running", reverted_at=None,
        versions={
            "model_version": "synthetic-model-v1", "model_route_digest": "a" * 64,
            "tool_definitions": {isolation: digest(registry.definitions(isolation))},
            "prompt_prefixes": {isolation: "c" * 64},
        },
    )
    arguments = {"query": "actual model argument"}
    model = AgentToolCall(
        id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, tool="model", state="completed",
        error_code=None, receipt_id=None, call_key="model:server-request-digest",
        input_digest="d" * 64,
        execution_binding={
            "kind": "model", "model_version": "synthetic-model-v1",
            "model_route_digest": "a" * 64,
            "tool_definitions_digest": run.versions["tool_definitions"][isolation],
            "prompt_digest": "c" * 64, "isolation": isolation, "cancel_epoch": 0,
            "loaded_skills": [],
        },
        result={"calls": [{"id": "provider-label", "name": name, "arguments": arguments}]},
    )
    source = ReadSource(model_call_id=model.id, response_index=0)
    return NS(
        scope=scope, run=run, model=model, spec=spec, source=source, registry=registry,
        arguments=deepcopy(arguments), session=MemorySession(run, model),
        route=NS(version="synthetic-model-v1", digest="a" * 64),
        intent=execution_key(run.id, model.id, 0),
    )


def verify(f, **kwargs):
    return verify_read_source(
        f.session, f.scope, f.run, f.spec, f.arguments, f.source, f.registry, f.route,
        intent_key=kwargs.get("intent_key", f.intent),
    )


def build(f, **kwargs):
    return build_read_binding(f.scope, f.run, f.spec, f.source, verify(f), **kwargs)


@pytest.mark.parametrize("isolation", ["main", "research", "extract"])
def test_actual_model_read_without_skills_or_t0_qualification(isolation):
    f = fixture(isolation)
    binding = build(f)
    assert binding.isolation == isolation
    assert binding.call_key == f.intent
    assert binding.model_call_id == f.model.id
    assert binding.requester_id == f.run.requester_id
    assert binding.data_categories == ("public",)
    encoded = binding.model_dump(mode="json")
    assert "page_chars" not in encoded and "engine_version" not in encoded
    assert encoded["product_id"] is None
    assert ReadBinding.model_validate(encoded) == binding
    with pytest.raises(ValidationError):
        binding.cancel_epoch = 1


@pytest.mark.parametrize("field", [
    "tenant_id", "requester_id", "writer_id", "category_id", "product_id", "proposal_id",
    "session_id", "run_id",
])
def test_scope_cannot_replace_actual_run_identity(field):
    f = fixture()
    f.scope = replace(f.scope, **{field: uuid4()})
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("changes", [
    {"private_context": True}, {"data_categories": frozenset({"customer"})},
    {"customer_identities": ("Private customer",)}, {"cancel_epoch": 1},
])
def test_actual_private_context_and_epoch_are_bound(changes):
    f = fixture()
    f.scope = replace(f.scope, **changes)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("state", ["completed", "partial", "failed", "cancelled", "cancelling"])
def test_ended_runs_cannot_start_new_read(state):
    f = fixture()
    f.run.state = state
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field,value", [
    ("id", uuid4()), ("tenant_id", uuid4()), ("run_id", uuid4()), ("tool", "category.read"),
    ("state", "started"), ("state", "unknown"), ("error_code", "ERROR"),
    ("receipt_id", uuid4()), ("result", None), ("result", {"calls": {}}),
    ("result", {"calls": []}), ("execution_binding", {"kind": "unbound"}),
])
def test_only_actual_successful_model_call_qualifies(field, value):
    f = fixture()
    setattr(f.model, field, value)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field,value", [
    ("isolation", "research"), ("cancel_epoch", 1), ("model_version", "other-model"),
    ("model_route_digest", "b" * 64), ("tool_definitions_digest", "b" * 64),
    ("prompt_digest", "b" * 64),
])
def test_model_binding_matches_run_and_execution_isolation(field, value):
    f = fixture()
    f.model.execution_binding = {**f.model.execution_binding, field: value}
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("bad", [None, {}, {"tool_definitions": []}, {
    "tool_definitions": {}, "prompt_prefixes": {},
}])
def test_missing_or_malformed_frozen_versions_fail_closed(bad):
    f = fixture()
    f.run.versions = bad
    with pytest.raises(DomainError):
        verify(f)


def test_database_run_is_reloaded_not_replaced_by_caller():
    f = fixture()
    f.session.rows.pop((AgentRun, f.run.id))
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("native_key", ["provider-label", "other-intent", ""])
def test_native_provider_call_labels_do_not_establish_intent(native_key):
    with pytest.raises(DomainError):
        verify(fixture(), intent_key=native_key)


@pytest.mark.parametrize("index", [True, False, -1, "0", 0.0])
def test_response_index_is_strict(index):
    with pytest.raises(ValidationError):
        ReadSource(model_call_id=uuid4(), response_index=index)


def test_source_must_be_an_internal_object_and_index_must_exist():
    f = fixture()
    f.source = f.source.model_dump()
    with pytest.raises(DomainError):
        verify(f)
    f.source = ReadSource(model_call_id=f.model.id, response_index=1)
    f.intent = execution_key(f.run.id, f.model.id, 1)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("response_call", [
    None, {"name": "other", "arguments": {}},
    {"name": "category.read", "arguments": []},
    {"name": "category.read", "arguments": {"query": "forged"}},
])
def test_actual_model_response_name_and_arguments_are_exact(response_call):
    f = fixture()
    f.model.result = {"calls": [response_call]}
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field,value", [
    ("tier", "T0"), ("kind", "write"), ("operation_key", "category.read"),
    ("input_schema", {"type": "object", "required": ["forged"]}),
])
def test_caller_spec_cannot_replace_registered_tool_or_schema(field, value):
    f = fixture()
    f.spec = replace(f.spec, **{field: value})
    with pytest.raises(DomainError):
        verify(f)


def test_actual_registry_definition_change_invalidates_model_binding():
    f = fixture()
    f.registry = ToolRegistry([replace(f.spec, description="new definition")])
    f.spec = f.registry.get(f.spec.name)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("route", [None, NS(version="new", digest="a" * 64),
                                   NS(version="synthetic-model-v1", digest="b" * 64)])
def test_current_route_must_equal_frozen_route(route):
    f = fixture()
    f.route = route
    with pytest.raises(DomainError):
        verify(f)


def test_research_read_cannot_be_claimed_from_main():
    f = fixture("research")
    f.scope = f.scope.child("main")
    with pytest.raises(DomainError):
        verify(f)


def test_persisted_research_binding_keeps_origin_isolation_for_main_consumer():
    f = fixture("research")
    stored = build(f, read_kind="registered_snapshot/v1", server_metadata={"page_chars": 512})
    consumer = f.scope.child("main")
    assert consumer.run_id == stored.run_id
    assert stored.isolation == "research" != consumer.isolation
    assert ReadBinding.model_validate(stored.model_dump(mode="json")) == stored


def test_model_arguments_cannot_smuggle_server_authority():
    f = fixture()
    f.arguments["execution_binding"] = {"kind": "read"}
    f.model.result["calls"][0]["arguments"] = deepcopy(f.arguments)
    with pytest.raises(DomainError):
        verify(f)


def test_compute_binding_is_complete_before_persistence():
    f = fixture(compute=True)
    binding = build(f, read_kind="compute/v1", server_metadata={
        "engine_version": "cost-v1", "result_digest": "e" * 64,
    })
    assert binding.engine_version == "cost-v1"
    assert binding.result_digest == "e" * 64
    assert "page_chars" not in binding.model_dump()


@pytest.mark.parametrize("kind,metadata", [
    ("compute/v1", {}), ("compute/v1", {"engine_version": "v1"}),
    ("compute/v1", {"engine_version": "v1", "result_digest": "invalid"}),
    ("ordinary/v1", {"page_chars": 12}), ("ordinary/v1", {"tenant_id": uuid4()}),
    ("unknown/v1", {}), ("ordinary/v1", []),
])
def test_metadata_is_closed_and_cannot_override_identity(kind, metadata):
    with pytest.raises(DomainError):
        build(fixture(compute=True), read_kind=kind, server_metadata=metadata)


@pytest.mark.parametrize("size", [True, "512", 0, -1, 200_001])
def test_page_policy_is_strict_and_bounded(size):
    with pytest.raises(DomainError):
        build(fixture("research"), read_kind="registered_snapshot/v1",
              server_metadata={"page_chars": size})


def test_ordinary_tool_cannot_supply_compute_metadata():
    with pytest.raises(DomainError):
        build(fixture(), read_kind="compute/v1", server_metadata={
            "engine_version": "v1", "result_digest": "e" * 64,
        })


def test_snapshot_binding_requires_registered_category():
    f = fixture("research")
    f.scope = replace(f.scope, category_id=None)
    f.run.category_id = None
    with pytest.raises(DomainError):
        build(f, read_kind="registered_snapshot/v1", server_metadata={"page_chars": 512})
