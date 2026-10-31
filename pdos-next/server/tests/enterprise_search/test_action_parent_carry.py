"""An explicit native action bridges selected discussion and complete parent taint."""
# ruff: noqa: F811 -- existing independent pure source fixture

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.enterprise_search import action_sources as carry
from pdos_next.enterprise_search import verification_actions as actions
from pdos_next.errors import DomainError
from tests.enterprise_search.test_action_sources import case  # noqa: F401


def action_case(case, monkeypatch):
    selected = case.source("artifact")
    uncited = case.source("artifact")
    child = case.source("artifact")
    parent = SimpleNamespace(**{**vars(case.run), "id": uuid4(), "versions": {}})
    parent_items = {cid: deepcopy(case.state.carried[cid]) for cid in (selected, uncited)}
    child_items = {child: deepcopy(case.state.carried[child])}
    proof = {"run_id": str(parent.id), "discussion_sources": [{"citation_id": selected}]}
    action = {
        "version": 1,
        "kind": "prepare_verification",
        "source_run_id": str(parent.id),
        "selection": {"id": str(case.build.id)},
        "citation_ids": [selected],
        "source_proof": proof,
    }
    case.run.continued_from_id = parent.id
    case.run.versions = {"verification_action": action}
    rows = {case.run.id: case.run, parent.id: parent}
    calls = []

    def get(model, identity):
        assert model is AgentRun
        return rows.get(identity)

    def ledger(_session, identity):
        assert identity in rows
        calls.append(("carried", identity))
        return deepcopy(parent_items if identity == parent.id else child_items), set()

    def target(_session, actual_ctx, actual_parent, selection):
        assert (
            actual_ctx is case.ctx and actual_parent is parent and selection is action["selection"]
        )
        calls.append(("target", actual_parent.id))

    def recheck(_session, actual_ctx, actual_parent, frozen):
        assert actual_ctx is case.ctx and actual_parent is parent and frozen is proof
        calls.append(("parent_proof", actual_parent.id))
        return deepcopy(proof)

    monkeypatch.setattr(case.session, "get", get)
    monkeypatch.setattr(carry.ledger, "carried", ledger)
    monkeypatch.setattr(actions, "_target", target)
    monkeypatch.setattr(actions, "recheck", recheck)
    return SimpleNamespace(
        selected=selected,
        uncited=uncited,
        child=child,
        parent=parent,
        parent_items=parent_items,
        child_items=child_items,
        action=action,
        calls=calls,
    )


def test_action_selection_survives_separate_execution_context_without_changing_ordinary_ledger(
    case,
    monkeypatch,
):
    f = action_case(case, monkeypatch)
    before = deepcopy(case.run.versions)
    proof = case.capture([f.selected])
    assert [(row["citation_id"], row["purpose"]) for row in proof["discussion_sources"]] == [
        (f.selected, "historical_discussion"),
    ]
    assert proof["execution_references"] == proof["execution_sources"] == proof["read_set"] == []
    assert case.run.read_sources == [] and case.run.versions == before
    assert set(case.state.current_calls[-1][0]) == {f.selected, f.uncited, f.child}
    assert ("target", f.parent.id) in f.calls and ("parent_proof", f.parent.id) in f.calls
    ordinary, _history = carry.ledger.carried(case.session, case.run.id)
    assert set(ordinary) == {f.child}  # Ordinary context_selection is still narrow.
    assert carry.recheck(case.session, case.ctx, case.run, proof) == proof


@pytest.mark.parametrize("origin", ["parent", "child"])
def test_uncited_parent_or_child_customer_context_still_blocks_a_shared_action(
    case, monkeypatch, origin
):
    f = action_case(case, monkeypatch)
    cid = f.uncited if origin == "parent" else f.child
    case.state.actual[cid]["customer_original"] = True
    with pytest.raises(DomainError) as failed:
        case.capture([f.selected])
    assert failed.value.detail["reason_key"] == "assistant_action_customer_original_shared"
    assert set(case.state.current_calls[-1][0]) == {f.selected, f.uncited, f.child}


def test_private_target_rechecks_uncited_parent_revocation_without_binding_that_source(
    case, monkeypatch
):
    f = action_case(case, monkeypatch)
    case.build.visibility = "private"
    case.state.actual[f.uncited]["private"] = True
    proof = case.capture([f.selected])
    assert f.uncited not in str(proof)
    assert case.run.read_sources == []
    case.state.actual.pop(f.uncited)
    with pytest.raises(DomainError) as failed:
        carry.recheck(case.session, case.ctx, case.run, proof)
    assert failed.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("field", ["continued_from_id", "session_id", "requester_id", "product_id"])
def test_frozen_action_cannot_borrow_another_parent_session_human_or_product(
    case, monkeypatch, field
):
    f = action_case(case, monkeypatch)
    setattr(case.run if field == "continued_from_id" else f.parent, field, uuid4())
    with pytest.raises(DomainError) as failed:
        case.capture([f.selected])
    assert failed.value.code == "FORBIDDEN_SCOPE"
    assert ("parent_proof", f.parent.id) not in f.calls
    assert not case.state.current_calls


def test_unselected_parent_taint_does_not_become_a_discussion_citation(case, monkeypatch):
    f = action_case(case, monkeypatch)
    with pytest.raises(DomainError) as failed:
        case.capture([f.uncited])
    assert failed.value.detail["reason_key"] == "assistant_action_citation_not_carried"


def test_same_citation_identity_cannot_merge_different_child_metadata(case, monkeypatch):
    f = action_case(case, monkeypatch)
    f.child_items[f.selected] = {**f.parent_items[f.selected], "content_hash": "0" * 64}
    with pytest.raises(DomainError) as failed:
        case.capture([f.selected])
    assert failed.value.detail["reason_key"] == "assistant_action_origin_changed"


def test_unselected_parent_taint_does_not_satisfy_actual_execution_read(case, monkeypatch):
    f = action_case(case, monkeypatch)
    identity = f.parent_items[f.uncited]["source_id"]
    reference = {"artifact_id": identity, "expected_revision": 3, "line": 1, "quote": "方法依据"}
    case.run.read_sources = [{"artifact_id": identity, "expected_revision": 3}]
    with pytest.raises(DomainError) as failed:
        case.capture([f.selected], refs=[reference])
    assert failed.value.detail["reason_key"] == "assistant_action_execution_read_missing"


def test_continuation_alone_does_not_import_parent_footprint_without_the_native_action(
    case, monkeypatch
):
    f = action_case(case, monkeypatch)
    case.run.versions.clear()
    with pytest.raises(DomainError) as failed:
        case.capture([f.selected])
    assert failed.value.detail["reason_key"] == "assistant_action_citation_not_carried"
    assert f.calls == [("carried", case.run.id)]
