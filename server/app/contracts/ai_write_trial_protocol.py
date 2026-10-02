"""Frozen trial registration shapes; publication and evidence trust remain service duties."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.contracts.ai_write_qualification import (
    QualificationBinding,
    QualificationConfiguration,
    TrialEvidenceKind,
)
from app.contracts.common_objects import Contract, Digest, Key, Positive, Text


class TrialConfigurationChoices(Contract):
    """Human choices only; identity, fixation time and policy thresholds are server-owned."""

    minimum_handled_drafts: Positive
    cohort_window_seconds: Positive
    minimum_followup_seconds: Positive
    sampling_basis_points: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    confirmation_basis: Literal["ever_confirmed", "retained_original"]
    recovery_protocol_version: Key
    recovery_conditions: Text


class RegisterTrial(Contract):
    request_id: UUID
    # Optional for existing declared protocols; preparation UI always supplies
    # the server candidate digest and registration rechecks its current source.
    preparation_digest: Digest | None = None
    project_ids: tuple[UUID, ...]
    binding: QualificationBinding
    evidence_kind: TrialEvidenceKind
    window_start: AwareDatetime
    window_end: AwareDatetime
    configuration: TrialConfigurationChoices
    reason: Text

    @field_validator("project_ids")
    @classmethod
    def unique_projects(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        result = tuple(sorted(set(values), key=str))
        if not 1 <= len(result) <= 100:
            raise ValueError("trial_requires_one_to_100_unique_projects")
        return result

    @model_validator(mode="after")
    def fixed_window(self) -> Self:
        if (self.window_end - self.window_start) // timedelta(microseconds=1) != (
            self.configuration.cohort_window_seconds * 1_000_000
        ):
            raise ValueError("trial_window_must_match_configuration")
        return self


class TrialProtocol(Contract):
    id: UUID
    tenant_id: UUID
    policy_id: UUID
    actor_user_id: UUID
    project_ids: tuple[UUID, ...]
    binding: QualificationBinding
    evidence_kind: TrialEvidenceKind
    window_start: AwareDatetime
    window_end: AwareDatetime
    configuration: QualificationConfiguration
    reason: Text
    created_at: AwareDatetime
    protocol_digest: Digest

    @field_validator("project_ids")
    @classmethod
    def unique_projects(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return RegisterTrial.unique_projects(values)

    @model_validator(mode="after")
    def frozen_protocol(self) -> Self:
        if (self.window_end - self.window_start) // timedelta(microseconds=1) != (
            self.configuration.cohort_window_seconds * 1_000_000
        ):
            raise ValueError("trial_window_must_match_configuration")
        if self.configuration.fixed_at != self.created_at:
            raise ValueError("trial_configuration_must_be_fixed_at_registration")
        if self.evidence_kind == "real_business" and self.window_start <= self.created_at:
            raise ValueError("real_business_trial_requires_preregistration")
        return self


class CollectTrial(Contract):
    request_id: UUID
    # The service supplies its clock when absent and rejects future cutoffs.
    as_of: AwareDatetime | None = None
