"""Closed declarations and internal actual-owner material, never attestations.

ActualData/ReceiptActualData may only be supplied by the bound host owner after
real rows, original bytes, issuer and Current checks. DTO construction and a
matching digest alone prove none of these facts and grant no external action.
"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.contracts import SourceRead
from pdos_next.domain.release.schemas import (
    DTO,
    DecisionPlan,
    Hash,
    OriginalRef,
    PackagePlan,
    ReleaseScope,
    SourcedText,
    SubjectConfiguration,
    Text,
    VersionRef,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef


class Destination(DTO):
    system: Text
    recipient_id: Text


class MappingRef(VersionRef):
    kind: Literal[
        "definition",
        "engineering_configuration",
        "process_revision",
        "part",
        "bom_revision",
        "artifact",
        "work_instruction",
        "control_plan",
    ]


class NumberMapping(DTO):
    ref: MappingRef
    external_number: Text
    external_version: Text
    sources: tuple[OriginalRef, ...] = Field(min_length=1)


class ManifestFile(DTO):
    artifact: VersionRef
    logical_name: Text
    content_sha256: Hash
    external_number: Text
    external_version: Text
    sources: tuple[OriginalRef, ...] = Field(min_length=1)


class AuthorizePayload(DTO):
    project_id: UUID
    package: VersionRef
    engineering_decision: VersionRef
    manufacturing_decision: VersionRef
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    visibility: Literal["private", "category", "audience"] = "private"
    destination: Destination
    external_id: Text
    mappings: tuple[NumberMapping, ...] = ()
    manifest: tuple[ManifestFile, ...] = ()
    sources: tuple[OriginalRef, ...] = Field(min_length=1)
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def fixed(self):
        if self.purpose != self.purpose.strip():
            raise ValueError("Handoff purpose must be the explicit original string")
        keys = [(value.ref.kind, value.ref.id) for value in self.mappings]
        if len(set(keys)) != len(keys):
            raise ValueError("A handoff cannot map the same native object twice")
        if len({value.logical_name for value in self.manifest}) != len(self.manifest):
            raise ValueError("Manifest logical names must be unique")
        if len({value.artifact for value in self.manifest}) != len(self.manifest):
            raise ValueError("A fixed manifest artifact cannot repeat")
        if self.engineering_decision == self.manufacturing_decision:
            raise ValueError("Engineering/manufacturing decisions are separate records")
        return self


class ActualDecision(DTO):
    ref: VersionRef
    plan: DecisionPlan
    current: bool | None


class ActualData(DTO):
    scope: Scope
    category_id: UUID
    visibility: Literal["private", "category", "audience"]
    package_ref: VersionRef
    package: PackagePlan
    package_current: bool | None
    decisions: tuple[ActualDecision, ...]
    mappings: tuple[NumberMapping, ...]
    files: tuple[ManifestFile, ...]
    # None means that the actual contract has not stated its required set.
    # An explicitly verified empty set is different from missing integration.
    contract_read: bool | None
    required_mapping_refs: tuple[MappingRef, ...] | None
    required_manifest_refs: tuple[VersionRef, ...] | None
    sources_current: bool | None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]


class AuthorizationPlan(DTO):
    structural_only: Literal[True] = True
    status: Literal["unexecuted_candidate"] = "unexecuted_candidate"
    operation: Literal["integration.handoff.authorize"] = "integration.handoff.authorize"
    scope: Scope
    category_id: UUID
    declaration: AuthorizePayload
    package_sha256: Hash
    manifest_sha256: Hash
    mappings_sha256: Hash
    content_sha256: Hash
    limits: tuple[SourcedText, ...]
    signers: tuple[UUID, ...]
    state: Literal["READY", "UNKNOWN", "BLOCKED"]
    unknown: tuple[Text, ...]
    blocked: tuple[Text, ...]
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    prepared_at: AwareDatetime
    network_send: Literal[False] = False
    external_received: Literal[False] = False
    external_effective: Literal[False] = False


class ReceiptRecordPayload(DTO):
    handoff: VersionRef
    intent: VersionRef
    source: OriginalRef
    reason: Text


Stage = Literal["sent", "accepted", "effective"]
Outcome = Literal["succeeded", "unknown", "rejected", "failed"]


class ReceiptOriginal(DTO):
    schema_version: Literal["pdos-external-receipt-v1"]
    handoff: VersionRef
    intent: VersionRef
    destination: Destination
    external_id: Text
    manifest_sha256: Hash
    release_scope: ReleaseScope
    stage: Stage
    outcome: Outcome
    external_receipt_id: Text
    occurred_at: AwareDatetime
    reconciles: VersionRef | None = None


class ReceiptIssuer(DTO):
    """Fixed material from a real host issuer proof, not a registration request."""

    key: Text
    version: Text
    epoch: int = Field(strict=True, ge=1)
    system: Text
    subject_id: Text
    proof_sha256: Hash


class ReceiptActualData(DTO):
    scope: Scope
    category_id: UUID
    handoff: VersionRef
    intent: VersionRef
    authorization: AuthorizationPlan
    authorized: bool | None
    source: OriginalRef
    original: ReceiptOriginal
    issuer: ReceiptIssuer | None
    issuer_current: bool | None
    sources_current: bool | None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]


class ReceiptPlan(DTO):
    structural_only: Literal[True] = True
    status: Literal["unexecuted_candidate"] = "unexecuted_candidate"
    operation: Literal["integration.receipt.record"] = "integration.receipt.record"
    scope: Scope
    category_id: UUID
    original: ReceiptOriginal
    source: OriginalRef
    issuer: ReceiptIssuer | None
    # A verified mismatched response can be recorded; it cannot satisfy a stage.
    mismatches: tuple[Text, ...]
    state: Literal["READY", "UNKNOWN"]
    unknown: tuple[Text, ...]
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    received_at: AwareDatetime
    network_send: Literal[False] = False


class ReceiptFact(VersionRef):
    """A saved immutable common atom supplied by the actual receipt owner."""

    original: ReceiptOriginal
    source: OriginalRef
    issuer: ReceiptIssuer
    received_at: AwareDatetime


class StageReading(DTO):
    stage: Stage
    state: Literal[
        "not_recorded", "succeeded", "partial", "unknown", "rejected", "failed", "conflict"
    ]
    active: tuple[VersionRef, ...]
    covered_scopes: tuple[ReleaseScope, ...]
    mismatches: tuple[Text, ...]


class HandoffReading(DTO):
    status: Literal["authorized", "sent", "acknowledged", "reconciled"]
    sent: StageReading
    accepted: StageReading
    effective: StageReading
    delivery_unknown: bool
    rejected: bool
    failed: bool
    conflict: bool
    history: tuple[ReceiptFact, ...]
    network_send: Literal[False] = False
