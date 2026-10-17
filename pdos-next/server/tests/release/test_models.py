"""Offline release metadata; no claim of installed PostgreSQL enforcement."""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.release.models import (
    BINDING,
    FIXED,
    SCOPE,
    ReleaseDecision,
    ReleasePackage,
    ReleasePackageCurrent,
)

TABLES = tuple(
    value.__table__ for value in (ReleasePackage, ReleasePackageCurrent, ReleaseDecision)
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Release metadata must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


def unique(table):
    return {
        tuple(value.columns.keys())
        for value in table.constraints
        if isinstance(value, UniqueConstraint)
    }


def test_postgresql_tables_resolve_every_fk_to_actual_unique_columns():
    for table in TABLES:
        ddl = str(CreateTable(table).compile(dialect=dialect()))
        assert "CREATE TABLE" in ddl and "TIMESTAMP WITH TIME ZONE" in ddl
        for constraint in table.foreign_key_constraints:
            columns = tuple(value.column for value in constraint.elements)
            remote = columns[0].table
            assert tuple(value.name for value in columns) in {
                tuple(remote.primary_key.columns.keys()),
                *unique(remote),
            }, (table.name, remote.name)
            assert all(value.table is remote for value in columns)


def test_t0_package_has_no_fabricated_confirmation_or_release_grant_columns():
    package, _, decision = TABLES
    assert package.c.write_tier.default.arg == "T0"
    assert package.c.status.default.arg == "assembled"
    assert not {
        "shared_proof_id",
        "confirmation_id",
        "qualified",
        "start_authorized",
        "manufacturing_release",
        "external_effective",
    } & set(package.c.keys())
    assert "actor_id=requester_id" not in checks(package)
    assert "actor_id=requester_id" in checks(decision)
    assert "writer_id=actor_id" in checks(package)


def test_package_successor_and_current_keep_same_series_scope_owner_and_audience():
    package, current, _ = TABLES
    prior = next(
        value for value in package.foreign_key_constraints if "previous_id" in value.column_keys
    )
    assert tuple(prior.column_keys) == (*BINDING, "previous_id", "previous_revision")
    assert tuple(value.column.name for value in prior.elements) == (*BINDING, "id", "revision")
    pointer = next(
        value for value in current.foreign_key_constraints if "version_id" in value.column_keys
    )
    assert tuple(pointer.column_keys) == (*BINDING, "version_id", "revision")
    assert (*SCOPE, "series_id", "revision") in unique(package)
    assert (*SCOPE, "series_id") in unique(current)
    assert "revision=previous_revision+1" in checks(package)
    assert "epoch=revision" in checks(current)


def test_decisions_are_independent_single_signed_records_for_each_fixed_package():
    decision = ReleaseDecision.__table__
    assert (*SCOPE, "package_id", "package_revision", "discipline") in unique(decision)
    assert "revision=1" in checks(decision)
    assert "discipline='engineering' AND operation='release.engineering.approve'" in checks(
        decision
    )
    assert "discipline='manufacturing' AND operation='release.manufacturing.approve'" in checks(
        decision
    )
    assert not {"previous_id", "series_id", "engineering_approved", "manufacturing_approved"} & set(
        decision.c.keys()
    )
    package = next(
        value for value in decision.foreign_key_constraints if "package_id" in value.column_keys
    )
    assert tuple(value.column.name for value in package.elements) == FIXED


def test_named_t2_keeps_original_common_fk_and_optional_deadline():
    decision = ReleaseDecision.__table__
    assert decision.c.proof_expires_at.nullable
    assert "proof_expires_at IS NULL OR created_at<proof_expires_at" in checks(decision)
    for table, fields in (
        (TABLES[0], ("receipt_id",)),
        (decision, ("receipt_id", "shared_proof_id")),
    ):
        for field in fields:
            reference = next(
                value for value in table.foreign_key_constraints if field in value.column_keys
            )
            assert reference.deferrable is True and reference.initially == "DEFERRED"
    assert "idempotency_key" not in decision.c and "approval_token" not in decision.c


def test_no_policy_skill_or_model_version_is_frozen_into_a_database_check():
    for table in TABLES:
        assert "policy_version" not in checks(table)
        assert "skill" not in checks(table) and "model_version" not in checks(table)
