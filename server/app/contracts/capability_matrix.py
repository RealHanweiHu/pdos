"""N0-02 explicit adoption candidates, never loaded by production dispatch."""

from __future__ import annotations

from typing import Any

from app.ai.capability_contract import CAPABILITY_CONTRACTS, CapabilityKey
from app.contracts.runtime_policy import CapabilityPolicy, PolicyPin, ToolPolicy

VERSION = "candidate.v2"
ALL_SCOPES = (
    "tenant",
    "market_space",
    "product_line",
    "opportunity",
    "product_definition",
    "portfolio",
    "project",
)
PRODUCT_SCOPES = ("product_line", "opportunity", "product_definition")
PLANNING_SCOPES = ("product_definition", "opportunity", "project")
RESEARCH = ("research.search_sources", "research.capture_snapshot")

TOOL_GUIDANCE = {
    "research.search_sources": (
        "Find public source leads for a bounded research query",
        "Do not cite snippets as facts; capture the original source first",
    ),
    "research.capture_snapshot": (
        "Capture an authorized public URL as a tainted evidence snapshot",
        "No credentials, login, internal addresses or executable downloads",
    ),
    "knowledge.search_applicable": (
        "Retrieve reviewed knowledge with product, phase and applicability constraints",
        "Do not promote past model output to verified knowledge or bypass source ACL",
    ),
    "verification.get_evidence": (
        "Inspect spec/case/sample/build/run evidence and configuration gaps",
        "Attachment existence is not a passing test; never fill missing actual values",
    ),
    "readiness.evaluate": (
        "Evaluate current prerequisites for a named action at an exact version",
        "Does not approve Gate, close Issue or replace the action's current checks",
    ),
    "schedule.evaluate_scenario": (
        "Compute a proposed task graph using calendar/capacity input snapshots",
        "Never change baseline/commitment or reserve capacity; missing inputs stay explicit",
    ),
    "engineering.trace_impact": (
        "Trace versioned spec/BOM/configuration/test/plan relations for a proposed change",
        "Does not execute ECN or convert evidence links into execution dependencies",
    ),
    "product.prepare_definition": (
        "Validate and package the model's structured definition draft into a Finding",
        "Do not publish definitions, confirm unknown criteria or call a hidden second model",
    ),
    "planning.prepare_initial_plan": (
        "Validate the supplied plan draft, sources and scenario for a plan Finding",
        "Do not create Project/Task/Baseline or treat unconfirmed estimates as commitments",
    ),
    "verification.prepare_plan_change": (
        "Package a typed test-plan diff for new requirements as a Finding",
        "Do not copy old results as new configuration passes or invent test results",
    ),
    "reports.preview_import": (
        "Read original values and mapping state from an already authorized import batch",
        "Do not parse new uploads, create drafts, confirm mappings or synthesize cell values",
    ),
    "change.prepare_work_package": (
        "Package the model's cross-domain change and revalidation actions as a Finding",
        "Customer confirmation does not replace internal ECN approval; do not apply",
    ),
    "quality.prepare_capa": (
        "Package failure evidence, root-cause hypotheses and effectiveness plan as a CAPA Finding",
        "Do not mark hypotheses proven, actions completed or effectiveness verified",
    ),
    "handoff.prepare_package": (
        "Read handoff gaps or propose a versioned package with sender/receiver and evidence",
        "Generating or sending a package is not acceptance; never impersonate the receiver",
    ),
}

