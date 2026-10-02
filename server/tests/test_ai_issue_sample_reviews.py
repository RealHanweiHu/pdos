"""Pure request and sampling contract checks; actual chain is tested separately."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.ai_issue_sample_reviews import SampleReviewRequest, _sampled


def request(**changes: Any) -> dict[str, Any]:
    return dict(
        request_id=str(UUID(int=1)),
        expected_digest="a" * 64,
        verdict="accepted",
        reason="具名核对原问题",
        **changes,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "  "},
        {"verdict": "publish"},
        {"expected_digest": "not-a-digest"},
        {"sampled": True},
        {"actor_user_id": str(UUID(int=2))},
    ],
)
def test_client_cannot_select_sample_or_author_and_must_supply_current_evidence(
    change: dict[str, Any],
) -> None:
    original = request()
    original.update(change)
    with pytest.raises(ValidationError):
        SampleReviewRequest.model_validate(original)


@pytest.mark.parametrize("verdict", ["accepted", "needs_correction"])
def test_named_review_keeps_explicit_verdict_and_reason(verdict: str) -> None:
    original = request()
    original["verdict"] = verdict
    assert SampleReviewRequest.model_validate(original).verdict == verdict


@pytest.mark.parametrize(
    ("mode", "sampled", "expected"),
    [
        ("direct", True, True),
        ("trial", True, False),
        ("direct", False, False),
        ("direct", "true", False),
        ("direct", 1, False),
    ],
)
def test_only_actual_direct_boolean_sample_is_reviewable(
    mode: str, sampled: Any, expected: bool
) -> None:
    assert (
        _sampled(dict(capture_mode=mode, receipt={"write_receipt": {"sampled": sampled}}))
        is expected
    )
    assert _sampled(None) is False
