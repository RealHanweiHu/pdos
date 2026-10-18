"""Offline exception metadata checks; no installed-schema claim."""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.release_exceptions.models import (
    BINDING,
    FIXED_FIELDS,
    ReleaseExceptionCurrent,
    ReleaseExceptionDecision,
)

TABLES = (ReleaseExceptionDecision.__table__, ReleaseExceptionCurrent.__table__)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Exception metadata checks must never connect")

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


def test_postgresql_declarations_resolve_only_actual_unique_foreign_keys():
    for table in TABLES:
        sql = str(CreateTable(table).compile(dialect=dialect()))
        assert "TIMESTAMP WITH TIME ZONE" in sql
        for foreign in table.foreign_key_constraints:
            remote = foreign.referred_table
            assert tuple(value.column.name for value in foreign.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *unique(remote),
            }, (table.name, remote.name)
    policy = next(
        value
        for value in TABLES[0].foreign_key_constraints
        if "policy_fact_id" in value.column_keys
    )
    assert tuple(value.column.name for value in policy.elements) == ("tenant_id", "id")


def test_approval_and_withdrawal_are_independent_facts_and_single_successor():
    decision = TABLES[0]
    assert "revision=1" in checks(decision)
    assert "action='approved' AND operation='release.exception.decide' AND series_id=id" in checks(
        decision
    )
    assert "previous_id=series_id AND previous_id<>id AND previous_revision=1" in checks(decision)
    assert ("tenant_id", "previous_id") in unique(decision)
    prior = next(
        value for value in decision.foreign_key_constraints if "previous_id" in value.column_keys
    )
    assert tuple(prior.column_keys) == (*BINDING, "previous_id", "previous_revision")


def test_current_keeps_scope_and_binding_while_advancing_only_once():
    decision, current = TABLES
    assert set(FIXED_FIELDS) <= set(decision.c.keys()) & set(current.c.keys())
    reference = next(
        value for value in current.foreign_key_constraints if "decision_id" in value.column_keys
    )
    assert tuple(reference.column_keys) == (*BINDING, "decision_id", "decision_revision", "action")
    assert "action='approved' AND epoch=1 AND decision_id=series_id" in checks(current)
    assert "action='withdrawn' AND epoch=2 AND decision_id<>series_id" in checks(current)


def test_named_writer_does_not_replace_actual_package_owner():
    decision = TABLES[0]
    assert "actor_id=requester_id AND writer_id=actor_id" in checks(decision)
    assert "owner_id=requester_id" not in checks(decision)
    assert decision.c.write_tier.default.arg == "T2"
    assert ReleaseExceptionDecision(action="approved").status == "approved"
    assert ReleaseExceptionDecision(action="withdrawn").status == "withdrawn"
    assert "status" not in decision.c
    assert not {
        "qualified",
        "approved_by_ai",
        "network_send",
        "idempotency_key",
        "approval_token",
    } & set(decision.c.keys())


def test_nullable_t2_and_business_deadlines_preserve_post_expiry_withdrawal():
    decision = TABLES[0]
    assert decision.c.proof_expires_at.nullable and decision.c.expiry.nullable
    assert "proof_expires_at IS NULL OR created_at<proof_expires_at" in checks(decision)
    assert "action='withdrawn' OR expiry IS NULL OR created_at<expiry" in checks(decision)
    for field in ("receipt_id", "shared_proof_id"):
        reference = next(
            value for value in decision.foreign_key_constraints if field in value.column_keys
        )
        assert reference.deferrable and reference.initially == "DEFERRED"


def test_policy_and_configuration_business_versions_are_not_database_qualification():
    for table in TABLES:
        predicate = checks(table)
        assert "policy_version" not in predicate and "skill" not in predicate
        assert "model_version" not in predicate
        assert not {"check_keys", "subject_config", "release_scope"} & set(table.c.keys())