# key, input, output, effect, scopes, owner, implementation work, reuse evidence
TOOL_ROWS = (
    (
        "research.search_sources",
        "SearchSourcesInput",
        "SearchSourcesResult",
        "read",
        ALL_SCOPES,
        "evidence",
        "N1-02",
        "app.ai.reach",
    ),
    (
        "research.capture_snapshot",
        "CaptureSnapshotInput",
        "EvidenceResult",
        "record_observation",
        ALL_SCOPES,
        "evidence",
        "N1-02",
        "app.ai.reach",
    ),
    (
        "knowledge.search_applicable",
        "SearchKnowledgeInput",
        "EvidenceResult",
        "read",
        ALL_SCOPES,
        "memories",
        "N3-03",
        "app.ai.tools.AgentReadTools.search_memory",
    ),
    (
        "verification.get_evidence",
        "GetVerificationEvidenceInput",
        "EvidenceResult",
        "read",
        ALL_SCOPES,
        "quality",
        "N4-01/02",
        "app.ai.tools.AgentReadTools.get_quality_evidence",
    ),
    (
        "readiness.evaluate",
        "EvaluateReadinessInput",
        "ReadinessResult",
        "read",
        ALL_SCOPES,
        "gates",
        "N0-04/N4-07",
        "app.domain.gates",
    ),
    (
        "schedule.evaluate_scenario",
        "EvaluateScenarioInput",
        "ScenarioResult",
        "simulate",
        ALL_SCOPES,
        "planning",
        "N2-01/02/N6-01/02",
        None,
    ),
    (
        "engineering.trace_impact",
        "TraceImpactInput",
        "ImpactResult",
        "read",
        ALL_SCOPES,
        "product_engineering",
        "N4-04",
        "app.ai.tools.AgentReadTools.get_engineering_evidence",
    ),
    (
        "product.prepare_definition",
        "PrepareDefinitionInput",
        "FindingResult",
        "propose_finding",
        PRODUCT_SCOPES,
        "product",
        "N1-05/06",
        None,
    ),
    (
        "planning.prepare_initial_plan",
        "PrepareInitialPlanInput",
        "FindingResult",
        "propose_finding",
        PLANNING_SCOPES,
        "planning",
        "N2-03/04",
        None,
    ),
    (
        "verification.prepare_plan_change",
        "PreparePlanChangeInput",
        "FindingResult",
        "propose_finding",
        ("project",),
        "quality",
        "N4-02",
        "app.domain.test_plan_changes",
    ),
    (
        "reports.preview_import",
        "PreviewImportInput",
        "ImportPreviewResult",
        "read",
        ("project",),
        "quality",
        "N4-01/N3-10",
        "app.domain.test_report_import",
    ),
    (
        "change.prepare_work_package",
        "PrepareChangePackageInput",
        "FindingResult",
        "propose_finding",
        ("project",),
        "change_governance",
        "N3-01/N4-03/04/06",
        None,
    ),
    (
        "quality.prepare_capa",
        "PrepareCapaInput",
        "FindingResult",
        "propose_finding",
        ("project",),
        "quality",
        "N4-05",
        None,
    ),
    (
        "handoff.prepare_package",
        "PrepareHandoffInput",
        "HandoffResult",
        "propose_finding",
        ALL_SCOPES,
        "projects",
        "N3-04/N4-07",
        None,
    ),
)

