"""Pure dispatcher checks: immutable helper controls only AI creation success routing."""

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Engine, Update
from sqlalchemy.exc import SQLAlchemyError

from app.worker import dispatcher

TENANT, PROJECT, ISSUE, CURSOR = (UUID(int=i) for i in range(1, 5))


def event(identity: int, kind: str = "ISSUE_CREATED", **values: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "entity": "issue",
        "entity_id": ISSUE,
        "event_type": kind,
        "source": "issue_service",
        "timestamp": datetime(2026, 9, 27, tzinfo=UTC),
        "payload": {"issue_id": str(ISSUE)},
        **values,
    }


def setup_dispatcher(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]], silent: Any
) -> tuple[dispatcher.AgentDispatcher, MagicMock, MagicMock, MagicMock]:
    c, engine, route, subscription = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    engine.begin.return_value.__enter__.return_value = c
    c.execute.return_value.mappings.return_value.__iter__.side_effect = lambda: iter(events)
    service = dispatcher.AgentDispatcher(cast(Engine, engine))
    monkeypatch.setattr(service, "_lock_tenant_consumer", lambda *a, **k: None)
    monkeypatch.setattr(service, "_cursor", lambda *a, **k: {"id": CURSOR, "last_event_row_id": 10})
    monkeypatch.setattr(dispatcher, "require_employee_agent", lambda *a: None)
    monkeypatch.setattr(dispatcher, "is_silent_ai_issue_event", silent)
    subscription.return_value = {"status": "active"}
    route.return_value = True
    monkeypatch.setattr(service, "_subscription", subscription)
    monkeypatch.setattr(service, "_route_event", route)
    return service, c, route, subscription


def test_silent_creation_advances_cursor_without_subscription_run_or_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = event(11)
    silent = MagicMock(return_value=True)
    service, c, route, subscription = setup_dispatcher(monkeypatch, [original], silent)
    result = service.dispatch_tenant(tenant_id=TENANT)
    assert result == dispatcher.DispatchResult(1, 0, 0, 0, 11)
    route.assert_not_called()
    subscription.assert_not_called()
    silent.assert_called_once_with(c, original)
    updates = [
        call.args[0] for call in c.execute.call_args_list if isinstance(call.args[0], Update)
    ]
    assert len(updates) == 1 and updates[0].compile().params["last_event_row_id"] == 11


@pytest.mark.parametrize("payload", [{}, {"origin": "ai", "writer_principal_id": str(ISSUE)}])
def test_human_or_unverified_creation_retains_original_routing(
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = event(11, payload=payload)
    service, _, route, subscription = setup_dispatcher(
        monkeypatch, [original], MagicMock(return_value=False)
    )
    result = service.dispatch_tenant(tenant_id=TENANT)
    assert result == dispatcher.DispatchResult(1, 1, 1, 0, 11)
    assert route.call_args.kwargs["event"] is original
    subscription.assert_called_once()


def test_mixed_batch_preserves_later_human_status_trigger_and_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [event(11), event(12), event(13, "ISSUE_STATUS_CHANGED")]
    silent = MagicMock(side_effect=lambda c, e: e["id"] == 11)
    service, _, route, _ = setup_dispatcher(monkeypatch, rows, silent)
    route.side_effect = [True, False]
    result = service.dispatch_tenant(tenant_id=TENANT)
    assert result == dispatcher.DispatchResult(3, 2, 1, 1, 13)
    assert [call.kwargs["event"]["id"] for call in route.call_args_list] == [12, 13]
    assert [call.args[1]["id"] for call in silent.call_args_list] == [11, 12]


def test_updated_event_retains_existing_no_route_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    silent = MagicMock(return_value=True)
    service, _, route, _ = setup_dispatcher(monkeypatch, [event(11, "ISSUE_UPDATED")], silent)
    assert service.dispatch_tenant(tenant_id=TENANT) == dispatcher.DispatchResult(1, 0, 0, 0, 11)
    silent.assert_not_called()
    route.assert_not_called()


def test_failed_trust_read_never_marks_event_scanned_or_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silent = MagicMock(side_effect=SQLAlchemyError("read failed"))
    service, c, route, _ = setup_dispatcher(monkeypatch, [event(11)], silent)
    with pytest.raises(SQLAlchemyError, match="read failed"):
        service.dispatch_tenant(tenant_id=TENANT)
    route.assert_not_called()
    assert not any(isinstance(call.args[0], Update) for call in c.execute.call_args_list)
