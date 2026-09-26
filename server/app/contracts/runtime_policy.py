"""N0-02 policy candidates; no runtime registration or authority is granted.

These validate proposed policy documents and accounting shapes. Actual ACL,
qualification, atomic reservations, handlers and retention must be wired in N0-03.
"""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import (
    Contract,
    Key,
    Nonnegative,
    Positive,
    ScopeKind,
    Text,
)


class PolicyPin(Contract):
    key: Key
    version: Key


class ScopePolicy(Contract):
    allowed_scopes: tuple[ScopeKind, ...] = Field(min_length=1)
    principal_source: Literal["server_authenticated_run"] = "server_authenticated_run"
    persona_grants_permissions: Literal[False] = False
    delegation: Literal["principal_delegate_intersection"] = "principal_delegate_intersection"
    project_role_null: Literal["preserve_existing_role_and_membership"] = (
        "preserve_existing_role_and_membership"
    )
    project_role_set: Literal["tenant_project_intersection"] = "tenant_project_intersection"
    scope_change: Literal["authorized_linked_run_preserve_lineage"] = (
        "authorized_linked_run_preserve_lineage"
    )
    current_acl_checks: tuple[
        Literal["tool", "model_egress", "disclosure", "export", "apply"], ...
    ] = ("tool", "model_egress", "disclosure", "export", "apply")
    derived_sources_inherit_acl: Literal[True] = True

    @model_validator(mode="after")
    def complete_boundaries(self) -> Self:
        if len(set(self.allowed_scopes)) != len(self.allowed_scopes):
            raise ValueError("duplicate_scope")
        required = {"tool", "model_egress", "disclosure", "export", "apply"}
        if set(self.current_acl_checks) != required or len(self.current_acl_checks) != 5:
            raise ValueError("all_acl_boundaries_required")
        return self


class RunBudgetProfile(PolicyPin):
    input_token_limit: Positive
    output_token_reserve: Positive
    lineage_token_limit: Positive
    tool_call_limit: Positive
    model_call_limit: Positive
    active_seconds: Positive
    lifetime_seconds: Positive
    tenant_parallel_lineages: Positive = 2
    lineage_parallel_calls: Literal[1] = 1
    lease_seconds: Positive = 60
    renew_seconds: Positive = 20
    next_tool_token_reserve: Positive = 2048
    min_safety_tokens: Positive = 1024
    window_safety_percent: Positive = Field(default=5, le=100)
    transient_attempt_limit: Positive = Field(default=2, le=3)
    max_backoff_seconds: Positive = 8
    wait_consumes_active_budget: Literal[False] = False
    resume_resets_budget: Literal[False] = False
    include_retries_and_seats: Literal[True] = True
    monetary_limit_microusd: Positive | None = None

    @model_validator(mode="after")
    def budget_is_feasible(self) -> Self:
        if self.input_token_limit + self.output_token_reserve > self.lineage_token_limit:
            raise ValueError("single_call_exceeds_lineage_budget")
        if self.renew_seconds >= self.lease_seconds:
            raise ValueError("renewal_must_precede_lease_expiry")
        if self.active_seconds > self.lifetime_seconds:
            raise ValueError("active_budget_exceeds_lifetime")
        return self

    def effective_input_limit(self, qualified_window: int) -> int:
        """Pure formula; caller must obtain a real qualification and token count."""
        if type(qualified_window) is not int or qualified_window <= 0:
            raise ValueError("qualified_window_required")
        safety = max(
            self.min_safety_tokens,
            (qualified_window * self.window_safety_percent + 99) // 100,
        )
        available = (
            qualified_window - self.output_token_reserve - self.next_tool_token_reserve - safety
        )
        if available <= 0:
            raise ValueError("qualified_window_insufficient")
        return min(self.input_token_limit, available)


class VersionedRateCard(PolicyPin):
    provider: Key
    model: Text
    unit: Literal["microusd_per_million_tokens"] = "microusd_per_million_tokens"
    status: Literal["priced", "unknown", "test_fixture"]
    input_rate: Nonnegative | None
    output_rate: Nonnegative | None
    cache_read_rate: Nonnegative | None = None
    cache_write_rate: Nonnegative | None = None
    source: Text | None
    effective_from: AwareDatetime

    @model_validator(mode="after")
    def unknown_is_not_free(self) -> Self:
        rates = (self.input_rate, self.output_rate, self.cache_read_rate, self.cache_write_rate)
        if self.status == "unknown":
            if any(rate is not None for rate in rates):
                raise ValueError("unknown_price_must_be_null")
        elif self.input_rate is None or self.output_rate is None or self.source is None:
            raise ValueError("priced_card_requires_rates_and_source")
        return self


