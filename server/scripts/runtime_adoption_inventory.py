"""Read-only N0-02 component/source, human-action and event adoption inventory."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.ai.capability_contract import CAPABILITY_CONTRACTS, CapabilityKey, capabilities_for_event
from app.auth.roles import Action, Role, allowed_actions
from app.contracts.capability_matrix import (
    CAPABILITY_ROWS,
    LEGACY_CAPABILITY_KEYS,
    LEGACY_SEMANTICS,
)
from app.contracts.runtime_adoption import TRIGGER_POLICIES, ComponentSource
from app.domain.findings import FindingService
from app.events.catalog import EVENT_REGISTRY

ROOT = Path(__file__).resolve().parents[2]


def component(
    key: str, path: str, symbol: str | None = None, *, work: str = "N0-03"
) -> dict[str, Any]:
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT) or target.suffix not in {".py", ".json"}:
        raise ValueError("component source must be repository Python or JSON")
    body = target.read_bytes()
    line = None
    version = None
    if symbol:
        nodes = ast.parse(body).body
        for part in symbol.split("."):
            found = next(
                (
                    node
                    for node in nodes
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == part
                ),
                None,
            )
            if found is None:
                raise ValueError(f"component symbol missing: {path}:{symbol}")
            line = found.lineno
            nodes = found.body
    if target.suffix == ".json":
        data = json.loads(body)
        version = data.get("version") or data.get("suite_version")
    value = ComponentSource(
        key=key,
        status="present",
        path=path,
        symbol=symbol,
        sha256=sha256(body).hexdigest(),
        version=version,
        implementation_work=work,
    ).model_dump(mode="json")
    return {**value, "line": line, "evidence_level": "source_present_not_runtime_verified"}


def planned(key: str, work: str) -> dict[str, Any]:
    return ComponentSource(
        key=key,
        status="planned",
        path=None,
        symbol=None,
        sha256=None,
        version=None,
        implementation_work=work,
    ).model_dump(mode="json")


def legacy_components() -> list[dict[str, Any]]:
    result = []
    for key, contract in CAPABILITY_CONTRACTS.items():
        # This section describes the original thirteen capabilities. Later
        # domain workflows do not use the legacy event worker or agent prompt.
        if key not in LEGACY_CAPABILITY_KEYS:
            continue
        prompt_file = f"server/app/ai/prompts/{contract.agent_key.value}_v1.json"
        handler_path, handler = "server/app/ai/executor.py", "AgentExecutor.execute_next"
        context_path, context = "server/app/ai/context_builder.py", "RunContextBuilder.build"
        output_path, output = "server/app/ai/executor.py", "AgentAssessment"
        if key == CapabilityKey.PROJECT_RISK_SUGGESTION_API:
            prompt_file = "server/app/ai/prompts/risk_suggestion_api_v1.json"
            handler_path, handler = (
                "server/app/ai/risk_suggestions.py",
                "RiskSuggestionService.create",
            )
            context_path, context = handler_path, "RiskSuggestionService._build_context"
        elif key == CapabilityKey.QUALITY_TEST_PLAN_CHANGE:
            prompt_file = "server/app/ai/prompts/test_plan_change_v5.json"
            handler_path, handler = (
                "server/app/ai/test_plan_suggestions.py",
                "TestPlanSuggestionService.create",
            )
            context_path, context = "server/app/domain/test_plan_changes.py", "plan_state"
            output_path, output = context_path, "TestPlanModelAssessment"
        elif key == CapabilityKey.QUALITY_TEST_REPORT_IMPORT:
            prompt_file = "server/app/ai/prompts/test_report_import_v1.json"
            handler_path, handler = (
                "server/app/domain/test_report_import.py",
                "TestReportImportService._parse_import",
            )
            context_path, context = handler_path, handler
            output_path, output = handler_path, "ExcelImportMapping"
        prompt = component("prompt", prompt_file)
        if prompt["version"] != contract.prompt_version:
            raise ValueError(f"registered prompt version drift: {key}")
        result.append(
            {
                "key": key.value,
                "current_rollout": contract.rollout.value,
                "prompt": prompt,
                "context": component("context", context_path, context),
                "model_output": component("model_output", output_path, output),
                "handler": component("handler", handler_path, handler),
                "projection": component(
                    "projection", "server/app/ai/context_projection.py", "project_gateway_context"
                ),
                "tool_declarations": component(
                    "toolset", "server/app/ai/tools.py", "tool_definitions_for_agent"
                ),
                "quality": component(
                    "quality", "server/app/ai/quality.py", "FindingQualityService"
                ),
                "current_qualification": component(
                    "provider_qualification", "server/golden/model-qualifications.json"
                ),
                "qualification_limitation": "provider suite only; capability qualification pending",
                "adoption_work": "N0-03 plus mapped domain items",
                "activation": "keep_current_version_until_candidate_bundle_verified_and_adopted",
            }
        )
    return result


ACTION_ROWS = (
    (
        "finding.review",
        Action.FINDING_REVIEW,
        "server/app/domain/findings.py",
        "FindingService.review",
        "server/app/api/findings.py",
        "FindingReviewRequest",
    ),
    (
        "finding.apply",
        Action.FINDING_APPLY,
        "server/app/domain/findings.py",
        "FindingService.apply",
        "server/app/api/findings.py",
        "FindingApplyResponse",
    ),
    (
        "gate.sign",
        Action.GATE_SIGN,
        "server/app/domain/gates.py",
        "GateService.sign",
        "server/app/api/gates.py",
        "GateSignRequest",
    ),
    (
        "gate.decide",
        Action.GATE_MANAGE,
        "server/app/domain/gates.py",
        "GateService.decide",
        "server/app/api/gates.py",
        "GateDecisionRequest",
    ),
    (
        "ecn.effectivity",
        Action.CHANGE_APPROVE,
        "server/app/domain/change_governance.py",
        "ChangeGovernanceService.decide_effectivity",
        "server/app/api/change_governance.py",
        "EffectivityDecisionRequest",
    ),
    (
        "issue.close",
        Action.ISSUE_VERIFY,
        "server/app/domain/issues.py",
        "IssueService.transition",
        "server/app/api/issue_risks.py",
        None,
    ),
    (
        "test_run.record",
        Action.PRODUCT_ENGINEERING_EDIT,
        "server/app/api/npi_execution.py",
        "record_test_run",
        "server/app/api/npi_execution.py",
        "TestRunCreateRequest",
    ),
    (
        "test_run.complete",
        Action.PRODUCT_ENGINEERING_EDIT,
        "server/app/api/npi_execution.py",
        "complete_test_run",
        "server/app/api/npi_execution.py",
        "TestRunCompleteRequest",
    ),
    (
        "report_import.confirm",
        Action.PRODUCT_ENGINEERING_EDIT,
        "server/app/domain/test_report_import.py",
        "TestReportImportService.confirm",
        "server/app/api/npi_execution.py",
        "ImportBatchResponse",
    ),
)


def human_actions() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "model_callable": False,
            "current_permission": permission.value,
            "current_role_candidates": [
                role.value for role in Role if permission in allowed_actions(role)
            ],
            "current_scope": "project; further current membership/domain guards required",
            "handler": component("handler", path, symbol),
            "api_contract": component("api_contract", api_path, schema),
            "additional_guards": "actor/source/target/policy and applicable independent signoff",
            "target_permission_change": "narrow Quality test_run/import permissions in N0-04"
            if key.startswith(("test_run.", "report_import."))
            else None,
        }
        for key, permission, path, symbol, api_path, schema in ACTION_ROWS
    ]


MILESTONES = frozenset(
    {
        "PROJECT_STAGE_CHANGED",
        "GATE_APPROVED",
        "TEST_FAILED",
        "ISSUE_CREATED",
        "ISSUE_STATUS_CHANGED",
        "SUPPLIER_DELAY_REPORTED",
        "COMPLAINT_CREATED",
        "NCR_CREATED",
        "CHANGE_RECORD_CHANGED",
    }
)
FREQUENT_EDITS = frozenset(
    {"DEVELOPMENT_BOM_CREATED", "DEVELOPMENT_BOM_ITEM_ADDED", "DOCUMENT_UPLOADED"}
)
CONTROL_EVENTS = frozenset(
    {"USER_DELEGATION_REVOKED", "USER_UPDATED", "TENANT_MODEL_SETTINGS_UPDATED"}
)


def events() -> list[dict[str, Any]]:
    result = []
    for key in sorted(EVENT_REGISTRY):
        routes = [route.value for route in capabilities_for_event(key)]
        if key in CONTROL_EVENTS:
            policy, reason = "control", "refresh/revoke affected authorization; no model on cleanup"
        elif routes:
            if key in MILESTONES:
                policy, reason = "milestone", "current routed milestone/change needs prompt outcome"
            elif key in FREQUENT_EDITS:
                policy, reason = (
                    "frequent_edit",
                    "coalesce document/BOM edits; explicit user request stays immediate",
                )
            else:
                raise ValueError(f"routed event lacks explicit trigger policy: {key}")
        else:
            policy, reason = (
                "no_model_route",
                "preserve current no-route; domain rule/event consumers unaffected",
            )
        result.append(
            {
                "event": key,
                "current_capabilities": routes,
                "proposed_trigger_policy": policy,
                "reason": reason,
                "status": (
                    "local_event_policy_wired"
                    if routes and policy in {"milestone", "frequent_edit"}
                    else "candidate_not_dispatcher_wired"
                ),
            }
        )
    return result


def inventory() -> dict[str, Any]:
    legacy = legacy_components()
    targets = []
    for row in CAPABILITY_ROWS:
        semantic, work = row[0], row[9]
        reuse = [
            key.value
            for key, semantics in LEGACY_SEMANTICS.items()
            if key in LEGACY_CAPABILITY_KEYS and semantic in semantics
        ]
        targets.append(
            {
                "semantic": semantic,
                "implementation_work": work,
                "partial_reuse_legacy_keys": reuse,
                "components": [
                    planned(f"{semantic}.{kind}", work)
                    for kind in ("context", "prompt", "model_output", "handler", "quality_suite")
                ],
                "common_tool_payload_source": component(
                    "tool_payloads", "server/app/contracts/tool_payloads.py", work=work
                ),
                "model_qualification": None,
                "candidate_activation": "disabled_until_all_components_and_qualification_verified",
                "domain_adoption_requires": [
                    "typed_payload_not_generic_risk",
                    "current_scope_acl",
                    "source_validity",
                    "qualified_model_and_golden",
                    "budget_and_trace",
                    "manual_fallback",
                    "human_review_apply_if_business",
                ],
            }
        )
    return {
        "status": "candidate_adoption_contract_not_runtime_enablement",
        "legacy_components": legacy,
        "target_components": targets,
        "human_actions": human_actions(),
        "apply_adapters": [
            {
                "payload": payload.__name__,
                "target": target,
                "source": component(
                    "adapter",
                    f"server/{adapter.__module__.replace('.', '/')}.py",
                    adapter.__qualname__,
                ),
            }
            for payload, (target, adapter) in FindingService._APPLY_ADAPTERS.items()
        ],
        "engines": [
            {"key": key, "source": component(key, path, symbol), "reuse_boundary": boundary}
            for key, path, symbol, boundary in (
                (
                    "gate_readiness",
                    "server/app/domain/gates.py",
                    "GateService._readiness",
                    "existing project gate only",
                ),
                (
                    "test_plan_validation",
                    "server/app/domain/test_plan_changes.py",
                    "validate_changes",
                    "test plan changes only",
                ),
                (
                    "raw_mapping",
                    "server/app/domain/test_report_import.py",
                    "_apply_mapping",
                    "deterministic original cells, model mapping separate",
                ),
            )
        ],
        "planned_engines": [
            planned(key, work)
            for key, work in (
                ("schedule_capacity", "N2-01/02/05/N6-01/02"),
                ("supply_kit", "N5-02"),
                ("cost_scenario", "N5-06/N6-03"),
                ("professional_metrics", "N4-01/02"),
            )
        ],
        "trigger_policies": [policy.model_dump(mode="json") for policy in TRIGGER_POLICIES],
        "events": events(),
        "current_dispatcher": component(
            "dispatcher", "server/app/worker/dispatcher.py", "AgentDispatcher"
        ),
        "current_dispatcher_limitation": "15-minute event debounce; project_id required",
        "qualification_format": component(
            "qualification_format", "server/app/ai/qualifications.py", "QualificationDocument"
        ),
        "role_policy": component("role_policy", "server/app/auth/roles.py", "allowed_actions"),
        "authorization_divergence": (
            "ProjectAccessService supports delegated membership; FindingService currently "
            "requires direct membership. Unify under approved intersection policy."
        ),
    }
