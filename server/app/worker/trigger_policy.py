"""Adopted event subset of the approved N0-02 trigger policies."""

from typing import Literal

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
    {
        "DEVELOPMENT_BOM_CREATED",
        "DEVELOPMENT_BOM_ITEM_ADDED",
        "DOCUMENT_UPLOADED",
    }
)


def policy_for_event(event_type: str) -> Literal["milestone", "frequent_edit"]:
    if event_type in MILESTONES:
        return "milestone"
    if event_type in FREQUENT_EDITS:
        return "frequent_edit"
    raise ValueError("routed event has no approved trigger policy")
