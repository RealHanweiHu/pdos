"""Supply source capture -> immutable snapshot -> canonical kit API boundary.

Root alone runs this file against its verified isolated PostgreSQL candidate.
All observations are synthetic; no source is quality-released or qualified.
"""

import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_demand import demand_work  # noqa: F401 - imported fixture
from test_builds import (  # noqa: F401 - fixture dependencies
    build_command,
    configuration,
    definition,
    project,
)
from test_project_first_plan import accepted, cmd, post

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build
from pdos_next.domain.supply_execution.models import (
    KitProjection,
    SupplyCapture,
    SupplyCurrent,
    SupplySnapshot,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    LoginSession,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.service import Context, digest, execute

SNAPSHOT = "supply.snapshot.record"
KIT = "supply.kit.compute"
TEXT = "Synthetic inventory balance is unverified"


@pytest.fixture
def supply_work(setup, demand_work):  # noqa: F811 - imported fixture
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic unverified warehouse observation",
                "content": TEXT,
                "source_label": "Synthetic isolated supply fixture",
                "visibility": "private",
            },
        ),
    )
    assert source.status_code == 200, source.text
    return {**demand_work, "supply_source": source.json()["subject_id"]}


def capture_input(work, *, quantity="6", key=None):
    motor = next(row for row in work["result"]["demands"] if row["item_id"] == "motor")
    return {
        "capture_key": key or str(uuid4()),
        "expected_product_revision": 1,
        "build_id": work["build_id"],
        "expected_build_revision": 1,
        "reason": "Synthetic sourced current balance",
        "records": [
            {
                "record_kind": "inventory",
                "record_id": "EXTERNAL-STOCK-1",
                "material_id": motor["material_id"],
                "quantity": quantity,
                "unit": "ea",
                "source_system": "Synthetic Warehouse",
                "pool_id": "ACTUAL-POOL-1",
                "note": "Synthetic unverified current balance",
                "sources": [
                    {
                        "artifact_id": work["supply_source"],
                        "expected_revision": 1,
                        "line": 1,
                        "quote": TEXT,
                    }
                ],
                "quality": "unknown",
                "availability": "unknown",
            }
        ],
    }


def prepare(setup, work, payload=None, *, headers=None, product=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/products/{product or setup.product}/supply-captures",
        headers=headers or setup.headers,
        json=payload or capture_input(work),
    )


def captured(setup, work, **kwargs):
    response = prepare(setup, work, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def snapshot_command(setup, work, capture):
    command = cmd(setup, SNAPSHOT, capture["snapshot_record_payload"])
    command["source_read_set"] = capture["required_source_read_set"]
    return command


def recorded(setup, work, *, payload=None):
    capture = captured(setup, work, payload=payload)
    receipt, prepared = accepted(setup, snapshot_command(setup, work, capture))
    return capture, receipt, prepared


def kit_command(setup, work, receipt, *, reads=None):
    command = cmd(
        setup,
        KIT,
        {
            "build_id": work["build_id"],
            "expected_build_revision": 1,
            "supply_snapshot_id": receipt["subject_id"],
            "expected_supply_revision": receipt["subject_revision"],
        },
    )
    command["source_read_set"] = reads or [
        {"artifact_id": value, "expected_revision": 1}
        for value in sorted([work["source"], work["supply_source"]])
    ]
    return command


def listed(setup, *, headers=None):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/supply",
        headers=headers or setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def count(setup, model, *, operation=None, physical=False):
    context = (
        Session(setup.admin)
        if physical
        else tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        )
    )
    with context as session:
        query = select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
        if operation is not None:
            query = query.where(model.operation == operation)
        return session.scalar(query)


def confirmation_consumed(setup, prepared):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["payload"]["confirmation_token"])
            )
        )
        return confirmation.consumed


def expire_grant(setup):
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(Grant.category_id == setup.category, Grant.principal_id == setup.human)
            .values(expires_at=now() - timedelta(seconds=1))
        )


