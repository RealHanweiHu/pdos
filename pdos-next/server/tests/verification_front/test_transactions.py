"""Real PG/API cases; the root executes these in the explicit guarded database only."""

# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_execution import actual, lot, planned  # noqa: F401
from test_builds import configuration, definition, project  # noqa: F401
from test_verification_execution import verification_work  # noqa: F401

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority.service import disable_issuer
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
    MethodApplicability,
    VerificationWindowProposal,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Outbox, Receipt
from pdos_next.service import Context, execute
from verification_front.fixtures import (
    create_command,
    created,
    front_work,  # noqa: F401 - imported pytest fixture
    import_fact,
    listed,
    method_command,
    method_saved,
    request_row,
    reviewed,
    schedule_command,
    send,
)


def count(work, model, *conditions):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def test_fixed_preparation_and_new_server_clock_never_inherit_document_completion(front_work):
    work = front_work
    receipt, row, command = created(work)
    assert receipt["subject_type"] == "verification_request" and row["id"] == receipt["subject_id"]
    assert row["request_id"] == command["payload"]["request_id"]
    assert row["preparation_id"] == work.preparation["id"]
    assert row["preparation_sha256"] == work.preparation["sha256"]
    assert row["first_requested_at"] > work.preparation["first_prepared_at"]
    assert row["request_snapshot"]["timeline"]["documents_complete"] is None
    assert row["documents_ready"] is False and row["physical_timeline_empty"] is True
    assert row["document_gaps"] and row["zero_occupancy"] is True
    assert all(
        not row["capabilities"][key] for key in ("handoff_offer", "handoff_accept", "run_start")
    )
    changed = deepcopy(command)
    changed["payload"]["preparation_sha256"] = "0" * 64
    changed["idempotency_key"] = str(uuid4())
    response = send(work, changed)
    assert response.status_code == 409 and response.json()["detail"]["reason"] == "VERSION_CONFLICT"
    assert count(work, FormalVerificationRequest) == 1


def test_current_issuer_configuration_and_not_product_grant_controls_formal_action(front_work):
    work = front_work
    command = create_command(work)
    disable_issuer(work.setup.engine, work.issuer.key)
    view = listed(work)
    prep = next(row for row in view["preparations"] if row["id"] == work.preparation["id"])
    assert prep["capabilities"]["request_create"] is False
    response = send(work, command)
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] in {"FORBIDDEN_OPERATION", "QUALIFICATION_REQUIRED"}
    assert count(work, FormalVerificationRequest) == 0


@pytest.mark.parametrize("status", ["unknown", "not_applicable"])
def test_unknown_and_rejected_method_facts_are_saved_and_never_complete_documents(
    front_work, status
):
    work = front_work
    _, before, _ = created(work)
    _, row, _ = method_saved(work, before, status=status)
    assert row["request_snapshot"]["timeline"]["documents_complete"] is None
    assert row["documents_ready"] is False and row["document_gaps"]
    assert len(row["method_assessments"]) == len(row["items"])
    assert {item["status"] for item in row["method_assessments"]} == {status}
    assert count(work, MethodApplicability) == len(row["items"])
    assert row["first_requested_at"] == before["first_requested_at"]


def test_positive_method_once_common_receipt_old_intent_replay_and_immutable_history(front_work):
    work = front_work
    _, before, _ = created(work)
    receipt, row, prepared = method_saved(work, before)
    assert row["revision"] == 2 and row["documents_ready"] is True
    assert row["request_snapshot"]["timeline"]["documents_complete"] is not None
    assert row["first_requested_at"] == before["first_requested_at"]
    repeated = deepcopy(prepared)
    repeated["command_id"], repeated["idempotency_key"] = str(uuid4()), str(uuid4())
    response = send(work, repeated)
    assert response.status_code == 200 and response.json() == receipt
    assert count(work, FormalVerificationRequest) == 2
    assert count(work, Receipt, Receipt.operation == "verification.method.prepare") == 1
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        identifier = UUID(receipt["id"])
        assert session.scalar(select(Audit.id).where(Audit.receipt_id == identifier))
        assert session.scalar(select(Outbox.id).where(Outbox.receipt_id == identifier))
    history = next(item for item in listed(work)["requests"] if item["id"] == before["id"])
    assert history["is_current"] is False and history["documents_ready"] is False


def test_revoked_original_reviewer_qualification_invalidates_current_milestone_not_history(
    front_work,
):
    work = front_work
    _, first, _ = created(work)
    _, method, _ = method_saved(work, first)
    old_clock = method["request_snapshot"]["timeline"]["documents_complete"]
    import_fact(work, "qualification", previous=work.facts["qualification"], state="revoked")
    row = next(item for item in listed(work)["requests"] if item["id"] == method["id"])
    assert row["documents_ready"] is False and row["document_milestone_current"] is False
    assert row["freshness"] == "requires_recalculation"
    assert row["request_snapshot"]["timeline"]["documents_complete"] == old_clock
    assert all(not item["current"] for item in row["method_assessments"])
    assert row["capabilities"]["method_prepare"] is False