# semantic, owner, scope, tools beyond common public research, candidate type,
# budget, triggers, user entry/result, context fields, work items
CAPABILITY_ROWS = (
    (
        "requirement_readiness",
        "project_intelligence",
        PLANNING_SCOPES,
        ("readiness.evaluate",),
        None,
        "short",
        ("user", "event"),
        "定义/Case的立项输入检查",
        ("requirement_versions", "definition_items", "professional_constraints"),
        "N1-07/N2-03",
    ),
    (
        "schedule_control",
        "project_intelligence",
        PLANNING_SCOPES,
        ("schedule.evaluate_scenario", "planning.prepare_initial_plan"),
        "initial_plan",
        "work_package",
        ("user", "event"),
        "初始计划/项目时间控制",
        ("plan_draft", "four_times", "calendar_capacity", "id_constraints"),
        "N2-03/06",
    ),
    (
        "execution_followup",
        "project_intelligence",
        ("project",),
        ("readiness.evaluate", "schedule.evaluate_scenario"),
        "execution_recovery",
        "short",
        ("user", "event", "scheduled"),
        "My Work执行偏差和恢复",
        ("tasks_actuals", "issues", "decisions", "reminder_history"),
        "N2-07/N3-02",
    ),
    (
        "gate_readiness",
        "project_intelligence",
        ("project",),
        ("readiness.evaluate", "verification.get_evidence"),
        None,
        "short",
        ("user", "event"),
        "项目Gate缺项说明",
        ("gate_round", "policy", "required_evidence", "valid_reviews"),
        "N0-04/N4-07",
    ),
    (
        "meeting_minutes",
        "knowledge_lite",
        ("project",),
        ("knowledge.search_applicable",),
        "meeting_minutes",
        "work_package",
        ("user", "event"),
        "项目会议纪要候选",
        ("transcript_segments", "participants", "agenda", "existing_actions"),
        "N3-06",
    ),
    (
        "document_extract",
        "knowledge_lite",
        ALL_SCOPES,
        ("knowledge.search_applicable",),
        None,
        "work_package",
        ("user",),
        "授权文档抽取/报告映射预览",
        ("document_fragments", "parser_version", "original_locators", "mapping_status"),
        "N1-02/N3-08/10/N4-01",
    ),
    (
        "project_memory",
        "knowledge_lite",
        ALL_SCOPES,
        ("knowledge.search_applicable",),
        "knowledge_draft",
        "short",
        ("user", "event", "scheduled"),
        "知识候选/适用经验卡",
        ("decisions", "outcomes", "verified_memory", "applicability"),
        "N3-03/N6-05",
    ),
    (
        "spec_bom",
        "engineering_intelligence",
        ("project",),
        ("engineering.trace_impact", "verification.get_evidence"),
        "spec_bom_change",
        "work_package",
        ("user", "event"),
        "规格与开发BOM关联",
        ("spec_versions", "bom_versions", "interfaces", "design_constraints"),
        "N4-03",
    ),
    (
        "material_substitution",
        "engineering_intelligence",
        ("project",),
        ("engineering.trace_impact", "verification.get_evidence", "change.prepare_work_package"),
        "material_substitution",
        "work_package",
        ("user", "event"),
        "替代件对比与验证候选",
        ("material_versions", "test_evidence", "supply_snapshots", "cost_estimates"),
        "N4-03/N5-05/06",
    ),
    (
        "change_impact",
        "engineering_intelligence",
        ("project",),
        ("engineering.trace_impact", "change.prepare_work_package"),
        "change_work_package",
        "work_package",
        ("user", "event"),
        "工程变更影响/复验工作包",
        ("change_versions", "spec_bom_graph", "sample_test_config", "four_times"),
        "N4-04/06",
    ),
    (
        "test_quality",
        "quality_intelligence",
        ("project",),
        ("verification.get_evidence", "verification.prepare_plan_change", "reports.preview_import"),
        "test_plan_change",
        "work_package",
        ("user", "event"),
        "测试矩阵/证据与计划变更",
        ("features", "test_plan", "run_config_versions", "raw_results"),
        "N4-01/02",
    ),
    (
        "issue_verification",
        "quality_intelligence",
        ("project",),
        ("verification.get_evidence", "readiness.evaluate"),
        "issue_verification_advice",
        "short",
        ("user", "event"),
        "Issue调查与独立验证辅助",
        ("issue_state", "owner_verifier", "closure_conditions", "investigation_evidence"),
        "N0-04/N4-05",
    ),
    (
        "capa_recurrence",
        "quality_intelligence",
        ("project",),
        ("verification.get_evidence", "quality.prepare_capa", "knowledge.search_applicable"),
        "capa_work_package",
        "work_package",
        ("user", "event", "scheduled"),
        "CAPA和复发知识",
        ("ncr_issue", "failure_evidence", "hypotheses", "effectiveness_plan"),
        "N4-05/N6-05",
    ),
    (
        "material_readiness",
        "supplier_intelligence",
        ("project",),
        ("readiness.evaluate",),
        None,
        "short",
        ("user", "event", "scheduled"),
        "Build齐套/短缺说明",
        ("kit_engine_result", "build_demand", "supply_as_of", "allocation_versions"),
        "N5-02/03",
    ),
    (
        "supplier_delay",
        "supplier_intelligence",
        ("project",),
        ("schedule.evaluate_scenario",),
        "supplier_recovery",
        "work_package",
        ("user", "event", "scheduled"),
        "供应延期恢复建议",
        ("supplier_commitments", "supply_snapshots", "affected_builds", "four_times"),
        "N5-03/05",
    ),
    (
        "sourcing_risk",
        "supplier_intelligence",
        ("project",),
        ("verification.get_evidence", "engineering.trace_impact"),
        "sourcing_verification",
        "work_package",
        ("user", "event", "scheduled"),
        "供方/EOL/PCN证据与验证",
        ("supplier_qualification", "pcn_eol", "critical_parts", "verification_requirements"),
        "N5-04/05",
    ),
    (
        "portfolio_schedule",
        "executive_intelligence",
        ("tenant", "portfolio"),
        ("schedule.evaluate_scenario",),
        None,
        "work_package",
        ("user", "scheduled"),
        "组合时间方案说明",
        ("authorized_project_set", "four_time_projections", "cross_project_edges"),
        "N6-02/03",
    ),
    (
        "resource_conflict",
        "executive_intelligence",
        ("tenant", "portfolio"),
        ("schedule.evaluate_scenario",),
        None,
        "work_package",
        ("user", "event", "scheduled"),
        "共享资源容量冲突情景",
        ("resource_identity", "capacity_calendar", "reservations", "priority_policy"),
        "N6-01/02",
    ),
    (
        "decision_brief",
        "executive_intelligence",
        ALL_SCOPES,
        ("knowledge.search_applicable", "readiness.evaluate"),
        "decision_brief",
        "research_discussion",
        ("user", "authorized_run"),
        "多专业Decision Brief",
        ("anchored_subjects", "seat_evidence", "consensus_dissent", "costs_and_unknowns"),
        "N3-07/N6-03",
    ),
    (
        "research_planning",
        "product_management_intelligence",
        ("market_space", *PRODUCT_SCOPES),
        (),
        "research_plan",
        "research_discussion",
        ("user", "scheduled"),
        "产品工作台研究任务计划",
        ("research_question", "market_users_channels", "time_window", "source_policy"),
        "N1-02",
    ),
    (
        "competitor_analysis",
        "product_management_intelligence",
        ("market_space", *PRODUCT_SCOPES),
        ("verification.get_evidence",),
        None,
        "research_discussion",
        ("user", "event"),
        "同工况竞品对照",
        ("competitor_snapshots", "units_conditions", "comparison_scope", "source_conflicts"),
        "N1-03",
    ),
    (
        "market_analysis",
        "product_management_intelligence",
        ("market_space", *PRODUCT_SCOPES),
        (),
        None,
        "research_discussion",
        ("user", "event"),
        "市场/JTBD/量化说明",
        ("market_evidence", "jtbd", "deterministic_estimates", "assumptions"),
        "N1-04",
    ),
    (
        "opportunity_mapping",
        "product_management_intelligence",
        PRODUCT_SCOPES,
        (),
        "opportunity_tree",
        "research_discussion",
        ("user", "event"),
        "机会树及至少三方案",
        ("desired_outcomes", "evidence", "solution_alternatives", "scoring_policy"),
        "N1-04",
    ),
    (
        "experiment_design",
        "product_management_intelligence",
        PRODUCT_SCOPES,
        (),
        "experiment_plan",
        "work_package",
        ("user", "event"),
        "VUVF实验计划与结果回链",
        ("hypotheses", "falsification", "value_usability_feasibility_viability", "results"),
        "N1-04",
    ),
    (
        "product_strategy",
        "product_management_intelligence",
        PRODUCT_SCOPES,
        (),
        "product_strategy",
        "research_discussion",
        ("user", "event"),
        "九区Canvas与开发策略",
        ("nine_area_canvas", "alternatives", "professional_constraints", "evidence_assumptions"),
        "N1-05",
    ),
    (
        "product_definition",
        "product_management_intelligence",
        PRODUCT_SCOPES,
        ("product.prepare_definition", "readiness.evaluate"),
        "product_definition",
        "work_package",
        ("user", "event"),
        "产品定义与正式发布候选",
        (
            "strategy_version",
            "features_included_excluded",
            "spec_items",
            "verification_and_constraints",
        ),
        "N1-06/07",
    ),
    (
        "product_matrix",
        "product_management_intelligence",
        ("tenant", "product_line", "portfolio"),
        (),
        "product_roadmap",
        "work_package",
        ("user", "scheduled"),
        "产品家族矩阵/路线图",
        ("product_hierarchy", "market_coverage", "platform_reuse", "authorized_portfolio"),
        "N6-04",
    ),
)