def withdraw(setup, source):
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Artifact).where(Artifact.id == UUID(source)).values(status="withdrawn")
        )


def test_capture_retry_keeps_fixed_identity_time_and_never_applies_stock(setup, supply_work):
    payload = capture_input(supply_work)
    first = captured(setup, supply_work, payload=payload)
    replay = captured(setup, supply_work, payload=deepcopy(payload))
    assert replay == first
    row = first["capture"]
    assert row["status"] == "unapplied" and row["applied_snapshot_id"] is None
    assert "expires_at" not in row and "expired" not in row
    assert (
        row["input_snapshot"] and row["snapshot_record_payload"] == first["snapshot_record_payload"]
    )
    assert {ref["artifact_id"] for ref in first["required_source_read_set"]} == {
        supply_work["source"],
        supply_work["supply_source"],
    }
    assert count(setup, SupplyCapture) == 1
    for model in (SupplySnapshot, SupplyCurrent, KitProjection):
        assert count(setup, model) == 0
    changed = deepcopy(payload)
    changed["records"][0]["quantity"] = "7"
    refused = prepare(setup, supply_work, changed)
    assert refused.status_code == 409, refused.text
    assert count(setup, SupplyCapture) == 1


@pytest.mark.parametrize("change", ["grant", "source", "product_revision"])
def test_capture_retry_still_checks_current_authority_and_fresh_revision(
    setup, supply_work, change
):
    payload = capture_input(supply_work)
    first = captured(setup, supply_work, payload=payload)
    if change == "grant":
        expire_grant(setup)
    elif change == "source":
        withdraw(setup, supply_work["supply_source"])
    else:
        with Session(setup.admin) as session, session.begin():
            session.execute(update(Product).where(Product.id == setup.product).values(revision=2))
    replay = prepare(setup, supply_work, payload)
    if change == "product_revision":
        assert replay.status_code == 200, replay.text
        assert replay.json()["capture"]["id"] == first["capture"]["id"]
        fresh = {**payload, "capture_key": str(uuid4())}
        assert prepare(setup, supply_work, fresh).json()["code"] == "VERSION_CONFLICT"
    elif change == "source":
        assert replay.status_code == 200, replay.text
        assert replay.json()["capture"]["source_status"] == "needs_recheck"
        fresh = {**payload, "capture_key": str(uuid4())}
        assert prepare(setup, supply_work, fresh).json()["code"] == "SOURCE_UNAVAILABLE"
    else:
        assert replay.status_code == 403, replay.text
    assert count(setup, SupplyCapture, physical=True) == 1
    if change == "grant":
        assert count(setup, SupplyCapture) == 0


@pytest.mark.parametrize("actor", ["peer", "other_human"])
def test_private_build_and_source_are_not_visible_or_capturable_to_other_identities(
    setup, supply_work, actor
):
    captured(setup, supply_work)
    headers = {"Authorization": f"Bearer {setup.tokens[getattr(setup, actor)]}"}
    refused = prepare(setup, supply_work, headers=headers)
    assert refused.status_code == 403, refused.text
    read = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/supply", headers=headers
    )
    if actor == "peer":
        assert read.status_code == 200, read.text
        data = read.json()
        assert data["captures"] == data["snapshots"] == data["kits"] == []
        assert data["current_by_build"] == {}
    else:
        assert read.status_code == 403


def test_capture_cannot_move_a_fixed_build_to_another_granted_product(setup, supply_work):
    product = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Product(
                id=product,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="Other synthetic product",
                purpose="Verify exact scope",
                category_id=setup.category,
            )
        )
        session.flush()

    refused = prepare(setup, supply_work, product=product)
    assert refused.status_code == 403, refused.text
    assert count(setup, SupplyCapture) == 0


