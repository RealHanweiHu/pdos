"""Offline native metadata/real FK targets, not installed PostgreSQL or RLS."""

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.manufacturing_trials.native_models import (
    BINDING,
    SCOPE,
    NativePilotCurrent,
    NativePilotObservation,
    NativePilotRun,
)

TABLES = tuple(
    value.__table__ for value in (NativePilotRun, NativePilotCurrent, NativePilotObservation)
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native metadata checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def checks(table):
    return " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_actual_postgresql_ddl_and_every_foreign_key_resolve_real_unique_targets():
    for table in TABLES:
        sql = str(CreateTable(table).compile(dialect=dialect()))
        assert "CREATE TABLE" in sql and "TIMESTAMP WITH TIME ZONE" in sql
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            columns = tuple(element.column for element in constraint.elements)
            remote = columns[0].table
            identities = [tuple(remote.primary_key.columns.keys())]
            identities.extend(
                tuple(value.columns.keys())
                for value in remote.constraints
                if isinstance(value, UniqueConstraint)
            )
            assert tuple(column.name for column in columns) in identities, (
                table.name,
                remote.name,
            )
            assert all(column.table is remote for column in columns)


def test_real_lot_actual_process_publication_bindings_keep_scope_without_fictional_revision_fk():
    root = NativePilotRun.__table__
    foreign = {
        constraint.referred_table.name: constraint
        for constraint in root.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.referred_table.name in {"build_lots", "actual_configurations"}
    }
    assert tuple(foreign["build_lots"].column_keys) == (
        "tenant_id",
        "product_id",
        "project_id",
        "build_id",
        "lot_id",
        "actual_configuration_id",
    )
    assert tuple(foreign["actual_configurations"].column_keys) == (
        "tenant_id",
        "product_id",
        "project_id",
        "build_id",
        "actual_configuration_id",
    )
    assert "lot_revision=1 AND actual_configuration_revision=1" in checks(root)
    publication = next(
        value
        for value in root.constraints
        if isinstance(value, ForeignKeyConstraint)
        and value.referred_table.name == "manufacturing_baseline_publications"
    )
    assert tuple(publication.column_keys) == (
        *SCOPE,
        "publication_id",
        "publication_revision",
        "process_id",
        "process_revision",
    )
    assert publication.match in (None, "SIMPLE")
    assert root.c.publication_id.nullable and root.c.publication_revision.nullable


def test_t1_common_group_has_actual_receipt_targets_and_finite_save_deadline():
    for table in (NativePilotRun.__table__, NativePilotObservation.__table__):
        assert not table.c.proof_expires_at.nullable
        assert "proof_consumed_at<=created_at AND created_at<proof_expires_at" in checks(table)
        assert "write_tier='T1' AND status='recorded'" in checks(table)
        assert "actor_id=requester_id AND writer_id=actor_id" in checks(table)
        assert "idempotency_key" not in table.c and "confirmation_token" not in table.c
        for field, expected in (
            ("receipt_id", "action_receipts"),
            ("shared_proof_id", "confirmations"),
        ):
            reference = next(
                value
                for value in table.constraints
                if isinstance(value, ForeignKeyConstraint) and field in value.column_keys
            )
            assert reference.referred_table.name == expected
            assert reference.deferrable is True and reference.initially == "DEFERRED"


def test_root_stays_revision_one_and_observations_store_raw_unknown_before_any_full_projection():
    root, current, observation = TABLES
    assert "revision=1 AND build_revision>0" in checks(root)
    assert root.c.statistics_basis.nullable and root.c.statistics_basis.type.none_as_null
    assert not observation.c.record.nullable
    for name in ("fixed_scope", "projection"):
        assert observation.c[name].nullable and observation.c[name].type.none_as_null
    assert "revision=pilot_revision_before+1" in checks(observation)
    assert "pilot_revision_before=1 AND previous_observation_id IS NULL" in checks(observation)
    assert current.c.latest_observation_id.nullable
    assert current.c.revision.default.arg == 1 and current.c.epoch.default.arg == 1
    for table in TABLES:
        assert not {"qualified", "start_authorized", "manufacturing_release"} & set(table.c.keys())


def test_current_and_observation_inherit_the_exact_root_audience_with_ready_unique_targets():
    for table in (NativePilotCurrent.__table__, NativePilotObservation.__table__):
        reference = next(
            value
            for value in table.constraints
            if isinstance(value, ForeignKeyConstraint)
            and value.referred_table.name == NativePilotRun.__tablename__
        )
        assert tuple(reference.column_keys) == (*BINDING, "pilot_id")
        assert tuple(element.column.name for element in reference.elements) == (*BINDING, "id")
    assert (*SCOPE, "pilot_id", "revision") in {
        tuple(value.columns.keys())
        for value in NativePilotObservation.__table__.constraints
        if isinstance(value, UniqueConstraint)
    }
