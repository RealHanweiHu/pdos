"""Actual app-role tampering against 0753, using receipts from native commands.

All cases require the explicit isolated PostgreSQL fixture. The downgrade test
executes only the rejecting preflight inside an always-rolled-back transaction.
"""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionSpecRow
from tests.products.test_definition_item_commands_pg import current_items, draft, patch, upsert
from tests.products.test_definition_transactions import post


def state(setup, definition_id):
    """Capture complete persisted rows, not merely an expected row count."""
    with Session(setup.admin) as session:
        return {
            "history": session.execute(
                text(
                    "SELECT to_jsonb(s) FROM definition_specs s "
                    "WHERE definition_id=:d ORDER BY item_id,item_version"
                ),
                {"d": definition_id},
            )
            .scalars()
            .all(),
            "current": session.execute(
                text(
                    "SELECT to_jsonb(c) FROM definition_spec_current c "
                    "WHERE definition_id=:d ORDER BY item_id"
                ),
                {"d": definition_id},
            )
            .scalars()
            .all(),
            "receipts": session.execute(
                text(
                    "SELECT to_jsonb(r) FROM action_receipts r "
                    "WHERE tenant_id=:t AND subject_id=:d ORDER BY id"
                ),
                {"t": setup.tenant, "d": definition_id},
            )
            .scalars()
            .all(),
        }


