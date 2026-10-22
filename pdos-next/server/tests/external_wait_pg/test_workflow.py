"""Actual waiting records, human delivery, accepted transfer and atomic recovery.

The existing guarded work fixture owns the isolated DB, synthetic original and
real G0 project. Every business fact below uses its registered command. There is
no direct native-fact insertion, fake calendar, model call or external delivery.
Only the root checkpoint executes this file.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, application, cmd, proposal_command
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work  # noqa: F401
from work_management_pg.test_workflow import work as work  # noqa: F401

from pdos_next.domain.external_wait import service
from pdos_next.domain.external_wait.models import (
    EVENT,
    OPERATION,
    SUBJECT,
    ExternalWaitCurrent,
    ExternalWaitVersion,
)
from pdos_next.domain.projects.models import (
    PlanProposal,
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    OriginalSecurity,
    Outbox,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.service import digest

TIMEZONE = "Asia/Shanghai"
WAIT_MODELS = (ExternalWaitVersion, ExternalWaitCurrent)
SOURCE_MODELS = (Artifact, OriginalSecurity)
MODELS = (
    *flow.MODELS,
    *WAIT_MODELS,
    *SOURCE_MODELS,
    Project,
    ProjectProductLink,
    PlanProposal,
    PlanRevision,
    ProjectTask,
    ProjectWorkPackage,
)


def _rows(work, models):
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: [
                digest(dict(row))
                for row in session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == work.setup.tenant)
                    .order_by(model.id)
                ).mappings()
            ]
            for model in models
        }


def snapshots(work):
    return _rows(work, MODELS)


def _endpoint(work):
    return flow.root(work) + "/project-work/external-waits"


def workspace(work, *, actor=None):
    before = snapshots(work)
    response = work.setup.client.get(
        _endpoint(work),
        params={"project_id": str(work.project_id)},
        headers=flow.headers(work, actor),
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    value = response.json()
    assert value["project"]["id"] == str(work.project_id)
    assert isinstance(value["waits"], list) and isinstance(value["available_calendars"], list)
    return value


def waiting(work, wait_id, *, actor=None):
    rows = [row for row in workspace(work, actor=actor)["waits"] if row["id"] == str(wait_id)]
    assert len(rows) == 1
    row = rows[0]
    assert row["wait_id"] == str(wait_id) and UUID(row["version_id"])
    return row


def reference(row):
    return {"id": row["id"], "revision": row["revision"]}


def inputs(work, record, *, wait=None, actor=None, expected=200):
    command = cmd(work.setup, OPERATION, flow.payload(work, wait=wait, record=deepcopy(record)))
    before = snapshots(work)
    response = work.setup.client.post(
        _endpoint(work) + "/inputs",
        headers=flow.headers(work, actor),
        json=command,
    )
    assert response.status_code == expected, response.text
    assert snapshots(work) == before
    if expected != 200:
        return response
    value = response.json()
    assert value["required_source_read_set"]
    assert isinstance(value["review"], dict) and value["review"]["operation"] == OPERATION
    assert "confirmation_token" not in value["payload"]
    command["payload"] = value["payload"]
    command["source_read_set"] = value["required_source_read_set"]
    return command


def assert_group(work, command, receipt, *, actor=None):
    actor = actor or work.setup.human
    assert receipt["operation"] == OPERATION and receipt["subject_type"] == SUBJECT
    with flow.scoped(work, actor) as session:
        row = session.get(ExternalWaitVersion, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row is not None and saved is not None
        assert row.receipt_id == saved.id and row.command_id == saved.command_id == UUID(
            command["command_id"]
        )
        assert row.actor_id == row.requester_id == row.writer_id == actor
        assert row.confirmation_id is saved.confirmation_id is None
        assert row.project_id == work.project_id
        assert (
            row.request_digest == saved.request_digest and row.intent_digest == saved.intent_digest
        )
        assert receipt["result"] == {
            "id": str(row.id),
            "revision": row.revision,
            "status": row.state,
            "wait_id": str(row.wait_id),
            "state": row.state,
            "project_id": str(work.project_id),
        }
        pointer = session.scalar(
            select(ExternalWaitCurrent).where(ExternalWaitCurrent.wait_id == row.wait_id)
        )
        assert (pointer.version_id, pointer.revision, pointer.state) == (
            row.id,
            row.revision,
            row.state,
        )
        for model in (Audit, Outbox, RequestKey):
            values = list(session.scalars(select(model).where(model.receipt_id == saved.id)))
            assert len(values) == 1 and values[0].actor_id == actor
            if model is Outbox:
                assert values[0].type == EVENT and values[0].correlation_id == saved.command_id
                assert (values[0].subject_id, values[0].subject_revision) == (row.id, row.revision)
        assert (
            session.scalar(select(Confirmation).where(Confirmation.operation == OPERATION)) is None
        )


def execute(work, record, *, wait=None, actor=None):
    command = inputs(work, record, wait=wait, actor=actor)
    response = flow.send(work, command, actor=actor)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert_group(work, command, receipt, actor=actor)
    return command, receipt


def create_record():
    return {
        "action": "create",
        "title": "Synthetic supplier drawing response",
        "target": "Synthetic supplier drawing contact",
        "request_content": "Return the fixed drawing evidence for this project",
        "closure_condition": "Record the response or an explicit internal disposition",
        "blocking": True,
        "next_check_at": None,
        "original_timezone": TIMEZONE,
        "calendar": None,
        "milestone": None,
        "build": None,
        "replaces": None,
    }


def details_record(row, **changes):
    return {
        "action": "details",
        "title": row["title"],
        "closure_condition": row["closure_condition"],
        "blocking": row["blocking"],
        "next_check_at": row["next_check_at"],
        "original_timezone": row["original_timezone"],
        "calendar": row["calendar"],
        **changes,
    }


def test_actual_delivery_transfer_history_and_exact_replay_are_one_t0_loop(work, monkeypatch):
    setup = work.setup
    source_before = _rows(work, SOURCE_MODELS)
    saved = []

    def attention(actor, queue):
        before = snapshots(work)
        response = setup.client.get(
            "/v1/personal/attention", params={"queue": queue}, headers=flow.headers(work, actor)
        )
        assert response.status_code == 200, response.text
        assert snapshots(work) == before
        return {item["id"] for item in response.json()["items"]}

    def save(record, *, row=None, actor=None):
        command, receipt = execute(work, record, wait=reference(row) if row else None, actor=actor)
        saved.append((deepcopy(command), receipt, actor or setup.human))
        return waiting(work, receipt["result"]["wait_id"], actor=actor)

    row = save(create_record())
    wait_id = UUID(row["id"])
    assert row["responsible_id"] == str(setup.human) and row["state"] == "open"
    assert row["clock"]["status"] == "delivery_unknown"
    assert row["clock"]["response_started_at"] is row["clock"]["working_minutes"] is None
    assert row["calendar"] is None and row["delivery"] is None
    inputs(work, details_record(row), wait=reference(row), actor=setup.peer, expected=403)

    event_at = now() - timedelta(minutes=2)
    row = save(
        {
            "action": "initiate",
            "at": event_at.isoformat(),
            "text": "Actual request record",
            "original_timezone": TIMEZONE,
        },
        row=row,
    )
    assert row["clock"]["response_started_at"] is None  # Initiation is not delivery.
    delivered_at = event_at + timedelta(seconds=30)
    row = save(
        {
            "action": "delivery",
            "status": "effective",
            "at": delivered_at.isoformat(),
            "text": "Human checks the synthetic delivery evidence",
            "original_timezone": TIMEZONE,
        },
        row=row,
    )
    assert row["delivery"]["time_basis"] == "human_recorded"
    assert row["delivery"]["actor_id"] == row["delivery"]["requester_id"] == str(setup.human)
    assert datetime.fromisoformat(row["clock"]["response_started_at"]) == delivered_at
    assert row["clock"]["status"] == "calendar_unknown" and row["clock"]["working_minutes"] is None
    delivery = deepcopy(row["delivery"])

    row = save(
        {
            "action": "commitment",
            "promised_at": (event_at + timedelta(days=3)).isoformat(),
            "text": "Counterparty stated a date; no formal acceptance inferred",
            "original_timezone": TIMEZONE,
        },
        row=row,
    )
    assert row["counterparty_commitment"]["sources"] == [work.source]
    assert row["clock"]["claimed_commitment_due"] is None
    row = save(
        {
            "action": "reply",
            "at": (event_at + timedelta(seconds=60)).isoformat(),
            "text": "Only part of the drawing material has returned",
            "status": "partial",
            "original_timezone": TIMEZONE,
        },
        row=row,
    )
    assert row["state"] == "open" and row["reply"]["status"] == "partial"
    assert row["delivery"] == delivery

    owner_ref = reference(row)
    row = save({"action": "transfer_request", "to_id": str(setup.peer)}, row=row)
    pending = deepcopy(row["transfer"])
    assert row["responsible_id"] == str(setup.human)
    assert f"external_wait:{wait_id}" in attention(setup.human, "external")
    assert f"external_wait_transfer:{wait_id}" in attention(setup.peer, "receive")
    assert pending["from_id"] == str(setup.human) and pending["to_id"] == str(setup.peer)
    inputs(
        work,
        {"action": "transfer_accept", "request_id": pending["request_id"]},
        wait=reference(row),
        expected=403,
    )
    inputs(
        work,
        {"action": "transfer_accept", "request_id": str(uuid4())},
        wait=reference(row),
        actor=setup.peer,
        expected=403,
    )
    inputs(work, details_record(row), wait=owner_ref, expected=409)
    row = save(
        {"action": "transfer_accept", "request_id": pending["request_id"]},
        row=row,
        actor=setup.peer,
    )
    assert row["responsible_id"] == str(setup.peer) and row["transfer"] is None
    assert f"external_wait:{wait_id}" not in attention(setup.human, "external")
    assert f"external_wait:{wait_id}" in attention(setup.peer, "external")
    assert f"external_wait_transfer:{wait_id}" not in attention(setup.peer, "receive")
    assert row["delivery"] == delivery

    # Peer reads the original owner's immutable fact and Receipt under ordinary
    # app RLS; its original RequestKey remains private to that owner's identity.
    owner_receipt = saved[0][1]
    with flow.scoped(work, setup.peer) as session:
        original = session.get(ExternalWaitVersion, UUID(owner_receipt["subject_id"]))
        receipt = session.get(Receipt, UUID(owner_receipt["id"]))
        assert original is not None and receipt is not None and original.receipt_id == receipt.id
        assert session.scalar(select(RequestKey).where(RequestKey.receipt_id == receipt.id)) is None
    assert (
        waiting(work, wait_id, actor=setup.peer)["history"][0]["receipt_id"] == owner_receipt["id"]
    )

    row = save(
        {
            "action": "close",
            "result": "Internal wait explicitly closed; no arrival or formal receipt asserted",
        },
        row=row,
        actor=setup.peer,
    )
    assert row["state"] == "closed" and row["clock"]["status"] == "closed"
    assert row["reply"]["status"] == "partial" and row["delivery"] == delivery
    closed = deepcopy(row["last_closure"])
    inputs(work, details_record(row), wait=reference(row), actor=setup.peer, expected=409)
    row = save({"action": "reopen"}, row=row, actor=setup.peer)
    assert row["state"] == "open" and row["last_closure"] == closed
    assert row["clock"]["status"] == "calendar_unknown"

    # Fail after the real late source/finalization check has run. The new fact,
    # Current and every original common-group member must all disappear together.
    command = inputs(
        work,
        details_record(row, next_check_at=(now() + timedelta(days=1)).isoformat()),
        wait=reference(row),
        actor=setup.peer,
    )
    before_failure = snapshots(work)
    finalize = service.finalize_receipt

    def fail_tail(*args, **kwargs):
        finalize(*args, **kwargs)
        raise DomainError("INTEGRATION_REQUIRED", "One deliberate late ExternalWait rollback", 503)

    with monkeypatch.context() as patch:
        patch.setattr(service, "finalize_receipt", fail_tail)
        failed = flow.send(work, deepcopy(command), actor=setup.peer)
        assert failed.status_code == 503, failed.text
    assert snapshots(work) == before_failure
    assert waiting(work, wait_id, actor=setup.peer)["revision"] == row["revision"]
    committed = flow.send(work, command, actor=setup.peer)
    assert committed.status_code == 200, committed.text
    receipt = committed.json()
    assert_group(work, command, receipt, actor=setup.peer)
    saved.append((deepcopy(command), receipt, setup.peer))
    row = waiting(work, wait_id, actor=setup.peer)
    assert [value["action"] for value in row["history"]] == [
        "create",
        "initiate",
        "delivery",
        "commitment",
        "reply",
        "transfer_request",
        "transfer_accept",
        "close",
        "reopen",
        "details",
    ]
    assert row["revision"] == len(saved) == 10
    assert _rows(work, SOURCE_MODELS) == source_before
    before_activity = snapshots(work)
    activity = setup.client.get(
        flow.root(work) + "/project-work/activity",
        params={"project_id": str(work.project_id), "page_size": 100},
        headers=flow.headers(work, setup.peer),
    )
    assert activity.status_code == 200, activity.text
    records = [item for item in activity.json()["items"] if item["operation"] == OPERATION]
    assert len(records) == len(saved)
    assert snapshots(work) == before_activity
    before_replay = snapshots(work)
    for command, expected, actor in saved:
        replay = flow.send(work, deepcopy(command), actor=actor)
        assert replay.status_code == 200, replay.text
        assert replay.json() == expected
        assert snapshots(work) == before_replay


def test_adopt_actual_project_plan_calendar_without_inventing_native_records(work):
    # Reuse the existing controlled planning path. Source/calendar references are
    # selected from real project results; none is fabricated or inserted by DML.
    with flow.scoped(work) as session:
        link = session.scalar(
            select(ProjectProductLink).where(ProjectProductLink.project_id == work.project_id)
        )
        assert link is not None
        definition_id = str(link.definition_id)
    definition = (work.source["id"], definition_id)
    proposed = flow.send(work, proposal_command(work.setup, definition, str(work.project_id)))
    assert proposed.status_code == 200, proposed.text
    applied, _ = accepted(
        work.setup,
        application(work.setup, definition, str(work.project_id), proposed.json()["subject_id"]),
    )
    calendars = [
        value
        for value in workspace(work)["available_calendars"]
        if value["ref"]["kind"] == "project_plan" and value["ref"]["id"] == applied["subject_id"]
    ]
    assert len(calendars) == 1
    selected = calendars[0]["ref"]
    command, receipt = execute(work, {**create_record(), "calendar": selected})
    row = waiting(work, receipt["result"]["wait_id"])
    assert row["calendar"] == selected and row["clock"]["response_started_at"] is None
    delivered_at = now() - timedelta(minutes=1)
    _, delivered = execute(
        work,
        {
            "action": "delivery",
            "status": "effective",
            "at": delivered_at.isoformat(),
            "text": "Actual synthetic delivery with explicitly adopted native calendar",
            "original_timezone": TIMEZONE,
        },
        wait=reference(row),
    )
    row = waiting(work, delivered["result"]["wait_id"])
    assert row["clock"]["status"] == "running" and row["clock"]["working_minutes"] >= 0
    with flow.scoped(work) as session:
        fact = session.get(ExternalWaitVersion, UUID(delivered["subject_id"]))
        basis = fact.source_basis["calendar"]
        plan = session.get(PlanRevision, UUID(selected["id"]))
        proposal = session.get(PlanProposal, plan.proposal_id)
        assert basis["ref"] == selected
        assert basis["source_calendar"] == proposal.input_snapshot["calendar"]
        assert all(
            value in fact.source_basis["artifacts"]
            for value in basis["material"]["source_basis"]["artifacts"]
        )
    before = snapshots(work)
    replay = flow.send(work, command)
    assert replay.status_code == 200 and replay.json() == receipt
    assert snapshots(work) == before
