"""Source facts, explicit physical location and separately recorded responses."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.work_management.schemas import DTO, SourceRef, Text, VersionRef

CREATE = "field.feedback.create"
LOCATE = "field.feedback.locate"
ACTION = "field.feedback.action.record"
LINK = "field.feedback.followup.link"


class Evidence(DTO):
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    reason: Text

    @field_validator("sources")
    @classmethod
    def originals(cls, values):
        if any(value.kind != "artifact" for value in values):
            raise ValueError("Field facts require exact original artifact references")
        return values


class ReportedIdentity(DTO):
    product_label: Text | None = None
    batch_label: Text | None = None
    configuration_label: Text | None = None


class CreatePayload(Evidence):
    visibility: Literal["private", "category"] = "private"
    title: str = Field(min_length=1, max_length=200)
    description: Text
    channel: Literal["field", "customer"]
    feedback_kind: Literal[
        "observation",
        "opinion",
        "change_request",
        "conditional_acceptance",
        "formal_acceptance_claim",
    ]
    received_at: AwareDatetime
    reported: ReportedIdentity
    purpose: str = Field(min_length=1, max_length=2000)


class Confirmed(Evidence):
    feedback: VersionRef
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class LocatePayload(Confirmed):
    project_id: UUID | None = None
    engineering_configuration: VersionRef
    manufacturing_configuration: VersionRef | None = None
    batch: VersionRef | None = None


class ActionPayload(Confirmed):
    action_kind: Literal["containment", "improvement"]
    description: Text
    occurred_at: AwareDatetime
    visibility: Literal["private", "category"] = "private"


class ResultRef(DTO):
    receipt_id: UUID


class FollowupPayload(Confirmed):
    description: Text
    occurred_at: AwareDatetime
    visibility: Literal["private", "category"] = "private"
    result_receipts: tuple[ResultRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def distinct(self):
        if len({value.receipt_id for value in self.result_receipts}) != len(self.result_receipts):
            raise ValueError("Fixed result receipts cannot repeat")
        return self


PAYLOADS = {
    CREATE: CreatePayload,
    LOCATE: LocatePayload,
    ACTION: ActionPayload,
    LINK: FollowupPayload,
}


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})