def edited(setup):
    identity, _ = draft(setup)
    old = current_items(setup, identity)["pressure"]
    response = post(setup, patch(setup, identity, upsert(old, reason="实际人工条目修订")))
    assert response.status_code == 200, response.text
    return identity, current_items(setup, identity)["pressure"]


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE"])
def test_app_current_has_no_direct_mutation_privilege(setup, verb):
    identity, row = edited(setup)
    before = state(setup, identity)
    statements = {
        "INSERT": "INSERT INTO definition_spec_current SELECT * FROM definition_spec_current "
        "WHERE item_id=:item",
        "UPDATE": "UPDATE definition_spec_current SET current_version=current_version+1 "
        "WHERE item_id=:item",
        "DELETE": "DELETE FROM definition_spec_current WHERE item_id=:item",
    }
    with (
        pytest.raises(DBAPIError) as rejected,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        assert (
            session.scalar(
                text("SELECT has_table_privilege(current_user,'definition_spec_current',:verb)"),
                {"verb": verb},
            )
            is False
        )
        session.execute(text(statements[verb]), {"item": row.item_id})
    assert rejected.value.orig.sqlstate == "42501"
    assert state(setup, identity) == before


@pytest.mark.parametrize("table", ["definition_specs", "definition_spec_current"])
@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE"])
def test_agent_has_zero_direct_business_dml(setup, table, verb):
    identity, _ = draft(setup)
    before = state(setup, identity)
    # Static table/verb choices only. The administrator merely enters the actual
    # unprivileged role; the attempted DML runs as pdos_agent with real scope.
    statements = {
        "INSERT": f"INSERT INTO {table} SELECT * FROM {table} WHERE definition_id=:d",
        "UPDATE": f"UPDATE {table} SET removed=true WHERE definition_id=:d",
        "DELETE": f"DELETE FROM {table} WHERE definition_id=:d",
    }
    with (
        pytest.raises(DBAPIError) as rejected,
        tenant_session(
            setup.admin,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        session.execute(text("SET LOCAL ROLE pdos_agent"))
        assert session.scalar(text("SELECT current_user")) == "pdos_agent"
        assert (
            session.scalar(
                text("SELECT has_table_privilege(current_user,:table,:verb)"),
                {"table": table, "verb": verb},
            )
            is False
        )
        session.execute(text(statements[verb]), {"d": identity})
    assert rejected.value.orig.sqlstate == "42501"
    assert state(setup, identity) == before


@pytest.mark.parametrize(
    "attack", ["copied_receipt", "false_writer", "version_gap", "tombstone_body"]
)
def test_app_append_cannot_reuse_real_old_receipt_or_forge_row(setup, attack):
    identity, row = edited(setup)
    before = state(setup, identity)
    fields = {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}
    fields.update(id=uuid4(), item_version=row.item_version + 1)
    if attack == "false_writer":
        fields["writer_id"] = setup.peer
    elif attack == "version_gap":
        fields["item_version"] += 1
    elif attack == "tombstone_body":
        fields.update(removed=True, reason="不能借删除写入另一份活跃业务内容")
    with (
        pytest.raises(DBAPIError) as rejected,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        session.execute(insert(DefinitionSpecRow.__table__).values(**fields))
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert rejected.value.orig.sqlstate == "23514"
    assert state(setup, identity) == before


@pytest.mark.parametrize("kind", ["native", "patch"])
def test_receipt_update_allowance_never_unlocks_committed_body(setup, kind):
    identity, _ = draft(setup)
    row = current_items(setup, identity)["pressure"]
    if kind == "patch":
        changed = post(setup, patch(setup, identity, upsert(row, reason="原封不动保留此事实")))
        assert changed.status_code == 200, changed.text
        row = current_items(setup, identity)["pressure"]
    before = state(setup, identity)
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        session.execute(
            update(DefinitionSpecRow)
            .where(DefinitionSpecRow.id == row.id)
            .values(
                receipt_id=row.receipt_id,
                reason="尝试借回执字段更新业务正文",
            )
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert state(setup, identity) == before


def test_actual_remove_command_cannot_change_tombstone_body_and_rolls_back_receipt(
    setup, monkeypatch
):
    from pdos_next.domain.products import definition_items

    identity, row = edited(setup)
    command = patch(
        setup,
        identity,
        {
            "op": "remove",
            "item_id": str(row.item_id),
            "base_version": row.item_version,
        },
    )
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=command,
    )
    assert preview.status_code == 200, preview.text
    before = state(setup, identity)
    original = definition_items._copy_fields

    def corrupt_body(existing):
        return {**original(existing), "reason": "故障注入：删除时不能改写正文"}

    monkeypatch.setattr(definition_items, "_copy_fields", corrupt_body)
    rejected = post(setup, preview.json()["command"])
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["reason"] == "CONSTRAINT_VALIDATION_FAILED"
    assert state(setup, identity) == before
    monkeypatch.setattr(definition_items, "_copy_fields", original)
    # The same genuine server confirmation remains usable after the failed atom.
    accepted = post(setup, preview.json()["command"])
    assert accepted.status_code == 200, accepted.text
    assert current_items(setup, identity)["pressure"].removed


def test_actual_patch_receipt_cannot_authorize_false_human_writer(setup, monkeypatch):
    from pdos_next.domain.products import definition_items

    identity, row = edited(setup)
    before = state(setup, identity)
    original = definition_items._writing_path

    def false_writer(*args, **kwargs):
        return {**original(*args, **kwargs), "writer_id": setup.peer}

    monkeypatch.setattr(definition_items, "_writing_path", false_writer)
    rejected = post(setup, patch(setup, identity, upsert(row, reason="真实回执不能替他人署名")))
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["reason"] == "CONSTRAINT_VALIDATION_FAILED"
    assert state(setup, identity) == before


def test_downgrade_history_preflight_rejects_before_schema_or_fact_loss(setup):
    from migrations.schema_s0_0753 import DOWNGRADE_SQL

    identity, _ = edited(setup)
    before = state(setup, identity)
    with setup.admin.connect() as connection:
        transaction = connection.begin()
        try:
            head = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            )
            columns = connection.execute(
                text(
                    "SELECT table_name,column_name,data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name IN "
                    "('definition_specs','definition_spec_current') "
                    "ORDER BY table_name,ordinal_position"
                )
            ).all()
            with pytest.raises(DBAPIError) as rejected, connection.begin_nested():
                connection.execute(text("SET LOCAL ROLE pdos_next_owner"))
                # Only preflight: never dispatch destructive downgrade statements.
                connection.exec_driver_sql(
                    DOWNGRADE_SQL[0], execution_options={"no_parameters": True}
                )
            assert rejected.value.orig.sqlstate == "23514"
            assert "cannot be downgraded without loss" in str(rejected.value.orig)
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                == head
            )
            assert (
                connection.execute(
                    text(
                        "SELECT table_name,column_name,data_type FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name IN "
                        "('definition_specs','definition_spec_current') "
                        "ORDER BY table_name,ordinal_position"
                    )
                ).all()
                == columns
            )
        finally:
            transaction.rollback()
    assert state(setup, identity) == before
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(DefinitionSpecRow.id).where(
                    DefinitionSpecRow.definition_id == identity,
                    DefinitionSpecRow.item_version == 2,
                )
            )
            is not None
        )
