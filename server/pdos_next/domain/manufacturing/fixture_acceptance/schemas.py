"""Closed T2 fixture acceptance declarations (P95 第 5 项, D306).

A manufacturing-role, currently qualified named person accepts, rejects or
revokes one imported fixture for one purpose and operation. Every action is a
new version; validity is optional and readiness blocks outside it.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Text, VersionRef

OPERATION = "npi.fixture.accept"
EVENT = "fixture.accepted"
SUBJECT = "fixture_acceptance"
ACTIONS = ("accept", "reject", "revoke")
STATES = ("accepted", "rejected", "revoked")
STATE_OF = {"accept": "accepted", "reject": "rejected", "revoke": "revoked"}
Key = Annotated[str, Field(min_length=1, max_length=200)]


class Scope(DTO):
    build_id: UUID
    resource: VersionRef
    purpose: Key
    operation_id: Key


class Payload(DTO):
    acceptance: VersionRef | None = None
    action: Literal["accept", "reject", "revoke"]
    scope: Scope | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    conditions: list[Text] = Field(default_factory=list, max_length=20)
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def shape(self):
        if (self.acceptance is None) != (self.scope is not None):
            raise ValueError("首次验收给出治具与用途范围；之后的办理固定原验收版本")
        if self.acceptance is None and self.action == "revoke":
            raise ValueError("撤销须针对已有的验收记录")
        if self.action != "accept" and (self.valid_until or self.valid_from or self.conditions):
            raise ValueError("只有接受可以带有效期和条件")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("有效期须严格递增")
        return self


PAYLOADS = {OPERATION: Payload}
