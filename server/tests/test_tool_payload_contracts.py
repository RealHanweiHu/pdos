from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts import tool_payloads as dto
from app.contracts.capability_matrix import (
    CAPABILITY_ROWS,
    HARD_GATE_ROWS,
    TOOL_ROWS,
    capabilities,
    legacy_dispositions,
    tools,
)
from app.contracts.runtime_policy import (
    DebatePolicy,
    EgressPolicy,
    HumanActionPolicy,
    PolicyCatalog,
    RetentionPolicy,
    RunBudgetProfile,
)
from scripts.export_runtime_policy_contracts import profile_candidates

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads((ROOT / "docs/contracts/pdos-runtime-v1/tool-examples.json").read_text())[
    "examples"
]
HANDLE = {"handle": "sample.ref", "version": 1}


@pytest.mark.parametrize("row", TOOL_ROWS, ids=[row[0] for row in TOOL_ROWS])
def test_all_tool_inputs_have_valid_examples_and_reject_self_reported_authority(row: Any) -> None:
    key, input_name, output_name, *_ = row
    model = getattr(dto, input_name)
    model.model_validate(EXAMPLES[key])
    assert hasattr(dto, output_name)
    for field in ("tenant_id", "project_id", "approved_by", "role", "principal_id"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model.model_validate({**EXAMPLES[key], field: "self-reported"})


def test_scoped_handle_and_citation_do_not_accept_unversioned_claims() -> None:
    with pytest.raises(ValidationError, match="public_capture_cannot_include_credentials"):
        dto.CaptureSnapshotInput.model_validate(
            {"url": "https://user:secret@example.com/page", "purpose": "public evidence"}
        )
    with pytest.raises(ValidationError, match="handle_requires_version_or_digest"):
        dto.BoundHandle.model_validate({"handle": "arbitrary"})
    with pytest.raises(ValidationError, match="factual_statement_requires_citation"):
        dto.CitedStatement.model_validate({"text": "passed", "nature": "observed", "citations": []})
    dto.CitedStatement.model_validate(
        {"text": "待验证假设", "nature": "hypothesis", "citations": []}
    )


def test_candidate_cannot_include_approval_or_actual_test_result() -> None:
    for key, field in (
        ("product.prepare_definition", "approved_by_user_id"),
        ("verification.prepare_plan_change", "actual_results"),
        ("planning.prepare_initial_plan", "baseline_approved"),
        ("reports.preview_import", "create_batch"),
    ):
        row = next(r for r in TOOL_ROWS if r[0] == key)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            getattr(dto, row[1]).model_validate({**EXAMPLES[key], field: True})


def test_plan_draft_rejects_orphan_cycles_and_unfounded_estimates() -> None:
    draft = deepcopy(EXAMPLES["planning.prepare_initial_plan"]["draft"])
    dto.PlanDraft.model_validate(draft)
    for edge, error in (
        ({"predecessor": "ID", "successor": "unknown"}, "draft_dependency_orphan"),
        ({"predecessor": "ID", "successor": "ID"}, "draft_dependency_cycle"),
    ):
        with pytest.raises(ValidationError, match=error):
            dto.PlanDraft.model_validate(
                {
                    **draft,
                    "dependencies": [
                        {**edge, "relation": "fs", "lag": "0", "lag_unit": "working_hours"}
                    ],
                }
            )
    draft["tasks"][0]["effort_hours"] = "12"
    with pytest.raises(ValidationError, match="task_estimate_requires_basis"):
        dto.PlanDraft.model_validate(draft)


def result(data: dict[str, Any] | None, status: str = "completed") -> dict[str, Any]:
    return {
        "operation_id": "op1",
        "tool_call_id": "call1",
        "tool_version": "candidate.v2",
        "status": status,
        "data": data,
        "evidence_refs": [],
        "source_versions": [],
        "as_of": "2026-09-10T00:00:00Z",
        "continuation": None,
        "error": None,
        "usage": {
            "elapsed_ms": 20,
            "payload_bytes": 10,
            "tool_cost_microusd": None,
            "price_status": "unknown",
        },
    }


def test_unavailable_search_is_not_zero_hits_and_snippets_are_not_citable() -> None:
    data = {"kind": "search", "hits": [], "query": "test", "provider_version": "v1"}
    dto.SearchSourcesResult.model_validate(result(data, "zero_results"))
    with pytest.raises(ValidationError, match="successful_tool_requires_data_without_error"):
        dto.SearchSourcesResult.model_validate(
            {
                **result(data, "zero_results"),
                "error": {"code": "tool_unavailable", "message": "no provider", "retryable": False},
            }
        )
    hit = {
        "url": "https://example.com/page",
        "title": "test",
        "snippet": "unverified",
        "citable": True,
    }
    with pytest.raises(ValidationError):
        dto.SearchHit.model_validate(hit)
    with pytest.raises(ValidationError, match="zero_results_has_search_hits"):
        dto.SearchSourcesResult.model_validate(
            result({**data, "hits": [{**hit, "citable": False}]}, "zero_results")
        )


def test_unknown_cost_and_uncomputable_dates_are_not_fabricated() -> None:
    with pytest.raises(ValidationError, match="unknown_tool_cost_must_be_null"):
        dto.ToolUsage.model_validate(
            {
                "elapsed_ms": 10,
                "payload_bytes": 10,
                "tool_cost_microusd": 0,
                "price_status": "unknown",
            }
        )
    data = {
        "kind": "scenario",
        "input_digest": "a" * 64,
        "algorithm_version": "v1",
        "completeness": "not_computable",
        "node_times": [],
        "critical_path": [],
        "conflicts": [],
        "missing": ["calendar"],
    }
    dto.ScenarioData.model_validate(data)
    with pytest.raises(ValidationError, match="uncomputable_scenario_cannot_invent_dates"):
        dto.ScenarioData.model_validate(
            {
                **data,
                "node_times": [{"node_key": "ID", "start": None, "end": "2026-09-11T00:00:00Z"}],
            }
        )


def test_import_preview_preserves_blank_and_zero_as_different_raw_values() -> None:
    cells = [
        {"locator": f"A{i}", "original_text": value, "mapped_item": None, "issue": None}
        for i, value in enumerate(("", "0", "N/A", "23.40 °C", " 0 ", "\n"))
    ]
    preview = dto.ImportPreviewData.model_validate(
        {"batch": HANDLE, "mapping_status": "missing", "cells": cells, "missing": ["mapping"]}
    )
    assert [cell.original_text for cell in preview.cells] == [
        "",
        "0",
        "N/A",
        "23.40 °C",
        " 0 ",
        "\n",
    ]


def test_brief_keeps_dissent_and_does_not_self_approve() -> None:
    statement = {"text": "待验证取舍", "nature": "hypothesis", "citations": [HANDLE]}
    data = {
        "topic": "更改方案",
        "context": [statement],
        "consensus": [],
        "options": [
            {
                "option_key": "A",
                "proposal": statement,
                "benefits": [],
                "costs": [statement],
                "dissent": [statement],
            }
        ],
        "recommended_option": "A",
        "rationale": [statement],
        "unresolved": ["成本待确认"],
        "source_handles": [HANDLE],
        "intended_use": "read_only",
        "finding": None,
        "stop_reason": "missing_input",
    }
    brief = dto.DecisionBrief.model_validate(data)
    assert len(brief.options[0].dissent) == 1
    with pytest.raises(ValidationError, match="brief_business_proposal_requires_finding"):
        dto.DecisionBrief.model_validate({**data, "intended_use": "business_proposal"})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        dto.DecisionBrief.model_validate({**data, "approved": True})


def test_design_semantics_legacy_keys_and_closed_hard_gates_are_covered() -> None:
    design = (ROOT / "docs/design/2026-09-10-pdos-complete-design-contract.md").read_text()
    appendix = design.split("## 附录 A")[1].split("## 附录 B")[0]
    import re

    semantics = set(re.findall(r"\| `([a-z_]+)` \|", appendix))
    assert {row[0] for row in CAPABILITY_ROWS} == semantics
    assert len(semantics) == 27
    assert len(legacy_dispositions()) == 13
    assert len(HARD_GATE_ROWS) == 14
    assert len(tools()) == len(EXAMPLES) == 14
    assert all(c.rollout == "disabled" and c.model_qualification is None for c in capabilities())


def test_target_matrix_references_the_candidate_profile_versions_and_scope() -> None:
    version = "candidate.v2"

    def pin(key: str) -> dict[str, str]:
        return {"key": key, "version": version}

    actions = [
        HumanActionPolicy.model_validate(
            {
                **pin(f"finding.{kind}"),
                "action_kind": kind,
                "input_schema": pin("human_action.input"),
                "output_schema": pin("human_action.output"),
                "binding": {
                    "status": "planned",
                    "owner_module": "findings",
                    "handler": None,
                    "verification_ref": None,
                },
                "scope_policy": {
                    "allowed_scopes": [
                        "tenant",
                        "market_space",
                        "product_line",
                        "opportunity",
                        "product_definition",
                        "portfolio",
                        "project",
                    ]
                },
                "required_permission": f"finding.{kind}",
                "prior_review_required": kind == "apply",
                "evidence_policy": "current_versions",
            }
        )
        for kind in ("review", "apply")
    ]
    PolicyCatalog.model_validate(
        {
            **pin("runtime"),
            "budgets": [
                RunBudgetProfile.model_validate({**p.model_dump(), "version": version})
                for p in profile_candidates()
            ],
            "retentions": [
                RetentionPolicy.model_validate({**pin("standard"), "temporary_body_days": 90})
            ],
            "egress_policies": [
                EgressPolicy.model_validate(
                    {**pin("source_aware_egress"), "projection": pin("projection")}
                )
            ],
            "tools": tools(),
            "engines": [],
            "human_actions": actions,
            "capabilities": capabilities(),
            "debate_policy": DebatePolicy.model_validate(pin("discussion")),
        }
    )
