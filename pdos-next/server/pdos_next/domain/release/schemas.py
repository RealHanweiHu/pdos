"""Fixed release content and unexecuted candidates, never owner attestations.

Public inputs select objects and originals. Only a future actual owner may bind
the internal material to current scope, applicable policy and independent
exception decisions. Constructing these DTOs establishes none of those facts.
"""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from pdos_next.contracts import SourceRead
from pdos_next.schemas.verification.contracts import DTO as VerificationDTO
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from .constants import ASSEMBLE, ENGINEERING_APPROVE, MANUFACTURING_APPROVE
from .constants import SCHEMA_VERSION as SCHEMA_VERSION

OPERATIONS = {
    ASSEMBLE: ("T0", "release.package_assembled"),
    ENGINEERING_APPROVE: ("T2", "release.engineering_approved"),
    MANUFACTURING_APPROVE: ("T2", "release.manufacturing_approved"),
}
Revision = Annotated[int, Field(strict=True, ge=1)]
Text = Annotated[str, Field(min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Discipline = Literal["engineering", "manufacturing"]
State = Literal["BLOCKED", "UNKNOWN", "READY_WITH_CONDITIONS", "READY"]


class DTO(VerificationDTO):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class VersionRef(DTO):
    id: UUID
    revision: Revision


class ObjectRef(VersionRef):
    kind: Literal[
        "definition",
        "engineering_configuration",
        "process_revision",
        "manufacturing_publication",
        "test_run",
        "pilot_run",
        "issue",
        "change",
        "exception",
        "artifact",
        "work_instruction",
        "control_plan",
        "build_lot",
        "line",
    ]


class OriginalRef(SourceRef):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    kind: Literal["artifact"] = "artifact"


class SourcedText(DTO):
    text: Text
    sources: tuple[OriginalRef, ...] = Field(min_length=1)


class SubjectConfiguration(DTO):
    definition: VersionRef
    engineering_configuration: VersionRef
    manufacturing_configuration: VersionRef


class ReleaseScope(DTO):
    """None is unknown/uncovered; an empty set never means all objects."""

    quantity: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)] | None = None
    unit: Text | None = None
    lots: tuple[VersionRef, ...] | None = None
    site: Text | None = None
    lines: tuple[VersionRef, ...] | None = None
    regions: tuple[Text, ...] | None = None

    @model_validator(mode="after")
    def exact_scope(self):
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("数量和单位须成对；未知不代表不限量")
        for field in ("lots", "lines", "regions"):
            values = getattr(self, field)
            identities = [v.id if isinstance(v, VersionRef) else v for v in values or ()]
            if len(set(identities)) != len(identities):
                raise ValueError("固定范围不能重复同一身份或地区")
        return self


class PackageAssemblePayload(DTO):
    project_id: UUID
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    manufacturing_publication: VersionRef | None = None
    verifications: tuple[VersionRef, ...] = ()
    pilots: tuple[VersionRef, ...] = ()
    residuals: tuple[ObjectRef, ...] = ()
    exceptions: tuple[VersionRef, ...] = ()
    documents: tuple[ObjectRef, ...] = ()
    limits: tuple[SourcedText, ...] = ()
    sources: tuple[OriginalRef, ...] = Field(min_length=1)
    visibility: Literal["private", "category", "audience"] = "private"
    previous: VersionRef | None = None
    reason: Text

    @model_validator(mode="after")
    def selected_objects(self):
        if any(value.kind not in {"issue", "change"} for value in self.residuals):
            raise ValueError("遗留项须引用实际问题或变更，不提交关闭/满足结论")
        for field in ("verifications", "pilots", "exceptions", "residuals", "documents"):
            values = getattr(self, field)
            keys = [(getattr(v, "kind", field), v.id) for v in values]
            if len(set(keys)) != len(keys):
                raise ValueError("同类固定对象不能重复")
        if self.purpose != self.purpose.strip():
            raise ValueError("用途须保留明确的原始字符串")
        return self


