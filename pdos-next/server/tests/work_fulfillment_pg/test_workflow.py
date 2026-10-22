"""One actual recipient-review loop over independently versioned promises.

Reuse the guarded original/G0 work fixture and the real common T0/T1 commands.
No task, promise, submission, fulfillment or common-group row is inserted here.
Only root executes this PG/HTTP checkpoint; there are no model/external calls.
"""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_original_security import withdraw_command
from test_project_first_plan import cmd
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work  # noqa: F401
from work_management_pg.test_workflow import work as work_case  # noqa: F401

from pdos_next.domain.work_fulfillment import service
from pdos_next.domain.work_fulfillment.models import (
    EVENT,
    OPERATION,
    SUBJECT,
    WorkCommitmentReview,
    WorkCommitmentReviewCurrent,
)
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    SUBMIT,
)
from pdos_next.domain.work_management.models import (
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
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

REVIEW_MODELS = (WorkCommitmentReview, WorkCommitmentReviewCurrent)
UNCHANGED_MODELS = (
    WorkTaskVersion,
    WorkTaskCurrent,
    WorkCommitmentVersion,
    WorkCommitmentCurrent,
    Artifact,
    OriginalSecurity,
)


@pytest.fixture
def work(request):
    return request.getfixturevalue("work_case")


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
    return {**flow.snapshots(work), **_rows(work, REVIEW_MODELS)}


def _endpoint(work):
    return flow.root(work) + "/project-work/fulfillment"


def _view(work, *, actor=None):
    before = snapshots(work)
    response = work.setup.client.get(
        _endpoint(work),
        params={"project_id": str(work.project_id)},
        headers=flow.headers(work, actor),
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    values = response.json()["commitments"]
    assert isinstance(values, list)
    return {value["id"]: value for value in values}


def _personal_promises(work):
    before = snapshots(work)
    response = work.setup.client.get(
        "/v1/personal/project-work",
        params={"queue": "commitments", "page_size": 100},
        headers=flow.headers(work, work.setup.peer),
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    value = response.json()
    assert value["queue"] == "commitments"
    assert value["principal_id"] == str(work.setup.peer) and value["next_cursor"] is None
    assert value["total_records"] == len(value["items"])
    return {item["commitment"]["id"]: item for item in value["items"]}


def _ref(receipt):
    return {"id": receipt["subject_id"], "revision": receipt["subject_revision"]}


def _task_ref(receipt):
    return {"id": receipt["result"]["task_id"], "revision": receipt["subject_revision"]}


def _checks(*keys, rejected=()):
    return [
        {
            "key": key,
            "decision": "rejected" if key in rejected else "accepted",
            "reason": (
                "The original submitted outcome is incomplete"
                if key in rejected
                else "Recipient checked this exact original submitted outcome"
            ),
        }
        for key in keys
    ]


def _declaration(work, commitment, task, submission, *, revision=0, decision="accepted", checks):
    return flow.payload(
        work,
        commitment=deepcopy(commitment),
        task=deepcopy(task),
        submission=deepcopy(submission),
        expected_review_revision=revision,
        decision=decision,
        checks=checks,
    )


def _inputs(work, value, *, actor=None):
    before = snapshots(work)
    command = cmd(work.setup, OPERATION, deepcopy(value))
    response = work.setup.client.post(
        _endpoint(work) + "/inputs", headers=flow.headers(work, actor), json=command
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    prepared = response.json()
    assert isinstance(prepared["review"], dict)
    assert prepared["required_source_read_set"]
    command["payload"] = prepared["payload"]
    command["source_read_set"] = prepared["required_source_read_set"]
    return command


def _refused(work, value, *, actor=None, statuses=(403, 409), code=None):
    before = snapshots(work)
    response = work.setup.client.post(
        _endpoint(work) + "/inputs",
        headers=flow.headers(work, actor),
        json=cmd(work.setup, OPERATION, deepcopy(value)),
    )
    assert response.status_code in statuses, response.text
    if code is not None:
        assert response.json()["code"] == code, response.text
    assert snapshots(work) == before


def _assert_group(work, command, receipt, actor):
    expected = command["payload"]
    with flow.scoped(work, actor) as session:
        row = session.get(WorkCommitmentReview, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row is not None and saved is not None
        assert row.operation == saved.operation == OPERATION
        assert saved.subject_type == SUBJECT == receipt["subject_type"]
        assert row.receipt_id == saved.id and row.command_id == saved.command_id
        assert row.revision == saved.subject_revision == receipt["subject_revision"]
        assert row.actor_id == row.writer_id == row.requester_id == row.recipient_id == actor
        assert row.owner_id == work.setup.human and row.visibility == "category"
        assert row.tenant_id == work.setup.tenant and row.category_id == work.setup.category
        assert row.product_id == work.setup.product and row.project_id == work.project_id
        assert row.commitment_id == UUID(expected["commitment"]["id"])
        assert row.commitment_revision == expected["commitment"]["revision"]
        assert row.task_id == UUID(expected["task"]["id"])
        assert row.task_revision == expected["task"]["revision"]
        assert row.submission_id == UUID(expected["submission"]["id"])
        assert row.submission_revision == expected["submission"]["revision"]
        assert row.decision == expected["decision"]
        assert row.state == ("fulfilled" if row.decision == "accepted" else "open")
        assert row.body["checks"] == expected["checks"]
        actual_task = session.scalar(
            select(WorkTaskVersion).where(
                WorkTaskVersion.task_id == row.task_id,
                WorkTaskVersion.revision == row.task_revision,
            )
        )
        assert actual_task.id == row.task_version_id
        actual_submission = session.get(WorkTaskVersion, row.submission_id)
        assert (
            actual_submission.action == "submit" and actual_submission.actor_id == row.promisor_id
        )
        if row.revision == 1:
            assert row.previous_id is None and row.previous_revision is None
        else:
            previous = session.get(WorkCommitmentReview, row.previous_id)
            assert previous.commitment_id == row.commitment_id
            assert previous.revision == row.previous_revision == row.revision - 1
        assert row.body_sha256 == digest(row.body)
        assert row.request_digest == saved.request_digest
        assert row.intent_digest == saved.intent_digest
        assert saved.run_id is None and saved.agent_run_id is None
        assert saved.result["status"] == row.state
        assert saved.result["commitment_id"] == str(row.commitment_id)
        assert saved.result["task_id"] == str(row.task_id)
        assert saved.result["recipient_id"] == str(actor)
        assert saved.result["project_id"] == str(work.project_id)
        pointer = session.scalar(
            select(WorkCommitmentReviewCurrent).where(
                WorkCommitmentReviewCurrent.commitment_id == row.commitment_id
            )
        )
        assert (pointer.version_id, pointer.revision, pointer.state) == (
            row.id,
            row.revision,
            row.state,
        )
        proof = session.get(Confirmation, row.confirmation_id)
        assert proof.id == saved.confirmation_id and proof.consumed is True
        assert proof.actor_id == actor and proof.operation == OPERATION
        assert proof.subject_type == "product" and proof.subject_id == work.setup.product
        assert proof.snapshot == row.command["review"]
        assert proof.token_hash == digest(command["payload"]["confirmation_token"])
        assert proof.expires_at is not None and saved.created_at < proof.expires_at
        for model in (Audit, Outbox, RequestKey):
            values = session.scalars(select(model).where(model.receipt_id == saved.id)).all()
            assert len(values) == 1 and values[0].actor_id == actor
            if model is Outbox:
                assert values[0].type == EVENT and values[0].correlation_id == row.command_id
            elif model is RequestKey:
                assert values[0].key == command["idempotency_key"]
                assert values[0].digest == saved.request_digest


def _save(work, value, *, actor=None, before_save=None):
    actor = actor or work.setup.human
    command = flow.preview(work, _inputs(work, value, actor=actor), actor=actor)
    if before_save is not None:
        before_save(command)
    before = _rows(work, UNCHANGED_MODELS)
    response = flow.send(work, command, actor=actor)
    assert response.status_code == 200, response.text
    assert _rows(work, UNCHANGED_MODELS) == before
    receipt = response.json()
    _assert_group(work, command, receipt, actor)
    return command, receipt, actor


def test_actual_recipient_fulfillment_optional_outcomes_versions_replay_and_rollback(
    work, monkeypatch
):
    setup = work.setup
    saved_reviews = []

    def step(operation, **values):
        actor = values.pop("actor", None)
        return flow.execute(work, operation, flow.payload(work, **values), actor=actor)[1]

    created = step(
        CREATE,
        title="Synthetic separate task and promise fulfillment",
        goal="Deliver required drawing and separately promised optional inspection",
        outcomes=[
            {"key": "drawing", "text": "Required traceable drawing", "required": True},
            {"key": "inspection", "text": "Optional traceable inspection", "required": False},
        ],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = step(
        ASSIGN,
        task=_task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    accepted = step(ACCEPT, task=_task_ref(assigned), actor=setup.peer)

    def promise(task, recipient, keys, *, replaces=None, promised_at=None):
        return step(
            COMMIT,
            task=task,
            recipient_id=str(recipient),
            outcome_keys=keys,
            promised_at=promised_at,
            original_timezone=flow.TIMEZONE,
            calendar_id=None,
            replaces=replaces,
            actor=setup.peer,
        )

    old_a = promise(_task_ref(accepted), setup.human, ["drawing", "inspection"])
    deadline = (now() + timedelta(days=1)).isoformat()
    first_b = promise(_task_ref(accepted), setup.peer, ["drawing"], promised_at=deadline)
    started = step(START, task=_task_ref(accepted), **flow.clock_fields(), actor=setup.peer)
    current_a = promise(
        _task_ref(started), setup.human, ["drawing", "inspection"], replaces=_ref(old_a)
    )
    partial = step(
        SUBMIT,
        task=_task_ref(started),
        **flow.clock_fields(),
        results=[
            {
                "key": key,
                "text": "Actual drawing" if key == "drawing" else "Inspection not delivered",
                "status": "present" if key == "drawing" else "missing",
                "sources": [work.source],
            }
            for key in ("drawing", "inspection")
        ],
        actor=setup.peer,
    )
    a_partial = _declaration(
        work,
        _ref(current_a),
        _task_ref(partial),
        _ref(partial),
        checks=_checks("drawing", "inspection"),
    )
    initial = _view(work)
    assert initial[current_a["subject_id"]]["fulfillment"] == {
        "state": "open",
        "revision": 0,
        "review": None,
        "history": [],
    }
    assert initial[current_a["subject_id"]]["can_review"] is True
    assert initial[old_a["subject_id"]]["can_review"] is False
    assert initial[first_b["subject_id"]]["can_review"] is False
    peer_view = _view(work, actor=setup.peer)
    assert peer_view[current_a["subject_id"]]["can_review"] is False
    assert peer_view[first_b["subject_id"]]["can_review"] is True
    _refused(work, a_partial, actor=setup.peer, statuses=(403,), code="FORBIDDEN_SCOPE")
    _refused(work, a_partial, actor=setup.other_human, statuses=(403, 404))
    _refused(work, {**a_partial, "commitment": _ref(old_a)}, code="VERSION_CONFLICT")
    _refused(work, {**a_partial, "task": _task_ref(started)}, code="VERSION_CONFLICT")
    _refused(work, {**a_partial, "submission": _ref(started)}, statuses=(409, 422))
    # Optional for Task completion still means required by this particular promise.
    _refused(work, a_partial, statuses=(409,), code="VALIDATION_FAILED")
    returned = _save(
        work,
        {
            **a_partial,
            "decision": "returned",
            "checks": _checks("drawing", "inspection", rejected=("inspection",)),
        },
    )
    saved_reviews.append(returned)
    saved_reviews.append(
        _save(
            work,
            _declaration(
                work,
                _ref(first_b),
                _task_ref(partial),
                _ref(partial),
                checks=_checks("drawing"),
            ),
            actor=setup.peer,
        )
    )
    states = _view(work)
    assert states[current_a["subject_id"]]["fulfillment"]["state"] == "open"
    assert states[first_b["subject_id"]]["fulfillment"]["state"] == "fulfilled"
    assert states[first_b["subject_id"]]["task"]["state"] == "submitted"
    assert set(_personal_promises(work)) == {current_a["subject_id"]}
    _refused(work, a_partial, code="VERSION_CONFLICT")

    task_returned = step(
        REVIEW,
        task=_task_ref(partial),
        decision="returned",
        **flow.clock_fields(),
        checks=_checks("drawing", "inspection", rejected=("inspection",)),
    )
    # A new current promise must not inherit fulfillment from its old fact.
    current_b = promise(
        _task_ref(task_returned),
        setup.peer,
        ["drawing"],
        replaces=_ref(first_b),
        promised_at=deadline,
    )
    complete = step(
        SUBMIT,
        task=_task_ref(task_returned),
        **flow.clock_fields(),
        results=[
            {
                "key": key,
                "text": f"Actual complete {key} result",
                "status": "present",
                "sources": [work.source],
            }
            for key in ("drawing", "inspection")
        ],
        actor=setup.peer,
    )
    a_complete = _declaration(
        work,
        _ref(current_a),
        _task_ref(complete),
        _ref(complete),
        revision=1,
        checks=_checks("drawing", "inspection"),
    )
    _refused(work, {**a_complete, "submission": _ref(partial)}, code="VERSION_CONFLICT")
    _refused(work, {**a_complete, "expected_review_revision": 0}, code="VERSION_CONFLICT")
    held_task = flow.preview(work, _inputs(work, a_complete))
    completed = step(
        REVIEW,
        task=_task_ref(complete),
        decision="accepted",
        **flow.clock_fields(),
        checks=_checks("drawing"),
    )
    before_stale = snapshots(work)
    refused = flow.send(work, held_task)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "VERSION_CONFLICT"
    assert snapshots(work) == before_stale
    states = _view(work)
    assert states[current_a["subject_id"]]["task"]["state"] == "completed"
    assert states[current_a["subject_id"]]["fulfillment"]["state"] == "open"
    assert states[current_b["subject_id"]]["fulfillment"]["state"] == "open"
    pending = _personal_promises(work)
    assert set(pending) == {current_a["subject_id"], current_b["subject_id"]}
    assert all(item["task"]["state"] == "completed" for item in pending.values())
    assert pending[current_a["subject_id"]]["commitment"]["promised_at"] is None

    def fail_then_reuse(command):
        altered = deepcopy(command)
        altered["payload"]["reason"] = "Changed material cannot consume the original preview"
        before = snapshots(work)
        invalid = flow.send(work, altered)
        assert invalid.status_code in {403, 409}, invalid.text
        assert snapshots(work) == before

        def tail(*args, **kwargs):
            raise DomainError("INTEGRATION_REQUIRED", "Deliberate fulfillment tail rollback", 503)

        with monkeypatch.context() as patch:
            patch.setattr(service, "finalize_receipt", tail)
            failed = flow.send(work, command)
            assert failed.status_code == 503, failed.text
        assert snapshots(work) == before

    saved_reviews.append(
        _save(
            work,
            {**a_complete, "task": _task_ref(completed)},
            before_save=fail_then_reuse,
        )
    )
    states = _view(work)
    a_state = states[current_a["subject_id"]]["fulfillment"]
    assert a_state["state"] == "fulfilled" and a_state["revision"] == 2
    assert [(item["decision"], item["state"]) for item in a_state["history"]] == [
        ("returned", "open"),
        ("accepted", "fulfilled"),
    ]
    assert states[current_b["subject_id"]]["fulfillment"]["revision"] == 0
    assert states[current_a["subject_id"]]["promised_at"] is None
    assert states[current_b["subject_id"]]["original_timezone"] == flow.TIMEZONE
    assert states[current_a["subject_id"]]["can_review"] is False
    assert set(_personal_promises(work)) == {current_b["subject_id"]}
    with flow.scoped(work) as session:
        old_b_review = session.scalar(
            select(WorkCommitmentReview).where(
                WorkCommitmentReview.commitment_id == UUID(first_b["subject_id"])
            )
        )
        assert old_b_review.state == "fulfilled" and old_b_review.recipient_id == setup.peer
        original_partial = session.get(WorkTaskVersion, UUID(partial["subject_id"]))
        assert original_partial.body["submission"]["results"][1]["status"] == "missing"
        retained_promise = session.get(WorkCommitmentVersion, UUID(current_a["subject_id"]))
        assert retained_promise.promised_at is None
        assert retained_promise.outcome_keys == ["drawing", "inspection"]
    before_replay = snapshots(work)
    for command, expected, actor in saved_reviews:
        replay = flow.send(work, deepcopy(command), actor=actor)
        assert replay.status_code == 200 and replay.json() == expected, replay.text
        assert snapshots(work) == before_replay

    # A live preview for another current promise is held across real withdrawal.
    pending_b = _declaration(
        work,
        _ref(current_b),
        _task_ref(completed),
        _ref(complete),
        checks=_checks("drawing"),
    )
    _refused(
        work,
        {**pending_b, "commitment": _ref(first_b)},
        actor=setup.peer,
        code="VERSION_CONFLICT",
    )
    held_source = flow.preview(work, _inputs(work, pending_b, actor=setup.peer), actor=setup.peer)
    with flow.scoped(work) as session:
        state = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == work.original_id)
        )
        epoch = state.epoch
    withdrawal = withdraw_command(work.security, work.original_id, expected_epoch=epoch)
    prepared = flow.send(work, withdrawal, preview=True)
    assert prepared.status_code == 200, prepared.text
    withdrawn = flow.send(work, prepared.json()["command"])
    assert withdrawn.status_code == 200, withdrawn.text
    with flow.scoped(work) as session:
        assert session.get(Artifact, UUID(work.source["id"])).status == "withdrawn"
    before_refusal = snapshots(work)
    refused = flow.send(work, held_source, actor=setup.peer)
    assert refused.status_code in {403, 409}, refused.text
    assert refused.json()["code"] in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}
    assert snapshots(work) == before_refusal
    _refused(work, pending_b, actor=setup.peer)
