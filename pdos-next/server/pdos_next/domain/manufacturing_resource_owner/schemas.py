"""Fixed Build-specific references; public inputs contain no authority assertions."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from pdos_next.contracts import SourceRead
from pdos_next.domain.build_operational_facts.schemas import (
    DTO,
    Hash,
    OperationalScope,
    Positive,
    Revision,
)
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.schemas.resource_readiness.contracts import ResourceRef
from pdos_next.schemas.verification.contracts import Scope, SourceRef

Key = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]


class VersionRef(DTO):
    id: UUID
    revision: Revision


class ResourceRequest(DTO):
    scope: Scope
    build: VersionRef
    process: VersionRef
    execution: OperationalScope
    operation_key: Key
    resource: ResourceRef | None = None
    # Explicit immutable historical selection. Omission selects actual Current.
    fact: VersionRef | None = None


class ResourceProjection(DTO):
    resource: ResourceRef
    lifecycle: Literal["active", "withdrawn", "unknown"]
    current: bool = Field(strict=True)
    originals: tuple[DefinitionReference, ...]
    acceptance: Literal["unknown"] = "unknown"
    calibration: Literal["unknown"] = "unknown"
    qualification: Literal["unknown"] = "unknown"


class ResourceRelation(DTO):
    build: VersionRef
    process: VersionRef
    operation_key: Key
    resource: ResourceRef
    units: Positive
    relation: Literal["operation_uses_resource"] = "operation_uses_resource"
    relation_source: SourceRef
    relation_originals: tuple[DefinitionReference, ...] = Field(min_length=1)


class ResourceView(DTO):
    request: ResourceRequest
    state: Literal["known", "historical", "unknown"]
    current: bool = Field(strict=True)
    fact: VersionRef | None = None
    fact_sha256: Hash | None = None
    nature: Literal["unknown", "real", "synthetic"] = "unknown"
    resources: tuple[ResourceProjection, ...] = ()
    relations: tuple[ResourceRelation, ...] = ()
    required_source_read_set: tuple[SourceRead, ...] = Field(default=())
    facts_revision: Hash
    valid_until: AwareDatetime | None = None
    fact_valid_until: AwareDatetime | None = None
    gaps: tuple[str, ...]
    # This adapter cannot certify global closure, execution or native T2 acceptance.
    negative_enumeration_complete: Literal[False] = False
    execution_authorized: Literal[False] = False
