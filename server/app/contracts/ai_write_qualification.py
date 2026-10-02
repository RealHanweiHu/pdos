"""DC11 meeting-draft qualification candidates, never execution authority.

Pure validation/calculation over supplied receipts. A trusted service must verify
receipt existence, provenance, scope, completeness and immutability before
publishing any qualification; a caller's evidence labels are not proof. No model,
database, clock, registry changes or automatic recovery happen in this module.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Positive, Text

DraftOperation = Literal[
    "meeting.minutes.draft", "meeting.actions.draft", "meeting.decisions.draft"
]
TrialEvidenceKind = Literal["real_business", "controlled_replay", "synthetic"]
EvaluationExecutionSource = Literal["live_model_evaluation", "offline_replay", "synthetic_output"]
BundleVersion = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
BasisPoints = Annotated[int, Field(strict=True, ge=0, le=10_000)]


class QualificationBinding(Contract):
    operation_key: DraftOperation
    provider: Key
    model: Text
    # None preserves missing provider metadata; it can never meet the criteria.
    model_version: Text | None
    release_bundle_version: BundleVersion
    # Gateway admission suite pinned by the original context manifest. The
    # independent capability golden suite belongs to EvaluationEvidence's
    # trusted golden publication, not to this runtime-target identity.
    suite_version: Key
    suite_digest: Digest
    adapter_version: Key
    policy_version: Key
    policy_revision: Positive


class QualificationConfiguration(Contract):
    """Unapproved numeric choices have no defaults; missing configuration fails closed.

    Both ratios use handled original drafts (confirmed OR withdrawn), not action
    count. Confirmation's numerator is an explicit policy choice. Recovery is a
    required versioned protocol reference, not an automatic transition here.
    """

    version: Literal["dc11-meeting-qualification-configuration.v1"] = (
        "dc11-meeting-qualification-configuration.v1"
    )
    configuration_id: UUID
    configuration_digest: Digest
    fixed_at: AwareDatetime
    minimum_handled_drafts: Positive
    cohort_window_seconds: Positive
    minimum_followup_seconds: Positive
    sampling_basis_points: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    confirmation_basis: Literal["ever_confirmed", "retained_original"]
    recovery_protocol_version: Key
    recovery_conditions: Text
    minimum_confirmation_basis_points: Annotated[int, Field(strict=True, ge=9000, le=10_000)] = 9000
    maximum_retraction_basis_points: Annotated[int, Field(strict=True, ge=0, le=500)] = 500


class EvaluationEvidence(Contract):
    """Execution provenance is distinct from the golden cases' business origin.

    A live model may evaluate controlled golden cases. The trusted publisher must
    verify the original call/report and the referenced frozen suite publication;
    supplying references or a live label alone never publishes a qualification.
    """

    evaluation_id: UUID
    execution_source: EvaluationExecutionSource
    evidence_ref: Text
    receipt_digest: Digest
    golden_publication_ref: Text
    golden_publication_digest: Digest
    binding: QualificationBinding
    real_provider_call: bool = Field(strict=True)
    completed_at: AwareDatetime
    outcome: Literal["passed", "failed", "incomplete"]


class DraftTrialEvidence(Contract):
    """A single original draft's first occurrence of each action, at cohort cutoff."""

    draft_id: UUID
    tenant_id: UUID
    project_id: UUID
    run_id: UUID
    model_invocation_id: UUID
    context_observation_id: UUID
    receipt_digest: Digest
    evidence_kind: TrialEvidenceKind
    real_provider_call: bool = Field(strict=True)
    binding: QualificationBinding
    created_at: AwareDatetime
    confirmed_at: AwareDatetime | None
    edited_at: AwareDatetime | None
    withdrawn_at: AwareDatetime | None

    @model_validator(mode="after")
    def action_order(self) -> Self:
        for stamp in (self.confirmed_at, self.edited_at, self.withdrawn_at):
            if stamp is not None and stamp < self.created_at:
                raise ValueError("draft_action_precedes_creation")
        if self.edited_at is not None and (
            self.confirmed_at is None or self.edited_at < self.confirmed_at
        ):
            raise ValueError("draft_edit_requires_prior_confirmation")
        if self.withdrawn_at is not None and any(
            stamp is not None and stamp > self.withdrawn_at
            for stamp in (self.confirmed_at, self.edited_at)
        ):
            raise ValueError("withdrawn_draft_cannot_be_handled_again")
        return self


