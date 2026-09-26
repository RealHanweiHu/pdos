"""Stable server-owned model call slots within a persisted business run.

Inputs, prompt revisions and transport attempts never mint a new logical call.
The budget journal binds actual request digests and rejects incompatible replay.
This does not create a run or authorize restarting a completed business action.
"""

from enum import StrEnum
from uuid import UUID, uuid5


class ModelCallSlot(StrEnum):
    MEETING_PLANNING = "meeting_planning"
    INTAKE_ORGANIZATION = "intake_organization"
    PROCESS_TEMPLATE = "process_template_configuration"
    PORTFOLIO_EXPLANATION = "portfolio_explanation"
    EXECUTIVE_BRIEF = "executive_brief"
    PRODUCT_MATRIX = "product_matrix"
    COST_REDUCTION = "cost_reduction"
    SUPPLIER_RECOVERY = "supplier_recovery"
    QUALITY_WORK_PACKAGE = "quality_work_package"
    CHANGE_WORK_PACKAGE = "change_work_package"
    EVENT_ASSESSMENT = "event_assessment"
    RISK_SUGGESTION = "risk_suggestion"
    TEST_PLAN_SUGGESTION = "test_plan_suggestion"
    CHAT_ANSWER = "chat_answer"
    REPORT_MAPPING = "report_mapping"
    MEETING_READING = "meeting_reading"
    MEETING_BUSINESS = "meeting_business"
    MEETING_DECISIONS = "meeting_decisions"
    MEETING_ACTIONS = "meeting_actions"
    MEETING_MINUTES = "meeting_minutes"


def model_call_id(run_id: UUID, slot: ModelCallSlot) -> UUID:
    if not isinstance(run_id, UUID) or not isinstance(slot, ModelCallSlot):
        raise ValueError("persisted run UUID and server-defined call slot required")
    return uuid5(run_id, f"pdos-model-call.v1:{slot.value}")


def loop_model_call_id(run_id: UUID, step: int) -> UUID:
    if not isinstance(run_id, UUID) or type(step) is not int or not 0 <= step < 100:
        raise ValueError("persisted run and bounded server step required")
    return uuid5(run_id, f"pdos-model-loop.v1:{step}")
