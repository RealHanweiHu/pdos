"""Closed T2 CAPA effectiveness decision (P96 第 1–4 项, F47, D307)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Text

OPERATION = "quality.capa.effectiveness.decide"
EVENT = "capa.effectiveness_decided"


class Evidence(DTO):
    kind: Literal["review", "observation"]
    id: UUID
    revision: int = Field(ge=1, strict=True)


class Payload(DTO):
    issue_id: UUID
    expected_issue_revision: int = Field(ge=1, strict=True)
    outcome: Literal["effective", "ineffective", "extend_observation"]
    observation_until: datetime | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=50)
    text: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("observation_until")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("观察截止须带时区")
        return value

    @model_validator(mode="after")
    def shape(self):
        if (self.outcome == "extend_observation") != (self.observation_until is not None):
            raise ValueError("只有延长观察带新的观察截止日")
        if self.outcome != "extend_observation" and not self.evidence:
            raise ValueError("有效或无效的结论须引用已有的具名复核或观察记录")
        if len({(e.kind, e.id) for e in self.evidence}) != len(self.evidence):
            raise ValueError("证据不能重复")
        return self


PAYLOADS = {OPERATION: Payload}