def test_snapshot_uses_one_common_confirmation_and_one_atomic_receipt(setup, supply_work):
    capture = captured(setup, supply_work)
    command = snapshot_command(setup, supply_work, capture)
    assert post(setup, command).json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, prepared = accepted(setup, command)
    assert receipt["subject_type"] == "supply_snapshot" and receipt["subject_revision"] == 1
    assert post(setup, prepared).json()["id"] == receipt["id"]
    semantic_replay = {**prepared, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    assert post(setup, semantic_replay).json()["id"] == receipt["id"]
    assert count(setup, SupplySnapshot) == count(setup, SupplyCurrent) == 1
    assert count(setup, Confirmation, operation=SNAPSHOT) == 1
    assert count(setup, Receipt, operation=SNAPSHOT) == 1
    assert confirmation_consumed(setup, prepared) is True
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        draft = session.get(SupplyCapture, UUID(capture["capture"]["id"]))
        saved = session.get(SupplySnapshot, UUID(receipt["subject_id"]))
        assert saved.id == draft.snapshot_id
        assert saved.snapshot == draft.proposed_snapshot
        assert saved.bound_demand == draft.bound_demand
        assert (
            saved.bound_demand["basis"]
            == supply_work["result"]["coverage"]["input_snapshot"]["basis"]
        )
        assert saved.bound_demand["demand"]["lines"] == supply_work["result"]["demands"]
        assert datetime.fromisoformat(saved.snapshot["ref"]["captured_at"]) == draft.created_at
        assert saved.snapshot["supply_scope_complete"] is False
        assert saved.snapshot["reservations"] == []
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.receipt_id == UUID(receipt["id"]))
                )
                == 1
            )
    data = listed(setup)
    assert data["current_by_build"][supply_work["build_id"]] == {
        "snapshot_id": receipt["subject_id"],
        "revision": 1,
    }


@pytest.mark.parametrize("change", ["reason", "source_reads", "actor"])
def test_snapshot_confirmation_does_not_cover_changed_command_scope(setup, supply_work, change):
    capture = captured(setup, supply_work)
    preview = post(setup, snapshot_command(setup, supply_work, capture), True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    original = deepcopy(prepared)
    headers = setup.headers
    if change == "reason":
        prepared["payload"]["reason"] = "Different unreviewed reason"
    elif change == "source_reads":
        prepared["source_read_set"] = prepared["source_read_set"][:1]
    else:
        headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    refused = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers, json=prepared
    )
    assert refused.status_code in {403, 409}, refused.text
    assert count(setup, SupplySnapshot) == count(setup, SupplyCurrent) == 0
    assert confirmation_consumed(setup, original) is False