class TrialCohort(Contract):
    cohort_id: UUID
    tenant_id: UUID
    evidence_ref: Text
    receipt_digest: Digest
    window_start: AwareDatetime
    window_end: AwareDatetime
    as_of: AwareDatetime
    # A trusted collector must prove this flag from the frozen selection query.
    selection_complete: bool = Field(strict=True)
    drafts: tuple[DraftTrialEvidence, ...]

    @field_validator("drafts")
    @classmethod
    def original_drafts(
        cls, values: tuple[DraftTrialEvidence, ...]
    ) -> tuple[DraftTrialEvidence, ...]:
        unique: dict[UUID, DraftTrialEvidence] = {}
        for draft in values:
            if draft.draft_id in unique and unique[draft.draft_id] != draft:
                raise ValueError("conflicting_original_draft_receipts")
            unique[draft.draft_id] = draft
        return tuple(unique[key] for key in sorted(unique, key=str))

    @model_validator(mode="after")
    def fixed_window(self) -> Self:
        if not self.window_start < self.window_end <= self.as_of:
            raise ValueError("cohort_requires_closed_observation_cutoff")
        for draft in self.drafts:
            if draft.tenant_id != self.tenant_id:
                raise ValueError("cohort_tenant_mismatch")
            if not self.window_start <= draft.created_at < self.window_end:
                raise ValueError("draft_outside_fixed_cohort")
            if any(
                stamp is not None and stamp > self.as_of
                for stamp in (draft.confirmed_at, draft.edited_at, draft.withdrawn_at)
            ):
                raise ValueError("action_after_observation_cutoff")
        return self


class QualificationInput(Contract):
    version: Literal["dc11-meeting-qualification-input.v1"] = "dc11-meeting-qualification-input.v1"
    tenant_id: UUID
    binding: QualificationBinding
    configuration: QualificationConfiguration | None
    evaluation: EvaluationEvidence | None
    cohort: TrialCohort | None
    as_of: AwareDatetime

    @model_validator(mode="after")
    def scope_and_cutoff(self) -> Self:
        if self.cohort is not None:
            if self.cohort.tenant_id != self.tenant_id:
                raise ValueError("qualification_tenant_mismatch")
            if self.cohort.as_of != self.as_of:
                raise ValueError("qualification_cutoff_mismatch")
        if self.evaluation is not None and self.evaluation.completed_at > self.as_of:
            raise ValueError("evaluation_after_observation_cutoff")
        return self


class TrialCounts(Contract):
    generated: Nonnegative
    confirmed: Nonnegative
    edited: Nonnegative
    withdrawn: Nonnegative
    handled: Nonnegative
    pending: Nonnegative
    retained_original: Nonnegative
    withdrawn_after_confirmation: Nonnegative


class QualificationResult(Contract):
    version: Literal["dc11-meeting-qualification-result.v1"] = (
        "dc11-meeting-qualification-result.v1"
    )
    input_digest: Digest
    binding: QualificationBinding
    as_of: AwareDatetime
    status: Literal["meets_candidate_criteria", "insufficient_evidence", "does_not_meet_criteria"]
    reasons: tuple[str, ...]
    counts: TrialCounts
    confirmation_numerator: Nonnegative | None
    ratio_denominator: Nonnegative
    confirmation_basis_points: BasisPoints | None
    retraction_basis_points: BasisPoints | None
    # Even a passing calculation is not a trusted published qualification.
    qualification_granted: Literal[False] = False


