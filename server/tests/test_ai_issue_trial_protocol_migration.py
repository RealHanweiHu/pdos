"""Pure 0391 DDL, provenance guard and registry checks; no database execution."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.ai.runtime_contract import NO_ROUTE_EVENT_TYPES, agents_for_event
from app.db.schema import tables
from app.events.catalog import definition_for

migration = import_module("migrations.versions.0391_ai_issue_trial_protocols")


def test_frozen_ddl_matches_schema_and_has_scoped_references() -> None:
    table = tables.ai_issue_trial_protocols
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert ddl == migration.DDL
    assert all(not column.nullable for column in table.columns)
    assert set(table.columns.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "actor_user_id",
        "request_id",
        "request_digest",
        "policy_id",
        "principal_id",
        "scope_revision_id",
        "window_start",
        "window_end",
        "evidence_kind",
        "protocol",
        "protocol_digest",
        "output_event_row_id",
        "created_at",
    }
    foreign_keys = {
        tuple(constraint.column_keys): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in table.foreign_key_constraints
    }
    assert foreign_keys == {
        ("tenant_id", "project_id"): (
            "cehub_project.projects.tenant_id",
            "cehub_project.projects.id",
        ),
        ("tenant_id", "actor_user_id"): ("cehub_core.users.tenant_id", "cehub_core.users.id"),
        ("tenant_id", "output_event_row_id"): (
            "cehub_event.events.tenant_id",
            "cehub_event.events.id",
        ),
        ("tenant_id", "policy_id"): (
            "cehub_ai.ai_write_policies.tenant_id",
            "cehub_ai.ai_write_policies.id",
        ),
        ("tenant_id", "principal_id"): (
            "cehub_ai.ai_principals.tenant_id",
            "cehub_ai.ai_principals.id",
        ),
        ("tenant_id", "project_id", "scope_revision_id"): (
            "cehub_ai.ai_write_scope_revisions.tenant_id",
            "cehub_ai.ai_write_scope_revisions.project_id",
            "cehub_ai.ai_write_scope_revisions.id",
        ),
    }
    for constraint in table.foreign_key_constraints:
        assert constraint.ondelete == "RESTRICT"
        # Resolve every target to its actual metadata column, not only its name.
        assert all(element.column is not None for element in constraint.elements)
    assert {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {("tenant_id", "project_id", "id"), ("tenant_id", "actor_user_id", "request_id")}


def test_shape_requires_explicit_json_values_and_prospective_real_business_window() -> None:
    shape = next(
        str(constraint.sqltext)
        for constraint in tables.ai_issue_trial_protocols.constraints
        if isinstance(constraint, CheckConstraint)
    )
    for fragment in (
        "window_start < window_end",
        "window_end-window_start <= interval '366 days'",
        "evidence_kind IN ('real_business','controlled_replay','synthetic')",
        "evidence_kind<>'real_business' OR window_start>created_at",
        "request_digest ~ '^[a-f0-9]{64}$'",
        "protocol_digest ~ '^[a-f0-9]{64}$'",
        "jsonb_typeof(protocol)='object'",
        "protocol->>'version'='event-issue-trial-protocol-v1'",
        "protocol->>'id'=id::text",
        "protocol->>'tenant_id'=tenant_id::text",
        "protocol->>'project_id'=project_id::text",
        "protocol->>'actor_user_id'=actor_user_id::text",
        "protocol->>'evidence_kind'=evidence_kind",
        "(protocol->>'window_start')::timestamptz=window_start",
        "(protocol->>'window_end')::timestamptz=window_end",
        "(protocol->>'created_at')::timestamptz=created_at",
        "protocol->'qualification_granted'='false'::jsonb) IS TRUE",
    ):
        assert fragment in shape


def test_insert_requires_same_named_event_and_audit_and_history_is_immutable() -> None:
    for fragment in (
        "e.tenant_id=NEW.tenant_id",
        "e.project_id=NEW.project_id",
        "e.id=NEW.output_event_row_id",
        "a.tenant_id=e.tenant_id",
        "a.project_id=e.project_id",
        "a.event_id=e.event_id",
        "a.entity=e.entity",
        "a.entity_id=e.entity_id",
        "a.timestamp=e.timestamp",
        "e.entity='ai_issue_trial_protocol'",
        "e.entity_id=NEW.id",
        "e.schema_version=1",
        "e.event_type='AI_ISSUE_TRIAL_REGISTERED'",
        "e.source='ai_issue_trial_service'",
        "e.payload->>'protocol_id'=NEW.id::text",
        "e.payload->>'protocol_digest'=NEW.protocol_digest",
        "e.payload->>'evidence_kind'=NEW.evidence_kind",
        "a.actor_user_id=NEW.actor_user_id",
        "a.action='ai_issue.trial_registered'",
        "a.after_snapshot->>'protocol_digest'=NEW.protocol_digest",
        "BEFORE INSERT ON cehub_ai.ai_issue_trial_protocols",
        "BEFORE UPDATE OR DELETE ON cehub_ai.ai_issue_trial_protocols",
        "cehub_ai.protect_checkpoint_history()",
        "REVOKE ALL ON cehub_ai.ai_issue_trial_protocols FROM PUBLIC",
        "REVOKE ALL ON cehub_ai.ai_issue_trial_protocols FROM pdos_agent",
    ):
        assert fragment in migration.GUARDS


def test_upgrade_and_empty_only_downgrade_order(monkeypatch: pytest.MonkeyPatch) -> None:
    operation = MagicMock()
    monkeypatch.setattr(migration, "op", operation)
    migration.upgrade()
    assert [call.args[0] for call in operation.execute.call_args_list] == [
        migration.DDL,
        migration.GUARDS,
    ]
    operation.reset_mock()
    migration.downgrade()
    statements = [call.args[0] for call in operation.execute.call_args_list]
    assert (
        "IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_trial_protocols) THEN RAISE EXCEPTION"
        in statements[0]
    )
    assert statements[1:] == [
        "DROP TABLE cehub_ai.ai_issue_trial_protocols",
        "DROP FUNCTION cehub_ai.guard_issue_trial_protocol()",
    ]
    operation.reset_mock()
    operation.execute.side_effect = RuntimeError("Retain original Issue trial protocols")
    with pytest.raises(RuntimeError, match="Retain original"):
        migration.downgrade()
    assert operation.execute.call_count == 1
    assert migration.down_revision == "0390_ai_issue_observations"


def test_registered_event_is_security_audit_only_without_agent_route() -> None:
    event = definition_for("AI_ISSUE_TRIAL_REGISTERED")
    assert (event.entity, event.producer, event.consumers) == (
        "ai_issue_trial_protocol",
        "ai_issue_trial_service",
        ("security_audit",),
    )
    assert event.payload_schema["required"] == ["protocol_id", "protocol_digest", "evidence_kind"]
    assert event.payload_schema["additionalProperties"] is False
    assert event.event_type in NO_ROUTE_EVENT_TYPES
    assert agents_for_event(event.event_type) == ()