def pin(key: str, version: str = VERSION) -> PolicyPin:
    return PolicyPin(key=key, version=version)


def tools() -> tuple[ToolPolicy, ...]:
    result = []
    for key, input_name, output_name, effect, scopes, owner, _work, _reuse in TOOL_ROWS:
        result.append(
            ToolPolicy.model_validate(
                {
                    **pin(key).model_dump(),
                    "use_when": TOOL_GUIDANCE[key][0],
                    "do_not_use_when": TOOL_GUIDANCE[key][1],
                    "input_schema": pin(input_name),
                    "output_schema": pin(output_name),
                    "scope_policy": {"allowed_scopes": scopes},
                    "side_effect": effect,
                    "binding": {
                        "status": "planned",
                        "owner_module": owner,
                        "handler": None,
                        "verification_ref": None,
                    },
                    "rollout": "disabled",
                    "timeout_seconds": 20 if key == "research.capture_snapshot" else 10,
                    "max_attempts": 2,
                    "max_payload_bytes": 2 * 1024 * 1024,
                    "idempotency": {
                        "record_observation": "run_call_digest",
                        "propose_finding": "finding_origin_digest",
                    }.get(effect, "query_version"),
                    "citation_policy": "resolved_source_version_locator",
                    "freshness_policy": "current_acl_and_critical_versions",
                    "validator": input_name,
                    "egress_policy": pin("source_aware_egress"),
                    "retention_policy": pin("standard"),
                    "budget_profile": pin("work_package"),
                }
            )
        )
    return tuple(result)