class BudgetEntry(Contract):
    tenant_id: UUID
    lineage_id: UUID
    run_id: UUID
    attempt_id: UUID
    policy_version: Key
    reservation_status: Literal["reserved", "settled", "unknown", "cancelled_before_dispatch"]
    reserved_tokens: Positive
    charged_tokens: Nonnegative | None
    held_tokens: Nonnegative
    price_status: Literal["priced", "unknown", "test_fixture"]
    rate_card: PolicyPin | None
    reserved_cost_microusd: Nonnegative | None
    charged_cost_microusd: Nonnegative | None
    provider_request_id: Text | None
    reconciliation_ref: Text | None

    @model_validator(mode="after")
    def preserve_uncertain_usage(self) -> Self:
        if self.price_status == "unknown":
            if self.reserved_cost_microusd is not None or self.charged_cost_microusd is not None:
                raise ValueError("unknown_price_cost_must_be_null")
        elif self.rate_card is None or self.reserved_cost_microusd is None:
            raise ValueError("known_price_requires_versioned_reservation")
        if self.reservation_status in {"reserved", "unknown"}:
            if self.held_tokens != self.reserved_tokens:
                raise ValueError("unresolved_attempt_keeps_full_reservation")
            if self.charged_cost_microusd is not None:
                raise ValueError("unresolved_attempt_has_no_final_charge")
        elif self.held_tokens != 0 or self.charged_tokens is None:
            raise ValueError("terminal_entry_requires_usage_and_releases_hold")
        if self.reservation_status == "settled":
            if self.reconciliation_ref is None:
                raise ValueError("settlement_requires_usage_evidence")
            if self.price_status != "unknown" and self.charged_cost_microusd is None:
                raise ValueError("priced_settlement_requires_charge")
        if self.reservation_status == "cancelled_before_dispatch" and (
            self.charged_tokens != 0
            or self.provider_request_id is not None
            or self.charged_cost_microusd not in {None, 0}
        ):
            raise ValueError("pre_dispatch_cancellation_cannot_hide_usage")
        return self


class RetentionPolicy(PolicyPin):
    temporary_body_days: Positive
    metadata_days: Positive = 365
    retrieval_cache_seconds: Positive = 300
    display_cache_seconds: Positive = 86400
    inbox_archive_days: Positive = 14
    purge_enabled: Literal[False] = False
    reference_protection: Literal["business_policy_overrides_temporary_ttl"] = (
        "business_policy_overrides_temporary_ttl"
    )
    protected_records: tuple[
        Literal["body", "manifest", "observation", "compaction_index", "reference_mapping"], ...
    ] = ("body", "manifest", "observation", "compaction_index", "reference_mapping")
    revoked_cache: Literal["invalidate_immediately_reauthorize_each_use"] = (
        "invalidate_immediately_reauthorize_each_use"
    )
    mandatory_source_deletion: Literal["authorized_tombstone_and_invalidate_references"] = (
        "authorized_tombstone_and_invalidate_references"
    )

    @model_validator(mode="after")
    def protect_entire_evidence_chain(self) -> Self:
        required = {"body", "manifest", "observation", "compaction_index", "reference_mapping"}
        if set(self.protected_records) != required or len(self.protected_records) != 5:
            raise ValueError("full_reference_chain_protection_required")
        return self


class ImplementationBinding(Contract):
    status: Literal["planned", "implemented"]
    owner_module: Key
    handler: Text | None
    verification_ref: Text | None

    @model_validator(mode="after")
    def implementation_needs_evidence(self) -> Self:
        if self.status == "implemented" and (self.handler is None or self.verification_ref is None):
            raise ValueError("implemented_binding_requires_handler_and_evidence")
        return self


