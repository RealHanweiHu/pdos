"""Offline policy metadata contracts; actual enforcement belongs to root's DB check."""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.release.policy_models import (
    BINDING,
    ReleasePolicyCurrent,
    ReleasePolicyFact,
)

TABLES = (ReleasePolicyFact.__table__, ReleasePolicyCurrent.__table__)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Policy metadata checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def unique(table):
    return {
        tuple(value.columns.keys())
        for value in table.constraints
        if isinstance(value, UniqueConstraint)
    }


def checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


def test_actual_postgresql_metadata_and_all_fk_targets_are_real_unique_columns():
    for table in TABLES:
        sql = str(CreateTable(table).compile(dialect=dialect()))
        assert "TIMESTAMP WITH TIME ZONE" in sql
        for foreign in table.foreign_key_constraints:
            remote = foreign.referred_table
            assert tuple(value.column.name for value in foreign.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *unique(remote),
            }, (table.name, remote.name)


def test_current_fixes_exact_scope_series_owner_audience_revision_and_epoch():
    fact, current = TABLES
    reference = next(
        value for value in current.foreign_key_constraints if "fact_id" in value.column_keys
    )
    assert tuple(reference.column_keys) == (*BINDING, "fact_id", "revision", "epoch")
    assert tuple(value.column.name for value in reference.elements) == (
        *BINDING,
        "id",
        "revision",
        "epoch",
    )
    assert ("tenant_id", "product_id", "project_id", "purpose_sha256") in unique(current)
    previous = next(
        value for value in fact.foreign_key_constraints if "previous_id" in value.column_keys
    )
    assert tuple(previous.column_keys) == (*BINDING, "previous_id", "previous_revision")
    assert previous.deferrable and previous.initially == "DEFERRED"


def test_host_policy_does_not_gain_a_public_tier_or_fabricate_confirmation():
    fact = TABLES[0]
    assert fact.c.operation.default.arg == "release.policy.import"
    assert "status IN ('active','withdrawn')" in checks(fact)
    assert "actor_id=requester_id" in checks(fact)
    assert not {"write_tier", "confirmation_id", "shared_proof_id", "qualified"} & set(
        fact.c.keys()
    )
    receipt = next(
        value for value in fact.foreign_key_constraints if "receipt_id" in value.column_keys
    )
    assert receipt.referred_table.name == "action_receipts"
    assert receipt.deferrable and receipt.initially == "DEFERRED"
    assert not fact.c.receipt_id.nullable


def test_withdrawal_is_an_explicit_successor_not_an_in_place_status_change():
    fact = TABLES[0]
    assert "series_id=id AND previous_id IS NULL" in checks(fact)
    assert "revision=previous_revision+1" in checks(fact)
    assert "epoch=revision" in checks(fact)
    assert ("tenant_id", "product_id", "project_id", "purpose_sha256", "revision") in unique(fact)
    for field in ("material", "input_snapshot", "authority_snapshot", "source_basis", "sources"):
        assert not fact.c[field].nullable


def test_optional_boundaries_have_no_invented_ttl_or_policy_version_constraint():
    fact = TABLES[0]
    assert fact.c.valid_from.nullable and fact.c.valid_until.nullable
    assert "valid_from IS NULL OR valid_until IS NULL OR valid_from<valid_until" in checks(fact)
    assert "created_at" not in checks(fact)
    assert "policy_version='" not in checks(fact)
    assert "schema_version" not in checks(fact)
    assert "prompt" not in checks(fact) and "skill" not in checks(fact)
