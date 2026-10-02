"""Issue-specific preregistration choices; no implicit qualification or rollout."""

from datetime import timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.common_objects import Contract, Digest, Key, Positive, Text


class IssueTrialChoices(Contract):
    minimum_handled_runs: Positive
    minimum_followup_seconds: Positive
    sampling_basis_points: Annotated[int, Field(strict=True, ge=1, le=10000)]
    confirmation_basis: Literal["ever_confirmed", "retained_original"]
    recovery_protocol_version: Key
    recovery_conditions: Text


class RegisterIssueTrial(Contract):
    request_id: UUID
    preparation_digest: Digest
    binding: IssueEvaluationBinding
    window_start: AwareDatetime
    window_end: AwareDatetime
    evidence_kind: Literal["real_business", "controlled_replay", "synthetic"]
    configuration: IssueTrialChoices
    reason: Text

    @model_validator(mode="after")
    def fixed_window(self) -> Self:
        if not timedelta(0) < self.window_end - self.window_start <= timedelta(days=366):
            raise ValueError("请选择不超过366天的完整试运行窗口")
        return self