def test_capture_has_no_material_deadline_but_confirmation_still_expires(setup, supply_work):
    from pdos_next.clock import using_clock

    payload = capture_input(supply_work)
    capture = captured(setup, supply_work, payload=payload)
    reviewed = post(setup, snapshot_command(setup, supply_work, capture), True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    advanced = now() + timedelta(minutes=31)
    with using_clock(lambda: advanced):
        replay = captured(setup, supply_work, payload=payload)
        assert replay["capture"]["id"] == capture["capture"]["id"]
        assert "expires_at" not in replay["capture"]
        refused = post(setup, prepared)
        assert refused.status_code == 409
        assert refused.json()["code"] == "CONFIRMATION_REQUIRED"
        preview = post(setup, snapshot_command(setup, supply_work, capture), True)
        assert preview.status_code == 200, preview.text
        committed = post(setup, preview.json()["command"])
        assert committed.status_code == 200, committed.text
    assert count(setup, SupplyCapture) == 1
    assert count(setup, SupplySnapshot) == count(setup, SupplyCurrent) == 1


@pytest.mark.parametrize("source", ["build", "supply"])
def test_saved_snapshot_replays_but_new_decision_requires_current_sources(
    setup, supply_work, source
):
    _, receipt, prepared = recorded(setup, supply_work)
    withdraw(setup, supply_work["source" if source == "build" else "supply_source"])
    assert post(setup, prepared).json()["id"] == receipt["id"]
    fresh = {
        **prepared,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {**prepared["payload"], "reason": "New decision on withdrawn source"},
    }
    refused = post(setup, fresh)
    assert refused.status_code in {403, 409}, refused.text
    assert count(setup, SupplySnapshot) == 1
    assert count(setup, Receipt, operation=SNAPSHOT) == 1
    assert receipt["subject_id"]


def test_parallel_successors_do_not_overwrite_history_or_advance_pointer_twice(setup, supply_work):
    _, first, _ = recorded(setup, supply_work)
    commands = []
    for quantity in ("7", "8"):
        capture = captured(
            setup, supply_work, payload=capture_input(supply_work, quantity=quantity)
        )
        command = snapshot_command(setup, supply_work, capture)
        assert command["payload"]["expected_previous_snapshot_id"] == first["subject_id"]
        assert command["payload"]["expected_previous_revision"] == 1
        reviewed = post(setup, command, True)
        assert reviewed.status_code == 200, reviewed.text
        commands.append(reviewed.json()["command"])
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda command: post(setup, command), commands))
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    winner = next(response.json() for response in outcomes if response.status_code == 200)
    loser = next(
        command
        for command, response in zip(commands, outcomes, strict=True)
        if response.status_code == 409
    )
    assert winner["subject_revision"] == 2
    assert confirmation_consumed(setup, loser) is False
    assert count(setup, SupplySnapshot) == count(setup, Receipt, operation=SNAPSHOT) == 2
    assert count(setup, SupplyCurrent) == 1
    data = listed(setup)
    assert data["current_by_build"][supply_work["build_id"]] == {
        "snapshot_id": winner["subject_id"],
        "revision": 2,
    }
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        history = session.get(SupplySnapshot, UUID(first["subject_id"]))
        assert history.revision == 1 and history.snapshot["pools"][0]["quantity"] == "6"


def test_canonical_kit_is_t0_and_unknown_supply_never_authorizes_start(setup, supply_work):
    capture, saved, _ = recorded(setup, supply_work)
    command = kit_command(setup, supply_work, saved, reads=capture["required_source_read_set"])
    assert post(setup, command, True).status_code == 403
    before_confirmations = count(setup, Confirmation)
    result = post(setup, command)
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["subject_type"] == "supply_coverage"
    assert post(setup, command).json()["id"] == receipt["id"]
    assert count(setup, KitProjection) == count(setup, Receipt, operation=KIT) == 1
    assert count(setup, Confirmation) == before_confirmations
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        kit = session.get(KitProjection, UUID(receipt["subject_id"]))
        supply = session.get(SupplySnapshot, UUID(saved["subject_id"]))
        assert kit.bound_demand == supply.bound_demand
        assert kit.projection["verified_alternates"] == []
        coverage = kit.projection["result"]
        assert coverage["secured_ready"] is not True
        assert coverage["potential_ready"] is not True
        assert coverage["critical_secured_ready"] is not True
        assert coverage["input_snapshot"]["supply_scope_complete"] is False
        build = session.get(Build, UUID(supply_work["build_id"]))
        assert build.status == "planned"
    assert post(setup, {**command, "operation": "build.start"}).status_code == 422
    assert post(setup, {**command, "operation": "release.manufacturing.approve"}).status_code == 403


@pytest.mark.parametrize("change", ["grant", "source"])
def test_committed_kit_replay_rechecks_current_scope_and_evidence(setup, supply_work, change):
    capture, saved, _ = recorded(setup, supply_work)
    command = kit_command(setup, supply_work, saved, reads=capture["required_source_read_set"])
    assert post(setup, command).status_code == 200
    if change == "grant":
        expire_grant(setup)
    else:
        withdraw(setup, supply_work["supply_source"])
    response = post(setup, command)
    if change == "grant":
        assert response.status_code == 403, response.text
        assert count(setup, KitProjection) == 0
    else:
        assert response.status_code == 200, response.text
        assert response.json()["subject_type"] == "supply_coverage"
    assert count(setup, KitProjection, physical=True) == 1