def evaluate_qualification(candidate: QualificationInput) -> QualificationResult:
    """Deterministic arithmetic only; no receipt label is promoted to authority."""
    config, evaluation, cohort = candidate.configuration, candidate.evaluation, candidate.cohort
    drafts = cohort.drafts if cohort is not None else ()
    confirmed = sum(d.confirmed_at is not None for d in drafts)
    withdrawn = sum(d.withdrawn_at is not None for d in drafts)
    handled = sum(d.confirmed_at is not None or d.withdrawn_at is not None for d in drafts)
    retained = sum(
        d.confirmed_at is not None and d.edited_at is None and d.withdrawn_at is None
        for d in drafts
    )
    counts = TrialCounts(
        generated=len(drafts),
        confirmed=confirmed,
        edited=sum(d.edited_at is not None for d in drafts),
        withdrawn=withdrawn,
        handled=handled,
        pending=len(drafts) - handled,
        retained_original=retained,
        withdrawn_after_confirmation=sum(
            d.confirmed_at is not None and d.withdrawn_at is not None for d in drafts
        ),
    )
    missing: set[str] = set()
    failed: set[str] = set()
    if candidate.binding.model_version is None or candidate.binding.model_version.casefold() in {
        "unknown",
        "unspecified",
        "unavailable",
        "latest",
        "未知",
        "未登记",
    }:
        missing.add("model_version_unknown")
    if config is None:
        missing.add("configuration_missing")
    if evaluation is None:
        missing.add("evaluation_missing")
    else:
        if evaluation.binding != candidate.binding:
            failed.add("evaluation_binding_mismatch")
        if (
            evaluation.execution_source != "live_model_evaluation"
            or not evaluation.real_provider_call
        ):
            failed.add("evaluation_not_real_evidence")
        if evaluation.outcome == "incomplete":
            missing.add("evaluation_incomplete")
        elif evaluation.outcome == "failed":
            failed.add("evaluation_failed")
    if cohort is None:
        missing.add("cohort_missing")
    else:
        if not cohort.selection_complete:
            missing.add("cohort_selection_incomplete")
        if any(d.binding != candidate.binding for d in drafts):
            failed.add("trial_binding_mismatch")
        if any(d.evidence_kind != "real_business" or not d.real_provider_call for d in drafts):
            failed.add("trial_not_real_evidence")
        if config is not None:
            if config.fixed_at > cohort.window_start:
                failed.add("configuration_not_fixed_before_cohort")
            window_us = (cohort.window_end - cohort.window_start) // timedelta(microseconds=1)
            if window_us != config.cohort_window_seconds * 1_000_000:
                failed.add("cohort_window_mismatch")
            followup_us = (cohort.as_of - cohort.window_end) // timedelta(microseconds=1)
            if followup_us < config.minimum_followup_seconds * 1_000_000:
                missing.add("followup_window_incomplete")
    numerator = None
    if config is not None:
        numerator = confirmed if config.confirmation_basis == "ever_confirmed" else retained
        if handled < config.minimum_handled_drafts:
            missing.add("minimum_handled_drafts_not_met")
        # Cross multiplication prevents rounded display values from granting a pass.
        if handled:
            if numerator * 10_000 < handled * config.minimum_confirmation_basis_points:
                failed.add("confirmation_below_threshold")
            if withdrawn * 10_000 > handled * config.maximum_retraction_basis_points:
                failed.add("retraction_above_threshold")
    if not handled:
        missing.add("handled_denominator_empty")
    return QualificationResult(
        input_digest=sha256(candidate.model_dump_json().encode()).hexdigest(),
        binding=candidate.binding,
        as_of=candidate.as_of,
        status="does_not_meet_criteria"
        if failed
        else "insufficient_evidence"
        if missing
        else "meets_candidate_criteria",
        reasons=tuple(sorted(missing | failed)),
        counts=counts,
        confirmation_numerator=numerator,
        ratio_denominator=handled,
        confirmation_basis_points=numerator * 10_000 // handled
        if numerator is not None and handled
        else None,
        retraction_basis_points=withdrawn * 10_000 // handled if handled else None,
    )
