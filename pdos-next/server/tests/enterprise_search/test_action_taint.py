"""Action-only classification follows actual carried context, never selected citations."""
# ruff: noqa: F811 -- imported fixture dependency tree

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next.enterprise_search import action_sources, action_taint, assistant_adapter
from pdos_next.errors import DomainError
from tests.enterprise_search.test_action_sources import case  # noqa: F401


def test_uncited_actual_source_classifies_without_changing_explicit_binding_reads():
    selected, uncited = str(uuid4()), str(uuid4())
    taint = action_taint.classify({
        selected: {"private": False, "customer_original": False},
        uncited: {"private": True, "customer_original": True},
    })
    reads = [{"artifact_id": selected, "expected_revision": 3}]
    parent = SimpleNamespace(read_sources=deepcopy(reads), _explicit_context_binding={
        "private_context": False, "data_categories": ["internal", "customer"],
        "customer_identities": ["SyntheticClient"],
    })
    action_taint.inherit(parent, taint)
    assert parent._explicit_context_binding == {
        "private_context": True,
        "data_categories": ["customer", "customer_original", "internal"],
        "customer_identities": ["SyntheticClient"],
    }
    assert parent.read_sources == reads
    action_taint.inherit(parent, action_taint.classify({}))
    assert parent._explicit_context_binding["private_context"] is True
    assert "customer_original" in parent._explicit_context_binding["data_categories"]


@pytest.mark.parametrize("taint", [None, {}, {"private": True},
    {"private": False, "customer_original": 1},
    {"private": False, "customer_original": False, "client_mode": "safe"}])
def test_unclassified_legacy_proof_cannot_silently_create_new_action_scope(taint):
    parent = SimpleNamespace()
    with pytest.raises(DomainError) as failure:
        action_taint.inherit(parent, taint)
    assert failure.value.code == "SOURCE_UNAVAILABLE"
    assert not hasattr(parent, "_explicit_context_binding")


def test_new_proof_includes_uncited_taint_and_legacy_proof_keeps_original_shape(case):
    selected = case.source()
    case.source(private=True, customer=True)
    case.build.visibility = "private"
    legacy = case.capture([selected])
    assert "taint" not in legacy
    assert action_sources.recheck(case.session, case.ctx, case.run, legacy) == legacy
    proof = action_sources.capture(
        case.session, case.ctx, case.run, [selected], product_id=case.run.product_id,
        build_id=case.build.id, include_taint=True,
    )
    assert proof["taint"] == {"private": True, "customer_original": True}
    assert [row["citation_id"] for row in proof["discussion_sources"]] == [selected]
    assert proof["read_set"] == [] and proof["execution_references"] == []
    assert action_sources.recheck(case.session, case.ctx, case.run, proof) == proof


@pytest.fixture
def guard_case(monkeypatch):
    scope = SimpleNamespace(
        isolation="main", tenant_id=uuid4(), requester_id=uuid4(), category_id=uuid4(),
        run_id=uuid4(), private_context=True,
        data_categories=frozenset({"internal", "customer_original"}),
    )
    run = SimpleNamespace(versions={"verification_action": {"version": 1}})
    state = SimpleNamespace(actual={"A": {"private": False, "customer_original": False},
                                    "B": {"private": True, "customer_original": True}},
                            missing={}, bridged=0, ordinary=0)
    @contextmanager
    def transaction(_scope):
        yield None, run
    @contextmanager
    def snapshot(*_args):
        yield SimpleNamespace(get=lambda *_args: run)
    def footprint(*_args):
        state.bridged += 1
        return {"A": {}}, set(), {"A": {}, "B": {}}
    def carried(*_args):
        state.ordinary += 1
        return {"A": {}}, set()
    monkeypatch.setattr(assistant_adapter, "human_snapshot", snapshot)
    monkeypatch.setattr(action_sources, "_discussion_footprint", footprint)
    monkeypatch.setattr(assistant_adapter.ledger, "carried", carried)
    def current(_session, selected, **_kwargs):
        return {key: value for key, value in state.actual.items() if key in selected}, state.missing
    monkeypatch.setattr(assistant_adapter, "current", current)
    adapter = assistant_adapter.AssistantReadAdapter(
        SimpleNamespace(engine=None, transaction=transaction), None,
    )
    return SimpleNamespace(scope=scope, state=state, run=run, adapter=adapter)


def test_action_model_guard_rechecks_uncited_direct_parent_context_before_egress(guard_case):
    case = guard_case
    assert case.adapter.guard(case.scope) == frozenset({"internal", "customer_original"})
    assert case.state.bridged == 1 and case.state.ordinary == 0
    case.state.missing = {"B": "source_unavailable"}
    with pytest.raises(DomainError) as failure:
        case.adapter.guard(case.scope)
    assert failure.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("missing", ["private_context", "data_categories"])
def test_legacy_action_run_requires_explicit_recontinuation_for_missing_classification(
    guard_case, missing,
):
    case = guard_case
    setattr(case.scope, missing, False if missing == "private_context" else frozenset({"internal"}))
    with pytest.raises(DomainError) as failure:
        case.adapter.guard(case.scope)
    assert failure.value.code == "FORBIDDEN_SCOPE"
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"
    assert "重新续接" in failure.value.message


def test_ordinary_run_model_guard_keeps_ordinary_read_selection(guard_case):
    case = guard_case
    case.run.versions = {}
    case.scope.private_context = False
    case.scope.data_categories = frozenset({"internal"})
    assert case.adapter.guard(case.scope) == frozenset({"internal"})
    assert case.state.bridged == 0 and case.state.ordinary == 1
