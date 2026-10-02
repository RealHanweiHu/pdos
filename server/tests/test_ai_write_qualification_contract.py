from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.contracts.ai_write_qualification import (
    DraftTrialEvidence,
    EvaluationEvidence,
    QualificationBinding,
    QualificationConfiguration,
    QualificationInput,
    TrialCohort,
    evaluate_qualification,
)

START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=1)
CUTOFF = END + timedelta(hours=1)
TENANT = UUID(int=1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("qualification contract tests must not access a database or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def binding(**changes: Any) -> QualificationBinding:
    return QualificationBinding.model_validate(
        {
            "operation_key": "meeting.minutes.draft",
            "provider": "openai",
            "model": "fixture-model",
            "model_version": "fixture-model-revision-1",
            "release_bundle_version": "sha256:" + "a" * 64,
            "suite_version": "meeting-minutes-test.v1",
            "suite_digest": "b" * 64,
            "adapter_version": "meeting-minutes-adapter.v1",
            "policy_version": "dc11-write-policy.v1",
            "policy_revision": 1,
            **changes,
        }
    )


def configuration(**changes: Any) -> QualificationConfiguration:
    # Arbitrary test-only settings; this fixture is not a published protocol.
    return QualificationConfiguration.model_validate(
        {
            "configuration_id": UUID(int=2),
            "configuration_digest": "c" * 64,
            "fixed_at": START - timedelta(days=1),
            "minimum_handled_drafts": 20,
            "cohort_window_seconds": 86400,
            "minimum_followup_seconds": 3600,
            "sampling_basis_points": 1000,
            "confirmation_basis": "retained_original",
            "recovery_protocol_version": "test-only-recovery.v1",
            "recovery_conditions": "Fixture only: new trial and evaluation before separate review.",
            **changes,
        }
    )


def draft(index: int, **changes: Any) -> DraftTrialEvidence:
    return DraftTrialEvidence.model_validate(
        {
            "draft_id": UUID(int=100 + index),
            "tenant_id": TENANT,
            "project_id": UUID(int=3),
            "run_id": UUID(int=10000 + index),
            "model_invocation_id": UUID(int=20000 + index),
            "context_observation_id": UUID(int=30000 + index),
            "receipt_digest": "d" * 64,
            # These are contract arithmetic fixtures, never published evidence.
            "evidence_kind": "real_business",
            "real_provider_call": True,
            "binding": binding(),
            "created_at": START + timedelta(seconds=index),
            "confirmed_at": END,
            "edited_at": None,
            "withdrawn_at": None,
            **changes,
        }
    )


def cohort(drafts: tuple[DraftTrialEvidence, ...] | None = None, **changes: Any) -> TrialCohort:
    return TrialCohort.model_validate(
        {
            "cohort_id": UUID(int=4),
            "tenant_id": TENANT,
            "evidence_ref": "fixture://cohort",
            "receipt_digest": "e" * 64,
            "window_start": START,
            "window_end": END,
            "as_of": CUTOFF,
            "selection_complete": True,
            "drafts": tuple(draft(i) for i in range(20)) if drafts is None else drafts,
            **changes,
        }
    )


def evaluation(**changes: Any) -> EvaluationEvidence:
    return EvaluationEvidence.model_validate(
        {
            "evaluation_id": UUID(int=5),
            "execution_source": "live_model_evaluation",
            "evidence_ref": "fixture://evaluation",
            "receipt_digest": "f" * 64,
            "golden_publication_ref": "fixture://controlled-golden-publication.v1",
            "golden_publication_digest": "a" * 64,
            "binding": binding(),
            "real_provider_call": True,
            "completed_at": START,
            "outcome": "passed",
            **changes,
        }
    )


def candidate(**changes: Any) -> QualificationInput:
    return QualificationInput.model_validate(
        {
            "tenant_id": TENANT,
            "binding": binding(),
            "configuration": configuration(),
            "evaluation": evaluation(),
            "cohort": cohort(),
            "as_of": CUTOFF,
            **changes,
        }
    )


def test_candidate_calculation_never_grants_authority_and_round_trips() -> None:
    original = candidate()
    restored = QualificationInput.model_validate_json(original.model_dump_json())
    result = evaluate_qualification(restored)
    assert result == evaluate_qualification(original)
    assert result.status == "meets_candidate_criteria"
    assert result.reasons == ()
    assert result.qualification_granted is False
    assert result.confirmation_basis_points == 10000
    assert result.retraction_basis_points == 0
    assert result.counts.generated == result.counts.handled == 20


def test_fixed_cohort_deduplicates_original_drafts_and_normalizes_order() -> None:
    originals = tuple(draft(i) for i in range(20))
    duplicate_input = candidate(cohort=cohort(tuple(reversed(originals)) + originals))
    assert evaluate_qualification(duplicate_input) == evaluate_qualification(candidate())
    with pytest.raises(ValidationError, match="conflicting_original_draft_receipts"):
        cohort((draft(0), draft(0, edited_at=END)))


def test_exact_thresholds_with_pending_and_modified_drafts() -> None:
    drafts = (
        draft(0, withdrawn_at=CUTOFF),
        draft(1, edited_at=END),
        *(draft(i) for i in range(2, 20)),
        draft(20, confirmed_at=None),
    )
    result = evaluate_qualification(candidate(cohort=cohort(drafts)))
    assert result.status == "meets_candidate_criteria"
    assert result.counts.model_dump() == {
        "generated": 21,
        "confirmed": 20,
        "edited": 1,
        "withdrawn": 1,
        "handled": 20,
        "pending": 1,
        "retained_original": 18,
        "withdrawn_after_confirmation": 1,
    }
    assert result.confirmation_numerator == 18
    assert result.ratio_denominator == 20
    assert result.confirmation_basis_points == 9000
    assert result.retraction_basis_points == 500
    ever = evaluate_qualification(
        candidate(
            cohort=cohort(drafts), configuration=configuration(confirmation_basis="ever_confirmed")
        )
    )
    assert ever.confirmation_numerator == 20


def test_withdrawn_without_confirmation_is_handled_but_not_confirmed() -> None:
    result = evaluate_qualification(
        candidate(cohort=cohort((draft(0, confirmed_at=None, withdrawn_at=CUTOFF),)))
    )
    assert result.counts.handled == result.counts.withdrawn == 1
    assert result.counts.confirmed == result.counts.withdrawn_after_confirmation == 0
    assert "confirmation_below_threshold" in result.reasons
    assert "retraction_above_threshold" in result.reasons


def test_fractional_retraction_rate_cannot_round_into_passing() -> None:
    # 1/199 = 50.251... bp, displayed as 50, but a configured 50 bp ceiling fails.
    drafts = tuple(draft(i, withdrawn_at=CUTOFF if i == 0 else None) for i in range(199))
    result = evaluate_qualification(
        candidate(
            cohort=cohort(drafts), configuration=configuration(maximum_retraction_basis_points=50)
        )
    )
    assert result.retraction_basis_points == 50
    assert "retraction_above_threshold" in result.reasons


@pytest.mark.parametrize("kind", ["controlled_replay", "synthetic"])
def test_non_real_trial_evidence_cannot_meet_criteria(kind: str) -> None:
    inputs = candidate(cohort=cohort((draft(0, evidence_kind=kind),)))
    result = evaluate_qualification(inputs)
    assert result.status == "does_not_meet_criteria"
    assert "trial_not_real_evidence" in result.reasons


@pytest.mark.parametrize("source", ["offline_replay", "synthetic_output"])
def test_non_live_evaluation_cannot_pass_even_with_provider_flag(source: str) -> None:
    result = evaluate_qualification(candidate(evaluation=evaluation(execution_source=source)))
    assert result.status == "does_not_meet_criteria"
    assert "evaluation_not_real_evidence" in result.reasons


def test_live_model_controlled_golden_is_valid_candidate_evaluation() -> None:
    inputs = candidate(evaluation=evaluation())
    assert inputs.evaluation is not None
    assert inputs.evaluation.execution_source == "live_model_evaluation"
    assert "controlled-golden" in inputs.evaluation.golden_publication_ref
    result = evaluate_qualification(inputs)
    assert result.status == "meets_candidate_criteria"
    assert result.qualification_granted is False


@pytest.mark.parametrize("source", ["real_business", "controlled_replay", "synthetic"])
def test_trial_origin_cannot_be_used_as_evaluation_execution_source(source: str) -> None:
    with pytest.raises(ValidationError):
        evaluation(execution_source=source)
    with pytest.raises(ValidationError):
        evaluation(evidence_kind=source)


@pytest.mark.parametrize("source", ["live_model_evaluation", "offline_replay", "synthetic_output"])
def test_evaluation_execution_source_cannot_substitute_for_trial_origin(source: str) -> None:
    with pytest.raises(ValidationError):
        draft(0, evidence_kind=source)


@pytest.mark.parametrize(
    "field",
    ["execution_source", "golden_publication_ref", "golden_publication_digest", "receipt_digest"],
)
def test_evaluation_requires_original_receipt_and_frozen_golden_publication(field: str) -> None:
    document = evaluation().model_dump()
    del document[field]
    with pytest.raises(ValidationError):
        EvaluationEvidence.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [("golden_publication_ref", " "), ("golden_publication_digest", "unknown")],
)
def test_golden_publication_reference_and_digest_must_be_present(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        evaluation(**{field: value})


@pytest.mark.parametrize("location", ["trial", "evaluation"])
def test_real_label_without_provider_call_is_insufficient(location: str) -> None:
    inputs = (
        candidate(cohort=cohort((draft(0, real_provider_call=False),)))
        if location == "trial"
        else candidate(evaluation=evaluation(real_provider_call=False))
    )
    assert f"{location}_not_real_evidence" in evaluate_qualification(inputs).reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation_key", "meeting.actions.draft"),
        ("provider", "minimax"),
        ("model", "another-model"),
        ("model_version", "another-revision"),
        ("release_bundle_version", "sha256:" + "b" * 64),
        ("suite_version", "another-suite.v2"),
        ("suite_digest", "c" * 64),
        ("adapter_version", "another-adapter.v2"),
        ("policy_version", "another-policy.v2"),
        ("policy_revision", 2),
    ],
)
@pytest.mark.parametrize("location", ["trial", "evaluation"])
def test_every_binding_dimension_is_enforced(field: str, value: Any, location: str) -> None:
    changed = binding(**{field: value})
    inputs = (
        candidate(cohort=cohort((draft(0, binding=changed),)))
        if location == "trial"
        else candidate(evaluation=evaluation(binding=changed))
    )
    assert f"{location}_binding_mismatch" in evaluate_qualification(inputs).reasons


