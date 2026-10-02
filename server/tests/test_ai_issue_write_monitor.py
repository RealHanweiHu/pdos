"""Pure deterministic sampling, SQL selection and latched stop behavior."""

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.domain import ai_issue_write_monitor as monitor

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def kwargs():
    return dict(
        tenant_id=uuid4(),
        project_id=uuid4(),
        policy_id=uuid4(),
        binding_digest="a" * 64,
        protocol_id=uuid4(),
        as_of=NOW,
        configuration={
            "maximum_retraction_basis_points": 500,
            "recovery_protocol_version": "fixture-recovery-v1",
            "recovery_conditions": "模拟恢复",
        },
    )


def test_sampling_is_fixed_by_protocol_and_run_not_read_time():
    protocol, run = UUID(int=1), UUID(int=2)
    boundary = int.from_bytes(sha256(f"{protocol}:{run}".encode()).digest(), "big") % 10000
    assert monitor.sampled_run(protocol, run, 10000)
    if boundary > 0:
        assert not monitor.sampled_run(protocol, run, boundary)
    assert monitor.sampled_run(protocol, run, boundary + 1)
    assert monitor.sampled_run(protocol, run, 100) == monitor.sampled_run(protocol, run, 100)


@pytest.mark.parametrize("value", [0, 10001, True, 1.0])
def test_sampling_rejects_invalid_ratio(value):
    with pytest.raises(ValueError):
        monitor.sampled_run(uuid4(), uuid4(), value)


def test_query_denominator_and_successful_withdrawal_are_exact():
    k = kwargs()
    query = monitor.monitor_query(
        **{
            key: k[key]
            for key in ("tenant_id", "project_id", "policy_id", "binding_digest", "as_of")
        }
    )
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    for fragment in (
        "capture_mode",
        "disposition",
        "write_receipt",
        "binding_digest",
        "ai_withdrawal_id",
        "withdrawn_at",
        "items @>",
        "jsonb_build_array",
        "jsonb_build_object",
        "FILTER (WHERE EXISTS",
    ):
        assert fragment in sql or fragment in compiled.params.values()
    for value in ("direct", "created", "application_id", "issue_id", "status", "withdrawn"):
        assert value in compiled.params.values()
    assert "scope_revision_id" not in sql and "protocol_id" not in sql


def test_existing_stop_is_not_cleared_by_new_protocol_or_scope():
    c = MagicMock()
    existing = {"id": uuid4(), "receipt": {"generated": 1, "withdrawn": 1}}
    c.execute.return_value.mappings.return_value.one_or_none.return_value = existing
    k = kwargs()
    first = monitor.quality_monitor(c, **k)
    k["protocol_id"] = uuid4()
    assert monitor.quality_monitor(c, **k) == first
    assert first["stopped"] and c.execute.call_count == 2
    for call in c.execute.call_args_list:
        sql = str(call.args[0])
        assert "scope_revision_id" not in sql and "protocol_id" not in sql


@pytest.mark.parametrize("total,withdrawn,stopped", [(0, 0, False), (20, 1, False), (19, 1, True)])
def test_integer_threshold_and_same_transaction_stop_event(monkeypatch, total, withdrawn, stopped):
    c = MagicMock()
    c.execute.return_value.mappings.return_value.one_or_none.return_value = None
    c.execute.return_value.one.return_value = SimpleNamespace(generated=total, withdrawn=withdrawn)
    writer = MagicMock()
    monkeypatch.setattr(monitor, "EventAuditWriter", writer)
    k = kwargs()
    result = monitor.quality_monitor(c, **k)
    assert result["stopped"] is stopped
    assert result["receipt"]["denominator"] == "all_direct_created_issues_in_project_policy_binding"
    assert result["receipt"]["automatic_recovery"] is False
    assert result["receipt"]["generated"] == total
    if stopped:
        assert c.execute.call_count == 3
        event, audit = writer.return_value.record.call_args.args
        assert event.event_type == "AI_WRITE_AUTOMATIC_STOPPED"
        assert event.source == "ai_meeting_write_service"
        assert event.payload["operation_key"] == "event.issue.create"
        assert audit.action == "ai_write.automatic_stop"
        assert audit.after_snapshot == result["receipt"]
    else:
        assert c.execute.call_count == 2
        writer.assert_not_called()
