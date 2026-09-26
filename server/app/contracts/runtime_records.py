"""N0-01 internal runtime record candidates, separate from model-visible context.

Shape validation cannot mint authorization or renew a lease. N0-02/03 must wire
current ACL checks, persistence, budgets and receipts before these can execute.
"""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import (
    Contract,
    Digest,
    Key,
    Nonnegative,
    Positive,
    ScopedRecord,
    SourceRef,
    Text,
)


class AuthorizationEnvelope(ScopedRecord):
    run_id: UUID
    lineage_id: UUID
    principal_kind: Literal["user", "service"]
    principal_id: UUID
    trigger_actor_user_id: UUID | None
    delegation_id: UUID | None = None
    policy_version: Key
    purpose: Text
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    capability_version: Key
    toolset_version: Key

    @model_validator(mode="after")
    def bounded_authorization(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization_expiry_required")
        if self.scope.kind == "tenant" and not self.sources:
            raise ValueError("tenant_run_requires_bound_anchor_set")
        return self


class Observation(Contract):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    tool_call_id: UUID
    parent_observation_id: UUID | None
    sequence: Positive
    tool_version: Key
    status: Literal["completed", "partial", "unavailable", "failed", "cancelled"]
    sources: tuple[SourceRef, ...]
    observed_at: AwareDatetime
    as_of: AwareDatetime
    fresh_until: AwareDatetime | None
    acl_policy_version: Key
    allowed_purpose: Key
    taint: Literal["untrusted_external", "internal", "verified"]
    derived_from_ids: tuple[UUID, ...] = ()
    input_digest: Digest
    output_digest: Digest
    shown_count: Nonnegative
    total_count: Nonnegative | None
    truncated: bool
    continuation: Text | None
    error_code: Key | None = None

    @model_validator(mode="after")
    def honest_observation(self) -> Self:
        if any(ref.tenant_id != self.tenant_id for ref in self.sources):
            raise ValueError("observation_source_tenant_mismatch")
        if self.total_count is not None:
            if self.total_count < self.shown_count:
                raise ValueError("observation_count_invalid")
            if self.truncated != (self.shown_count < self.total_count):
                raise ValueError("observation_truncation_mismatch")
        if self.truncated and self.continuation is None:
            raise ValueError("observation_continuation_required")
        if self.status in {"unavailable", "failed", "cancelled"} and self.error_code is None:
            raise ValueError("observation_failure_reason_required")
        if self.fresh_until is not None and self.fresh_until < self.as_of:
            raise ValueError("observation_freshness_reversed")
        return self


class ContextManifest(Contract):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    authorization_id: UUID
    revision_no: Positive
    parent_revision_id: UUID | None
    goal_revision: Positive
    release_bundle_version: Key
    capability_version: Key
    prompt_version: Key
    skill_versions: tuple[Key, ...]
    toolset_version: Key
    projection_version: Key
    model_qualification_version: Key
    output_schema_version: Key
    policy_version: Key
    observation_ids: tuple[UUID, ...]
    event_watermark: Nonnegative
    selected_sources: tuple[SourceRef, ...]
    omission_reasons: tuple[Text, ...]
    estimated_input_tokens: Nonnegative
    reserved_output_tokens: Positive
    completeness: Literal["complete", "partial", "context_incomplete"]
    missing: tuple[Text, ...]
    built_at: AwareDatetime
    digest: Digest

    @model_validator(mode="after")
    def append_only_revision_shape(self) -> Self:
        if (self.revision_no == 1) != (self.parent_revision_id is None):
            raise ValueError("manifest_parent_revision_required")
        if self.parent_revision_id == self.id:
            raise ValueError("manifest_self_parent")
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("manifest_duplicate_observation")
        if any(ref.tenant_id != self.tenant_id for ref in self.selected_sources):
            raise ValueError("manifest_source_tenant_mismatch")
        if self.completeness == "complete" and self.missing:
            raise ValueError("complete_manifest_has_missing_inputs")
        return self


class CompactionRecord(Contract):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    manifest_id: UUID
    observation_ids: tuple[UUID, ...] = Field(min_length=1)
    source_acl_dependencies: tuple[SourceRef, ...] = Field(min_length=1)
    compressor_version: Key
    summary_digest: Digest
    exact_facts: tuple[Text, ...]
    approval_ids: tuple[UUID, ...]
    unresolved: tuple[Text, ...]
    omitted: tuple[Text, ...]
    reread_observation_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def preserve_acl_and_reread(self) -> Self:
        if any(ref.tenant_id != self.tenant_id for ref in self.source_acl_dependencies):
            raise ValueError("compaction_source_tenant_mismatch")
        if not set(self.reread_observation_ids).issubset(self.observation_ids):
            raise ValueError("compaction_reread_not_in_sources")
        return self


class RunControl(Contract):
    """One control snapshot; the stored current pointer is mutable, body is not context."""

    run_id: UUID
    tenant_id: UUID
    lineage_id: UUID
    generation: Positive
    attempt: Positive
    lease_token: UUID | None
    lease_expires_at: AwareDatetime | None
    checkpoint_id: UUID | None
    budget_ledger_id: UUID
    absolute_deadline: AwareDatetime
    state: Literal[
        "queued", "running", "waiting_input", "completed", "degraded", "failed", "cancelled"
    ]
    outcome: Literal["read_only_ready", "proposal_ready", "no_action"] | None = None
    stop_reason: Key | None = None

    @model_validator(mode="after")
    def lifecycle_shape(self) -> Self:
        if (self.lease_token is None) != (self.lease_expires_at is None):
            raise ValueError("lease_pair_required")
        if self.state == "running" and self.lease_token is None:
            raise ValueError("running_requires_lease")
        if self.state == "waiting_input" and (
            self.checkpoint_id is None or self.lease_token is not None
        ):
            raise ValueError("waiting_releases_worker_and_keeps_checkpoint")
        if (self.state == "completed") != (self.outcome is not None):
            raise ValueError("run_completion_outcome_required")
        if (
            self.state in {"completed", "degraded", "failed", "cancelled"}
            and self.stop_reason is None
        ):
            raise ValueError("run_stop_reason_required")
        return self


class TargetMapping(Contract):
    node_key: Key
    target: SourceRef


class OperationReceipt(Contract):
    id: UUID
    tenant_id: UUID
    source_run_id: UUID | None
    finding_id: UUID | None
    candidate_digest: Digest
    idempotency_key: Key
    reviewed_by_user_id: UUID | None
    reviewed_at: AwareDatetime | None
    applied_by_user_id: UUID | None
    applied_at: AwareDatetime | None
    status: Literal["pending", "applied", "failed", "receipt_unknown"]
    targets: tuple[TargetMapping, ...]
    event_row_ids: tuple[Positive, ...]
    audit_row_ids: tuple[Positive, ...]
    execution_state: Literal["not_required", "pending", "in_progress", "completed"]
    execution_evidence: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def application_is_not_execution(self) -> Self:
        refs = tuple(mapping.target for mapping in self.targets) + self.execution_evidence
        if any(ref.tenant_id != self.tenant_id for ref in refs):
            raise ValueError("receipt_target_tenant_mismatch")
        if len({mapping.node_key for mapping in self.targets}) != len(self.targets):
            raise ValueError("receipt_duplicate_node_mapping")
        if (self.reviewed_by_user_id is None) != (self.reviewed_at is None):
            raise ValueError("receipt_review_pair_required")
        if (self.applied_by_user_id is None) != (self.applied_at is None):
            raise ValueError("receipt_apply_pair_required")
        if self.status == "applied":
            if (
                self.applied_at is None
                or not self.targets
                or not self.event_row_ids
                or not self.audit_row_ids
            ):
                raise ValueError("applied_receipt_requires_actor_targets_event_audit")
            if self.finding_id is not None and self.reviewed_at is None:
                raise ValueError("model_finding_requires_prior_review")
            if self.reviewed_at is not None and self.applied_at < self.reviewed_at:
                raise ValueError("application_precedes_review")
        elif self.applied_at is not None:
            raise ValueError("unapplied_receipt_has_application")
        if self.execution_state == "completed" and (
            self.status != "applied" or not self.execution_evidence
        ):
            raise ValueError("actual_execution_requires_applied_receipt_and_evidence")
        return self
