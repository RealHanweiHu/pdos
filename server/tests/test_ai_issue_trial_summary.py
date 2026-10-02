"""Pure per-run descriptive arithmetic and consistency checks, without a database."""

from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.ai_issue_trial_summary import aggregate


def item(n: int, **changes: Any) -> dict[str, Any]:
    return {
        "run_id": str(UUID(int=n)),
        "status": "succeeded",
        "result_id": str(UUID(int=100 + n)),
        "disposition": "create_issue",
        "binding_kind": "trial_candidate",
        "review_state": "unreviewed",
        "application_kind": None,
        "same_source_applied": False,
        "withdrawn": False,
        "human_edited": False,
        **changes,
    }


def test_full_population_preserves_failed_pending_old_and_unhandled_runs() -> None:
    rows = [
        item(1, application_kind="created", withdrawn=True),
        item(2, application_kind="created", human_edited=True),
        item(3, application_kind="created"),
        item(4, disposition="reuse_issue", application_kind="reused", binding_kind="evidence_only"),
        item(
            5,
            disposition="insufficient_evidence",
            review_state="declined",
            binding_kind="evidence_only",
        ),
        item(6, review_state="declined", same_source_applied=True),
        item(7, review_state="reopened"),
        item(8, same_source_applied=True, binding_kind="not_recorded"),
        item(9, binding_kind="evidence_only"),
        item(10, status="queued", result_id=None, disposition=None, binding_kind="not_recorded"),
        item(11, status="failed", result_id=None, disposition=None, binding_kind="evidence_only"),
        item(12, status="degraded", result_id=None, disposition=None),
        item(13, result_id=None, disposition=None, binding_kind="not_recorded"),
        item(14, status="waiting_input", result_id=None, disposition=None),
    ]
    before = deepcopy(rows)
    actual = aggregate(rows)
    assert rows == before
    assert actual["counts"] == {
        "total_runs": 14,
        "succeeded_runs": 10,
        "failed_runs": 2,
        "pending_runs": 2,
        "proposal_runs": 9,
        "insufficient_runs": 1,
        "created_issues": 3,
        "reused_issues": 1,
        "same_source_applied_runs": 2,
        "declined_runs": 2,
        "reopened_runs": 1,
        "unhandled_proposals": 2,
        "withdrawn_issues": 1,
        "human_edited_issues": 1,
        "trial_candidates": 7,
        "evidence_only_runs": 4,
        "unrecorded_bindings": 3,
    }
    assert actual["ratios"] == {
        "handled_proposals": 6,
        "confirmed_proposals": 4,
        "confirmation_basis_points": 6666,
        "withdrawal_basis_points": 3333,
        "descriptive_only": True,
    }
    assert actual["qualification_granted"] is False
    assert aggregate(list(reversed(rows))) == actual


def test_empty_denominators_remain_unknown_and_never_grant_qualification() -> None:
    actual = aggregate([])
    assert all(n == 0 for n in actual["counts"].values())
    assert actual["ratios"]["confirmation_basis_points"] is None
    assert actual["ratios"]["withdrawal_basis_points"] is None
    perfect = aggregate([item(1, application_kind="created")])
    assert perfect["ratios"]["confirmation_basis_points"] == 10000
    assert perfect["ratios"]["withdrawal_basis_points"] == 0
    assert perfect["qualification_granted"] is False


def test_same_source_application_is_not_adoption_and_does_not_hide_declined_opinion() -> None:
    same = aggregate([item(1, same_source_applied=True)])
    assert same["counts"]["unhandled_proposals"] == 0
    assert same["counts"]["same_source_applied_runs"] == 1
    assert same["ratios"]["handled_proposals"] == same["ratios"]["confirmed_proposals"] == 0
    assert same["ratios"]["confirmation_basis_points"] is None
    declined = aggregate([item(1, same_source_applied=True, review_state="declined")])
    assert declined["ratios"]["handled_proposals"] == 1
    assert declined["ratios"]["confirmation_basis_points"] == 0


def test_reopened_opinion_leaves_denominator_until_own_application() -> None:
    reopened = aggregate([item(1, review_state="reopened")])
    assert reopened["counts"]["unhandled_proposals"] == 1
    assert reopened["ratios"]["handled_proposals"] == 0
    applied = aggregate([item(1, review_state="reopened", application_kind="created")])
    assert applied["ratios"]["handled_proposals"] == applied["ratios"]["confirmed_proposals"] == 1


def test_insufficient_evidence_decline_stays_in_handled_denominator() -> None:
    actual = aggregate([item(1, disposition="insufficient_evidence", review_state="declined")])
    assert actual["counts"]["proposal_runs"] == actual["counts"]["insufficient_runs"] == 1
    assert actual["ratios"]["handled_proposals"] == 1
    assert actual["ratios"]["confirmation_basis_points"] == 0


@pytest.mark.parametrize("status", ["debouncing", "queued", "running", "waiting_input"])
def test_all_current_nonterminal_statuses_remain_in_pending_denominator(status: str) -> None:
    actual = aggregate([item(1, status=status, result_id=None, disposition=None)])
    assert actual["counts"]["pending_runs"] == actual["counts"]["total_runs"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"disposition": "invented"},
        {"status": "invented"},
        {"binding_kind": "qualified"},
        {"review_state": "approved"},
        {"application_kind": "applied"},
        {"same_source_applied": "false"},
        {"withdrawn": 1},
        {"human_edited": "true"},
        {"result_id": None},
        {"disposition": None},
        {"status": "failed"},
        {"status": "running"},
        {"result_id": None, "disposition": None, "review_state": "declined"},
        {"application_kind": "reused"},
        {"application_kind": "created", "review_state": "declined"},
        {"application_kind": "created", "same_source_applied": True},
        {"withdrawn": True},
        {"human_edited": True},
        {"disposition": "reuse_issue", "application_kind": "reused", "human_edited": True},
        {"application_kind": "created", "withdrawn": True, "human_edited": True},
        {"disposition": "insufficient_evidence", "application_kind": "created"},
    ],
)
def test_invalid_or_contradictory_facts_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        aggregate([item(1, **changes)])


def test_duplicate_run_ids_are_rejected_even_with_equivalent_uuid_representations() -> None:
    with pytest.raises(ValueError, match="同一运行"):
        aggregate([item(1), item(1, run_id=UUID(int=1))])