@pytest.mark.parametrize("version", [None, "unknown", "UNKNOWN", "latest", "未知", "未登记"])
def test_unknown_model_even_if_all_receipts_match_cannot_pass(version: str | None) -> None:
    unknown = binding(model_version=version)
    inputs = candidate(
        binding=unknown,
        evaluation=evaluation(binding=unknown),
        cohort=cohort(tuple(draft(i, binding=unknown) for i in range(20))),
    )
    result = evaluate_qualification(inputs)
    assert result.status == "insufficient_evidence"
    assert result.reasons == ("model_version_unknown",)


@pytest.mark.parametrize("field", ["configuration", "evaluation", "cohort"])
def test_missing_evidence_or_configuration_never_passes(field: str) -> None:
    result = evaluate_qualification(candidate(**{field: None}))
    assert result.status == "insufficient_evidence"
    assert f"{field}_missing" in result.reasons


def test_empty_or_pending_cohort_has_no_rate_and_no_zero_filled_pass() -> None:
    for drafts in ((), (draft(0, confirmed_at=None),)):
        result = evaluate_qualification(candidate(cohort=cohort(drafts)))
        assert result.status == "insufficient_evidence"
        assert result.confirmation_basis_points is None
        assert result.retraction_basis_points is None
        assert "handled_denominator_empty" in result.reasons


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"selection_complete": False}, "cohort_selection_incomplete"),
        ({"window_start": START - timedelta(seconds=1)}, "cohort_window_mismatch"),
    ],
)
def test_incomplete_or_different_selection_cannot_pass(
    changes: dict[str, Any], reason: str
) -> None:
    assert reason in evaluate_qualification(candidate(cohort=cohort(**changes))).reasons