class ToolPolicy(PolicyPin):
    use_when: Text
    do_not_use_when: Text
    input_schema: PolicyPin
    output_schema: PolicyPin
    scope_policy: ScopePolicy
    side_effect: Literal["read", "simulate", "record_observation", "propose_finding"]
    binding: ImplementationBinding
    rollout: Literal["disabled", "shadow", "live"]
    timeout_seconds: Positive
    max_attempts: Positive = Field(le=3)
    max_payload_bytes: Positive
    idempotency: Literal["query_version", "run_call_digest", "finding_origin_digest"]
    cancellation: Literal["cooperative_with_lease_fence"] = "cooperative_with_lease_fence"
    citation_policy: Key
    freshness_policy: Key
    validator: Key
    egress_policy: PolicyPin
    retention_policy: PolicyPin
    budget_profile: PolicyPin
    hidden_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def bounded_tool(self) -> Self:
        if self.rollout == "live" and self.binding.status != "implemented":
            raise ValueError("live_tool_requires_implementation")
        if self.side_effect == "propose_finding" and self.idempotency != "finding_origin_digest":
            raise ValueError("finding_tool_requires_origin_idempotency")
        if self.side_effect == "record_observation" and self.idempotency != "run_call_digest":
            raise ValueError("observation_tool_requires_call_idempotency")
        return self


class EnginePolicy(PolicyPin):
    input_schema: PolicyPin
    output_schema: PolicyPin
    binding: ImplementationBinding
    algorithm_version: Key
    source_snapshot_required: Literal[True] = True
    unit_policy: Key
    calendar_policy: Key | None
    missing_input: Literal["explicit_partial_or_not_computable"] = (
        "explicit_partial_or_not_computable"
    )
    max_nodes: Positive
    max_edges: Positive
    timeout_seconds: Positive
    invokes_model: Literal[False] = False
    writes_business: Literal[False] = False


class HumanActionPolicy(PolicyPin):
    action_kind: Literal[
        "review", "apply", "publish", "professional_approval", "confirm_raw_import", "send"
    ]
    input_schema: PolicyPin
    output_schema: PolicyPin
    binding: ImplementationBinding
    scope_policy: ScopePolicy
    required_permission: Key
    current_source_and_target_check: Literal[True] = True
    model_callable: Literal[False] = False
    idempotency: Literal["tenant_action_key_digest"] = "tenant_action_key_digest"
    prior_review_required: bool
    evidence_policy: Key

    @model_validator(mode="after")
    def apply_is_independent(self) -> Self:
        if self.action_kind == "apply" and not self.prior_review_required:
            raise ValueError("apply_requires_prior_review")
        return self


class CapabilityPolicy(PolicyPin):
    semantic_keys: tuple[Key, ...] = Field(min_length=1)
    purpose: Text
    entry_points: tuple[Text, ...] = Field(min_length=1)
    triggers: tuple[Literal["user", "event", "scheduled", "authorized_run"], ...] = Field(
        min_length=1
    )
    deduplication: Key
    scope_policy: ScopePolicy
    context_builder: PolicyPin
    prompt: PolicyPin
    skill_pins: tuple[PolicyPin, ...] = ()
    tool_pins: tuple[PolicyPin, ...]
    output_schema: PolicyPin
    output_modes: tuple[Literal["read_only", "propose_finding"], ...] = Field(min_length=1)
    finding_types: tuple[Key, ...] = ()
    review_action: PolicyPin | None = None
    apply_action: PolicyPin | None = None
    zone: Literal["free", "hard_gate"]
    rollout: Literal["disabled", "shadow", "live"]
    binding: ImplementationBinding
    model_qualification: PolicyPin | None
    quality_profile: PolicyPin
    budget_profile: PolicyPin
    retention_policy: PolicyPin
    expiration_policy: Key
    manual_fallback: Text
    result_backlink: Text

    @model_validator(mode="after")
    def business_candidates_require_two_human_actions(self) -> Self:
        candidate = "propose_finding" in self.output_modes
        if candidate:
            if (
                not self.finding_types
                or self.review_action is None
                or self.apply_action is None
                or self.review_action == self.apply_action
                or self.zone != "hard_gate"
            ):
                raise ValueError("finding_capability_requires_separate_review_apply")
        elif self.finding_types or self.review_action or self.apply_action or self.zone != "free":
            raise ValueError("read_only_capability_has_no_business_approval")
        if self.rollout == "live" and (
            self.binding.status != "implemented" or self.model_qualification is None
        ):
            raise ValueError("live_capability_requires_implementation_and_qualification")
        for values in (self.semantic_keys, self.triggers, self.output_modes):
            if len(set(values)) != len(values):
                raise ValueError("duplicate_capability_declaration")
        if len({pin.key for pin in self.tool_pins}) != len(self.tool_pins):
            raise ValueError("duplicate_tool_pin")
        return self


