"""One actual work/commitment/result loop, with local synthetic original evidence.

The existing setup owns identity and isolated DB provisioning. This module never
inserts a task, commitment or status fact directly, grants qualification, calls a
model or sends external data. Only root runs this PG/HTTP checkpoint.
"""

import os
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_original_security import (
    parsed,
    uploaded,
    withdraw_command,
)
from test_original_security import (
    security_work as original_security_work,  # noqa: F401
)
from test_project_first_plan import cmd

from pdos_next.database import tenant_session
from pdos_next.domain.work_management import service
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    OPERATIONS,
    REVIEW,
    START,
    STATUS,
    SUBMIT,
)
from pdos_next.domain.work_management.models import (
    ProjectStatusUpdate,
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
    Grant,
    OriginalSecurity,
    Outbox,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

MODELS = (
    WorkTaskVersion,
    WorkTaskCurrent,
    WorkCommitmentVersion,
    WorkCommitmentCurrent,
    ProjectStatusUpdate,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
)
SOURCE_LINE = (
    "Synthetic project work evidence: drawing and inspection results remain individually traceable."
)
TIMEZONE = "Asia/Shanghai"


@pytest.fixture
def work(request):
    security = request.getfixturevalue("original_security_work")
    setup = security.setup
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    prior_client = setup.client
    setup.client = security.client
    try:
        g0 = create_g0_project(
            setup,
            visibility="category",
            name="Synthetic named work loop",
            purpose="Actual work acceptance with bounded independent commitments",
        )
        original_id = uploaded(
            security,
            content=(SOURCE_LINE + "\n").encode(),
            visibility="category",
        )
        artifact_id = parsed(security, original_id)
        source = {
            "kind": "artifact",
            "id": str(artifact_id),
            "revision": 1,
            "position": "line:1;quote_sha256:" + sha256(SOURCE_LINE.encode()).hexdigest(),
        }
        yield SimpleNamespace(
            setup=setup,
            project_id=UUID(g0.project_id),
            original_id=original_id,
            source=source,
            security=security,
            task_id=None,
        )
    finally:
        setup.client = prior_client


def headers(work, actor=None):
    return {"Authorization": f"Bearer {work.setup.tokens[actor or work.setup.human]}"}


def root(work):
    setup = work.setup
    return f"/v1/categories/{setup.category}/products/{setup.product}"


def scoped(work, actor=None):
    identity = actor or work.setup.human
    return tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=identity,
        requester_id=identity,
        category_id=work.setup.category,
    )


def snapshots(work):
    """Complete tenant row hashes, including Current and consumed confirmations."""
    with Session(work.setup.admin) as session:
        result = {}
        for model in MODELS:
            rows = list(
                session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == work.setup.tenant)
                    .order_by(model.id)
                ).mappings()
            )
            result[model.__tablename__] = [digest(dict(row)) for row in rows]
        return result


def payload(work, **values):
    return {
        "project_id": str(work.project_id),
        "sources": [deepcopy(work.source)],
        "reason": "Actual isolated synthetic work command with exact original evidence",
        **values,
    }


def send(work, command, *, actor=None, preview=False):
    return work.setup.client.post(
        f"/v1/categories/{work.setup.category}/commands" + ("/preview" if preview else ""),
        headers=headers(work, actor),
        json=command,
    )