def test_old_snapshots_cannot_start_new_kit_but_saved_kit_replays_as_history(setup, supply_work):
    first_capture, first, _ = recorded(setup, supply_work)
    second_capture, second, _ = recorded(
        setup, supply_work, payload=capture_input(supply_work, quantity="7")
    )
    old_request = kit_command(
        setup, supply_work, first, reads=first_capture["required_source_read_set"]
    )
    refused = post(setup, old_request)
    assert refused.status_code == 409 and refused.json()["code"] == "VERSION_CONFLICT"
    assert count(setup, KitProjection) == 0
    command = kit_command(
        setup, supply_work, second, reads=second_capture["required_source_read_set"]
    )
    computed = post(setup, command)
    assert computed.status_code == 200, computed.text
    _, third, _ = recorded(setup, supply_work, payload=capture_input(supply_work, quantity="8"))
    assert post(setup, command).json()["id"] == computed.json()["id"]
    assert count(setup, KitProjection) == count(setup, Receipt, operation=KIT) == 1
    data = listed(setup)
    assert data["current_by_build"][supply_work["build_id"]]["snapshot_id"] == third["subject_id"]
    assert data["kits"][0]["freshness"] == "requires_recalculation"
    assert data["kits"][0]["supply_snapshot_id"] == second["subject_id"]


def test_agent_has_neither_human_api_session_nor_supply_write_qualification(setup, supply_work):
    capture, saved, _ = recorded(setup, supply_work)
    command = kit_command(setup, supply_work, saved, reads=capture["required_source_read_set"])
    token = secrets.token_urlsafe(32)
    with Session(setup.admin) as session, session.begin():
        session.add(
            LoginSession(
                tenant_id=setup.tenant,
                principal_id=setup.agent,
                token_hash=digest(token),
                expires_at=now() + timedelta(hours=1),
            )
        )
    refused = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        json=command,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 401
    with (
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
        pytest.raises(DomainError) as denied,
    ):
        execute(
            session,
            Context(setup.tenant, setup.agent, setup.human, category_id=setup.category),
            Command.model_validate(command),
        )
    assert denied.value.code == "FORBIDDEN_SCOPE"
    assert count(setup, KitProjection) == 0


def test_unknown_source_quantity_stays_null_and_pool_scope_stays_incomplete(setup, supply_work):
    capture, receipt, _ = recorded(
        setup, supply_work, payload=capture_input(supply_work, quantity=None)
    )
    command = kit_command(setup, supply_work, receipt, reads=capture["required_source_read_set"])
    result = post(setup, command)
    assert result.status_code == 200, result.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        snapshot = session.get(SupplySnapshot, UUID(receipt["subject_id"]))
        assert snapshot.snapshot["pools"][0]["quantity"] is None
        assert snapshot.snapshot["supply_scope_complete"] is False
        projection = session.get(KitProjection, UUID(result.json()["subject_id"]))
        assert projection.projection["result"]["secured_ready"] is not True


@pytest.mark.parametrize(
    "field,value",
    [("quality", "released"), ("availability", "available"), ("supply_scope_complete", True)],
)
def test_payload_cannot_assert_release_availability_or_complete_authority(
    setup, supply_work, field, value
):
    payload = capture_input(supply_work)
    if field == "supply_scope_complete":
        payload[field] = value
    else:
        payload["records"][0][field] = value
    refused = prepare(setup, supply_work, payload)
    assert refused.status_code == 422, refused.text
    assert count(setup, SupplyCapture) == count(setup, SupplySnapshot) == 0


def test_source_quote_must_locate_actual_original_text(setup, supply_work):
    payload = capture_input(supply_work)
    payload["records"][0]["sources"][0]["quote"] = "Fabricated released stock"
    refused = prepare(setup, supply_work, payload)
    assert refused.status_code == 409 and refused.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    assert count(setup, SupplyCapture) == 0