def test_t1_preview_binds_professional_epoch_and_saved_replay_requires_only_read_access(front_work):
    work = front_work
    _, row, _ = created(work)
    prepared = reviewed(work, method_command(work, row))
    new = import_fact(
        work,
        "qualification",
        previous=work.facts["qualification"],
        reason="Synthetic renewed qualification changes fixed epoch",
    )
    response = send(work, prepared)
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "CONFIRMATION_SCOPE_CHANGED"
    )
    assert count(work, MethodApplicability) == 0
    receipt, result, committed = method_saved(work, row)
    import_fact(work, "qualification", previous=new, state="revoked")
    response = send(work, committed)
    assert response.status_code == 200 and response.json()["id"] == receipt["id"], response.text
    fresh = send(work, method_command(work, result), preview=True)
    assert fresh.status_code == 403 and fresh.json()["detail"]["reason"] == "FORBIDDEN_OPERATION", (
        fresh.text
    )
    assert count(work, FormalVerificationRequest) == result["revision"]


def test_two_competing_method_successors_cannot_overwrite_current(front_work):
    work = front_work
    _, row, _ = created(work)
    one = reviewed(work, method_command(work, row, status="unknown"))
    two = reviewed(work, method_command(work, row, status="not_applicable"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda command: send(work, command), (one, two)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert count(work, FormalVerificationRequest) == 2
    assert count(work, MethodApplicability) == len(row["items"])
    assert listed(work)["current_by_request"][row["request_id"]]["revision"] == 2


def test_final_outbox_failure_rolls_back_method_fact_request_pointer_and_confirmation(front_work):
    work = front_work
    _, before, _ = created(work)
    prepared = reviewed(work, method_command(work, before))

    def fail(_mapper, _connection, row):
        if row.type == "verification.method_prepared":
            raise RuntimeError("Synthetic front transaction failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic front transaction failure"):
            send(work, prepared)
    finally:
        event.remove(Outbox, "before_insert", fail)
    assert count(work, MethodApplicability) == 0 and count(work, FormalVerificationRequest) == 1
    assert listed(work)["current_by_request"][before["request_id"]]["revision"] == 1
    response = send(work, prepared)
    assert response.status_code == 200, response.text
    assert request_row(work, response.json())["documents_ready"] is True


def test_schedule_is_t0_unknown_interval_and_never_resource_occupancy_or_actual(front_work):
    work = front_work
    _, before, _ = created(work)
    command = schedule_command(work, before)
    response = send(work, command)
    assert response.status_code == 200, response.text
    row = request_row(work, response.json())
    window = row["window_proposals"][0]
    assert window["window"]["original_timezone"] == "America/Los_Angeles"
    assert window["window"]["start"] == command["payload"]["start"].replace("+00:00", "Z")
    assert window["readiness"] == "UNKNOWN" and window["occupancy"] == 0
    assert {gap["code"] for gap in window["gaps"]} >= {"CALENDAR_UNKNOWN", "DURATION_UNKNOWN"}
    assert row["request_snapshot"]["timeline"]["promised_start"] is None
    assert row["request_snapshot"]["timeline"]["actual_start"] is None
    assert count(work, VerificationWindowProposal) == 1
    assert count(work, Receipt, Receipt.operation == "verification.schedule.propose") == 1
    replay = deepcopy(command)
    replay["idempotency_key"], replay["command_id"] = str(uuid4()), str(uuid4())
    result = send(work, replay)
    assert result.status_code == 200 and result.json() == response.json()


def test_private_scope_rls_immutability_and_agent_zero_direct_write(front_work):
    work = front_work
    receipt, row, _ = created(work)
    _, _, method = method_saved(work, row)
    peer = {"Authorization": f"Bearer {work.setup.tokens[work.setup.peer]}"}
    assert listed(work, headers=peer)["requests"] == []
    with tenant_session(work.setup.engine, uuid4()) as session:
        assert session.scalar(select(func.count()).select_from(FormalVerificationRequest)) == 0
    with (
        Session(work.setup.admin) as session,
        session.begin(),
        pytest.raises(DBAPIError, match="immutable"),
    ):
        session.execute(
            update(FormalVerificationRequest)
            .where(FormalVerificationRequest.id == UUID(receipt["subject_id"]))
            .values(reason="forbidden")
        )
    with Session(work.setup.admin) as session:
        for model in (
            FormalVerificationRequest,
            FormalVerificationCurrent,
            MethodApplicability,
            VerificationWindowProposal,
        ):
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )
            assert session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid=CAST(:name AS regclass)"
                ),
                {"name": model.__tablename__},
            ).one() == (True, True)
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as session,
    ):
        execute(
            session,
            Context(work.setup.tenant, work.setup.agent, work.setup.agent),
            Command(**method),
        )
    # The common guard rejects an agent without a server-bound Run before the
    # professional handler can assess named human duties or qualifications.
    assert error.value.reason == "FORBIDDEN_SCOPE"