def inputs(work, operation, value, *, actor=None):
    before = snapshots(work)
    command = cmd(work.setup, operation, deepcopy(value))
    response = work.setup.client.post(
        root(work) + "/project-work/inputs", headers=headers(work, actor), json=command
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    result = response.json()
    assert isinstance(result["review"], dict)
    assert result["required_source_read_set"]
    command["payload"] = result["payload"]
    command["source_read_set"] = result["required_source_read_set"]
    return command, result


def preview(work, command, *, actor=None):
    response = send(work, command, actor=actor, preview=True)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value.get("named_decision") is not True and value.get("approval_token") is None
    prepared = value["command"]
    assert prepared["payload"]["confirmation_token"]
    assert prepared["command_id"] == command["command_id"]
    assert prepared["idempotency_key"] == command["idempotency_key"]
    assert prepared["source_read_set"] == command["source_read_set"]
    return prepared


def execute(work, operation, value, *, actor=None, before_save=None):
    command, _ = inputs(work, operation, value, actor=actor)
    if operation != CREATE:
        command = preview(work, command, actor=actor)
    if before_save is not None:
        before_save(command)
    response = send(work, command, actor=actor)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["subject_type"] == (
        "work_commitment"
        if operation == COMMIT
        else "project_status_update"
        if operation == STATUS
        else "work_task"
    )
    assert receipt["operation"] == operation
    assert_atom(work, command, receipt, actor=actor)
    return command, receipt


def workspace(work, *, actor=None):
    before = snapshots(work)
    response = work.setup.client.get(
        root(work) + f"/project-work?project_id={work.project_id}", headers=headers(work, actor)
    )
    assert response.status_code == 200, response.text
    assert snapshots(work) == before
    value = response.json()
    assert all(isinstance(value[key], list) for key in ("tasks", "commitments", "updates"))
    return value


def task(work, expected):
    rows = workspace(work)["tasks"]
    selected = [row for row in rows if row["id"] == str(work.task_id)]
    assert len(selected) == 1
    row = selected[0]
    assert row["state"] == expected
    assert UUID(row["version_id"])
    return {"id": row["id"], "revision": row["revision"]}


def assert_atom(work, command, receipt, *, actor=None):
    actor = actor or work.setup.human
    operation = command["operation"]
    model = (
        WorkCommitmentVersion
        if operation == COMMIT
        else ProjectStatusUpdate
        if operation == STATUS
        else WorkTaskVersion
    )
    with scoped(work, actor) as session:
        row = session.get(model, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row is not None and saved is not None
        assert row.receipt_id == saved.id and row.command_id == saved.command_id
        assert row.actor_id == row.writer_id == row.requester_id == actor
        assert row.project_id == work.project_id and row.product_id == work.setup.product
        assert (
            row.request_digest == saved.request_digest and row.intent_digest == saved.intent_digest
        )
        assert row.confirmation_id == saved.confirmation_id
        if operation == CREATE:
            assert row.confirmation_id is None
            current = session.scalar(
                select(WorkTaskCurrent).where(WorkTaskCurrent.task_id == row.task_id)
            )
            assert current.version_id == row.id and current.revision == row.revision
        else:
            proof = session.get(Confirmation, row.confirmation_id)
            assert (
                proof.consumed is True and proof.actor_id == actor and proof.operation == operation
            )
            assert proof.token_hash == digest(command["payload"]["confirmation_token"])
        for actual in (Audit, Outbox, RequestKey):
            values = list(session.scalars(select(actual).where(actual.receipt_id == saved.id)))
            assert len(values) == 1 and values[0].actor_id == actor
            if actual is Outbox:
                assert values[0].type == OPERATIONS[operation][1]


def refused(work, operation, value, *, actor, expected=(403, 409)):
    before = snapshots(work)
    response = work.setup.client.post(
        root(work) + "/project-work/inputs",
        headers=headers(work, actor),
        json=cmd(work.setup, operation, deepcopy(value)),
    )
    assert response.status_code in expected, response.text
    assert snapshots(work) == before


def clock_fields():
    return {"actual_at": now().isoformat(), "original_timezone": TIMEZONE, "calendar_id": None}


def test_named_work_commitments_return_and_acceptance_are_one_real_loop(work, monkeypatch):
    setup = work.setup
    saved_commands = []

    def save(operation, value, *, actor=None, before_save=None):
        command, receipt = execute(work, operation, value, actor=actor, before_save=before_save)
        saved_commands.append((deepcopy(command), receipt, actor or setup.human))
        return receipt

    created = save(
        CREATE,
        payload(
            work,
            title="Synthetic drawing and inspection delivery",
            goal="Deliver separately reviewable drawing and inspection outcomes",
            outcomes=[
                {"key": "drawing", "text": "Fixed drawing outcome", "required": True},
                {"key": "inspection", "text": "Traceable inspection outcome", "required": True},
            ],
            plan_task=None,
        ),
    )
    work.task_id = UUID(created["result"]["task_id"])
    initial = task(work, "proposed")
    assert initial["revision"] == 1 and workspace(work)["commitments"] == []
    assigned = save(
        ASSIGN,
        payload(work, task=initial, assignee_id=str(setup.peer), recipient_id=str(setup.human)),
    )
    assigned_ref = task(work, "assigned")
    assert assigned["result"]["task_id"] == str(work.task_id)
    assert workspace(work)["commitments"] == []
    refused(work, ACCEPT, payload(work, task=assigned_ref), actor=setup.human)
    refused(
        work, ACCEPT, payload(work, task=assigned_ref), actor=setup.other_human, expected=(403, 404)
    )
    before = snapshots(work)
    forbidden = setup.client.get(
        root(work) + f"/project-work?project_id={work.project_id}",
        headers=headers(work, setup.other_human),
    )
    assert forbidden.status_code in {403, 404} and snapshots(work) == before

    def reject_changed_preview(command):
        changed = deepcopy(command)
        changed["payload"]["reason"] = "A changed reason cannot consume the old confirmation"
        before = snapshots(work)
        response = send(work, changed, actor=setup.peer)
        assert response.status_code in {403, 409}, response.text
        assert snapshots(work) == before

    save(
        ACCEPT,
        payload(work, task=assigned_ref),
        actor=setup.peer,
        before_save=reject_changed_preview,
    )
    accepted_ref = task(work, "accepted")
    assert workspace(work)["commitments"] == []
    refused(work, START, payload(work, task=assigned_ref, **clock_fields()), actor=setup.peer)
    for recipient, promised_at in (
        (setup.human, None),
        (setup.peer, (now() + timedelta(days=1)).isoformat()),
    ):
        save(
            COMMIT,
            payload(
                work,
                task=accepted_ref,
                recipient_id=str(recipient),
                outcome_keys=["drawing", "inspection"],
                promised_at=promised_at,
                original_timezone=TIMEZONE,
                calendar_id=None,
                replaces=None,
            ),
            actor=setup.peer,
        )
    commitments = workspace(work)["commitments"]
    assert len(commitments) == 2
    with scoped(work) as session:
        facts = list(
            session.scalars(
                select(WorkCommitmentVersion).where(WorkCommitmentVersion.task_id == work.task_id)
            )
        )
        currents = list(
            session.scalars(
                select(WorkCommitmentCurrent).where(WorkCommitmentCurrent.task_id == work.task_id)
            )
        )
        assert len(facts) == len(currents) == 2
        assert {row.recipient_id for row in facts} == {setup.human, setup.peer}
        assert all(row.promisor_id == setup.peer and row.revision == 1 for row in facts)
        assert sum(row.promised_at is None for row in facts) == 1
        assert all(row.original_timezone == TIMEZONE and row.calendar_id is None for row in facts)
        retained_commitments = {row.id: deepcopy(row.body) for row in facts}
    save(START, payload(work, task=accepted_ref, **clock_fields()), actor=setup.peer)
    started_ref = task(work, "in_progress")

    def rollback_tail(command):
        before = snapshots(work)

        def fail_tail(*args, **kwargs):
            raise DomainError(
                "INTEGRATION_REQUIRED", "One deliberate work finalization rollback", 503
            )

        with monkeypatch.context() as patch:
            patch.setattr(service, "finalize_receipt", fail_tail)
            failed = send(work, command, actor=setup.peer)
            assert failed.status_code == 503, failed.text
        assert snapshots(work) == before

    partial = save(
        SUBMIT,
        payload(
            work,
            task=started_ref,
            **clock_fields(),
            results=[
                {
                    "key": "drawing",
                    "text": "Actual drawing result",
                    "status": "present",
                    "sources": [work.source],
                },
                {
                    "key": "inspection",
                    "text": "Inspection still partial",
                    "status": "partial",
                    "sources": [work.source],
                },
            ],
        ),
        actor=setup.peer,
        before_save=rollback_tail,
    )
    submitted = task(work, "submitted")
    refused(
        work,
        REVIEW,
        payload(
            work,
            task=submitted,
            decision="accepted",
            **clock_fields(),
            checks=[
                {
                    "key": key,
                    "decision": "accepted",
                    "reason": "Cannot erase actual partial evidence",
                }
                for key in ("drawing", "inspection")
            ],
        ),
        actor=setup.human,
    )
    returned = save(
        REVIEW,
        payload(
            work,
            task=submitted,
            decision="returned",
            **clock_fields(),
            checks=[
                {
                    "key": "drawing",
                    "decision": "accepted",
                    "reason": "Drawing is individually present",
                },
                {
                    "key": "inspection",
                    "decision": "rejected",
                    "reason": "Complete the actual inspection result",
                },
            ],
        ),
    )
    returned_ref = task(work, "in_progress")
    save(
        SUBMIT,
        payload(
            work,
            task=returned_ref,
            **clock_fields(),
            results=[
                {
                    "key": key,
                    "text": f"Complete traceable {key} result",
                    "status": "present",
                    "sources": [work.source],
                }
                for key in ("drawing", "inspection")
            ],
        ),
        actor=setup.peer,
    )
    submitted = task(work, "submitted")
    refused(
        work,
        REVIEW,
        payload(
            work,
            task=submitted,
            decision="accepted",
            **clock_fields(),
            checks=[
                {
                    "key": "drawing",
                    "decision": "accepted",
                    "reason": "Wrong reviewer remains forbidden",
                }
            ],
        ),
        actor=setup.peer,
    )
    save(
        REVIEW,
        payload(
            work,
            task=submitted,
            decision="accepted",
            **clock_fields(),
            checks=[
                {
                    "key": key,
                    "decision": "accepted",
                    "reason": "Actual complete outcome individually accepted",
                }
                for key in ("drawing", "inspection")
            ],
        ),
    )
    final_ref = task(work, "completed")
    save(
        STATUS,
        payload(
            work,
            fact_summary="Named owner records completed work with retained return history",
            next_steps="Keep the fixed drawing and inspection evidence for the next project action",
            task_refs=[final_ref],
        ),
    )
    final = workspace(work)
    assert len(final["updates"]) == 1 and len(final["commitments"]) == 2
    with scoped(work) as session:
        versions = list(
            session.scalars(
                select(WorkTaskVersion)
                .where(WorkTaskVersion.task_id == work.task_id)
                .order_by(WorkTaskVersion.revision)
            )
        )
        assert [row.state for row in versions] == [
            "proposed",
            "assigned",
            "accepted",
            "in_progress",
            "submitted",
            "in_progress",
            "submitted",
            "completed",
        ]
        partial_row = session.get(WorkTaskVersion, UUID(partial["subject_id"]))
        returned_row = session.get(WorkTaskVersion, UUID(returned["subject_id"]))
        assert partial_row.body["submission"]["results"][1]["status"] == "partial"
        assert returned_row.body["review"]["decision"] == "returned"
        assert versions[-1].body["submission"]["results"][1]["status"] == "present"
        assert versions[-1].body["review"]["decision"] == "accepted"
        assert versions[-1].body["actual_start"] == versions[3].body["actual_start"]
        for identity, body in retained_commitments.items():
            assert session.get(WorkCommitmentVersion, identity).body == body
        update_row = session.scalar(
            select(ProjectStatusUpdate).where(ProjectStatusUpdate.project_id == work.project_id)
        )
        assert update_row.actor_id == setup.human and update_row.task_refs == [final_ref]
    before_replay = snapshots(work)
    for command, expected, actor in saved_commands:
        replay = send(work, deepcopy(command), actor=actor)
        assert replay.status_code == 200 and replay.json() == expected
        assert snapshots(work) == before_replay
    if os.environ.get("PDOS_PROJECT_WORK_BROWSER_SEED") == "1":
        from work_management_pg.browser_seed import run_browser_seed

        run_browser_seed(work)
    # A valid preview is deliberately held while its actual source is withdrawn.
    blocked_command, _ = inputs(
        work,
        STATUS,
        payload(
            work,
            fact_summary="Later update requires a live source",
            next_steps="Recheck actual source",
            task_refs=[final_ref],
        ),
    )
    blocked_command = preview(work, blocked_command)
    with scoped(work) as session:
        security = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == work.original_id)
        )
        epoch = security.epoch
    withdrawal = withdraw_command(work.security, work.original_id, expected_epoch=epoch)
    prepared = send(work, withdrawal, preview=True)
    assert prepared.status_code == 200, prepared.text
    withdrawn = send(work, prepared.json()["command"])
    assert withdrawn.status_code == 200, withdrawn.text
    with scoped(work) as session:
        assert session.get(Artifact, UUID(work.source["id"])).status == "withdrawn"
    before_refusal = snapshots(work)
    denied = send(work, blocked_command)
    assert denied.status_code in {403, 409}, denied.text
    assert snapshots(work) == before_refusal
    # Use a separately registered live source so the later authorization refusal
    # is independent of the already withdrawn original.
    fresh_line = "Synthetic live status source for the independent authorization-loss check."
    registered = send(
        work,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic independent live work source",
                "content": fresh_line,
                "source_label": "Isolated work authorization check",
                "visibility": "category",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    fresh_source = {
        "kind": "artifact",
        "id": registered.json()["subject_id"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(fresh_line.encode()).hexdigest(),
    }
    lost_access, _ = inputs(
        work,
        STATUS,
        payload(
            work,
            fact_summary="Independent later update with an actual live source",
            next_steps="Only an authorized owner may record this update",
            task_refs=[],
            sources=[fresh_source],
        ),
    )
    lost_access = preview(work, lost_access)
    # Only the identity/Grant boundary is changed, never a task or result row.
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
            .values(can_write=False)
        )
    before_refusal = snapshots(work)
    denied = send(work, lost_access)
    assert denied.status_code == 403, denied.text
    assert snapshots(work) == before_refusal