def capabilities() -> tuple[CapabilityPolicy, ...]:
    result = []
    for (
        semantic,
        owner,
        scopes,
        local_tools,
        finding,
        profile,
        triggers,
        entry,
        _context,
        _work,
    ) in CAPABILITY_ROWS:
        result.append(
            CapabilityPolicy.model_validate(
                {
                    **pin(f"{owner}.{semantic}").model_dump(),
                    "semantic_keys": [semantic],
                    "purpose": entry,
                    "entry_points": [entry],
                    "triggers": triggers,
                    "deduplication": "tenant_scope_capability_goal_source_version",
                    "scope_policy": {"allowed_scopes": scopes},
                    "context_builder": pin(f"{semantic}.context"),
                    "prompt": pin(f"{semantic}.prompt"),
                    "tool_pins": [pin(key) for key in (*RESEARCH, *local_tools)],
                    "output_schema": pin(
                        "DecisionBrief" if semantic == "decision_brief" else f"{semantic}.output"
                    ),
                    "output_modes": ["read_only", "propose_finding"] if finding else ["read_only"],
                    "finding_types": [finding] if finding else [],
                    "review_action": pin("finding.review") if finding else None,
                    "apply_action": pin("finding.apply") if finding else None,
                    "zone": "hard_gate" if finding else "free",
                    "rollout": "disabled",
                    "binding": {
                        "status": "planned",
                        "owner_module": owner,
                        "handler": None,
                        "verification_ref": None,
                    },
                    "model_qualification": None,
                    "quality_profile": pin(f"{semantic}.quality"),
                    "budget_profile": pin(profile),
                    "retention_policy": pin("standard"),
                    "expiration_policy": "critical_source_target_policy_versions_and_current_acl",
                    "manual_fallback": f"在{entry}读取原始来源并通过对应人工表单办理；缺项显式保留",
                    "result_backlink": entry,
                }
            )
        )
    return tuple(result)


