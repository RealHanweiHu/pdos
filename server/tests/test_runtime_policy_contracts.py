from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.runtime_policy import (
    BudgetEntry,
    CapabilityPolicy,
    DebatePolicy,
    EgressPolicy,
    HumanActionPolicy,
    PolicyCatalog,
    RetentionPolicy,
    RunBudgetProfile,
    ScopePolicy,
    ToolPolicy,
    VersionedRateCard,
)


def pin(key: str) -> dict[str, str]:
    return {"key": key, "version": "v1"}


def budget() -> dict[str, Any]:
    return {
        **pin("short"),
        "input_token_limit": 16000,
        "output_token_reserve": 2000,
        "lineage_token_limit": 60000,
        "tool_call_limit": 8,
        "model_call_limit": 3,
        "active_seconds": 120,
        "lifetime_seconds": 86400,
    }


def binding() -> dict[str, Any]:
    return {"status": "planned", "owner_module": "ai", "handler": None, "verification_ref": None}


def tool(effect: str = "read") -> dict[str, Any]:
    return {
        **pin("evidence.read"),
        "use_when": "Need current authorized evidence",
        "do_not_use_when": "Need to approve or write a business object",
        "input_schema": pin("EvidenceInput"),
        "output_schema": pin("EvidenceOutput"),
        "scope_policy": {"allowed_scopes": ["project"]},
        "side_effect": effect,
        "binding": binding(),
        "rollout": "disabled",
        "timeout_seconds": 10,
        "max_attempts": 2,
        "max_payload_bytes": 65536,
        "idempotency": "finding_origin_digest" if effect == "propose_finding" else "query_version",
        "citation_policy": "source-version-required",
        "freshness_policy": "current-source",
        "validator": "evidence-output-v1",
        "egress_policy": pin("outbound"),
        "retention_policy": pin("standard"),
        "budget_profile": pin("short"),
    }


def capability(candidate: bool = False) -> dict[str, Any]:
    return {
        **pin("quality.explain"),
        "semantic_keys": ["test_quality"],
        "purpose": "Explain test evidence with citations",
        "entry_points": ["verification panel"],
        "triggers": ["user"],
        "deduplication": "request_source_version",
        "scope_policy": {"allowed_scopes": ["project"]},
        "context_builder": pin("quality_context"),
        "prompt": pin("quality_prompt"),
        "tool_pins": [pin("evidence.read")],
        "output_schema": pin("QualityOutput"),
        "output_modes": ["read_only", "propose_finding"] if candidate else ["read_only"],
        "finding_types": ["test_plan_change"] if candidate else [],
        "review_action": pin("finding.review") if candidate else None,
        "apply_action": pin("finding.apply") if candidate else None,
        "zone": "hard_gate" if candidate else "free",
        "rollout": "disabled",
        "binding": binding(),
        "model_qualification": None,
        "quality_profile": pin("quality_evidence"),
        "budget_profile": pin("short"),
        "retention_policy": pin("standard"),
        "expiration_policy": "critical_source_target_version",
        "manual_fallback": "Read original test records and edit a plan manually",
        "result_backlink": "project verification evidence",
    }


def action(kind: str) -> dict[str, Any]:
    return {
        **pin(f"finding.{kind}"),
        "action_kind": kind,
        "input_schema": pin("ActionInput"),
        "output_schema": pin("ActionOutput"),
        "binding": binding(),
        "scope_policy": {"allowed_scopes": ["project"]},
        "required_permission": f"finding.{kind}",
        "prior_review_required": kind == "apply",
        "evidence_policy": "current_approval_and_sources",
    }


def catalog(candidate: bool = False) -> dict[str, Any]:
    return {
        **pin("runtime-policy"),
        "budgets": [budget()],
        "retentions": [{**pin("standard"), "temporary_body_days": 90}],
        "egress_policies": [{**pin("outbound"), "projection": pin("projected_context")}],
        "tools": [tool()],
        "engines": [],
        "human_actions": [action("review"), action("apply")],
        "capabilities": [capability(candidate)],
        "debate_policy": pin("discussion"),
    }


