"""Publication content and saved-group shapes, never a live owner attestation.

The public payload contains declarations and selectors only. A trusted host must
read their actual scope, sources, professional authority and common T2 group.
These standalone types do not register a command, grant qualification or prove
that a publication is Current.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from pdos_next.schemas.resource_readiness.contracts import ResourceRef
from pdos_next.schemas.verification.contracts import Scope

from .schemas import (
    Closed,
    Key,
    ObjectRef,
    OperationDocuments,
    PreparationView,
    ProcessRef,
    RequiredRead,
    Revision,
    Source,
    Text,
)

OPERATION = "npi.manufacturing_baseline.publish"
SUBJECT_TYPE = "manufacturing_publication"
EVENT = "manufacturing_baseline.published"
SCHEMA_VERSION = "pdos-manufacturing-publication-v1"
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Visibility = Literal["private", "category", "audience"]
ResourceKind = Literal["tooling", "fixture", "equipment", "line", "person"]


class VersionRef(Closed):
    id: UUID
    revision: Revision


class SourcedText(Closed):
    text: Text
    sources: tuple[Source, ...] = Field(min_length=1)


class ResourceRequirement(SourcedText):
    operation_keys: tuple[Key, ...] = ()
    resource: ResourceRef | None = None

    @model_validator(mode="after")
    def distinct_operations(self):
        if len(set(self.operation_keys)) != len(self.operation_keys):
            raise ValueError("要求的工序范围不能重复")
        return self


class RequirementGroup(Closed):
    kind: ResourceKind
    requirements: tuple[ResourceRequirement, ...]
    # An explicit empty declaration still has its own original evidence.
    sources: tuple[Source, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def resource_kinds(self):
        refs = [v.resource for v in self.requirements if v.resource is not None]
        if any(v.kind != self.kind for v in refs):
            raise ValueError("要求须引用同类固定资源")
        return self


class Applicability(Closed):
    site: Text | None = None
    lines: tuple[ResourceRef, ...] | None = None
    conditions: SourcedText | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    sources: tuple[Source, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def declared_scope(self):
        if self.lines is not None:
            if any(v.kind != "line" for v in self.lines) or len(self.lines) != len(set(self.lines)):
                raise ValueError("产线范围须为不重复的固定产线引用")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("材料声明的适用有效期须为正区间")
        return self


class PublishPayload(Closed):
    project_id: UUID
    baseline: ObjectRef
    purpose: Text
    applicability: Applicability
    requirements: tuple[RequirementGroup, ...] = ()
    risk: SourcedText | None = None
    packaging: SourcedText | None = None
    reaction_plan: SourcedText | None = None
    previous_id: UUID | None = None
    expected_previous_revision: Revision | None = None
    visibility: Visibility = "private"
    reason: Text
    sources: tuple[Source, ...] = Field(min_length=1)
    approval_token: Annotated[str, Field(min_length=20, max_length=128)] | None = None

    @model_validator(mode="after")
    def publication_target(self):
        if self.baseline.kind != "manufacturing_baseline":
            raise ValueError("发布须固定实际制造基线草稿")
        if (self.previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("发布前版ID与revision须成对")
        if len({v.kind for v in self.requirements}) != len(self.requirements):
            raise ValueError("同类资源要求须合并为一个有来源的声明")
        if self.purpose != self.purpose.strip():
            raise ValueError("用途须是明确的原始字符串")
        return self


class PublicationMaterial(Closed):
    """Actual owner inputs; constructing this DTO does not attest their truth."""

    scope: Scope
    category_id: UUID
    product_revision: Revision
    baseline: PreparationView
    process_snapshot: dict[str, JsonValue]
    current_process: ProcessRef
    documents: tuple[PreparationView, ...]
    additional_sources: tuple[Source, ...] = ()
    required_source_read_set: tuple[RequiredRead, ...] = Field(min_length=1)


class PublicationGap(Closed):
    code: Key
    detail: Text
    operation_key: Key | None = None


class PublicationPlan(Closed):
    structural_only: Literal[True] = True
    scope: Scope
    category_id: UUID
    product_revision: Revision
    owner_id: UUID
    visibility: Visibility
    purpose: Text
    baseline: ObjectRef
    process: ProcessRef
    observed_latest_process: ProcessRef
    operations: tuple[OperationDocuments, ...] = Field(min_length=1)
    previous: VersionRef | None
    input_snapshot: dict[str, JsonValue]
    body: dict[str, JsonValue]
    body_sha256: Hash
    payload_sha256: Hash
    sources: tuple[Source, ...] = Field(min_length=1)
    required_source_read_set: tuple[RequiredRead, ...] = Field(min_length=1)
    gaps: tuple[PublicationGap, ...]
    qualification: Literal["unknown"] = "unknown"
    manufacturing_release: None = None


class PublicationDecision(Closed):
    """Saved common consumption fields, not a public qualification flag."""

    id: UUID
    tier: Literal["T2"] = "T2"
    scope: Scope
    category_id: UUID
    actor_id: UUID
    requester_id: UUID
    actor_kind: Literal["human"]
    command_id: UUID
    operation: Literal["npi.manufacturing_baseline.publish"] = OPERATION
    subject_id: UUID  # Common Confirmation subject is Product.
    product_revision: Revision
    consumed_at: AwareDatetime
    expires_at: AwareDatetime | None
    token_sha256: Hash
    material_sha256: Hash
    payload_sha256: Hash
    body_sha256: Hash
    read_set_sha256: Hash


class PublicationReceipt(Closed):
    id: UUID
    tenant_id: UUID
    category_id: UUID
    product_id: UUID
    command_id: UUID
    confirmation_id: UUID
    actor_id: UUID
    requester_id: UUID
    operation: Literal["npi.manufacturing_baseline.publish"] = OPERATION
    subject_type: Literal["manufacturing_publication"] = SUBJECT_TYPE
    subject_id: UUID
    subject_revision: Revision
    visibility: Visibility
    request_digest: Hash
    intent_digest: Hash
    result: dict[str, JsonValue]
    created_at: AwareDatetime


class PublicationRecord(Closed):
    """Immutable row/group description. Current authorization remains host-owned."""

    schema_version: Literal["pdos-manufacturing-publication-v1"] = SCHEMA_VERSION
    ref: VersionRef
    series_id: UUID
    previous: VersionRef | None
    plan: PublicationPlan
    actor_id: UUID
    created_at: AwareDatetime
    decision: PublicationDecision
    receipt: PublicationReceipt
    authority_snapshot: dict[str, JsonValue]
    source_basis: dict[str, JsonValue]
    status: Literal["published"] = "published"
    qualification: Literal["unknown"] = "unknown"
    manufacturing_release: None = None


class PublicationCurrent(Closed):
    """Pointer/CAS material only; not proof that this is actual database Current."""

    scope: Scope
    category_id: UUID
    series_id: UUID
    owner_id: UUID
    visibility: Visibility
    version: VersionRef
    epoch: Revision
