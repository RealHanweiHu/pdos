"""Recognize committed AI Issue success without trusting event payload claims."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, text


def is_silent_ai_issue_event(c: Connection, event: Mapping[str, Any]) -> bool:
    """Only the exact original creation bound to an immutable application is silent.

    Consumers run after commit. Later human edits and current policy changes do
    not retroactively turn that successful creation into a new notification.
    The synchronous FMEA observer has a separate pre-application check.
    """
    if event.get("event_type") != "ISSUE_CREATED" or event.get("project_id") is None:
        return False
    return bool(
        c.execute(
            text(
                "SELECT cehub_ai.is_silent_ai_issue_event("
                "CAST(:tenant_id AS uuid), CAST(:project_id AS uuid), "
                "CAST(:event_row_id AS bigint), CAST(:issue_id AS uuid))"
            ),
            {
                "tenant_id": event["tenant_id"],
                "project_id": event["project_id"],
                "event_row_id": event["id"],
                "issue_id": event["entity_id"],
            },
        ).scalar_one()
    )
