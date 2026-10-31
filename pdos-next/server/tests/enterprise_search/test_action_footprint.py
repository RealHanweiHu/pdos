"""Whole-context audience checks preserve the Human's explicit discussion selection."""
# ruff: noqa: F811 -- existing pure source fixture

import pytest
from pdos_next.enterprise_search import action_sources as carry
from pdos_next.errors import DomainError
from tests.enterprise_search.test_action_sources import case  # noqa: F401


def test_uncited_customer_context_cannot_be_removed_by_selecting_only_shared_a(case):
    selected = case.source(private=False)
    customer = case.source(customer=True)
    with pytest.raises(DomainError) as failure:
        case.capture([selected])
    assert failure.value.detail["reason_key"] == "assistant_action_customer_original_shared"
    assert set(case.state.current_calls[-1][0]) == {selected, customer}


def test_uncited_private_context_must_cover_the_actual_shared_target(case, monkeypatch):
    selected = case.source(private=False)
    private = case.source(private=True)
    monkeypatch.setattr(carry, "_audience_roots", lambda *_args, **_kw: set())
    monkeypatch.setattr(
        carry,
        "_source_roots",
        lambda *_args: {
            (
                "artifact_versions",
                case.state.carried[private]["source_id"],
                str(case.ctx.requester_id),
            ),
        },
    )
    with pytest.raises(DomainError) as failure:
        case.capture([selected])
    assert failure.value.detail["reason_key"] == "assistant_action_audience_widened"


def test_private_target_checks_full_context_without_selecting_or_binding_uncited_b(case):
    selected = case.source(private=False)
    private = case.source(private=True, customer=True)
    case.build.visibility = "private"
    proof = case.capture([selected])
    assert [source["citation_id"] for source in proof["discussion_sources"]] == [selected]
    assert proof["read_set"] == proof["execution_sources"] == proof["execution_references"] == []
    assert set(case.state.current_calls[-1][0]) == {selected, private}
    assert private not in str(proof)


def test_reopening_rechecks_newly_restricted_uncited_context(case, monkeypatch):
    selected = case.source(private=False)
    uncited = case.source(private=False)
    proof = case.capture([selected])
    case.state.actual[uncited]["customer_original"] = True
    with pytest.raises(DomainError) as failure:
        carry.recheck(case.session, case.ctx, case.run, proof)
    assert failure.value.detail["reason_key"] == "assistant_action_customer_original_shared"
    assert [row["citation_id"] for row in proof["discussion_sources"]] == [selected]


def test_reopening_cannot_omit_a_revoked_uncited_context_dependency(case):
    selected = case.source(private=False)
    uncited = case.source(private=False)
    proof = case.capture([selected])
    case.state.actual.pop(uncited)
    with pytest.raises(DomainError) as failure:
        carry.recheck(case.session, case.ctx, case.run, proof)
    assert failure.value.code == "SOURCE_UNAVAILABLE"
