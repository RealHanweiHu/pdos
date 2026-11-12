"""Closed T1 interface-contract declarations (v1.1 §04.2; P100 第 4–6 项; D312).

One command both creates an interface (version 1) and revises it; each
participating discipline confirms or disputes separately through the same
command. The named responsible person is a project member and never one of the
confirmers. Affected items are explicit references only; AI leads stay apart.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Key, Text, VersionRef

OPERATION = "engineering.interface.update"
EVENT = "interface.updated"
SUBJECT = "engineering_interface"
ACTIONS = ("create", "revise", "confirm", "dispute")
STATES = ("pending", "confirmed", "disputed")
RoleKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
# Affected kinds that the change graph can resolve through a real owner read.
AffectedKind = Literal[
    "engineering_configuration",
    "manufacturing_configuration",
    "operation",
    "sop",
    "bom",
    "part",
    "spec",
    "build",
    "sample",
    "test_run",
    "work_instruction",
    "control_plan",
    "manufacturing_baseline",
]
Short = Annotated[str, Field(min_length=1, max_length=200)]


class Module(DTO):
    key: Key
    label: Short


class Constraint(DTO):
    text: Text
    unit: Key | None = None


class Affected(DTO):
    kind: AffectedKind
    id: UUID
    revision: int = Field(ge=1, strict=True)
    key: Key | None = None
    note: Text | None = None


class Lead(DTO):
    """An AI or human lead to verify; never fed into impact as a confirmed item."""

    text: Text


class Content(DTO):
    name: Short
    kind: Short
    modules: list[Module] = Field(min_length=1, max_length=40)
    disciplines: list[RoleKey] = Field(min_length=1, max_length=20)
    constraints: list[Constraint] = Field(default_factory=list, max_length=100)
    units: list[Key] = Field(default_factory=list, max_length=40)
    verification_method: Text | None = None
    responsible_id: UUID
    affected: list[Affected] = Field(default_factory=list, max_length=100)
    leads: list[Lead] = Field(default_factory=list, max_length=50)

    @field_validator("disciplines", "units")
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("专业或单位不能重复")
        return sorted(values)

    @model_validator(mode="after")
    def distinct(self):
        if len({m.key for m in self.modules}) != len(self.modules):
            raise ValueError("参与模块标识不能重复")
        keys = [(a.kind, a.id, a.revision, a.key) for a in self.affected]
        if len(set(keys)) != len(keys):
            raise ValueError("受影响项不能重复")
        return self


class Create(Content):
    action: Literal["create"]
    project_id: UUID
    configuration: VersionRef


class Revise(Content):
    action: Literal["revise"]
    configuration: VersionRef


class Confirm(DTO):
    action: Literal["confirm", "dispute"]
    discipline: RoleKey
    note: Text | None = None

    @model_validator(mode="after")
    def dispute_has_reason(self):
        if self.action == "dispute" and not self.note:
            raise ValueError("提出异议须写明理由")
        return self


Record = Annotated[Create | Revise | Confirm, Field(discriminator="action")]


class Payload(DTO):
    interface: VersionRef | None = None
    record: Record
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def target(self):
        if (self.record.action == "create") != (self.interface is None):
            raise ValueError("建立接口不带原接口；修订、确认与异议须固定原接口版本")
        return self


PAYLOADS = {OPERATION: Payload}
