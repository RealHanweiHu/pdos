from typing import Literal
from uuid import UUID

from pydantic import Field

from pdos_next.schema_base import StrictModel


class Ref(StrictModel):
    id: UUID
    revision: int = Field(ge=1, strict=True)


class Payload(StrictModel):
    project_id: UUID
    expected_project_revision: int = Field(ge=1, strict=True)
    expected_governance_revision: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class AdoptPayload(Payload):
    template: Literal["standard@1", "derivative@1", "small-change@1"]
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


class DecidePayload(Payload):
    review: Ref
    outcome: Literal["approved", "returned"]
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)


OPERATIONS = {
    "work.stage.milestone.bind": (MilestonePayload, "T1", "stage.milestone_bound"),
    "work.stage.adopt": (AdoptPayload, "T1", "stage.adopted"),
    "work.baseline.approve": (BaselinePayload, "T2", "baseline.approved"),
    "work.stage.review.submit": (ReviewPayload, "T1", "stage.review_submitted"),
    "work.stage.decide": (DecidePayload, "T2", "stage.decided"),
}
