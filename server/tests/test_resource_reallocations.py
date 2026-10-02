"""Service boundary regressions; no engine connects to a database."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine

from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.domain import resource_reallocations as module
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest
from app.domain.resource_reallocation_inputs import (
    ReallocationApply,
    ReallocationDecision,
    ReallocationReview,
    ReallocationSubmit,
)


def context(role: Role = Role.OWNER) -> AuthContext:
    tenant = TenantRecord(uuid4(), "test", "test", "active")
    return AuthContext(
        tenant,
        UserRecord(uuid4(), tenant.id, "test", "test", role, None, None, 1, True),
    )


def service() -> tuple[module.ResourceReallocationService, MagicMock]:
    engine = MagicMock(spec=Engine)
    connection = MagicMock(spec=Connection)
    engine.begin.return_value.__enter__.return_value = connection
    return module.ResourceReallocationService(engine), connection


@pytest.mark.parametrize("mismatch", [False, True])
def test_waiting_duplicate_reads_receipt_after_project_locks(
    monkeypatch: pytest.MonkeyPatch, mismatch: bool
) -> None:
    caller, project, other = context(), uuid4(), uuid4()
    command = ReallocationDecision(
        request_id=uuid4(),
        allocation_id=uuid4(),
        expected_digest="a" * 64,
        action="approve",
        reason="confirmed",
    )
    saved = {"id": command.allocation_id, "payload_digest": command.expected_digest}
    monkeypatch.setattr(module, "row", lambda *args: saved)
    monkeypatch.setattr(module, "access", lambda *args: {"owner_user_id": caller.user.id})
    participants = [{"project_id": p} for p in sorted((project, other), key=str)]
    monkeypatch.setattr(module, "parts", lambda *args: participants)
    target, connection = service()
    locked: list[Any] = []
    receipt = {
        "id": uuid4(),
        "action": "approve",
        "request_digest": "b" * 64
        if mismatch
        else digest({"project_id": str(project), **command.model_dump(mode="json")}),
    }

    def execute(statement: Any) -> MagicMock:
        result = MagicMock()
        if statement._for_update_arg is not None:
            locked.append(statement.compile().params["id_1"])
        else:
            assert locked == [part["project_id"] for part in participants]
            result.mappings.return_value.one_or_none.return_value = receipt
        return result

    connection.execute.side_effect = execute
    if mismatch:
        with pytest.raises(ProductWorkError, match="请求编号"):
            target.decide(caller, project, command)
    else:
        result = target.decide(caller, project, command)
        assert result["id"] == str(receipt["id"])
    assert connection.execute.call_count == 3


@pytest.mark.parametrize("role", [Role.OWNER, Role.PROJECT_MANAGER])
@pytest.mark.parametrize("reason", ["优先级已失效：另一项目秘密名称", "容量已变化"])
def test_review_blocks_drift_without_exposing_other_project_sources(
    monkeypatch: pytest.MonkeyPatch, role: Role, reason: str
) -> None:
    caller, project = context(role), uuid4()
    command = ReallocationReview(allocation_id=uuid4(), expected_digest="a" * 64)
    saved = {"id": command.allocation_id, "payload_digest": command.expected_digest}
    monkeypatch.setattr(module, "row", lambda *args: saved)
    monkeypatch.setattr(module, "access", lambda *args: {})
    monkeypatch.setattr(module, "outcomes", lambda *args: ([], None))

    def stale(*args: Any) -> None:
        raise ProductWorkError(reason)

    monkeypatch.setattr(module, "ensure_current", stale)
    target, connection = service()
    result = target.review(caller, project, command)
    assert not result["sources_current"] and not result["capacity_clear"]
    assert result["blockers"]
    if role == Role.OWNER:
        assert result["blockers"] == [reason]
    else:
        assert reason not in result["blockers"]
        assert "秘密" not in str(result)
    connection.execute.assert_not_called()


def test_review_cannot_grant_access_or_replace_reviewed_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller, project = context(), uuid4()
    command = ReallocationReview(allocation_id=uuid4(), expected_digest="a" * 64)
    monkeypatch.setattr(
        module, "row", lambda *args: {"id": command.allocation_id, "payload_digest": "b" * 64}
    )
    target, _ = service()

    def denied(*args: Any) -> None:
        raise ProductWorkAccessError("当前无项目权限")

    monkeypatch.setattr(module, "access", denied)
    with pytest.raises(ProductWorkAccessError):
        target.review(caller, project, command)
    monkeypatch.setattr(module, "access", lambda *args: {})
    with pytest.raises(ProductWorkError, match="版本不一致"):
        target.review(caller, project, command)


@pytest.mark.parametrize("ended", ["applied", "reject", "withdraw", None])
def test_review_returns_current_eligibility_and_never_another_project_snapshot(
    monkeypatch: pytest.MonkeyPatch, ended: str | None
) -> None:
    caller, project = context(), uuid4()
    command = ReallocationReview(allocation_id=uuid4(), expected_digest="a" * 64)
    saved = {"id": command.allocation_id, "payload_digest": command.expected_digest}
    monkeypatch.setattr(module, "row", lambda *args: saved)
    monkeypatch.setattr(module, "access", lambda *args: {})
    monkeypatch.setattr(
        module,
        "outcomes",
        lambda *args: (
            [{"action": ended}] if ended in ("reject", "withdraw") else [],
            {"id": uuid4()} if ended == "applied" else None,
        ),
    )
    check = MagicMock(return_value={"private_snapshot": "not public"})
    monkeypatch.setattr(module, "ensure_current", check)
    target, _ = service()
    result = target.review(caller, project, command)
    assert result["sources_current"] is (ended is None)
    assert result["capacity_clear"] is (ended is None)
    assert "private_snapshot" not in result
    assert check.call_count == (1 if ended is None else 0)


@pytest.mark.parametrize("mismatch", [False, True])
def test_concurrent_submit_serializes_request_before_reading_existing_receipt(
    monkeypatch: pytest.MonkeyPatch, mismatch: bool
) -> None:
    caller, project = context(), uuid4()
    command = ReallocationSubmit.model_validate(
        {
            "request_id": str(uuid4()),
            "title": "synthetic",
            "reason": "synthetic",
            "expected_preview_digest": "a" * 64,
            "items": [
                {
                    "reservation_id": str(uuid4()),
                    "expected_digest": "b" * 64,
                    "impact": "synthetic",
                    "target": {
                        "request_id": str(uuid4()),
                        "node_id": str(uuid4()),
                        "capacity_version_id": str(uuid4()),
                        "window_start": "2026-10-01T09:00Z",
                        "window_end": "2026-10-01T17:00Z",
                        "parallel_units": "1",
                        "occupancy_policy": "working_only",
                        "basis": "synthetic",
                    },
                }
                for _ in range(2)
            ],
        }
    )
    monkeypatch.setattr(module, "_project", lambda *args: {})
    monkeypatch.setattr(module, "access", lambda *args: {})
    capture = MagicMock()
    monkeypatch.setattr(module, "capture", capture)
    target, connection = service()
    held = False
    saved = {
        "id": uuid4(),
        "request_digest": "c" * 64 if mismatch else digest(command.model_dump(mode="json")),
    }

    def execute(statement: Any, parameters: Any = None) -> MagicMock:
        nonlocal held
        result = MagicMock()
        if parameters is not None:
            assert "pg_advisory_xact_lock" in str(statement)
            assert parameters["key"] == (
                f"resource-reallocation:{caller.tenant.id}:{caller.user.id}:{command.request_id}"
            )
            held = True
        else:
            assert held
            result.mappings.return_value.one_or_none.return_value = saved
        return result

    connection.execute.side_effect = execute
    if mismatch:
        with pytest.raises(ProductWorkError, match="请求编号"):
            target.submit(caller, project, command)
    else:
        assert target.submit(caller, project, command) == {"id": str(saved["id"])}
    capture.assert_not_called()


def test_repeated_application_returns_receipt_without_creating_or_releasing_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller, project = context(), uuid4()
    command = ReallocationApply(
        request_id=uuid4(),
        allocation_id=uuid4(),
        expected_digest="a" * 64,
        reason="synthetic",
    )
    saved, applied = {"id": command.allocation_id}, {"id": uuid4(), "receipt": {"items": []}}
    monkeypatch.setattr(module, "row", lambda *args: saved)
    monkeypatch.setattr(module, "access", lambda *args: {})
    monkeypatch.setattr(module, "_project", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "parts", lambda *args: [{"project_id": project}])
    monkeypatch.setattr(module, "outcomes", lambda *args: ([], applied))
    reservations = MagicMock()
    monkeypatch.setattr(module, "ResourceReservationService", reservations)
    target, connection = service()
    assert target.apply(caller, project, command)["id"] == str(applied["id"])
    reservations.assert_not_called()
    connection.execute.assert_not_called()


def test_second_confirmation_failure_exits_shared_transaction_without_application_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller, project, other = context(), uuid4(), uuid4()
    command = ReallocationApply(
        request_id=uuid4(),
        allocation_id=uuid4(),
        expected_digest="a" * 64,
        reason="synthetic",
    )
    saved = {"id": command.allocation_id, "payload_digest": command.expected_digest}
    participants = [{"project_id": p} for p in sorted((project, other), key=str)]
    monkeypatch.setattr(module, "row", lambda *args: saved)
    monkeypatch.setattr(module, "access", lambda *args: {})
    monkeypatch.setattr(module, "_project", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "parts", lambda *args: participants)
    monkeypatch.setattr(
        module,
        "outcomes",
        lambda *args: (
            [{"project_id": p["project_id"], "action": "approve"} for p in participants],
            None,
        ),
    )
    snapshot = {
        "items": [
            {
                "reservation_id": str(uuid4()),
                "project_id": str(p["project_id"]),
                "rank": index,
                "original": {"id": str(uuid4()), "state": "proposed"},
            }
            for index, p in enumerate(participants)
        ]
    }
    monkeypatch.setattr(module, "ensure_current", lambda *args: snapshot)
    reservations = MagicMock()
    reservations._act_in_transaction.side_effect = [
        {"id": str(uuid4())},
        ProductWorkError("second confirmation capacity conflict"),
    ]
    monkeypatch.setattr(module, "ResourceReservationService", lambda engine: reservations)
    target, connection = service()
    with pytest.raises(ProductWorkError, match="second confirmation"):
        target.apply(caller, project, command)
    assert reservations._act_in_transaction.call_count == 2
    assert all(
        call.args[0] is connection for call in reservations._act_in_transaction.call_args_list
    )
    connection.execute.assert_not_called()
    transaction = target.engine.begin.return_value  # type: ignore[attr-defined]
    assert transaction.__exit__.call_args.args[0] is ProductWorkError
