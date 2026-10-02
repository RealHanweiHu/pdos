"""Common-contract examples, not golden cases or real employee/production evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.contracts.common_objects import Contract
from app.contracts.object_operations import (
    LIFECYCLES,
    OPERATIONS,
    InitialPlanApplyRequest,
    ResearchTaskChangedPayload,
    ReservationChangedPayload,
    assert_contract_transition,
)
from app.contracts.planning_records import (
    CaseProjectConversion,
    InitialPlanApplication,
    ProjectContractAdoption,
    ResourceReservation,
    WorkItemTransfer,
)
from app.contracts.product_records import (
    Experiment,
    FactStatement,
    Opportunity,
    ProductDefinition,
    ProductHierarchy,
    ProductStrategy,
    ResearchTask,
    StrategyCanvas,
)
from app.events.catalog import EVENT_REGISTRY
from scripts.export_common_contracts import candidate_models

TENANT, PROJECT, USER = uuid4(), uuid4(), uuid4()
NOW = datetime(2026, 9, 10, tzinfo=UTC)
DIGEST = "a" * 64


def ref(kind: str = "requirement") -> dict[str, Any]:
    return {"tenant_id": TENANT, "kind": kind, "ref_id": uuid4(), "version": 1}


def scoped() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": TENANT,
        "scope": {"kind": "opportunity", "ref_id": uuid4()},
        "version": 1,
        "owner_user_id": USER,
        "sources": [ref()],
    }


def approval() -> dict[str, Any]:
    return {
        "approval_id": uuid4(),
        "payload_digest": DIGEST,
        "policy_version": "policy.v1",
        "approved_by_user_id": USER,
        "approved_at": NOW,
    }


def hypothesis() -> dict[str, Any]:
    return {"text": "needs validation", "fact_kind": "hypothesis"}


def solution() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "title": "route",
        "approach": "new_development",
        "rationale": hypothesis(),
        "constraints": [],
        "unknowns": ["supplier lead time"],
    }


def opportunity() -> dict[str, Any]:
    return {
        **scoped(),
        "title": "bike pump",
        "segment": "rider",
        "job_to_be_done": "inflate",
        "desired_outcome_id": uuid4(),
        "parent_opportunity_id": None,
        "importance": None,
        "satisfaction": None,
        "scoring_policy_version": None,
        "solutions": [solution() for _ in range(3)],
        "selected_solution_id": None,
        "state": "exploring",
    }


def experiment() -> dict[str, Any]:
    return {
        **scoped(),
        "opportunity_id": uuid4(),
        "solution_id": uuid4(),
        "dimension": "feasibility",
        "hypothesis": "reusable pump platform",
        "method": "bench test",
        "sample_basis": "engineering assessment",
        "success_criterion": "criterion A",
        "falsification_criterion": "criterion B",
        "due_at": None,
        "state": "draft",
        "approval": None,
        "result": None,
    }


def definition() -> dict[str, Any]:
    item: dict[str, Any] = {
        "item_key": "PRESSURE",
        "title": "pressure",
        "target_text": None,
        "target_value": None,
        "unit": None,
        "tolerance": None,
        "conditions": [],
        "priority": "must",
        "required_for_release": True,
        "rationale": hypothesis(),
        "verification_method": None,
        "acceptance_criterion": None,
        "verification_stage": None,
        "owner_user_id": None,
        "state": "needs_confirmation",
    }
    return {
        **scoped(),
        "product_id": uuid4(),
        "strategy_ref": ref("product_strategy"),
        "title": "bicycle pump",
        "target_users": ["rider"],
        "scenarios": ["roadside"],
        "included_features": ["inflation"],
        "excluded_features": ["lighting"],
        "region_constraints": [],
        "target_cost": hypothesis(),
        "price_position": hypothesis(),
        "launch_window": hypothesis(),
        "service_requirements": [],
        "success_criteria": [hypothesis()],
        "items": [item],
        "state": "draft",
        "approval": None,
        "published_at": None,
    }


def transfer() -> dict[str, Any]:
    return {
        "source_work_item_id": uuid4(),
        "source_version": 1,
        "source_state": "in_progress",
        "disposition": "transfer_remaining",
        "target_task_id": uuid4(),
        "remaining_work": "supplier confirmation",
        "evidence_refs": [ref()],
    }


def reservation() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version": 1,
        "resource_id": uuid4(),
        "capacity_version": 1,
        "calendar_version": 1,
        "node_id": uuid4(),
        "owner_user_id": USER,
        "window": {"start": NOW, "end": NOW + timedelta(hours=4)},
        "amount": "4",
        "unit": "equipment_hours",
        "priority_policy_version": "v1",
        "state": "proposed",
        "approval": None,
        "reservation_receipt_id": None,
        "reserved_at": None,
        "released_at": None,
        "release_reason": None,
    }


def reject(
    model: type[Contract], payload: dict[str, Any], change: dict[str, Any], error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        model.model_validate({**payload, **change})


def test_product_hierarchy_complete_chain_and_invalid_cross_tenant_parent() -> None:
    parent: UUID | None = None
    nodes: list[dict[str, Any]] = []
    for level in ("line", "family", "platform", "series", "model", "variant"):
        node = {
            **scoped(),
            "code": level,
            "name": level,
            "level": level,
            "parent_id": parent,
            "lifecycle": "proposed",
        }
        nodes.append(node)
        parent = node["id"]
    ProductHierarchy.model_validate({"tenant_id": TENANT, "nodes": nodes})
    changes: list[tuple[dict[str, Any], str]] = [
        ({"tenant_id": uuid4(), "sources": []}, "product_tenant_mismatch"),
        ({"parent_id": uuid4()}, "product_parent_level_or_reference_invalid"),
        ({"parent_id": nodes[0]["id"]}, "product_parent_level_or_reference_invalid"),
        ({"code": "line"}, "duplicate_product_code"),
    ]
    for change, error in changes:
        with pytest.raises(ValidationError, match=error):
            ProductHierarchy.model_validate(
                {"tenant_id": TENANT, "nodes": [*nodes[:-1], {**nodes[-1], **change}]}
            )


def test_research_can_complete_with_no_hits_but_not_fabricated_findings() -> None:
    payload: dict[str, Any] = {
        **scoped(),
        "question": "research pump",
        "user_groups": [],
        "regions": [],
        "time_scope": "2026",
        "method": "public search",
        "expected_decision": "viable?",
        "stop_conditions": ["bounded evidence search"],
        "state": "completed",
        "sources": [],
        "conclusion": "no usable evidence",
        "completed_at": NOW,
        "unresolved": ["market evidence"],
    }
    ResearchTask.model_validate(payload)
    reject(
        ResearchTask,
        payload,
        {"findings": ["market is growing"]},
        "research_findings_require_sources",
    )
    reject(ResearchTask, payload, {"owner_user_id": None}, "research_owner_required")


def test_approval_does_not_convert_hypothesis_to_observed_fact() -> None:
    fact = FactStatement.model_validate({**hypothesis(), "approval": approval()})
    assert fact.fact_kind == "hypothesis"
    reject(FactStatement, hypothesis(), {"fact_kind": "observed"}, "fact_requires_sources")


def test_opportunity_requires_three_unique_compared_solutions_before_selection() -> None:
    payload = opportunity()
    Opportunity.model_validate(payload)
    selected = payload["solutions"][0]["id"]
    Opportunity.model_validate({**payload, "state": "selected", "selected_solution_id": selected})
    reject(
        Opportunity,
        payload,
        {"solutions": payload["solutions"][:2], "selected_solution_id": selected},
        "selection_requires_three",
    )
    reject(Opportunity, payload, {"selected_solution_id": uuid4()}, "selection_requires_three")
    reject(Opportunity, payload, {"importance": "0.7"}, "scoring_policy_required")
    reject(
        Opportunity,
        payload,
        {"requirement_refs": [{**ref(), "tenant_id": uuid4()}]},
        "source_tenant_mismatch",
    )


@pytest.mark.parametrize("dimension", ["value", "usability", "viability", "feasibility"])
def test_experiments_keep_plan_and_result_independent(dimension: str) -> None:
    payload: dict[str, Any] = {**experiment(), "dimension": dimension}
    Experiment.model_validate(payload)
    reject(Experiment, payload, {"result": "supported"}, "unfinished_experiment_has_result")
    completed = {
        **payload,
        "state": "concluded",
        "approval": approval(),
        "result": "refuted",
        "result_evidence": [ref()],
        "result_explanation": "criterion B observed",
        "concluded_at": NOW,
    }
    Experiment.model_validate(completed)
    reject(Experiment, completed, {"result_evidence": []}, "decisive_experiment_requires_evidence")
    Experiment.model_validate({**completed, "result": "inconclusive", "result_evidence": []})


def test_nine_area_canvas_and_incomplete_strategy_draft() -> None:
    canvas = {key: hypothesis() for key in StrategyCanvas.model_fields}
    payload: dict[str, Any] = {
        **scoped(),
        "opportunity_id": uuid4(),
        "selected_solution_id": None,
        "canvas": canvas,
        "compared_solution_ids": [],
        "professional_constraints": [],
        "state": "draft",
        "approval": None,
    }
    ProductStrategy.model_validate(payload)
    reject(
        ProductStrategy,
        payload,
        {"state": "published", "approval": approval()},
        "three_alternatives",
    )
    choices = [uuid4() for _ in range(3)]
    ProductStrategy.model_validate(
        {
            **payload,
            "state": "published",
            "approval": approval(),
            "compared_solution_ids": choices,
            "selected_solution_id": choices[0],
        }
    )
    missing = dict(canvas)
    missing.pop("defensibility")
    reject(ProductStrategy, payload, {"canvas": missing}, "defensibility")


def test_definition_unknowns_survive_draft_but_required_items_block_publish() -> None:
    payload = definition()
    ProductDefinition.model_validate(payload)
    published = {**payload, "state": "published", "approval": approval(), "published_at": NOW}
    reject(ProductDefinition, published, {}, "required_items_unconfirmed")
    confirmed = {
        **payload["items"][0],
        "target_text": "approved target",
        "verification_method": "method A",
        "acceptance_criterion": "criterion A",
        "verification_stage": "evt",
        "owner_user_id": USER,
        "state": "confirmed",
    }
    ProductDefinition.model_validate({**published, "items": [confirmed]})
    reject(ProductDefinition, payload, {"included_features": ["lighting"]}, "feature_conflict")
    reject(
        ProductDefinition,
        payload,
        {"items": [payload["items"][0]] * 2},
        "duplicate_specification_item_key",
    )
    reject(
        ProductDefinition,
        payload,
        {"strategy_ref": {**ref("product_strategy"), "tenant_id": uuid4()}},
        "source_tenant_mismatch",
    )


def test_transfer_retains_completed_history_and_only_maps_unfinished_work() -> None:
    payload = transfer()
    WorkItemTransfer.model_validate(payload)
    reject(
        WorkItemTransfer, payload, {"source_state": "completed"}, "terminal_work_cannot_be_reopened"
    )
    historic = {
        **payload,
        "source_state": "completed",
        "disposition": "retain_history",
        "target_task_id": None,
        "remaining_work": None,
    }
    WorkItemTransfer.model_validate(historic)
    reject(WorkItemTransfer, historic, {"target_task_id": uuid4()}, "retained_history")


def test_initial_plan_binds_approval_payload_and_unique_transfer_mapping() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "conversion_id": uuid4(),
        "source_scope": {"kind": "tenant", "ref_id": TENANT},
        "finding_id": uuid4(),
        "candidate_digest": DIGEST,
        "execution_approval": approval(),
        "baseline_id": uuid4(),
        "operation_receipt_id": uuid4(),
        "work_transfers": [transfer()],
    }
    InitialPlanApplication.model_validate(payload)
    reject(
        InitialPlanApplication, payload, {"candidate_digest": "b" * 64}, "approved_digest_mismatch"
    )
    reject(
        InitialPlanApplication,
        payload,
        {"work_transfers": payload["work_transfers"] * 2},
        "duplicate_transfer_mapping",
    )
    reject(
        InitialPlanApplication,
        payload,
        {"source_scope": {"kind": "project", "ref_id": uuid4()}},
        "source_project_mismatch",
    )
    conversion = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "case_ref": ref("development_case"),
        "project_id": PROJECT,
        "converted_by_user_id": USER,
        "converted_at": NOW,
        "event_row_id": 11,
        "audit_row_id": 12,
    }
    CaseProjectConversion.model_validate(conversion)
    reject(
        CaseProjectConversion,
        conversion,
        {"case_ref": ref("requirement")},
        "conversion_case_scope_invalid",
    )


def test_active_project_adoption_does_not_rewind_history_or_invent_approval() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "contract_version": "pdos.v1",
        "policy_version": "v1",
        "captured_at": NOW,
        "historical_status": "active",
        "snapshot_ref": {**ref("project"), "project_id": PROJECT},
        "preserved_approval_ids": [],
        "missing": ["baseline"],
        "state": "inventoried",
        "remediation_receipt_id": None,
        "adopted_at": None,
        "adopted_by_user_id": None,
    }
    assert ProjectContractAdoption.model_validate(payload).historical_status == "active"
    reject(ProjectContractAdoption, payload, {"state": "adopted"}, "resolved_gaps_and_receipt")
    ProjectContractAdoption.model_validate(
        {
            **payload,
            "state": "adopted",
            "missing": [],
            "remediation_receipt_id": uuid4(),
            "adopted_at": NOW,
            "adopted_by_user_id": USER,
        }
    )


def test_resource_proposal_cannot_claim_capacity_and_release_keeps_receipt() -> None:
    payload = reservation()
    ResourceReservation.model_validate(payload)
    reject(
        ResourceReservation,
        payload,
        {"reserved_at": NOW, "reservation_receipt_id": uuid4(), "approval": approval()},
        "scenario_cannot_occupy_capacity",
    )
    reject(ResourceReservation, payload, {"state": "reserved"}, "requires_approval_and_receipt")
    reserved = {
        **payload,
        "state": "reserved",
        "approval": approval(),
        "reservation_receipt_id": uuid4(),
        "reserved_at": NOW,
    }
    ResourceReservation.model_validate(reserved)
    released = {
        **reserved,
        "state": "released",
        "released_at": NOW,
        "release_reason": "test finished",
    }
    ResourceReservation.model_validate(released)
    reject(
        ResourceReservation,
        released,
        {"reservation_receipt_id": None},
        "reservation_time_receipt_pair_required",
    )


@pytest.mark.parametrize(
    "kind,current,target",
    [
        ("definition", "published", "draft"),
        ("review", "draft", "finalized"),
        ("experiment", "draft", "concluded"),
        ("reservation", "proposed", "released"),
        ("scoped_work_item", "completed", "in_progress"),
        ("unknown", "draft", "published"),
    ],
)
def test_lifecycles_reject_skip_and_history_rewrite(kind: str, current: str, target: str) -> None:
    with pytest.raises(ValueError, match="invalid_contract_transition"):
        assert_contract_transition(kind, current, target)


def test_commands_reject_caller_supplied_actor_and_events_reject_state_skips() -> None:
    payload: dict[str, Any] = {
        "expected_version": 1,
        "payload_digest": DIGEST,
        "idempotency_key": "apply-1",
        "project_id": PROJECT,
        "conversion_id": uuid4(),
        "finding_id": uuid4(),
        "execution_approval_id": uuid4(),
        "candidate_digest": DIGEST,
    }
    InitialPlanApplyRequest.model_validate(payload)
    for field in ("tenant_id", "applied_by_user_id", "approved", "accepted"):
        reject(InitialPlanApplyRequest, payload, {field: True}, "extra_forbidden")
    event = {
        "object_id": uuid4(),
        "object_version": 1,
        "operation_id": uuid4(),
        "correlation_id": uuid4(),
        "causation_event_row_id": None,
        "from_state": "draft",
        "to_state": "completed",
    }
    reject(ResearchTaskChangedPayload, event, {}, "invalid_contract_transition")
    reject(
        ReservationChangedPayload,
        {
            **event,
            "project_id": PROJECT,
            "resource_id": uuid4(),
            "capacity_version": 1,
            "from_state": "proposed",
            "to_state": "released",
        },
        {},
        "invalid_contract_transition",
    )


def test_logical_operations_resolve_and_registered_payloads_match_contract_fields() -> None:
    models = candidate_models()
    assert len({operation.key for operation in OPERATIONS}) == len(OPERATIONS)
    for operation in OPERATIONS:
        assert operation.request_schema in models
        assert operation.response_schema in models
        assert operation.event_payload_schema in models
        assert operation.failure_schema in models
        if operation.event_type in EVENT_REGISTRY:
            registered = EVENT_REGISTRY[operation.event_type]
            assert set(registered.payload_schema["properties"]).issubset(
                models[operation.event_payload_schema].model_fields
            )
        assert operation.policy_checks and operation.work_item
    for lifecycle in LIFECYCLES.values():
        for targets in lifecycle.values():
            assert set(targets).issubset(lifecycle)


@pytest.mark.parametrize("unit", ["°C", "%", "m³/s", "kg/m^3"])
def test_engineering_units_are_preserved_instead_of_treated_as_identifier_keys(unit: str) -> None:
    from app.contracts.common_objects import Metric

    metric = Metric.model_validate(
        {
            "metric_key": "measurement",
            "raw_value": None,
            "normalized_value": None,
            "unit": unit,
            "verdict": "unknown",
        }
    )
    assert metric.unit == unit


def test_project_role_uses_existing_rbac_values_and_keeps_discipline_separate() -> None:
    from app.contracts.planning_records import ProjectRoleAssignment

    payload = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "user_id": USER,
        "tenant_role": "quality",
        "project_role": None,
        "disciplines": ["DQE", "SQE"],
        "effective_from": NOW,
        "effective_until": None,
    }
    assignment = ProjectRoleAssignment.model_validate(payload)
    assert assignment.project_role is None
    reject(ProjectRoleAssignment, payload, {"project_role": "DQE"}, "enum")


def test_object_ownership_catalog_resolves_models_namespaces_and_work_items() -> None:
    import json
    from pathlib import Path

    from app.db.namespaces import SCHEMAS

    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "docs/contracts/pdos-v1/object-ownership.json").read_text())
    models = candidate_models()
    names: set[str] = set()
    for record in catalog["objects"]:
        assert record["model"] not in names
        names.add(record["model"])
        assert record["model"] in models
        assert record["namespace"] in SCHEMAS
        assert record["sor"] and record["owner"] and record["keys"]
        assert all(
            item in (root / "tasks/ai-native-integrated-todo.md").read_text()
            for item in record["work_items"]
        )


def strategy_candidate_payload(disciplines: list[str]) -> dict[str, Any]:
    """Unconfirmed proposal with explicit unknown budgets and existing work identifiers."""
    fact = hypothesis()
    budget = {"amount": None, "basis": fact}
    return {
        "opportunity_id": uuid4(),
        "title": "专业约束候选",
        "canvas": {key: fact for key in StrategyCanvas.model_fields},
        "route_comparisons": [
            {
                "solution_id": uuid4(),
                "currency": "CNY",
                "price_target": budget,
                "nre_budget": budget,
                "id_cycle_days": budget,
                "modules": [{"key": "assembly", "name": "装配", "target": budget}],
                **{
                    key: fact
                    for key in (
                        "scope",
                        "quality",
                        "supply",
                        "manufacturing",
                        "resources",
                        "trade_off",
                    )
                },
            }
            for _ in range(3)
        ],
        "professional_constraints": [
            {"discipline": discipline, "statement": fact, "work_item_id": uuid4()}
            for discipline in disciplines
        ],
        "unknowns": ["设备投入与产能待验证，未形成承诺"],
        "decision_reason": "待人工核对",
    }


@pytest.mark.parametrize("manufacturing", ["ie", "pie", "IE", "PIE"])
def test_strategy_candidate_accepts_pie_without_rewriting_legacy_ie(manufacturing: str) -> None:
    from app.contracts.product_planning_ai import StrategyCandidate

    payload = strategy_candidate_payload(["dqe", "sqe", manufacturing])
    value = StrategyCandidate.model_validate(payload)
    assert value.professional_constraints[-1].discipline == manufacturing
    assert (
        value.professional_constraints[-1].work_item_id
        == payload["professional_constraints"][-1]["work_item_id"]
    )
    assert value.professional_constraints[-1].statement.fact_kind == "hypothesis"
    assert value.route_comparisons[0].modules[0].target.amount is None
    assert value.unknowns == ("设备投入与产能待验证，未形成承诺",)


@pytest.mark.parametrize(
    "disciplines", [["dqe", "sqe", "product"], ["pie", "sqe", "test"], ["dqe", "pie", "test"]]
)
def test_pie_does_not_replace_dqe_sqe_or_missing_manufacturing(disciplines: list[str]) -> None:
    from app.contracts.product_planning_ai import StrategyCandidate

    with pytest.raises(ValidationError, match="DQE/SQE"):
        StrategyCandidate.model_validate(strategy_candidate_payload(disciplines))


def test_pie_candidate_cannot_supply_disposition_or_authority() -> None:
    from app.contracts.product_planning_ai import StrategyCandidate

    payload = strategy_candidate_payload(["dqe", "sqe", "pie"])
    payload["professional_constraints"][-1]["disposition"] = {
        "outcome": "accepted",
        "reason": "AI宣称已确认",
        "sources": [],
    }
    with pytest.raises(ValidationError, match="disposition"):
        StrategyCandidate.model_validate(payload)