@pytest.mark.parametrize("boundary", ["tool", "model_egress", "disclosure", "export", "apply"])
def test_revocation_cannot_be_skipped_at_any_boundary(boundary: str) -> None:
    required = ["tool", "model_egress", "disclosure", "export", "apply"]
    with pytest.raises(ValidationError, match="all_acl_boundaries_required"):
        ScopePolicy.model_validate(
            {
                "allowed_scopes": ["project"],
                "current_acl_checks": [s for s in required if s != boundary],
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"persona_grants_permissions": True},
        {"principal_source": "model_argument"},
        {"delegation": "delegate_role_only"},
        {"project_role_set": "union"},
    ],
)
def test_identity_cannot_expand_authority(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScopePolicy.model_validate({"allowed_scopes": ["project"], **change})


def test_qualified_window_accounts_for_all_reserves() -> None:
    profile = RunBudgetProfile.model_validate(budget())
    assert profile.effective_input_limit(10000) == 4928
    assert profile.effective_input_limit(128000) == 16000
    with pytest.raises(ValueError, match="qualified_window_insufficient"):
        profile.effective_input_limit(4000)
    for value in (0, -1, True):
        with pytest.raises(ValueError, match="qualified_window_required"):
            profile.effective_input_limit(value)


@pytest.mark.parametrize(
    "change",
    [
        {"resume_resets_budget": True},
        {"include_retries_and_seats": False},
        {"lineage_parallel_calls": 2},
        {"renew_seconds": 60},
        {"lineage_token_limit": 1000},
        {"active_seconds": 100000},
    ],
)
def test_resume_and_invalid_profiles_cannot_bypass_budget(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RunBudgetProfile.model_validate({**budget(), **change})


def rate_card() -> dict[str, Any]:
    return {
        **pin("provider.model.pricing"),
        "provider": "openrouter",
        "model": "provider/model-name",
        "status": "unknown",
        "input_rate": None,
        "output_rate": None,
        "source": None,
        "effective_from": "2026-09-10T00:00:00Z",
    }


def test_unknown_prices_are_not_free_but_sourced_zero_can_be_real() -> None:
    VersionedRateCard.model_validate(rate_card())
    with pytest.raises(ValidationError, match="unknown_price_must_be_null"):
        VersionedRateCard.model_validate({**rate_card(), "input_rate": 0, "output_rate": 0})
    with pytest.raises(ValidationError, match="priced_card_requires_rates_and_source"):
        VersionedRateCard.model_validate({**rate_card(), "status": "priced"})
    result = VersionedRateCard.model_validate(
        {
            **rate_card(),
            "status": "priced",
            "input_rate": 0,
            "output_rate": 0,
            "source": "approved tariff",
        }
    )
    assert result.input_rate == 0


def entry() -> dict[str, Any]:
    return {
        "tenant_id": uuid4(),
        "lineage_id": uuid4(),
        "run_id": uuid4(),
        "attempt_id": uuid4(),
        "policy_version": "v1",
        "reservation_status": "unknown",
        "reserved_tokens": 18000,
        "charged_tokens": None,
        "held_tokens": 18000,
        "price_status": "unknown",
        "rate_card": None,
        "reserved_cost_microusd": None,
        "charged_cost_microusd": None,
        "provider_request_id": "request-timeout",
        "reconciliation_ref": None,
    }


def test_timeout_keeps_hold_and_settlement_requires_evidence() -> None:
    original = BudgetEntry.model_validate(entry())
    for change in ({"held_tokens": 0}, {"charged_cost_microusd": 0}):
        with pytest.raises(ValidationError):
            BudgetEntry.model_validate({**original.model_dump(), **change})
    settled = {
        **original.model_dump(),
        "reservation_status": "settled",
        "held_tokens": 0,
        "charged_tokens": 9000,
    }
    with pytest.raises(ValidationError, match="settlement_requires_usage_evidence"):
        BudgetEntry.model_validate(settled)
    result = BudgetEntry.model_validate(
        {**settled, "reconciliation_ref": "provider usage statement"}
    )
    assert result.charged_cost_microusd is None
    assert original.held_tokens == 18000
    with pytest.raises(ValidationError, match="pre_dispatch_cancellation_cannot_hide_usage"):
        BudgetEntry.model_validate(
            {**settled, "reservation_status": "cancelled_before_dispatch", "charged_tokens": 0}
        )


@pytest.mark.parametrize(
    "protected", ["body", "manifest", "observation", "compaction_index", "reference_mapping"]
)
def test_retention_protects_entire_replay_chain(protected: str) -> None:
    policy = RetentionPolicy.model_validate({**pin("standard"), "temporary_body_days": 90})
    with pytest.raises(ValidationError, match="full_reference_chain_protection_required"):
        RetentionPolicy.model_validate(
            {
                **policy.model_dump(),
                "protected_records": [p for p in policy.protected_records if p != protected],
            }
        )
    with pytest.raises(ValidationError):
        RetentionPolicy.model_validate({**policy.model_dump(), "purge_enabled": True})


@pytest.mark.parametrize("effect", ["apply", "send", "write_business", "approve", "create_draft"])
def test_model_tools_cannot_write_formal_business(effect: str) -> None:
    with pytest.raises(ValidationError):
        ToolPolicy.model_validate(tool(effect))


def test_read_only_needs_no_review_and_candidate_needs_two_actions() -> None:
    CapabilityPolicy.model_validate(capability())
    CapabilityPolicy.model_validate(capability(True))
    for change in (
        {"review_action": None},
        {"apply_action": pin("finding.review")},
        {"zone": "free"},
    ):
        with pytest.raises(
            ValidationError, match="finding_capability_requires_separate_review_apply"
        ):
            CapabilityPolicy.model_validate({**capability(True), **change})
    with pytest.raises(ValidationError, match="read_only_capability_has_no_business_approval"):
        CapabilityPolicy.model_validate({**capability(), "review_action": pin("finding.review")})
    with pytest.raises(ValidationError):
        HumanActionPolicy.model_validate({**action("apply"), "model_callable": True})


def test_live_label_needs_implementation_and_qualification() -> None:
    with pytest.raises(
        ValidationError, match="live_capability_requires_implementation_and_qualification"
    ):
        CapabilityPolicy.model_validate({**capability(), "rollout": "live"})
    with pytest.raises(ValidationError, match="live_tool_requires_implementation"):
        ToolPolicy.model_validate({**tool(), "rollout": "live"})


def test_cross_registry_scope_versions_and_write_boundaries() -> None:
    PolicyCatalog.model_validate(catalog())
    PolicyCatalog.model_validate(catalog(True))
    cases = []
    changed = catalog()
    changed["capabilities"][0]["budget_profile"]["version"] = "v2"
    cases.append((changed, "unresolved_policy_pin"))
    changed = catalog()
    changed["capabilities"][0]["scope_policy"]["allowed_scopes"] = ["tenant"]
    cases.append((changed, "tool_scope_does_not_cover_capability"))
    changed = catalog()
    changed["tools"][0]["key"] = "finding.apply"
    cases.append((changed, "human_action_key_cannot_be_a_model_tool"))
    changed = catalog()
    changed["tools"] = [tool("propose_finding")]
    cases.append((changed, "read_only_capability_cannot_use_finding_tool"))
    changed = catalog(True)
    changed["human_actions"][0]["action_kind"] = "publish"
    cases.append((changed, "candidate_action_kind_mismatch"))
    changed = catalog()
    changed["budgets"] *= 2
    cases.append((changed, "duplicate_registry_key"))
    for value, error in cases:
        with pytest.raises(ValidationError, match=error):
            PolicyCatalog.model_validate(value)


def test_reach_and_debate_keep_approved_defaults() -> None:
    EgressPolicy.model_validate({**pin("outbound"), "projection": pin("context")})
    for change in (
        {"first_domain_approval": True},
        {"public_http_method": "POST"},
        {"unavailable_is_zero_results": True},
    ):
        with pytest.raises(ValidationError):
            EgressPolicy.model_validate({**pin("outbound"), "projection": pin("context"), **change})
    DebatePolicy.model_validate(pin("discussion"))
    for change in (
        {"business_scenario_allowlist": True},
        {"outside_run_messages": True},
        {"hidden_chain_of_thought_visible": True},
    ):
        with pytest.raises(ValidationError):
            DebatePolicy.model_validate({**pin("discussion"), **change})
