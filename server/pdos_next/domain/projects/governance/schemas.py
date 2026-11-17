from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.core.schema_base import StrictModel


class Ref(StrictModel):
    id: UUID
    revision: int = Field(ge=1, strict=True)


class Payload(StrictModel):
    project_id: UUID
    expected_project_revision: int = Field(ge=1, strict=True)
    expected_governance_revision: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class AdoptPayload(Payload):
    template: Literal["standard@1", "derivative@1", "small-change@1", "framework"]
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class BaselinePayload(Payload):
    plan: Ref
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)


class ReviewPayload(Payload):
    stage_id: UUID
    release_package: Ref | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class MilestonePayload(Payload):
    stage_id: UUID
    task_key: str = Field(min_length=1, max_length=80)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class FollowUp(StrictModel):
    task: Ref
    owner_id: UUID
    due_date: date


class DecidePayload(Payload):
    review: Ref
    outcome: Literal["approved", "returned"]
    follow_ups: tuple[FollowUp, ...] = Field(default=(), max_length=30)
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def approved_follow_ups(self):
        if self.follow_ups and self.outcome != "approved":
            raise ValueError("Follow-up work belongs to an approved stage decision")
        if len({item.task.id for item in self.follow_ups}) != len(self.follow_ups):
            raise ValueError("A stage follow-up task may occur only once")
        return self


OPERATIONS = {
    "work.stage.milestone.bind": (MilestonePayload, "T1", "stage.milestone_bound"),
    "work.stage.adopt": (AdoptPayload, "T1", "stage.adopted"),
    "work.baseline.approve": (BaselinePayload, "T2", "baseline.approved"),
    "work.stage.review.submit": (ReviewPayload, "T1", "stage.review_submitted"),
    "work.stage.decide": (DecidePayload, "T2", "stage.decided"),
}
