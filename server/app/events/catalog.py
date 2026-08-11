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
        event_type="ISSUE_CREATED",
        version=1,
        entity="issue",
        producer="issue_service",
        consumers=("timeline_projection", "agent_dispatcher"),
        payload_schema=_payload_schema(issue_id="string", severity="string"),
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


def definition_for(event_type: str) -> EventDefinition:
    try:
        return EVENT_REGISTRY[event_type]
    except KeyError as error:
        raise UnknownEventTypeError(event_type) from error