class ApprovePayload(DTO):
    package: VersionRef
    release_scope: ReleaseScope
    purpose: Text
    limits: tuple[SourcedText, ...] = ()
    expiry: AwareDatetime | None = None
    sources: tuple[OriginalRef, ...] = Field(min_length=1)
    reason: Text
    approval_token: Annotated[str, Field(min_length=20, max_length=128)] | None = None

    @model_validator(mode="after")
    def exact_purpose(self):
        if self.purpose != self.purpose.strip():
            raise ValueError("用途须保留明确的原始字符串")
        return self


class EngineeringApprovePayload(ApprovePayload):
    pass


class ManufacturingApprovePayload(ApprovePayload):
    pass


PAYLOADS = {
    ASSEMBLE: PackageAssemblePayload,
    ENGINEERING_APPROVE: EngineeringApprovePayload,
    MANUFACTURING_APPROVE: ManufacturingApprovePayload,
}


class FixedObject(DTO):
    ref: ObjectRef
    product_id: UUID
    # Fixed definitions/configurations are product-scoped; do not invent a
    # project column for them when binding their real use to this project.
    project_id: UUID | None = None
    sha256: Hash


class PolicyBasis(DTO):
    version: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class ReleaseCheck(DTO):
    key: Text
    discipline: Literal["engineering", "manufacturing", "both"]
    applicable: bool = Field(strict=True)
    required: bool = Field(strict=True)
    state: Literal["satisfied", "unknown", "blocked"]
    non_waivable: bool = Field(strict=True)
    detail: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    release_scope: ReleaseScope | None = None
    exception: VersionRef | None = None


class ExceptionBasis(DTO):
    """Material read from a separate actual authority decision, not text limits."""

    decision: VersionRef
    scope: Scope
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    policy_version: Text
    discipline: Discipline
    check_keys: tuple[Text, ...] = Field(min_length=1)
    state: Literal["current", "unknown", "withdrawn"]
    limits: tuple[SourcedText, ...] = Field(min_length=1)
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    expiry: AwareDatetime | None = None


class ReleaseMaterial(DTO):
    scope: Scope
    category_id: UUID
    product_revision: Revision
    purpose: Text
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    objects: tuple[FixedObject, ...] = Field(min_length=1)
    policy: PolicyBasis | None
    checks: tuple[ReleaseCheck, ...]
    exceptions: tuple[ExceptionBasis, ...] = ()
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)


class PackagePlan(DTO):
    structural_only: Literal[True] = True
    status: Literal["unexecuted_candidate"] = "unexecuted_candidate"
    scope: Scope
    category_id: UUID
    product_revision: Revision
    owner_id: UUID
    declaration: PackageAssemblePayload
    objects: tuple[FixedObject, ...]
    policy: PolicyBasis | None
    checks: tuple[ReleaseCheck, ...]
    exceptions: tuple[ExceptionBasis, ...]
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    evidence_digest: Hash
    body_sha256: Hash


class Assessment(DTO):
    discipline: Discipline
    state: State
    checks: tuple[ReleaseCheck, ...]
    blocked: tuple[Text, ...]
    unknown: tuple[Text, ...]
    conditions: tuple[VersionRef, ...]


class DecisionPlan(DTO):
    """Server-bound proposed signer; no persisted T2 or grant is established."""

    structural_only: Literal[True] = True
    status: Literal["unexecuted_candidate"] = "unexecuted_candidate"
    operation: Literal["release.engineering.approve", "release.manufacturing.approve"]
    discipline: Discipline
    package: VersionRef
    package_sha256: Hash
    scope: Scope
    category_id: UUID
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    limits: tuple[SourcedText, ...]
    evidence_digest: Hash
    policy_version: Text | None
    input_snapshot: dict[str, JsonValue]
    signers: tuple[UUID, ...] = Field(min_length=1)
    expiry: AwareDatetime | None
    assessment: Assessment
    prepared_at: AwareDatetime
    customer_acceptance: None = None
    external_received: Literal[False] = False
    external_effective: Literal[False] = False
