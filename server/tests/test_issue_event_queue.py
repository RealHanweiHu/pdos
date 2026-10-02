"""Dispatch authentication and late-commit selection contracts; no model calls."""

from copy import deepcopy
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.issue_event_queue import SkipIssueEvent, original_actor, pending_events_query
from app.domain.product_workspace import _plain
from tests.test_ai_issue_event_sources import ACTOR, audit, event


@pytest.mark.parametrize("kind", ["test", "confirmed", "reviewed"])
def test_original_actor_requires_exact_scoped_event_and_audit(kind: str) -> None:
    e = event()
    a = audit(e, {})
    if kind != "test":
        e.update(
            event_type="NPI_RECORD_CHANGED",
            source="npi_service",
            entity="npi_record",
            payload={"record_type": "material_exception", "action": kind},
        )
        a = audit(e, {}, action="npi.material_exception." + kind)
    source: dict[str, Any] = dict(
        event_row_id=e["id"],
        event_id=e["event_id"],
        event_type=e["event_type"],
        source={"event": _plain(e), "audit": _plain(a)},
    )
    assert original_actor(e, source) == ACTOR
    for name in (
        "tenant_id",
        "project_id",
        "event_id",
        "entity_id",
        "timestamp",
        "action",
        "actor_user_id",
    ):
        bad = deepcopy(source)
        bad["source"]["audit"][name] = "forged"
        with pytest.raises(SkipIssueEvent):
            original_actor(e, bad)


def test_pending_events_use_per_event_receipts_not_high_water_cursor() -> None:
    sql = str(
        pending_events_query().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert (
        "NOT (EXISTS" in sql
        and "ai_issue_event_receipts.event_row_id = cehub_event.events.id" in sql
    )
    assert "confirmed" in sql and "reviewed" in sql and "TEST_FAILED" in sql
    assert "events.id >" not in sql and "max(" not in sql
