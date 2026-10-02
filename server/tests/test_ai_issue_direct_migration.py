"""Pure frozen DDL and lineage guard checks; no SQL execution."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.ai.runtime_contract import NO_ROUTE_EVENT_TYPES, agents_for_event
from app.db.schema import tables
from app.events.catalog import definition_for

migration = import_module("migrations.versions.0393_ai_issue_direct_samples")


def shape(table: object) -> str:
    assert hasattr(table, "constraints")
    return str(next(c.sqltext for c in table.constraints if isinstance(c, CheckConstraint)))


def test_frozen_table_and_changed_constraints_match_schema() -> None:
    ddl = str(CreateTable(tables.ai_issue_sample_reviews).compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert ddl == migration.DDL
    assert shape(tables.ai_issue_applications) == migration.NEW_APPLICATION_SHAPE
    assert shape(tables.ai_write_runtime_stops) == migration.NEW_STOP_SHAPE
    assert tables.ai_issue_applications.c.confirmed_by_user_id.nullable
    for fk in tables.ai_issue_sample_reviews.foreign_key_constraints:
        assert fk.ondelete == "RESTRICT"
        assert all(element.column is not None for element in fk.elements)
    assert len(tables.ai_issue_sample_reviews.foreign_key_constraints) == 4


def test_direct_shape_rejects_missing_receipt_keys_and_does_not_name_fake_human() -> None:
    for fragment in (
        "capture_mode IN ('trial','direct')",
        "capture_mode='trial' AND confirmed_by_user_id IS NOT NULL",
        "receipt->>'route'='confirmed_trial'",
        "capture_mode='direct' AND confirmed_by_user_id IS NULL",
        "receipt->>'route'='automatic'",
        "jsonb_typeof(receipt->'write_receipt'->'sampled')='boolean'",
        "receipt->'write_receipt'->>'route'='direct'",
        "receipt->'write_receipt'->>'run_id'=run_id::text",
        "receipt->'write_receipt'->>'policy_id'=policy_id::text",
        "receipt->'write_receipt'->>'scope_revision_id'=scope_revision_id::text",
        "receipt->'write_receipt'->>'principal_id'=principal_id::text",
        ") IS TRUE",
    ):
        assert fragment in migration.NEW_APPLICATION_SHAPE
    assert "'event.issue.create'" in migration.NEW_STOP_SHAPE


def test_direct_guard_binds_original_policy_scope_protocol_collection_and_both_audits() -> None:
    for fragment in (
        "a.actor_user_id IS NULL",
        "a.after_snapshot=NEW.receipt",
        "a.action='ai_issue.automatic_apply'",
        "a.action='ai_issue.confirmed_apply'",
        "a.context->'confirmed_by_user_id'='null'::jsonb",
        "a.context->'write_execution'=NEW.receipt->'write_receipt'",
        "((run.run_context->'issue_write_execution')-'application_id')=NEW.receipt->'write_receipt'",
        "protocol.evidence_kind='real_business'",
        "protocol.scope_revision_id=NEW.scope_revision_id",
        "collection.protocol_id=protocol.id",
        "later.created_at<=NEW.created_at",
        "(later.created_at,later.id)>(collection.created_at,collection.id)",
        "->'original_result'->>'status'='meets_candidate_criteria'",
        "->'fresh_result'->>'status'='meets_candidate_criteria'",
        "->'provider_verified'='true'::jsonb",
        "->'provenance_verified'='true'::jsonb",
        "->'references'->>'result_id'=NEW.result_id::text",
        "->'references'->>'invocation_id'=NEW.model_invocation_id::text",
        "->'monitor'->'stopped'='false'::jsonb",
    ):
        assert fragment in migration.APPLICATION_GUARD


def test_review_guard_requires_sample_and_current_issue_named_event_and_immutable_history() -> None:
    for fragment in (
        "a.capture_mode='direct'",
        "a.receipt->'write_receipt'->'sampled'='true'::jsonb",
        "i.withdrawn_at IS NULL",
        "i.updated_at=NEW.issue_updated_at",
        "MAX(version)",
        "a.actor_user_id=NEW.actor_user_id",
        "a.action='ai_issue.sample_review'",
        "a.after_snapshot->'issue_snapshot'=NEW.issue_snapshot",
        "a.after_snapshot->>'issue_digest'=NEW.issue_digest",
        "BEFORE UPDATE OR DELETE",
        "protect_checkpoint_history()",
    ):
        assert fragment in migration.SAMPLE_GUARD
    event = definition_for("AI_ISSUE_SAMPLE_REVIEWED")
    assert event.consumers == ("security_audit",)
    assert event.event_type in NO_ROUTE_EVENT_TYPES and agents_for_event(event.event_type) == ()


def test_downgrade_cannot_discard_any_new_history(monkeypatch: pytest.MonkeyPatch) -> None:
    operation = MagicMock()
    monkeypatch.setattr(migration, "op", operation)
    migration.downgrade()
    statements = [call.args[0] for call in operation.execute.call_args_list]
    for marker in (
        "ai_issue_sample_reviews",
        "capture_mode='direct'",
        "operation_key='event.issue.create'",
    ):
        assert marker in statements[0]
    assert "RAISE EXCEPTION" in statements[0]
    assert migration.OLD_APPLICATION_GUARD in statements
    assert any("SET NOT NULL" in item for item in statements)
    operation.reset_mock()
    operation.execute.side_effect = RuntimeError("Retain history")
    with pytest.raises(RuntimeError, match="Retain history"):
        migration.downgrade()
    assert operation.execute.call_count == 1
