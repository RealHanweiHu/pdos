"""Actual receipt guard against temporary SQL ports, without business writes.

These cases test the SQL event/receipt correspondence only. They do not prove
native facts, qualifications, app RLS or a committed business transaction.
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from pdos_next.safety import verify_test_target

OPERATIONS = (
    "change.effectivity.record",
    "change.verification.record",
    "change.close",
    "change.implementation.record",
    "quality.capa.verification.review",
)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_actual_receipt_guard_requires_registered_event_for_named_common_group(engines, operation):
    admin = engines[0]
    verify_test_target(admin)
    contracts = Path(__file__).resolve().parents[3] / "contracts"
    items = [
        item
        for filename in ("operations.json", "auxiliary-operations.json")
        for item in json.loads((contracts / filename).read_text())["items"]
    ]
    event = next(item["event"] for item in items if item["operation"] == operation)
    values = {
        key: uuid4() for key in ("tenant", "product", "subject", "actor", "receipt", "command")
    }
    values.update(operation=operation, event=event)
    with admin.connect() as connection:
        transaction = connection.begin()
        try:
            ordinary = connection.execute(
                text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='pdos_next_owner'")
            ).one()
            assert ordinary == (False, False)
            connection.exec_driver_sql("SET LOCAL ROLE pdos_next_owner")
            connection.exec_driver_sql("SET LOCAL search_path TO pg_temp,public")
            # Exact column types, no public data, no public constraints/triggers.
            # This connection's temporary ports disappear on rollback below.
            for table in ("action_receipts", "audit_entries", "outbox_events"):
                connection.exec_driver_sql(
                    f"CREATE TEMP TABLE {table} ON COMMIT DROP AS "
                    f"SELECT * FROM public.{table} WITH NO DATA"
                )
            connection.execute(
                text("""INSERT INTO pg_temp.action_receipts
                    (id,tenant_id,product_id,subject_id,subject_revision,operation,subject_type,
                     actor_id,requester_id,run_id,visibility,command_id)
                    VALUES(:receipt,:tenant,:product,:subject,2,:operation,'change_request',
                     :actor,:actor,NULL,'category',:command)"""),
                values,
            )
            connection.execute(
                text("""INSERT INTO pg_temp.audit_entries(tenant_id,receipt_id,actor_id,operation)
                    VALUES(:tenant,:receipt,:actor,:operation)"""),
                values,
            )
            connection.execute(
                text("""INSERT INTO pg_temp.outbox_events
                    (tenant_id,receipt_id,type,actor_id,subject_id,subject_revision,
                     correlation_id,schema_version)
                    VALUES(:tenant,:receipt,:event,:actor,:subject,2,:command,1)"""),
                values,
            )
            call = text("""SELECT public.assert_quality_change_receipt(
                :tenant,:product,:subject,2,:operation,'change_request',:actor,'category')""")
            connection.execute(call, values)
            connection.exec_driver_sql("UPDATE pg_temp.outbox_events SET type='wrong.event'")
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError, match="exactly one named receipt, audit and event"):
                connection.execute(call, values)
            savepoint.rollback()
        finally:
            transaction.rollback()
