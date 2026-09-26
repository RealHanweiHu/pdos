"""N0-01 version validity and release compatibility candidates.

A validity record describes a control revision, never an edit to a published
body. Handlers still verify current authorization and the referenced lineage.
"""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Positive, SourceRef, Text


class VersionValidity(Contract):
    id: UUID
    tenant_id: UUID
    subject: SourceRef
    body_digest: Digest
    control_revision: Positive
    previous_control_id: UUID | None
    state: Literal["active", "superseded", "withdrawn", "invalidated"]
    replacement: SourceRef | None
    reason: Text
    policy_version: Key
    decided_by_kind: Literal["user", "service"]
    decided_by_id: UUID
    decided_at: AwareDatetime
    effective_at: AwareDatetime
    operation_id: UUID
    source_dependencies: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def validity_does_not_rewrite_body(self) -> Self:
        if self.subject.tenant_id != self.tenant_id or self.subject.version is None:
            raise ValueError("validity_subject_requires_tenant_and_version")
        if (self.control_revision == 1) != (self.previous_control_id is None):
            raise ValueError("validity_previous_control_required")
        if self.previous_control_id == self.id:
            raise ValueError("validity_control_self_reference")
        if (self.state == "superseded") != (self.replacement is not None):
            raise ValueError("supersession_requires_replacement_only")
        if self.replacement is not None and (
            self.replacement.tenant_id != self.tenant_id
            or self.replacement.project_id != self.subject.project_id
            or self.replacement.kind != self.subject.kind
            or self.replacement.version is None
            or self.replacement.version <= self.subject.version
        ):
            raise ValueError("replacement_requires_same_scope_kind_and_newer_version")
        if any(source.tenant_id != self.tenant_id for source in self.source_dependencies):
            raise ValueError("validity_source_tenant_mismatch")
        return self


class ReleaseComponent(Contract):
    kind: Literal[
        "capability",
        "schema",
        "prompt",
        "tool",
        "skill",
        "projection",
        "policy",
        "model_qualification",
        "golden_suite",
    ]
    key: Key
    version: Key
    digest: Digest


class RuntimeReleaseBundle(Contract):
    id: UUID
    version: Key
    code_digest: Digest
    migration_head: Key
    compatible_context_versions: tuple[Positive, ...] = Field(min_length=1)
    components: tuple[ReleaseComponent, ...] = Field(min_length=1)
    released_by_user_id: UUID
    released_at: AwareDatetime

    @model_validator(mode="after")
    def bundle_is_exact_and_qualified(self) -> Self:
        identities = [(component.kind, component.key) for component in self.components]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate_release_component")
        required = {
            "capability",
            "schema",
            "prompt",
            "tool",
            "projection",
            "policy",
            "model_qualification",
            "golden_suite",
        }
        if not required.issubset(component.kind for component in self.components):
            raise ValueError("release_bundle_required_components_missing")
        if len(set(self.compatible_context_versions)) != len(self.compatible_context_versions):
            raise ValueError("duplicate_compatible_context_version")
        return self


class LegacyContextCompatibility(Contract):
    run_id: UUID
    tenant_id: UUID
    project_id: UUID
    original_schema_version: Literal[2] = 2
    original_digest: Digest
    adapter_version: Key
    authorization_status: Literal["legacy_unknown"] = "legacy_unknown"
    disposition: Literal["read_only"] = "read_only"
    resumable: Literal[False] = False
    missing_fields: tuple[Key, ...] = Field(min_length=1)
    continuation_action: Literal["create_new_authorized_run"] = "create_new_authorized_run"
