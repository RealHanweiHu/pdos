"""One actual G0 risk follow-up chain, separate from its linked task lifecycle.

Only root runs this PostgreSQL/HTTP checkpoint. Sources are registered native
synthetic text; no upload fixture, real model, external call or business DML.
"""

from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from g0_fixture import add_category_human
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.models import ProjectOpenItem, ProposalDecision
from pdos_next.domain.project_risk import service
from pdos_next.domain.project_risk.models import (
    EVENT,
    OPERATION,
    SUBJECT,
    ProjectRiskFollowup,
    ProjectRiskFollowupCurrent,
)
from pdos_next.domain.work_management.models import WorkTaskCurrent, WorkTaskVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.service import digest
from tests.preproject.test_g0 import create, decide_request, payload, read, save, submit
from tests.preproject.test_g0 import work as work  # noqa: F401

MODELS = (
    ProjectRiskFollowup,
    ProjectRiskFollowupCurrent,
    ProjectOpenItem,
    ProposalDecision,
    WorkTaskVersion,
    WorkTaskCurrent,
    Artifact,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
)


def test_native_risk_followup_t1_chain_preserves_g0_task_and_actual_responsibility(
    work, monkeypatch
):
    performer = add_category_human(work, name="Synthetic G0 risk follow-up person")
    proposal_id, _ = create(work, payload(work))
    submit(work, proposal_id)
    request = decide_request(work, proposal_id)
    request["payload"]["project"]["owner_id"] = str(work.human)
    for arrangement in request["payload"]["dispositions"]:
        arrangement["owner_id"] = str(performer)
    approved, _ = save(work, request, actor=work.peer)
    pid, project_id = approved["result"]["product_id"], approved["result"]["project_id"]
    root = f"/v1/categories/{work.category}/products/{pid}"
    route = f"/v1/categories/{work.category}/commands"

    def headers(actor=performer):
        return {"Authorization": f"Bearer {work.tokens[actor]}"}

    def rows(models=MODELS):
        with Session(work.admin) as session:
            return {
                model.__tablename__: [
                    digest(dict(row))
                    for row in session.execute(
                        select(model.__table__)
                        .where(model.tenant_id == work.tenant)
                        .order_by(model.id)
                    ).mappings()
                ]
                for model in models
            }

    response = work.client.get(
        root + "/project-work", params={"project_id": project_id}, headers=headers()
    )
    assert response.status_code == 200, response.text
    initial = response.json()
    native = next(item for item in initial["g0_open_items"] if item["kind"] == "risk")
    risk = {"id": native["id"], "decision_id": native["decision_id"]}
    risk_key = "project_risk:" + risk["id"]
    assert read(work, proposal_id, performer).status_code == 404

    def command(operation, value):
        return dict(
            command_id=str(uuid4()),
            idempotency_key=str(uuid4()),
            operation=operation,
            category_id=str(work.category),
            product_id=pid,
            expected_revision=initial["product_revision"],
            source_read_set=[],
            payload=value,
        )

    def send(c, actor=performer, *, expected=200):
        response = work.client.post(route, headers=headers(actor), json=c)
        assert response.status_code == expected, response.text
        return response

    line = (
        "Synthetic actual investigation completed; unresolved professional questions stay explicit."
    )
    source_receipt = send(
        command(
            "evidence.artifact.register",
            {
                "title": "Synthetic internal risk follow-up evidence",
                "content": line,
                "visibility": "category",
                "source_label": "Synthetic named human record",
            },
        )
    ).json()
    source = {
        "id": source_receipt["subject_id"],
        "revision": 1,
        "kind": "artifact",
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }
    native_before = rows((ProjectOpenItem, ProposalDecision))

    def attention(actor=performer):
        before = rows()
        response = work.client.get(
            "/v1/personal/attention",
            params={"queue": "decide", "page_size": 100},
            headers=headers(actor),
        )
        assert response.status_code == 200, response.text
        assert rows() == before
        return {item["id"]: item for item in response.json()["items"]}

    assert risk_key in attention()
    assert risk_key not in attention(work.human)
    entry = attention()[risk_key]
    assert entry["responsible"]["id"] == str(performer)
    assert entry["due_at"] is None and entry["details"]["g0_due_date"] == native["due_date"]

    def prepare(operation, value, actor=performer, *, risk_inputs=False):
        c = command(operation, value)
        before = rows()
        endpoint = "/project-work/risks/inputs" if risk_inputs else "/project-work/inputs"
        response = work.client.post(root + endpoint, headers=headers(actor), json=c)
        assert response.status_code == 200, response.text
        assert rows() == before
        c["payload"] = response.json()["payload"]
        c["source_read_set"] = response.json()["required_source_read_set"]
        return c

    def preview(c, actor=performer):
        before = rows()
        response = work.client.post(route + "/preview", headers=headers(actor), json=c)
        assert response.status_code == 200, response.text
        prepared = response.json()["command"]
        assert prepared["payload"]["confirmation_token"]
        after = rows()
        assert {key: value for key, value in after.items() if key != "confirmations"} == {
            key: value for key, value in before.items() if key != "confirmations"
        }
        return prepared

    # Complete the actual associated Task. That independently received outcome
    # must leave the native risk open and still pending in its owner's queue.
    def task_step(operation, value, actor=performer):
        c = prepare(
            operation,
            {
                "project_id": project_id,
                "sources": [],
                "reason": "Continue the exact G0 risk investigation task",
                **value,
            },
            actor,
        )
        if operation != "work.task.create":
            c = preview(c, actor)
        receipt = send(c, actor).json()
        return {"id": receipt["result"]["task_id"], "revision": receipt["subject_revision"]}

    task = task_step(
        "work.task.create",
        {
            "title": "Investigate the native risk",
            "goal": native["note"],
            "outcomes": [{"key": "finding", "text": "Actual investigation", "required": True}],
            "g0_open_item": risk,
        },
    )
    task = task_step(
        "work.task.assign",
        {"task": task, "assignee_id": str(performer), "recipient_id": str(work.human)},
        work.human,
    )
    task = task_step("work.task.accept", {"task": task})
    task = task_step(
        "work.task.start",
        {
            "task": task,
            "actual_at": (now() - timedelta(seconds=20)).isoformat(),
            "original_timezone": "Asia/Shanghai",
        },
    )
    task = task_step(
        "work.task.submit",
        {
            "task": task,
            "actual_at": (now() - timedelta(seconds=10)).isoformat(),
            "original_timezone": "Asia/Shanghai",
            "results": [{"key": "finding", "text": line, "status": "present", "sources": [source]}],
        },
    )
    task = task_step(
        "work.task.review",
        {
            "task": task,
            "actual_at": now().isoformat(),
            "original_timezone": "Asia/Shanghai",
            "decision": "accepted",
            "checks": [
                {
                    "key": "finding",
                    "decision": "accepted",
                    "reason": "Received the real investigation result",
                }
            ],
        },
        work.human,
    )
    assert task["revision"] == 6 and risk_key in attention()
    assert rows((ProjectOpenItem, ProposalDecision)) == native_before
    with Session(work.admin) as session:
        pointer = session.scalar(
            select(WorkTaskCurrent).where(WorkTaskCurrent.task_id == UUID(task["id"]))
        )
        assert pointer.state == "completed"
        assert (
            session.scalar(
                select(ProjectRiskFollowupCurrent).where(
                    ProjectRiskFollowupCurrent.risk_id == UUID(risk["id"])
                )
            )
            is None
        )

    def declaration(action, current=None):
        return {
            "project_id": project_id,
            "risk": risk,
            "current": current,
            "action": action,
            "summary": "Named internal risk follow-up " + action,
            "sources": [source],
            "reason": "Record internal follow-up independently of professional approval",
        }

    before = rows()
    for actor in (work.human, work.peer, work.other_human):
        rejected = work.client.post(
            root + "/project-work/risks/inputs",
            headers=headers(actor),
            json=command(OPERATION, declaration("close")),
        )
        assert rejected.status_code == 403, rejected.text
        assert rows() == before
    wrong = declaration("close")
    wrong["risk"] = {**risk, "decision_id": str(uuid4())}
    rejected = work.client.post(
        root + "/project-work/risks/inputs", headers=headers(), json=command(OPERATION, wrong)
    )
    assert rejected.status_code in (403, 409), rejected.text
    assert rows() == before

    close = preview(prepare(OPERATION, declaration("close"), risk_inputs=True))
    before_failure = rows()
    finalize = service.finalize_receipt

    def fail_tail(*args, **kwargs):
        finalize(*args, **kwargs)
        raise DomainError("INTEGRATION_REQUIRED", "Synthetic late risk follow-up rollback", 503)

    with monkeypatch.context() as patch:
        patch.setattr(service, "finalize_receipt", fail_tail)
        send(close, expected=503)
    assert rows() == before_failure
    closed = send(close).json()
    assert closed["subject_type"] == SUBJECT and closed["result"]["status"] == "closed"
    assert risk_key not in attention()
    after_close = rows()
    assert send(close).json() == closed and rows() == after_close

    closed_ref = {"id": closed["subject_id"], "revision": closed["subject_revision"]}
    stale = preview(prepare(OPERATION, declaration("reopen", closed_ref), risk_inputs=True))
    fresh_value = declaration("reopen", closed_ref)
    fresh_value["summary"] = "New evidence requires renewed internal follow-up"
    fresh = preview(prepare(OPERATION, fresh_value, risk_inputs=True))
    reopened = send(fresh).json()
    assert reopened["result"]["status"] == "open"
    before_stale = rows()
    send(stale, expected=409)
    assert rows() == before_stale
    with Session(work.admin) as session:
        proof = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(stale["payload"]["confirmation_token"])
            )
        )
        assert proof is not None and proof.consumed is False

    entry = attention()[risk_key]
    assert entry["source"] == {
        "id": risk["id"],
        "version_id": reopened["subject_id"],
        "revision": 2,
        "epoch": None,
    }
    assert entry["responsible"]["id"] == str(performer) and entry["due_at"] is None
    assert rows((ProjectOpenItem, ProposalDecision)) == native_before
    assert read(work, proposal_id, performer).status_code == 404
    for actor in (performer, work.peer):
        before_read = rows()
        response = work.client.get(
            root + "/project-work/risks", params={"project_id": project_id}, headers=headers(actor)
        )
        assert response.status_code == 200, response.text
        assert rows() == before_read

    # Ordinary peer scope sees actual retained facts without the performer's
    # private RequestKey, while the common owner still verifies the real group.
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        requester_id=work.peer,
        category_id=work.category,
    ) as session:
        row = session.get(ProjectRiskFollowup, UUID(reopened["subject_id"]))
        assert row is not None and row.actor_id == row.writer_id == row.requester_id == performer
        assert (
            session.scalar(select(RequestKey).where(RequestKey.receipt_id == UUID(reopened["id"])))
            is None
        )
        assert session.get(ProjectOpenItem, UUID(risk["id"])).status == "open"

    for c, receipt in ((close, closed), (fresh, reopened)):
        with Session(work.admin) as session:
            row = session.get(ProjectRiskFollowup, UUID(receipt["subject_id"]))
            assert row.body_sha256 == digest(row.body) and row.risk_id == UUID(risk["id"])
            assert row.g0_decision_id == UUID(risk["decision_id"])
            assert row.receipt_id == UUID(receipt["id"]) and row.command_id == UUID(c["command_id"])
            assert row.source_basis["g0_open_item"]["owner_id"] == str(performer)
            proof = session.get(Confirmation, row.confirmation_id)
            assert proof.consumed is True and proof.snapshot == row.command["review"]
            for model in (Audit, Outbox, RequestKey):
                group = session.scalars(
                    select(model).where(model.receipt_id == row.receipt_id)
                ).all()
                assert len(group) == 1 and group[0].actor_id == performer
                if model is Outbox:
                    assert group[0].type == EVENT

    before_activity = rows()
    response = work.client.get(
        root + "/project-work/activity",
        params={"project_id": project_id, "page_size": 100},
        headers=headers(work.peer),
    )
    assert response.status_code == 200, response.text
    activity = [item for item in response.json()["items"] if item["operation"] == OPERATION]
    assert len(activity) == 2 and {item["receipt_id"] for item in activity} == {
        closed["id"],
        reopened["id"],
    }
    assert rows() == before_activity
    for c, receipt in ((close, closed), (fresh, reopened)):
        assert send(c).json() == receipt
        assert rows() == before_activity
