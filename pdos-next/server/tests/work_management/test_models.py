"""Offline metadata: actual keys, immutable versions and distinct responsibility."""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.work_management.models import (
    ProjectStatusUpdate,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)

TABLES = tuple(
    value.__table__
    for value in (
        WorkTaskVersion,
        WorkTaskCurrent,
        WorkCommitmentVersion,
        WorkCommitmentCurrent,
        ProjectStatusUpdate,
    )
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Work metadata must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def uniques(table):
    return {
        tuple(value.columns.keys())
        for value in table.constraints
        if isinstance(value, UniqueConstraint)
    }


def checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


def test_five_tables_compile_and_every_fk_uses_actual_unique_target():
    assert len(TABLES) == 5
    for table in TABLES:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=dialect()))
        for reference in table.foreign_key_constraints:
            remote = reference.referred_table
            assert tuple(value.column.name for value in reference.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *uniques(remote),
            }, (table.name, remote.name)


def test_task_stable_identity_and_version_predecessor_are_separate():
    task, current = TABLES[:2]
    assert ("tenant_id", "product_id", "task_id", "revision") in uniques(task)
    assert ("tenant_id", "product_id", "task_id") in uniques(current)
    assert "previous_revision=revision-1" in checks(task)
    assert not {"promised_at", "plan_id", "work_package_id"} & set(task.c.keys())
    assert WorkTaskVersion(state="assigned").status == "assigned"


def test_commitment_chain_is_fixed_to_task_promisor_and_each_recipient():
    version, current = TABLES[2:4]
    assert ("tenant_id", "product_id", "task_id", "promisor_id", "recipient_id") in uniques(current)
    prior = next(
        value for value in version.foreign_key_constraints if "replaces_id" in value.column_keys
    )
    assert {"task_id", "promisor_id", "recipient_id", "series_id"} <= set(prior.column_keys)
    assert version.c.promised_at.nullable and version.c.calendar_id.nullable
    assert "actor_id=requester_id AND promisor_id=actor_id" in checks(version)
    assert WorkCommitmentVersion().status == "recorded"


def test_status_update_is_named_append_without_a_current_or_domain_state():
    table = TABLES[4]
    assert "revision=1" in checks(table)
    assert "actor_id=requester_id" in checks(table)
    assert not {"state", "promised_at", "forecast", "health"} & set(table.c.keys())
    assert ProjectStatusUpdate().status == "recorded"


def test_common_facts_keep_original_receipt_and_confirmation_and_no_t2_grants():
    for table in (TABLES[0], TABLES[2], TABLES[4]):
        for field in ("receipt_id", "confirmation_id"):
            reference = next(
                value for value in table.foreign_key_constraints if field in value.column_keys
            )
            assert reference.deferrable and reference.initially == "DEFERRED"
        assert table.c.confirmation_id.nullable
        assert not {"approval_token", "qualified", "proof_expires_at", "policy_version"} & set(
            table.c.keys()
        )
