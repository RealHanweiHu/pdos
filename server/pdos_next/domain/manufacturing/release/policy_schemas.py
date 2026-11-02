"""Closed host publication inputs; constructing them supplies no authority."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from pdos_next.schemas.verification.contracts import Scope

from .schemas import (
    DTO,
    ObjectRef,
    OriginalRef,
    ReleaseScope,
    SubjectConfiguration,
    Text,
    VersionRef,
)


class PolicyImport(DTO):
    project_id: UUID
    source: OriginalRef
    expected_previous: VersionRef | None = None
    reason: Text


class PolicyRule(DTO):
    id: Text
    version: Text
    scope: ReleaseScope
    discipline: Literal["engineering", "manufacturing", "both"]
    # Unknown expression objects are retained, never evaluated as Python/SQL.
    applicable_if: dict[str, JsonValue]
    predicate: dict[str, JsonValue]
    required_evidence: tuple[ObjectRef | Text, ...]
    freshness: Text
    severity: Literal["hard", "required", "advisory"]
    responsible_role: Text
    waivable: bool = Field(strict=True)
    allowed_purpose: tuple[Text, ...]

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.allowed_purpose)) != len(self.allowed_purpose):
            raise ValueError("Policy purposes cannot repeat")
        evidence = [
            (value.kind, value.id, value.revision) if isinstance(value, ObjectRef) else value
            for value in self.required_evidence
        ]
        if len(set(evidence)) != len(evidence):
            raise ValueError("Policy evidence selectors cannot repeat")
        return self


class PolicyMaterial(DTO):
    schema_version: Literal["pdos-release-policy-v1"]
    scope: Scope
    category_id: UUID
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    policy_version: Text
    publisher_id: UUID
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    nature: Literal["real", "synthetic"]
    status: Literal["active", "withdrawn"]
    valid_from: AwareDatetime | None
    valid_until: AwareDatetime | None
    rules: tuple[PolicyRule, ...]

    @model_validator(mode="after")
    def fixed(self):
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("Policy validity must increase")
        if self.purpose != self.purpose.strip():
            raise ValueError("Policy purpose must preserve an explicit original string")
        if len({value.id for value in self.rules}) != len(self.rules):
            raise ValueError("A policy version cannot repeat a rule identity")
        return self


class PolicyFact(DTO):
    """Internal projection supplied only after the actual owner reads its row.

    ``value._release_current`` is the host's direct Current comparison, not a
    public policy or command field. This pure DTO is not an owner attestation.
    """

    ref: ObjectRef
    value: JsonValue