LEGACY_SEMANTICS = {
    CapabilityKey.PROJECT_RISK_SUGGESTION: ("requirement_readiness", "schedule_control"),
    CapabilityKey.PROJECT_BLOCKER_ALERT: ("execution_followup", "schedule_control"),
    CapabilityKey.PROJECT_GATE_READINESS_ANOMALY: ("gate_readiness",),
    CapabilityKey.PROJECT_RISK_SUGGESTION_API: ("execution_followup",),
    CapabilityKey.KNOWLEDGE_DRAFT: ("project_memory", "meeting_minutes", "document_extract"),
    CapabilityKey.ENGINEERING_BOM_IMPACT: ("spec_bom", "material_substitution"),
    CapabilityKey.ENGINEERING_CHANGE_IMPACT: ("change_impact",),
    CapabilityKey.QUALITY_CAPA_WORK_PACKAGE: ("capa_recurrence",),
    CapabilityKey.ENGINEERING_CHANGE_WORK_PACKAGE: ("change_impact",),
    CapabilityKey.QUALITY_CLUSTER_ALERT: ("test_quality", "issue_verification"),
    CapabilityKey.QUALITY_CAPA_SUGGESTION: ("capa_recurrence",),
    CapabilityKey.QUALITY_TEST_PLAN_CHANGE: ("test_quality",),
    CapabilityKey.QUALITY_TEST_REPORT_IMPORT: ("document_extract",),
    CapabilityKey.SUPPLIER_DELAY_RISK: ("supplier_delay", "material_readiness", "sourcing_risk"),
    CapabilityKey.EXECUTIVE_PORTFOLIO_BRIEF: (
        "decision_brief",
        "portfolio_schedule",
        "resource_conflict",
    ),
}


LEGACY_CAPABILITY_KEYS = frozenset(
    {
        CapabilityKey.PROJECT_RISK_SUGGESTION,
        CapabilityKey.PROJECT_BLOCKER_ALERT,
        CapabilityKey.PROJECT_GATE_READINESS_ANOMALY,
        CapabilityKey.PROJECT_RISK_SUGGESTION_API,
        CapabilityKey.KNOWLEDGE_DRAFT,
        CapabilityKey.ENGINEERING_BOM_IMPACT,
        CapabilityKey.ENGINEERING_CHANGE_IMPACT,
        CapabilityKey.QUALITY_CLUSTER_ALERT,
        CapabilityKey.QUALITY_CAPA_SUGGESTION,
        CapabilityKey.QUALITY_TEST_PLAN_CHANGE,
        CapabilityKey.QUALITY_TEST_REPORT_IMPORT,
        CapabilityKey.SUPPLIER_DELAY_RISK,
        CapabilityKey.EXECUTIVE_PORTFOLIO_BRIEF,
    }
)


def legacy_dispositions() -> list[dict[str, Any]]:
    result = []
    for key, current in CAPABILITY_CONTRACTS.items():
        if key not in LEGACY_CAPABILITY_KEYS:
            continue
        import_path = key == CapabilityKey.QUALITY_TEST_REPORT_IMPORT
        risk_api = key == CapabilityKey.PROJECT_RISK_SUGGESTION_API
        result.append(
            {
                "key": key.value,
                "current_declaration": current.model_dump(mode="json"),
                "target_semantics": list(LEGACY_SEMANTICS[key]),
                "mapping_strength": "partial_reuse_not_full_semantic_coverage",
                "adoption": "preserve_current_until_explicit_version_adoption",
                "target_exit": "deterministic_raw_import_with_human_confirm"
                if import_path
                else "finding_review_then_apply",
                "context_source": list(current.projections),
                "budget_candidate": "work_package"
                if import_path or key == CapabilityKey.QUALITY_TEST_PLAN_CHANGE
                else "short",
                "retention_candidate": "standard",
                "entry_kind": "user"
                if import_path or risk_api or not current.event_driven
                else "event",
                "registry_correction": (
                    "split_model_mapping_from_deterministic_raw_values; preview_tool_read_only"
                    if import_path
                    else "zone_confirm_to_finding_double_action; no_runtime_downgrade"
                    if risk_api
                    else "inherit_finding_boundary; add_scope_budget_and_qualification"
                ),
                "expired_or_disabled": "deny_new_disclosure_and_apply; preserve_history",
                "idempotency": "reuse_origin_and_digest; changed_payload_conflicts",
            }
        )
    return result


