"""No database: preregistration boundaries and frozen 0381 DDL contracts."""

from __future__ import annotations

import importlib.util
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, create_mock_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.contracts.ai_write_trial_protocol import CollectTrial, RegisterTrial, TrialProtocol
from app.db.schema import tables
from tests.test_ai_write_qualification_contract import binding, configuration

START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=1)
CREATED = START - timedelta(hours=1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("trial protocol contracts must not access database or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def request(**changes: Any) -> dict[str, Any]:
    return {
        "request_id": UUID(int=1),
        "project_ids": [UUID(int=3), UUID(int=2), UUID(int=3)],
        "binding": binding(),
        "evidence_kind": "real_business",
        "window_start": START,
        "window_end": END,
        "configuration": configuration().model_dump(
            exclude={
                "version",
                "configuration_id",
                "configuration_digest",
                "fixed_at",
                "minimum_confirmation_basis_points",
                "maximum_retraction_basis_points",
            }
        ),
        "reason": "预登记试运行",
        **changes,
    }


def protocol(**changes: Any) -> dict[str, Any]:
    return {
        **{key: value for key, value in request().items() if key != "request_id"},
        "id": UUID(int=10),
        "tenant_id": UUID(int=11),
        "policy_id": UUID(int=12),
        "actor_user_id": UUID(int=13),
        "configuration": configuration(fixed_at=CREATED),
        "created_at": CREATED,
        "protocol_digest": "a" * 64,
        **changes,
    }


def test_project_selection_is_frozen_sorted_deduplicated_and_bounded() -> None:
    registered = RegisterTrial.model_validate(request())
    assert registered.project_ids == (UUID(int=2), UUID(int=3))
    assert TrialProtocol.model_validate(protocol()).project_ids == registered.project_ids
    for projects in ([], [UUID(int=i) for i in range(101)]):
        with pytest.raises(ValidationError, match="one_to_100_unique_projects"):
            RegisterTrial.model_validate(request(project_ids=projects))


@pytest.mark.parametrize(
    "field,value",
    [
        ("configuration_id", str(UUID(int=9))),
        ("configuration_digest", "b" * 64),
        ("fixed_at", CREATED.isoformat()),
        ("minimum_confirmation_basis_points", 9000),
        ("maximum_retraction_basis_points", 500),
    ],
)
def test_client_cannot_supply_server_owned_configuration(field: str, value: Any) -> None:
    candidate = request()
    candidate["configuration"][field] = value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RegisterTrial.model_validate(candidate)


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_handled_drafts", 0),
        ("minimum_handled_drafts", True),
        ("cohort_window_seconds", 0),
        ("minimum_followup_seconds", 0),
        ("sampling_basis_points", 0),
        ("sampling_basis_points", 10001),
        ("confirmation_basis", "invented"),
        ("recovery_conditions", "   "),
    ],
)
def test_trial_numeric_and_recovery_choices_are_explicit(field: str, value: Any) -> None:
    candidate = request()
    candidate["configuration"][field] = value
    with pytest.raises(ValidationError):
        RegisterTrial.model_validate(candidate)


def test_window_is_aware_exact_and_real_business_cannot_be_registered_afterward() -> None:
    for end in (START, END + timedelta(microseconds=1), END - timedelta(seconds=1)):
        with pytest.raises(ValidationError, match="trial_window_must_match_configuration"):
            RegisterTrial.model_validate(request(window_end=end))
    with pytest.raises(ValidationError, match="timezone"):
        RegisterTrial.model_validate(request(window_start=START.replace(tzinfo=None)))
    for created in (START, START + timedelta(seconds=1)):
        with pytest.raises(ValidationError, match="requires_preregistration"):
            TrialProtocol.model_validate(
                protocol(created_at=created, configuration=configuration(fixed_at=created))
            )
    with pytest.raises(ValidationError, match="fixed_at_registration"):
        TrialProtocol.model_validate(protocol(configuration=configuration(fixed_at=START)))
    for kind in ("controlled_replay", "synthetic"):
        saved = TrialProtocol.model_validate(
            protocol(evidence_kind=kind, created_at=END, configuration=configuration(fixed_at=END))
        )
        assert saved.evidence_kind == kind


def test_collection_requires_aware_cutoff_and_leaves_clock_validation_to_service() -> None:
    assert CollectTrial(request_id=UUID(int=1)).as_of is None
    assert CollectTrial(request_id=UUID(int=1), as_of=END).as_of == END
    with pytest.raises(ValidationError, match="timezone"):
        CollectTrial(request_id=UUID(int=1), as_of=END.replace(tzinfo=None))


def migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0381_ai_write_trial_protocols.py"
    )
    spec = importlib.util.spec_from_file_location("trial_protocol_0381", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized(sql: str) -> str:
    return " ".join(sql.split())


def test_frozen_migration_matches_metadata_and_preserves_scoped_references() -> None:
    module = migration()
    assert module.down_revision == "0380_ai_meeting_work_drafts"
    dialect = create_mock_engine("postgresql://", lambda *_args, **_kwargs: None).dialect
    for table in (tables.ai_write_trial_protocols, tables.ai_write_trial_receipts):
        assert normalized(str(CreateTable(table).compile(dialect=dialect))) in normalized(
            module.DDL
        )
        for index in table.indexes:
            assert normalized(str(CreateIndex(index).compile(dialect=dialect))) in normalized(
                module.DDL
            )
        unique = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert ("tenant_id", "id") in unique
        assert ("tenant_id", "actor_user_id", "request_id") in unique
        foreign = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        ]
        assert all(constraint.ondelete == "RESTRICT" for constraint in foreign)
        assert any(
            tuple(constraint.columns.keys()) == ("tenant_id", "actor_user_id")
            for constraint in foreign
        )
    assert "as_of<=created_at" in module.DDL


def test_migration_adds_append_only_guards_and_refuses_to_drop_recorded_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    assert statements[0] == module.DDL
    assert len(statements) == 7
    for index, name in enumerate(module.TABLES):
        statement, public_revoke, agent_revoke = statements[1 + index * 3 : 4 + index * 3]
        assert f"BEFORE UPDATE OR DELETE ON cehub_ai.{name}" in statement
        assert "protect_checkpoint_history()" in statement
        assert public_revoke == f"REVOKE ALL ON cehub_ai.{name} FROM PUBLIC"
        assert "IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent')" in agent_revoke
        assert f"REVOKE ALL ON cehub_ai.{name} FROM pdos_agent" in agent_revoke
    statements.clear()
    module.downgrade()
    assert all(f"EXISTS(SELECT 1 FROM cehub_ai.{name})" in statements[0] for name in module.TABLES)
    assert "RAISE EXCEPTION" in statements[0]
    assert statements[1:] == [f"DROP TABLE cehub_ai.{name}" for name in reversed(module.TABLES)]
