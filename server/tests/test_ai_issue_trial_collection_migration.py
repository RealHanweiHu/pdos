"""Pure 0392 canonical DDL and immutable protocol/event provenance contracts."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.ai.runtime_contract import NO_ROUTE_EVENT_TYPES, agents_for_event
from app.db.schema import tables
from app.events.catalog import definition_for

migration = import_module("migrations.versions.0392_ai_issue_trial_collections")


def test_canonical_collection_ddl_has_complete_scoped_foreign_keys() -> None:
    table = tables.ai_issue_trial_collections
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert ddl == migration.DDL
    assert all(not column.nullable for column in table.columns)
    assert set(table.columns.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "protocol_id",
        "actor_user_id",
        "request_id",
        "request_digest",
        "collection_digest",
        "as_of",
        "created_at",
        "collection",
        "output_event_row_id",
    }
    assert {
        tuple(constraint.column_keys): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in table.foreign_key_constraints
    } == {
        ("tenant_id", "project_id"): (
            "cehub_project.projects.tenant_id",
            "cehub_project.projects.id",
        ),
        ("tenant_id", "actor_user_id"): ("cehub_core.users.tenant_id", "cehub_core.users.id"),
        ("tenant_id", "output_event_row_id"): (
            "cehub_event.events.tenant_id",
            "cehub_event.events.id",
        ),
        ("tenant_id", "project_id", "protocol_id"): (
            "cehub_ai.ai_issue_trial_protocols.tenant_id",
            "cehub_ai.ai_issue_trial_protocols.project_id",
            "cehub_ai.ai_issue_trial_protocols.id",
        ),
    }
    for fk in table.foreign_key_constraints:
        assert fk.ondelete == "RESTRICT"
        target_columns = tuple(element.column for element in fk.elements)
        target = target_columns[0].table
        assert tuple(column.name for column in target_columns) in {
            tuple(target.primary_key.columns.keys()),
            *(
                tuple(c.columns.keys())
                for c in target.constraints
                if isinstance(c, UniqueConstraint)
            ),
        }
    assert {
        tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)
    } == {
        ("tenant_id", "actor_user_id", "request_id"),
        ("tenant_id", "project_id", "protocol_id", "id"),
    }


def test_shape_requires_explicit_identity_complete_selection_and_integer_counts() -> None:
    shape = next(
        str(c.sqltext)
        for c in tables.ai_issue_trial_collections.constraints
        if isinstance(c, CheckConstraint)
    )
    for fragment in (
        "as_of<=created_at",
        "request_digest ~ '^[a-f0-9]{64}$'",
        "collection_digest ~ '^[a-f0-9]{64}$'",
        "jsonb_typeof(collection)='object'",
        "collection->>'version'='event-issue-trial-collection-v1'",
        *(
            f"collection->>'{key}'={key}::text"
            for key in ("id", "tenant_id", "project_id", "protocol_id", "actor_user_id")
        ),
        "(collection->>'as_of')::timestamptz=as_of",
        "(collection->>'created_at')::timestamptz=created_at",
        "collection->'selection_complete'='true'::jsonb",
        "collection->'qualification_granted'='false'::jsonb",
        "jsonb_typeof(collection->'items')='array'",
        "jsonb_typeof(collection->'total_runs')='number'",
        "collection->>'total_runs' ~ '^(0|[1-9][0-9]*)$'",
        "jsonb_typeof(collection->'matching_runs')='number'",
        "collection->>'matching_runs' ~ '^(0|[1-9][0-9]*)$'",
        "jsonb_array_length(collection->'items')=(collection->>'total_runs')::numeric",
        "(collection->>'matching_runs')::numeric <=(collection->>'total_runs')::numeric) IS TRUE",
    ):
        assert fragment in shape


def test_insert_binds_original_protocol_and_exact_named_event_audit() -> None:
    for fragment in (
        "p.tenant_id=NEW.tenant_id",
        "p.project_id=NEW.project_id",
        "p.id=NEW.protocol_id",
        "NEW.collection->>'protocol_digest'=p.protocol_digest",
        "(NEW.collection->>'window_start')::timestamptz=p.window_start",
        "(NEW.collection->>'window_end')::timestamptz=p.window_end",
        "p.window_end<=NEW.as_of",
        "p.created_at<=NEW.as_of",
        "e.tenant_id=NEW.tenant_id",
        "e.project_id=NEW.project_id",
        "e.id=NEW.output_event_row_id",
        "a.tenant_id=e.tenant_id",
        "a.project_id=e.project_id",
        "a.event_id=e.event_id",
        "a.entity=e.entity",
        "a.entity_id=e.entity_id",
        "a.timestamp=e.timestamp",
        "e.entity='ai_issue_trial_collection'",
        "e.entity_id=NEW.id",
        "e.schema_version=1",
        "e.event_type='AI_ISSUE_TRIAL_COLLECTED'",
        "e.source='ai_issue_trial_service'",
        "e.payload=jsonb_build_object(",
        "'collection_id',NEW.id::text,'collection_digest',NEW.collection_digest",
        "'protocol_id',NEW.protocol_id::text,'total_runs',NEW.collection->'total_runs'",
        "a.actor_user_id=NEW.actor_user_id",
        "a.action='ai_issue.trial_collected'",
        "a.after_snapshot=e.payload",
        "BEFORE INSERT ON cehub_ai.ai_issue_trial_collections",
        "BEFORE UPDATE OR DELETE\n ON cehub_ai.ai_issue_trial_collections",
        "cehub_ai.protect_checkpoint_history()",
        "REVOKE ALL ON cehub_ai.ai_issue_trial_collections FROM PUBLIC",
        "REVOKE ALL ON cehub_ai.ai_issue_trial_collections FROM pdos_agent",
    ):
        assert fragment in migration.GUARDS


def test_upgrade_and_history_preserving_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    operation = MagicMock()
    monkeypatch.setattr(migration, "op", operation)
    migration.upgrade()
    assert [c.args[0] for c in operation.execute.call_args_list] == [
        migration.DDL,
        migration.GUARDS,
    ]
    operation.reset_mock()
    migration.downgrade()
    statements = [c.args[0] for c in operation.execute.call_args_list]
    assert (
        "IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_trial_collections) THEN RAISE EXCEPTION"
        in statements[0]
    )
    assert statements[1:] == [
        "DROP TABLE cehub_ai.ai_issue_trial_collections",
        "DROP FUNCTION cehub_ai.guard_issue_trial_collection()",
    ]
    operation.reset_mock()
    operation.execute.side_effect = RuntimeError("Retain original Issue trial collections")
    with pytest.raises(RuntimeError, match="Retain original"):
        migration.downgrade()
    assert operation.execute.call_count == 1
    assert migration.down_revision == "0391_ai_issue_trial_protocols"


def test_collection_event_is_security_audit_only_and_never_routes_an_agent() -> None:
    event = definition_for("AI_ISSUE_TRIAL_COLLECTED")
    assert (event.entity, event.producer, event.consumers) == (
        "ai_issue_trial_collection",
        "ai_issue_trial_service",
        ("security_audit",),
    )
    assert event.payload_schema["required"] == [
        "collection_id",
        "collection_digest",
        "protocol_id",
        "total_runs",
    ]
    assert event.payload_schema["additionalProperties"] is False
    assert event.payload_schema["properties"]["total_runs"]["type"] == "integer"
    assert event.event_type in NO_ROUTE_EVENT_TYPES
    assert agents_for_event(event.event_type) == ()
