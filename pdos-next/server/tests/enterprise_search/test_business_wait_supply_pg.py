"""Real native waiting/commitment commands; external message fields stay out of indexes."""
# ruff: noqa: F811, F401 -- imported fixtures retain their real dependency tree

from datetime import timedelta
from uuid import UUID

from external_wait_pg.test_workflow import (
    create_record,
    original_security_work,
    work,
)
from external_wait_pg.test_workflow import (
    execute as wait_execute,
)
from sqlalchemy import select
from test_supply_execution import (
    build_command,
    capture_input,
    configuration,
    definition,
    demand_work,
    recorded,
    supply_work,
)
from test_supply_execution import (
    project as project_fixture,
)

from pdos_next.domain.external_wait.models import ExternalWaitVersion
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.models import now
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_search,
    native_session,
)

# demand_work resolves the existing project fixture by its registered name.
project = project_fixture


def test_native_wait_current_history_and_external_reply_are_separated(work):
    _command, receipt = wait_execute(work, create_record())
    setup = work.setup
    first = UUID(receipt["subject_id"])
    identity = receipt["result"]["wait_id"]
    assert apply_event(setup, receipt["id"])["processed"] == 1
    found = native_search(setup, identity, ["external_wait"])
    assert found["items"][0]["source_id"] == str(first)
    _command, updated = wait_execute(
        work,
        {
            "action": "reply",
            "at": now().isoformat(),
            "original_timezone": "UTC",
            "status": "received",
            "text": "RAW_EXTERNAL_REPLY_DO_NOT_SEND",
        },
        wait={"id": identity, "revision": 1},
    )
    assert apply_event(setup, updated["id"])["processed"] == 1
    current = native_search(setup, identity, ["external_wait"])
    assert current["returned"] == 1 and current["items"][0]["source_revision"] == 2
    history = native_search(setup, identity, ["external_wait"], include_history=True)
    assert history["returned"] == 2
    with native_session(setup) as session:
        prepare_read(session, ["external_wait"])
        rows = (
            session.execute(select_sources(source_type="external_wait", include_body=True))
            .mappings()
            .all()
        )
        assert all("RAW_EXTERNAL_REPLY_DO_NOT_SEND" not in row["body"] for row in rows)
        latest = next(row for row in rows if row["source_revision"] == 2)
        assert latest["structured"]["facts"]["reply"]["status"] == "received"
    client = NativeClient(identity, ["external_wait"])
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert (
        client.calls == 3
        and output["result"]["assistant"]["sources"][0]["source_type"] == "external_wait"
    )


def test_actual_supplier_commitment_is_structured_and_never_claims_stock(setup, supply_work):
    work = supply_work
    value = capture_input(work)
    row = value["records"][0]
    for key in ("source_system", "pool_id", "quality", "availability"):
        row.pop(key)
    row.update(
        record_kind="commitment",
        supplier_id="SYN-SUPPLIER",
        expected_at=(now() + timedelta(days=3)).isoformat(),
        note="RAW_SUPPLIER_NOTE_DO_NOT_SEND",
    )
    _capture, receipt, _command = recorded(setup, work, payload=value)
    assert apply_event(setup, receipt["id"])["processed"] == 1
    found = native_search(setup, receipt["subject_id"], ["supply"])
    assert found["returned"] == 1 and found["items"][0]["private"] is True
    with native_session(setup) as session:
        prepare_read(session, ["supply"])
        source = (
            session.execute(
                select_sources(
                    source_type="supply", source_id=UUID(receipt["subject_id"]), include_body=True
                )
            )
            .mappings()
            .one()
        )
        assert "RAW_SUPPLIER_NOTE_DO_NOT_SEND" not in source["body"]
        assert "on_hand" not in source["body"]
        commitment = source["structured"]["facts"]["commitments"][0]
        assert commitment["supplier_id"] == "SYN-SUPPLIER" and commitment["quantity"] == "6"
    client = NativeClient(receipt["subject_id"], ["supply"])
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert client.calls == 3