@pytest.mark.parametrize("operation", [SNAPSHOT, KIT])
def test_final_receipt_failure_rolls_back_domain_pointer_token_and_outbox(
    setup, supply_work, monkeypatch, operation
):
    from pdos_next import service

    if operation == SNAPSHOT:
        capture = captured(setup, supply_work)
        reviewed = post(setup, snapshot_command(setup, supply_work, capture), True)
        assert reviewed.status_code == 200, reviewed.text
        command = reviewed.json()["command"]
    else:
        capture, receipt, _ = recorded(setup, supply_work)
        command = kit_command(
            setup, supply_work, receipt, reads=capture["required_source_read_set"]
        )
    tables = (SupplySnapshot, SupplyCurrent, KitProjection, Receipt, Audit, Outbox, RequestKey)
    before = {model: count(setup, model) for model in tables}
    original = service.append_receipt

    def fail_after_receipt(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2].operation == operation:
            raise DomainError("SYNTHETIC_RECEIPT_FAILURE", "Synthetic final-stage rollback")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service, "append_receipt", fail_after_receipt)
        refused = post(setup, command)
    assert refused.json()["code"] == "INTERNAL_ERROR", refused.text
    assert {model: count(setup, model) for model in tables} == before
    if operation == SNAPSHOT:
        assert confirmation_consumed(setup, command) is False
    assert count(setup, SupplyCapture) == 1
    success = post(setup, command)
    assert success.status_code == 200, success.text
    assert count(setup, Receipt, operation=operation) == 1


def test_supply_history_is_immutable_scoped_and_agent_has_zero_direct_writes(setup, supply_work):
    capture, snapshot, _ = recorded(setup, supply_work)
    computed = post(
        setup, kit_command(setup, supply_work, snapshot, reads=capture["required_source_read_set"])
    )
    assert computed.status_code == 200, computed.text
    history = (
        (SupplyCapture, capture["capture"]["id"]),
        (SupplySnapshot, snapshot["subject_id"]),
        (KitProjection, computed.json()["subject_id"]),
    )
    for model, row_id in history:
        with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
            session.execute(
                update(model)
                .where(model.id == UUID(row_id))
                .values(reason="Invalid historical overwrite")
            )
    with Session(setup.engine) as session:
        for model in (SupplyCapture, SupplySnapshot, SupplyCurrent, KitProjection):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with Session(setup.admin) as session:
        for model in (SupplyCapture, SupplySnapshot, SupplyCurrent, KitProjection):
            flags = session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = CAST(:name AS regclass)"
                ),
                {"name": model.__tablename__},
            ).one()
            assert flags == (True, True)
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )


def test_current_pointer_cannot_move_build_or_rewind_valid_history(setup, supply_work):
    _, first, _ = recorded(setup, supply_work)
    _, second, _ = recorded(setup, supply_work, payload=capture_input(supply_work, quantity="9"))
    assert second["subject_revision"] == 2
    other, _ = accepted(
        setup, build_command(setup, supply_work, name="Other fixed synthetic Build")
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        pointer = session.scalar(
            select(SupplyCurrent).where(SupplyCurrent.build_id == UUID(supply_work["build_id"]))
        )
        pointer_id = pointer.id
    # Both target identities really exist. The old snapshot has a valid same-Build
    # foreign key; rejecting it proves that history cannot become the live pointer.
    for changed in (
        {"build_id": UUID(other["subject_id"])},
        {"snapshot_id": UUID(first["subject_id"]), "snapshot_revision": 1},
    ):
        with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
            session.execute(
                update(SupplyCurrent).where(SupplyCurrent.id == pointer_id).values(**changed)
            )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        pointer = session.get(SupplyCurrent, pointer_id)
        assert pointer.build_id == UUID(supply_work["build_id"])
        assert pointer.snapshot_id == UUID(second["subject_id"])
        assert pointer.snapshot_revision == 2
        assert session.get(SupplySnapshot, UUID(first["subject_id"])).revision == 1
    assert count(setup, SupplyCurrent) == 1
    assert count(setup, SupplySnapshot) == 2