# Closed business approval set from complete design section 2. No model toolset.
HARD_GATE_ROWS = (
    ("baseline_change", "Baseline版本批准", "project", "计划批准人", "N2-04/06"),
    (
        "commitment_change",
        "对外/跨团队Commitment确认",
        "project",
        "承诺责任人及适用批准人",
        "N2-06",
    ),
    ("gate_conclusion", "Gate结论", "project", "当轮版本化签核席位", "N4-07"),
    ("dcp_conclusion", "DCP商业结论", "typed_product_scope", "商业批准人", "N1-07"),
    (
        "tr_conclusion",
        "TR技术结论",
        "typed_product_or_project_scope",
        "具名专业评审人",
        "N1-07/N4-06",
    ),
    ("bom_freeze", "开发BOM冻结", "project", "BOM批准人", "N4-03"),
    ("ecn_effectivity", "ECN生效", "project", "适用变更批准席位", "N4-04/06"),
    ("supplier_selection", "供应商选定", "project", "采购/品质及适用商业批准人", "N5-04/05"),
    (
        "high_critical_issue_close",
        "高/严重Issue关闭",
        "project",
        "Owner以外的独立Verifier",
        "N0-04/N4-05",
    ),
    (
        "external_send_or_write",
        "真实外发/外部写",
        "authorized_audience_scope",
        "具备具体或已批准自动化授权的主体",
        "N3-05/06/P3",
    ),
    (
        "history_delete_or_overwrite",
        "历史删除/覆盖",
        "governed_scope",
        "授权治理人；不可违反冻结历史保护",
        "N0-03/N7",
    ),
    (
        "financial_approval_or_commitment",
        "正式金额批准/承诺",
        "business_scope",
        "适用金额权限批准人",
        "N5-06/N6-03",
    ),
    (
        "product_definition_publish",
        "产品定义发布",
        "product_definition",
        "产品及适用专业批准人",
        "N1-06/07",
    ),
    ("project_execution_approval", "项目执行批准", "project", "适用项目执行批准人", "N2-04"),
)


def matrix_metadata() -> dict[str, Any]:
    return {
        "status": "candidate_not_wired_not_qualified",
        "target_capabilities": [item.model_dump(mode="json") for item in capabilities()],
        "legacy_capabilities": legacy_dispositions(),
        "semantic_details": {
            row[0]: {
                "context_fields": row[8],
                "implementation_work": row[9],
                "qualification": "pending_domain_golden_publication",
                "quality_requirements": [
                    "cited_source_correctness",
                    "scope_injection_zero",
                    "explicit_unknowns",
                    "executable_output",
                    "human_accept_modify_reject_by_scenario",
                ],
                "quality_threshold": "inherit_hard_lines; new_professional_threshold_pending",
                "user_queue_visibility_seconds": 5,
                "user_trigger": "immediate_queue_not_event_debounce",
                "event_policy": (
                    "milestone_outcome_or_failure_within_180s; frequent_edit_900s_separate"
                ),
                "event_policy_adoption": "requires_N0_03_routing_implementation",
            }
            for row in CAPABILITY_ROWS
        },
        "tools": [item.model_dump(mode="json") for item in tools()],
        "tool_implementation": {
            row[0]: {
                "implementation_work": row[6],
                "reuse_source": row[7],
                "handler_status": "not_wired",
                "schema_status": "candidate_executable",
                "future_domain_extension": "versioned_before_live",
            }
            for row in TOOL_ROWS
        },
        "hard_gates": [
            {
                "key": key,
                "action": action,
                "scope_rule": scope,
                "approver_rule": approver,
                "work_item": work,
                "model_callable": False,
                "rule": "current_domain_permission_sources_versions_and_applicable_separation",
            }
            for key, action, scope, approver, work in HARD_GATE_ROWS
        ],
        "decision_brief": {
            "schema": "DecisionBrief",
            "read_only": "direct_authorized_display",
            "business_proposal": "typed_finding_review_then_independent_apply_and_domain_gates",
            "consensus_does_not_approve": True,
            "dissent_and_costs_preserved": True,
        },
        "raw_import": {
            "parser": "deterministic_original_cells",
            "unknown_mapping": "model_mapping_proposal",
            "mapping_acceptance": "human_confirm_of_exact_mapping_and_preview",
            "reuse_confirmed_mapping": "same_fingerprint_zero_model",
            "model_tool": "read_existing_batch_only",
            "actual_values": "never_model_generated",
            "formal_test_runs": "existing_authorized_human_confirmation_with_event_audit",
        },
    }