def test_fixed_configuration_and_followup_must_precede_decision() -> None:
    result = evaluate_qualification(
        candidate(configuration=configuration(fixed_at=START + timedelta(seconds=1)))
    )
    assert "configuration_not_fixed_before_cohort" in result.reasons
    result = evaluate_qualification(
        candidate(configuration=configuration(minimum_followup_seconds=3601))
    )
    assert "followup_window_incomplete" in result.reasons


def test_small_sample_and_subsecond_shortfall_are_not_rounded_up() -> None:
    result = evaluate_qualification(candidate(cohort=cohort(tuple(draft(i) for i in range(19)))))
    assert result.status == "insufficient_evidence"
    assert result.reasons == ("minimum_handled_drafts_not_met",)
    cutoff = CUTOFF - timedelta(microseconds=1)
    result = evaluate_qualification(candidate(cohort=cohort(as_of=cutoff), as_of=cutoff))
    assert result.reasons == ("followup_window_incomplete",)


def test_large_configured_windows_fail_without_overflow() -> None:
    result = evaluate_qualification(
        candidate(
            configuration=configuration(
                cohort_window_seconds=10**30, minimum_followup_seconds=10**30
            )
        )
    )
    assert "cohort_window_mismatch" in result.reasons
    assert "followup_window_incomplete" in result.reasons


