"""Registered local-list observation clocks retain strict Host replay digests."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.registry import ToolRegistry
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError
from pdos_next.service import digest
from tests.agent_kernel.test_bound_read_host import read
from tests.agent_kernel.test_result_continuation import host

NAMES = sorted(DomainReads.OBSERVED_LISTS)


def local_list(name):
    f = host()
    callback = f.host.adapters.read_tools[f.spec.name]
    f.spec = default_registry().get(name)
    registry = ToolRegistry([f.spec, default_registry().get("result.read")])
    f.arguments = {}
    f.model.result["calls"] = [{"id": "local-list", "name": name, "arguments": {}}]
    f.model.execution_binding = {**f.model.execution_binding,
                                 "tool_definitions_digest": digest(registry.definitions())}
    f.run.versions["tool_definitions"]["main"] = digest(registry.definitions())
    f.result = {"items": [{"version": 1, "body": "native source",
                           "as_of": "nested business value"}],
                "next_cursor": None, "as_of": "2026-10-29T12:00:00+00:00"}
    reads = DomainReads(f.store, None)

    def fresh(scope, arguments, *, name):
        assert name == f.spec.name and scope == f.scope and arguments == f.arguments
        return callback(scope, arguments)

    reads.call = fresh
    f.host.adapters = replace(f.host.adapters, tool_registry=registry,
                              read_tools=reads.handlers(), read_restores=reads.restores())
    return f


@pytest.mark.parametrize("name", NAMES)
def test_observation_clock_moves_but_real_host_replay_preserves_original_ledger(name):
    f = local_list(name)
    first = read(f)
    original = deepcopy(f.store.session.call.result)
    f.result["as_of"] = "2026-10-29T12:30:00+00:00"
    assert read(f) == first
    assert f.callbacks == 2 and f.store.settled == 1
    assert f.store.session.call.result == original
    assert f.result["as_of"] != first["as_of"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("change", ["body", "version", "cursor", "nested_as_of", "extra_field"])
def test_only_top_level_observation_clock_is_retained_other_changes_stay_source_stale(name, change):
    f = local_list(name)
    read(f)
    original = deepcopy(f.store.session.call.result)
    f.result["as_of"] = "2026-10-29T12:30:00+00:00"
    if change in {"body", "version"}:
        f.result["items"][0][change] = "changed"
    elif change == "cursor":
        f.result["next_cursor"] = "new-native-cursor"
    elif change == "nested_as_of":
        f.result["items"][0]["as_of"] = "changed business value"
    else:
        f.result["new_column"] = "changed"
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value.code == "SOURCE_STALE"
    assert failure.value.message == "读取结果已变化，请使用新的运行重新读取。"
    assert f.callbacks == 2 and f.store.session.call.result == original
    assert f.store.settled == 1 and not f.store.released


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("code", ["FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"])
def test_restore_reexecutes_ordinary_source_checks_and_preserves_failure(name, code):
    f = local_list(name)
    read(f)
    original = deepcopy(f.store.session.call.result)
    f.callback_error = DomainError(code, "Synthetic current native source denial")
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value is f.callback_error and f.callbacks == 2
    assert f.store.session.call.result == original and f.store.settled == 1


@pytest.mark.parametrize("name", NAMES)
def test_missing_fresh_observation_clock_is_not_silently_added(name):
    f = local_list(name)
    read(f)
    del f.result["as_of"]
    with pytest.raises(DomainError) as failure:
        read(f)
    assert failure.value.code == "SOURCE_STALE" and f.callbacks == 2


def test_bootstrap_registers_only_the_three_native_domain_list_restores():
    assert set(NAMES) == {
        "category.parameters.list", "category.knowledge.list", "category.competitors.list",
    }
    owner = Bootstrap(SimpleNamespace(), ports=RuntimePorts())
    restores = owner.adapters().read_restores
    for name in NAMES:
        assert restores[name].func.__self__.__class__ is DomainReads
        assert restores[name].keywords == {"name": name}
    assert "category.read" not in restores and "evidence.search" not in restores


def test_custom_host_callback_does_not_inherit_native_clock_restore():
    owner = Bootstrap(SimpleNamespace(), ports=RuntimePorts(read_tools={
        "category.parameters.list": lambda *_: {"as_of": "custom host value"},
    }))
    restores = owner.adapters().read_restores
    assert "category.parameters.list" not in restores
    assert {"category.knowledge.list", "category.competitors.list"} <= set(restores)
