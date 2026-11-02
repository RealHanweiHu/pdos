"""Probe the installed decision deadline predicate, including its T1 boundary."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.mark.parametrize(
    "operation,named",
    (
        ("change.verification.record", True),
        ("change.close", True),
        ("change.order.approve", True),
        ("knowledge.rule.publish", True),
        ("work.task.review", False),
        ("unregistered.operation", False),
    ),
)
def test_installed_deadline_allows_named_decisions_but_retains_t1_expiry(
    engines, operation, named
):
    admin, _, _ = engines
    with admin.connect() as connection, connection.begin() as transaction:
        predicate = connection.exec_driver_sql(
            "SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint "
            "WHERE conrelid='public.confirmations'::regclass "
            "AND conname='ck_confirmations_decision_deadline'"
        ).scalar_one()
        table = f"deadline_probe_{uuid4().hex}"
        connection.exec_driver_sql(
            f"CREATE TEMP TABLE {table} (operation varchar(100), expires_at timestamptz, "
            f"CONSTRAINT installed_deadline CHECK ({predicate})) ON COMMIT DROP"
        )
        insert = text(f"INSERT INTO {table}(operation,expires_at) VALUES (:operation,NULL)")
        if named:
            connection.execute(insert, {"operation": operation})
        else:
            with pytest.raises(IntegrityError) as error, connection.begin_nested():
                connection.execute(insert, {"operation": operation})
            assert error.value.orig.sqlstate == "23514"
            assert error.value.orig.diag.constraint_name == "installed_deadline"
        connection.execute(
            text(f"INSERT INTO {table} VALUES (:operation,now()+interval '10 minutes')"),
            {"operation": operation},
        )
        transaction.rollback()