@pytest.mark.parametrize("outcome", ["failed", "incomplete"])
def test_evaluation_must_pass(outcome: str) -> None:
    result = evaluate_qualification(candidate(evaluation=evaluation(outcome=outcome)))
    assert f"evaluation_{outcome}" in result.reasons
    assert result.status != "meets_candidate_criteria"


@pytest.mark.parametrize(
    "field",
    [
        "minimum_handled_drafts",
        "cohort_window_seconds",
        "minimum_followup_seconds",
        "sampling_basis_points",
        "confirmation_basis",
        "recovery_protocol_version",
        "recovery_conditions",
    ],
)
def test_unfixed_policy_choices_have_no_defaults(field: str) -> None:
    document = configuration().model_dump()
    del document[field]
    with pytest.raises(ValidationError):
        QualificationConfiguration.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_confirmation_basis_points", 8999),
        ("maximum_retraction_basis_points", 501),
        ("minimum_handled_drafts", 0),
        ("minimum_handled_drafts", True),
        ("cohort_window_seconds", 0),
        ("minimum_followup_seconds", 0),
        ("sampling_basis_points", 0),
        ("sampling_basis_points", 10001),
        ("recovery_conditions", " "),
    ],
)
def test_policy_cannot_weaken_frozen_bounds_or_use_invalid_values(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        configuration(**{field: value})


@pytest.mark.parametrize(
    "operation", ["formal_action.execute", "event.issue.create", "test_report.rows.confirm"]
)
def test_contract_cannot_expand_to_t2_or_other_operations(operation: str) -> None:
    with pytest.raises(ValidationError):
        binding(operation_key=operation)


@pytest.mark.parametrize("operation", ["meeting.actions.draft", "meeting.decisions.draft"])
def test_other_two_draft_operations_use_same_bound_calculation(operation: str) -> None:
    identity = binding(operation_key=operation)
    inputs = candidate(
        binding=identity,
        evaluation=evaluation(binding=identity),
        cohort=cohort(tuple(draft(i, binding=identity) for i in range(20))),
    )
    assert evaluate_qualification(inputs).status == "meets_candidate_criteria"


def test_cutoff_scope_and_temporal_shape_are_strict() -> None:
    with pytest.raises(ValidationError, match="cohort_tenant_mismatch"):
        cohort((draft(0, tenant_id=UUID(int=999)),))
    with pytest.raises(ValidationError, match="qualification_tenant_mismatch"):
        candidate(tenant_id=UUID(int=999))
    with pytest.raises(ValidationError, match="qualification_cutoff_mismatch"):
        candidate(as_of=CUTOFF + timedelta(seconds=1))
    with pytest.raises(ValidationError, match="action_after_observation_cutoff"):
        cohort((draft(0, confirmed_at=CUTOFF + timedelta(seconds=1)),))
    with pytest.raises(ValidationError, match="draft_outside_fixed_cohort"):
        cohort((draft(0, created_at=END),))
    with pytest.raises(ValidationError, match="evaluation_after_observation_cutoff"):
        candidate(evaluation=evaluation(completed_at=CUTOFF + timedelta(seconds=1)))
    with pytest.raises(ValidationError, match="draft_edit_requires_prior_confirmation"):
        draft(0, confirmed_at=None, edited_at=END)
    with pytest.raises(ValidationError, match="draft_action_precedes_creation"):
        draft(0, confirmed_at=START - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="withdrawn_draft_cannot_be_handled_again"):
        draft(0, withdrawn_at=START, confirmed_at=END)


def test_unknown_fields_and_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        candidate(qualification_granted=True)
    with pytest.raises(ValidationError):
        candidate(as_of=CUTOFF.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        binding(release_bundle_version="latest")
