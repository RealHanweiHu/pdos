"""Frozen event registry derived from the CEHub v3.2 event catalog."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

IDEMPOTENCY_RULE = "unique(source,event_id); reuse event_id on retry"


class UnknownEventTypeError(ValueError):
    """Raised when a producer attempts to emit an unregistered event type."""


@dataclass(frozen=True)
class EventDefinition:
    event_type: str
    version: int
    entity: str
    producer: str
    consumers: tuple[str, ...]
    payload_schema: dict[str, Any]
    idempotency: str = IDEMPOTENCY_RULE


def _payload_schema(**required_properties: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {"type": property_type} for name, property_type in required_properties.items()
        },
        "required": list(required_properties),
        "additionalProperties": False,
    }


_DEFINITIONS = (
    EventDefinition(
        event_type="PROJECT_CREATED",
        version=1,
        entity="project",
        producer="project_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(project_code="string", project_name="string"),
    ),
    EventDefinition(
        event_type="PROJECT_STAGE_CHANGED",
        version=1,
        entity="project",
        producer="project_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_stage_id="string", to_stage_id="string"),
    ),
    EventDefinition(
        event_type="PROJECT_UPDATED",
        version=1,
        entity="project",
        producer="project_service",
        consumers=("timeline_projection",),
        payload_schema=_payload_schema(changed_fields="array", status="string"),
    ),
    EventDefinition(
        event_type="PROJECT_STATUS_CHANGED",
        version=1,
        entity="project",
        producer="project_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="SPECIFICATION_CREATED",
        version=1,
        entity="specification",
        producer="product_engineering_service",
        consumers=("product_projection", "timeline_projection"),
        payload_schema=_payload_schema(specification_code="string", version="integer"),
    ),
    EventDefinition(
        event_type="DEVELOPMENT_BOM_CREATED",
        version=1,
        entity="development_bom",
        producer="product_engineering_service",
        consumers=("product_projection", "timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(
            bom_code="string",
            bom_type="string",
            version="integer",
        ),
    ),
    EventDefinition(
        event_type="DEVELOPMENT_BOM_ITEM_ADDED",
        version=1,
        entity="development_bom_item",
        producer="product_engineering_service",
        consumers=("product_projection", "cost_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(
            bom_id="string",
            part_number="string",
            line_number="integer",
        ),
    ),
    EventDefinition(
        event_type="ERP_BOM_REFERENCE_ADDED",
        version=1,
        entity="erp_bom_reference",
        producer="product_engineering_service",
        consumers=("product_projection", "erp_handoff_projection"),
        payload_schema=_payload_schema(
            reference_type="string",
            source_system="string",
            external_id="string",
        ),
    ),
    EventDefinition(
        event_type="GATE_APPROVED",
        version=1,
        entity="gate",
        producer="gate_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(gate_id="string", decision_id="string"),
    ),
    EventDefinition(
        event_type="DOCUMENT_UPLOADED",
        version=1,
        entity="document",
        producer="document_service",
        consumers=("document_pipeline", "agent_dispatcher"),
        payload_schema=_payload_schema(document_id="string", classification="string"),
    ),
    EventDefinition(
        event_type="TEST_FAILED",
        version=1,
        entity="test",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(test_record_id="string", severity="string"),
    ),
    EventDefinition(
        event_type="NPI_RECORD_CHANGED",
        version=1,
        entity="npi_record",
        producer="npi_service",
        consumers=("timeline_projection", "quality_projection"),
        payload_schema=_payload_schema(record_type="string", action="string"),
    ),
    EventDefinition(
        event_type="CHANGE_RECORD_CHANGED",
        version=1,
        entity="change_record",
        producer="change_service",
        consumers=("timeline_projection", "product_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(record_type="string", action="string"),
    ),
    EventDefinition(
        event_type="DELIVERABLE_CHECK_CHANGED",
        version=1,
        entity="deliverable_check",
        producer="deliverable_check_service",
        consumers=("timeline_projection", "gate_projection"),
        payload_schema=_payload_schema(record_type="string", action="string", count="integer"),
    ),
    EventDefinition(
        event_type="ISSUE_CREATED",
        version=1,
        entity="issue",
        producer="issue_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(issue_id="string", severity="string"),
    ),
    EventDefinition(
        event_type="TASK_CREATED",
        version=1,
        entity="task",
        producer="task_service",
        consumers=("timeline_projection",),
        payload_schema=_payload_schema(task_id="string", status="string", priority="string"),
    ),
    EventDefinition(
        event_type="TASK_UPDATED",
        version=1,
        entity="task",
        producer="task_service",
        consumers=("timeline_projection",),
        payload_schema=_payload_schema(changed_fields="array", status="string"),
    ),
    EventDefinition(
        event_type="TASK_STATUS_CHANGED",
        version=1,
        entity="task",
        producer="task_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="ISSUE_UPDATED",
        version=1,
        entity="issue",
        producer="issue_service",
        consumers=("timeline_projection",),
        payload_schema=_payload_schema(changed_fields="array", status="string", severity="string"),
    ),
    EventDefinition(
        event_type="ISSUE_STATUS_CHANGED",
        version=1,
        entity="issue",
        producer="issue_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="RISK_CREATED",
        version=1,
        entity="risk",
        producer="risk_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(risk_id="string", score="integer", status="string"),
    ),
    EventDefinition(
        event_type="RISK_UPDATED",
        version=1,
        entity="risk",
        producer="risk_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(changed_fields="array", status="string", score="integer"),
    ),
    EventDefinition(
        event_type="RISK_STATUS_CHANGED",
        version=1,
        entity="risk",
        producer="risk_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="SUPPLIER_DELAY_REPORTED",
        version=1,
        entity="supplier_delay",
        producer="supplier_service",
        consumers=("supplier_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(
            supplier_id="string",
            expected_date="string",
            reported_date="string",
        ),
    ),
    EventDefinition(
        event_type="COMPLAINT_CREATED",
        version=1,
        entity="complaint",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(complaint_id="string", severity="string"),
    ),
    EventDefinition(
        event_type="COMPLAINT_STATUS_CHANGED",
        version=1,
        entity="complaint",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="NCR_CREATED",
        version=1,
        entity="nonconformance_report",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(complaint_id="string", severity="string"),
    ),
    EventDefinition(
        event_type="NCR_STATUS_CHANGED",
        version=1,
        entity="nonconformance_report",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="ROOT_CAUSE_ANALYSIS_CHANGED",
        version=1,
        entity="root_cause_analysis",
        producer="quality_service",
        consumers=("quality_projection",),
        payload_schema=_payload_schema(action="string", status="string", version="integer"),
    ),
    EventDefinition(
        event_type="CAPA_ACTION_CREATED",
        version=1,
        entity="capa_action",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(ncr_id="string", action_type="string"),
    ),
    EventDefinition(
        event_type="CAPA_ACTION_STATUS_CHANGED",
        version=1,
        entity="capa_action",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="EFFECTIVENESS_REVIEWED",
        version=1,
        entity="effectiveness_review",
        producer="quality_service",
        consumers=("quality_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(ncr_id="string", result="string", review_number="integer"),
    ),
    EventDefinition(
        event_type="NCR_PREVENTIVE_DISPOSITION_APPROVED",
        version=1,
        entity="nonconformance_report",
        producer="quality_service",
        consumers=("quality_projection",),
        payload_schema=_payload_schema(ncr_id="string"),
    ),
    EventDefinition(
        event_type="MEMORY_DRAFT_CREATED",
        version=1,
        entity="memory",
        producer="memory_service",
        consumers=("knowledge_projection", "timeline_projection"),
        payload_schema=_payload_schema(memory_id="string", source_type="string"),
    ),
    EventDefinition(
        event_type="MEMORY_DRAFT_UPDATED",
        version=1,
        entity="memory",
        producer="memory_service",
        consumers=("knowledge_projection",),
        payload_schema=_payload_schema(memory_id="string", content_sha256="string"),
    ),
    EventDefinition(
        event_type="MEMORY_VERIFIED",
        version=1,
        entity="memory",
        producer="memory_service",
        consumers=("knowledge_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(memory_id="string", content_sha256="string"),
    ),
    EventDefinition(
        event_type="MEMORY_ARCHIVED",
        version=1,
        entity="memory",
        producer="memory_service",
        consumers=("knowledge_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(memory_id="string", content_sha256="string"),
    ),
    EventDefinition(
        event_type="MEMORY_EMBEDDED",
        version=1,
        entity="memory",
        producer="memory_service",
        consumers=("knowledge_projection",),
        payload_schema=_payload_schema(
            memory_id="string",
            provider="string",
            model="string",
            dimensions="integer",
            content_sha256="string",
        ),
    ),
    EventDefinition(
        event_type="AI_FINDING_CREATED",
        version=1,
        entity="ai_finding",
        producer="ai_runtime",
        consumers=("review_inbox", "timeline_projection"),
        payload_schema=_payload_schema(finding_id="string", agent_run_id="string"),
    ),
    EventDefinition(
        event_type="AI_FEEDBACK_RECEIVED",
        version=1,
        entity="ai_finding",
        producer="finding_review_service",
        consumers=("ai_evaluation", "timeline_projection"),
        payload_schema=_payload_schema(finding_id="string", decision="string"),
    ),
    EventDefinition(
        event_type="TENANT_BOOTSTRAPPED",
        version=1,
        entity="tenant",
        producer="auth_service",
        consumers=("security_audit",),
        payload_schema=_payload_schema(initial_admin_user_id="string"),
    ),
    EventDefinition(
        event_type="USER_SIGNED_IN",
        version=1,
        entity="user",
        producer="auth_service",
        consumers=("security_audit",),
        payload_schema=_payload_schema(authentication_method="string"),
    ),
    EventDefinition(
        event_type="DINGTALK_IDENTITY_LINKED",
        version=1,
        entity="dingtalk_identity",
        producer="dingtalk_connector_service",
        consumers=("security_audit",),
        payload_schema=_payload_schema(user_id="string", status="string"),
    ),
    EventDefinition(
        event_type="DINGTALK_APPROVAL_UPDATED",
        version=1,
        entity="dingtalk_approval",
        producer="dingtalk_connector_service",
        consumers=("integration_projection", "timeline_projection"),
        payload_schema=_payload_schema(approval_id="string", status="string"),
    ),
    EventDefinition(
        event_type="DINGTALK_NOTIFICATION_DELIVERED",
        version=1,
        entity="integration_outbox",
        producer="dingtalk_connector_service",
        consumers=("integration_projection",),
        payload_schema=_payload_schema(outbox_id="string", operation="string"),
    ),
    EventDefinition(
        event_type="DINGTALK_CARD_ACTION_RECEIVED",
        version=1,
        entity="dingtalk_card",
        producer="dingtalk_connector_service",
        consumers=("integration_projection", "security_audit"),
        payload_schema=_payload_schema(card_id="string", action="string"),
    ),
    EventDefinition(
        event_type="REQUIREMENT_CREATED",
        version=1,
        entity="requirement",
        producer="requirement_service",
        consumers=("intake_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(
            requirement_code="string",
            status="string",
            priority="string",
        ),
    ),
    EventDefinition(
        event_type="REQUIREMENT_UPDATED",
        version=1,
        entity="requirement",
        producer="requirement_service",
        consumers=("intake_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(
            changed_fields="array",
            status="string",
            priority="string",
        ),
    ),
    EventDefinition(
        event_type="REQUIREMENT_CONVERTED",
        version=1,
        entity="requirement",
        producer="development_case_service",
        consumers=("intake_projection", "timeline_projection"),
        payload_schema=_payload_schema(
            development_case_id="string",
            decision_id="string",
        ),
    ),
    EventDefinition(
        event_type="DEVELOPMENT_CASE_CREATED",
        version=1,
        entity="development_case",
        producer="development_case_service",
        consumers=("case_projection", "timeline_projection"),
        payload_schema=_payload_schema(
            case_code="string",
            requirement_id="string",
            status="string",
        ),
    ),
    EventDefinition(
        event_type="DEVELOPMENT_CASE_UPDATED",
        version=1,
        entity="development_case",
        producer="development_case_service",
        consumers=("case_projection", "timeline_projection"),
        payload_schema=_payload_schema(changed_fields="array", status="string"),
    ),
    EventDefinition(
        event_type="DEVELOPMENT_CASE_STATUS_CHANGED",
        version=1,
        entity="development_case",
        producer="development_case_service",
        consumers=("case_projection", "timeline_projection"),
        payload_schema=_payload_schema(from_status="string", to_status="string"),
    ),
    EventDefinition(
        event_type="DECISION_RECORDED",
        version=1,
        entity="decision",
        producer="development_case_service",
        consumers=("decision_projection", "timeline_projection"),
        payload_schema=_payload_schema(decision_kind="string", outcome="string"),
    ),
    EventDefinition(
        event_type="TENANT_MODEL_SETTINGS_UPDATED",
        version=1,
        entity="tenant_model_settings",
        producer="model_governance_service",
        consumers=("security_audit", "ai_runtime"),
        payload_schema=_payload_schema(
            provider="string",
            model="string",
            daily_token_budget="integer",
        ),
    ),
)

EVENT_REGISTRY = MappingProxyType(
    {definition.event_type: definition for definition in _DEFINITIONS}
)
SPEC_EVENT_TYPES = frozenset(
    {
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
)
SPRINT_1_IMPLEMENTED_EVENT_TYPES = frozenset(
    {
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
    }
)


def definition_for(event_type: str) -> EventDefinition:
    try:
        return EVENT_REGISTRY[event_type]
    except KeyError as error:
        raise UnknownEventTypeError(event_type) from error
