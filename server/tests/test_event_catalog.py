from __future__ import annotations

import pytest

from app.events.catalog import (
    EVENT_REGISTRY,
    SPEC_EVENT_TYPES,
    SPRINT_1_IMPLEMENTED_EVENT_TYPES,
    UnknownEventTypeError,
    definition_for,
)

EXPECTED_SPEC_EVENT_TYPES = {
    "PROJECT_CREATED",
    "PROJECT_STAGE_CHANGED",
    "GATE_APPROVED",
    "DOCUMENT_UPLOADED",
    "TEST_FAILED",
    "ISSUE_CREATED",
    "SUPPLIER_DELAY_REPORTED",
    "COMPLAINT_CREATED",
    "AI_FINDING_CREATED",
    "AI_FEEDBACK_RECEIVED",
}


def test_spec_event_catalog_is_complete_and_versioned() -> None:
    assert SPEC_EVENT_TYPES == EXPECTED_SPEC_EVENT_TYPES
    assert EVENT_REGISTRY.keys() >= SPEC_EVENT_TYPES

    for event_type in SPEC_EVENT_TYPES:
        definition = definition_for(event_type)
        assert definition.event_type == event_type
        assert definition.version == 1
        assert definition.producer
        assert definition.consumers
        assert definition.idempotency == "unique(source,event_id); reuse event_id on retry"
        assert definition.payload_schema["type"] == "object"
        assert set(definition.payload_schema["required"]) <= set(
            definition.payload_schema["properties"]
        )
        assert definition.payload_schema["additionalProperties"] is False


def test_domain_write_events_are_registered_without_changing_the_spec_catalog() -> None:
    assert {
        "TENANT_BOOTSTRAPPED",
        "USER_SIGNED_IN",
        "REQUIREMENT_CREATED",
        "REQUIREMENT_UPDATED",
        "REQUIREMENT_CONVERTED",
        "DEVELOPMENT_CASE_CREATED",
        "DEVELOPMENT_CASE_UPDATED",
        "DEVELOPMENT_CASE_STATUS_CHANGED",
        "DECISION_RECORDED",
        "PROJECT_CREATED",
        "PROJECT_UPDATED",
        "PROJECT_STATUS_CHANGED",
        "PROJECT_STAGE_CHANGED",
        "TASK_CREATED",
        "TASK_UPDATED",
        "TASK_STATUS_CHANGED",
        "ISSUE_CREATED",
        "ISSUE_UPDATED",
        "ISSUE_STATUS_CHANGED",
        "RISK_CREATED",
        "RISK_UPDATED",
        "RISK_STATUS_CHANGED",
    } == SPRINT_1_IMPLEMENTED_EVENT_TYPES
    assert EVENT_REGISTRY.keys() >= SPRINT_1_IMPLEMENTED_EVENT_TYPES
    assert "TENANT_BOOTSTRAPPED" not in SPEC_EVENT_TYPES
    assert "USER_SIGNED_IN" not in SPEC_EVENT_TYPES
    assert "REQUIREMENT_CREATED" not in SPEC_EVENT_TYPES
    assert "REQUIREMENT_UPDATED" not in SPEC_EVENT_TYPES

    created = definition_for("REQUIREMENT_CREATED")
    assert created.entity == "requirement"
    assert created.producer == "requirement_service"
    assert created.payload_schema["required"] == ["requirement_code", "status", "priority"]

    updated = definition_for("REQUIREMENT_UPDATED")
    assert updated.entity == "requirement"
    assert updated.producer == "requirement_service"
    assert updated.payload_schema["properties"]["changed_fields"] == {"type": "array"}

    converted = definition_for("REQUIREMENT_CONVERTED")
    assert converted.entity == "requirement"
    assert converted.producer == "development_case_service"

    case_created = definition_for("DEVELOPMENT_CASE_CREATED")
    assert case_created.entity == "development_case"
    assert case_created.payload_schema["required"] == [
        "case_code",
        "requirement_id",
        "status",
    ]

    decision = definition_for("DECISION_RECORDED")
    assert decision.entity == "decision"
    assert decision.payload_schema["required"] == ["decision_kind", "outcome"]

    issue_created = definition_for("ISSUE_CREATED")
    assert issue_created.payload_schema["required"] == ["issue_id", "severity"]
    task_status = definition_for("TASK_STATUS_CHANGED")
    assert task_status.payload_schema["required"] == ["from_status", "to_status"]
    risk_created = definition_for("RISK_CREATED")
    assert risk_created.payload_schema["required"] == ["risk_id", "score", "status"]

    model_settings = definition_for("TENANT_MODEL_SETTINGS_UPDATED")
    assert model_settings.entity == "tenant_model_settings"
    assert model_settings.producer == "model_governance_service"
    assert model_settings.payload_schema["required"] == [
        "provider",
        "model",
        "daily_token_budget",
    ]

    specification_created = definition_for("SPECIFICATION_CREATED")
    assert specification_created.entity == "specification"
    assert specification_created.producer == "product_engineering_service"
    assert specification_created.payload_schema["required"] == [
        "specification_code",
        "version",
    ]

    change_record = definition_for("CHANGE_RECORD_CHANGED")
    assert change_record.entity == "change_record"
    assert change_record.producer == "change_service"
    assert change_record.payload_schema["required"] == ["record_type", "action"]

    bom_created = definition_for("DEVELOPMENT_BOM_CREATED")
    assert bom_created.entity == "development_bom"
    assert bom_created.payload_schema["required"] == ["bom_code", "bom_type", "version"]

    item_added = definition_for("DEVELOPMENT_BOM_ITEM_ADDED")
    assert item_added.payload_schema["required"] == ["bom_id", "part_number", "line_number"]

    erp_reference_added = definition_for("ERP_BOM_REFERENCE_ADDED")
    assert erp_reference_added.payload_schema["required"] == [
        "reference_type",
        "source_system",
        "external_id",
    ]


def test_unknown_event_types_fail_closed() -> None:
    with pytest.raises(UnknownEventTypeError):
        definition_for("NOT_REGISTERED")
