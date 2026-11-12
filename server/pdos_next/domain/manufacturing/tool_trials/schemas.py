"""Closed T1 tool-trial declarations (P79 D97; P95 第 1–4 项与补充确认; D305).

The first trial registers a lightweight tooling record (part, version, supplier
external id, cavities); later trials reference it and version it when it
changes. The same confirmation creates the verification request from an existing
preparation. Engineering or manufacturing named people initiate; 小Pai prefills.
"""

from typing import Annotated

from pydantic import Field, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Text, VersionRef
from pdos_next.domain.verification.preparation.schemas import RequestCreatePayload

OPERATION = "npi.tooltrial.create"
EVENT = "tooltrial.created"
SUBJECT = "tool_trial"
Short = Annotated[str, Field(min_length=1, max_length=200)]


class ToolingFields(DTO):
    part: Short
    version: Short
    supplier_ref: Short
    cavities: int = Field(ge=1, le=1000, strict=True)


class ToolingNew(ToolingFields):
    # The imported tooling resource of this Build, when the controlled import has one.
    resource: VersionRef | None = None


class ToolingChanges(DTO):
    part: Short | None = None
    version: Short | None = None
    supplier_ref: Short | None = None
    cavities: int | None = Field(default=None, ge=1, le=1000, strict=True)


class ToolingRef(VersionRef):
    changes: ToolingChanges | None = None


class Parameter(DTO):
    name: Short
    value: Short
    unit: Short | None = None


class Trial(DTO):
    round: Short
    purpose: Text
    material_lots: list[Short] = Field(default_factory=list, max_length=50)
    parameters: list[Parameter] = Field(default_factory=list, max_length=100)
    cavities: list[int] = Field(default_factory=list, max_length=1000)
    issues: list[Text] = Field(default_factory=list, max_length=50)
    corrective_actions: list[Text] = Field(default_factory=list, max_length=50)


class Payload(DTO):
    build: VersionRef
    tooling_new: ToolingNew | None = None
    tooling: ToolingRef | None = None
    trial: Trial
    verification: RequestCreatePayload
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def one_tooling(self):
        if (self.tooling_new is None) == (self.tooling is None):
            raise ValueError("首次试模登记模具，之后的试模引用已有模具，二者选一")
        if (
            self.tooling
            and self.tooling.changes
            and not self.tooling.changes.model_dump(exclude_none=True)
        ):
            raise ValueError("模具变化须至少改一项")
        return self


PAYLOADS = {OPERATION: Payload}