class EgressPolicy(PolicyPin):
    source_acl_and_purpose_required: Literal[True] = True
    projection: PolicyPin
    internal_authorization_visible_to_model: Literal[False] = False
    credentials_visible_to_model: Literal[False] = False
    taint_inherited: Literal[True] = True
    public_research: Literal["default_allow_with_blocklist"] = "default_allow_with_blocklist"
    public_http_method: Literal["GET"] = "GET"
    public_credentials_allowed: Literal[False] = False
    public_all_seats: Literal[True] = True
    first_domain_approval: Literal[False] = False
    each_redirect_and_all_resolved_ips_checked: Literal[True] = True
    block_private_login_and_executable: Literal[True] = True
    max_public_bytes: Positive = 2 * 1024 * 1024
    max_redirects: Nonnegative = 3
    unavailable_is_zero_results: Literal[False] = False


class DebatePolicy(PolicyPin):
    initiation: Literal["inside_authorized_run"] = "inside_authorized_run"
    business_scenario_allowlist: Literal[False] = False
    outside_run_messages: Literal[False] = False
    new_internal_scope: Literal["new_authorized_linked_run"] = "new_authorized_linked_run"
    shared_lineage_budget: Literal[True] = True
    stop_on_no_evidence_increment: Literal[True] = True
    visible_output: Literal["brief_sources_disagreements_tradeoffs_progress"] = (
        "brief_sources_disagreements_tradeoffs_progress"
    )
    hidden_chain_of_thought_visible: Literal[False] = False


class PolicyCatalog(PolicyPin):
    """Cross-register document validation, not a runtime policy loader."""

    status: Literal["candidate"] = "candidate"
    budgets: tuple[RunBudgetProfile, ...]
    retentions: tuple[RetentionPolicy, ...]
    egress_policies: tuple[EgressPolicy, ...]
    tools: tuple[ToolPolicy, ...]
    engines: tuple[EnginePolicy, ...]
    human_actions: tuple[HumanActionPolicy, ...]
    capabilities: tuple[CapabilityPolicy, ...]
    debate_policy: DebatePolicy

    @model_validator(mode="after")
    def references_and_write_boundaries(self) -> Self:
        def index(values: tuple[PolicyPin, ...]) -> dict[str, PolicyPin]:
            result = {value.key: value for value in values}
            if len(result) != len(values):
                raise ValueError("duplicate_registry_key")
            return result

        def resolve(pin: PolicyPin, values: dict[str, PolicyPin]) -> PolicyPin:
            target = values.get(pin.key)
            if target is None or target.version != pin.version:
                raise ValueError(f"unresolved_policy_pin:{pin.key}:{pin.version}")
            return target

        budgets, retentions, egress, tools, actions = (
            index(values)
            for values in (
                self.budgets,
                self.retentions,
                self.egress_policies,
                self.tools,
                self.human_actions,
            )
        )
        index(self.engines)
        index(self.capabilities)
        if tools.keys() & actions.keys():
            raise ValueError("human_action_key_cannot_be_a_model_tool")
        for registered_tool in self.tools:
            resolve(registered_tool.budget_profile, budgets)
            resolve(registered_tool.retention_policy, retentions)
            resolve(registered_tool.egress_policy, egress)
        for capability in self.capabilities:
            resolve(capability.budget_profile, budgets)
            resolve(capability.retention_policy, retentions)
            for pin in capability.tool_pins:
                tool = resolve(pin, tools)
                assert isinstance(tool, ToolPolicy)
                if not set(capability.scope_policy.allowed_scopes).issubset(
                    tool.scope_policy.allowed_scopes
                ):
                    raise ValueError("tool_scope_does_not_cover_capability")
                if capability.rollout == "live" and tool.rollout != "live":
                    raise ValueError("live_capability_cannot_use_unavailable_tool")
                if (
                    tool.side_effect == "propose_finding"
                    and "propose_finding" not in capability.output_modes
                ):
                    raise ValueError("read_only_capability_cannot_use_finding_tool")
            for action_pin, kind in (
                (capability.review_action, "review"),
                (capability.apply_action, "apply"),
            ):
                if action_pin is None:
                    continue
                action = resolve(action_pin, actions)
                assert isinstance(action, HumanActionPolicy)
                if action.action_kind != kind:
                    raise ValueError("candidate_action_kind_mismatch")
                if not set(capability.scope_policy.allowed_scopes).issubset(
                    action.scope_policy.allowed_scopes
                ):
                    raise ValueError("human_action_scope_does_not_cover_capability")
        return self
