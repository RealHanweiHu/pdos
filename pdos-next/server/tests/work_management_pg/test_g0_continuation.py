"""One real G0 native source → task lifecycle; private proposal stays private."""

from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from g0_fixture import add_category_human
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.work_management import service
from pdos_next.domain.work_management.models import WorkTaskCurrent, WorkTaskVersion
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from tests.preproject.test_g0 import create, decide_request, payload, read, save, submit
from tests.preproject.test_g0 import work as work  # noqa: F401


def test_g0_native_task_lifecycle_preserves_private_sources_and_open_risk(work, monkeypatch):
    performer = add_category_human(work, name="Synthetic G0 action owner")
    proposal_id, _ = create(work, payload(work))
    submit(work, proposal_id)
    request = decide_request(work, proposal_id)
    request["payload"]["project"]["owner_id"] = str(work.human)
    for item in request["payload"]["dispositions"]:
        item["owner_id"] = str(performer)
    approved, _ = save(work, request, actor=work.peer)
    pid, project_id = approved["result"]["product_id"], approved["result"]["project_id"]
    assert read(work, proposal_id, performer).status_code == 404
    root = f"/v1/categories/{work.category}/products/{pid}"
    route = f"/v1/categories/{work.category}/commands"

    def headers(actor):
        return {"Authorization": f"Bearer {work.tokens[actor]}"}

    def view(actor=performer):
        response = work.client.get(
            root + f"/project-work?project_id={project_id}", headers=headers(actor)
        )
        assert response.status_code == 200, response.text
        return response.json()

    def counts():
        with Session(work.admin) as s:
            return {
                m.__tablename__: s.scalar(
                    select(func.count()).select_from(m).where(m.tenant_id == work.tenant)
                )
                for m in [
                    WorkTaskVersion,
                    WorkTaskCurrent,
                    Receipt,
                    Audit,
                    Outbox,
                    RequestKey,
                    Confirmation,
                ]
            }

    initial = view()
    assert len(initial["g0_open_items"]) == 2 and initial["tasks"] == []
    assert all(item["task"] is None for item in initial["g0_open_items"])

    def command(op, payload):
        return dict(
            command_id=str(uuid4()),
            idempotency_key=str(uuid4()),
            operation=op,
            category_id=str(work.category),
            product_id=pid,
            expected_revision=initial["product_revision"],
            source_read_set=[],
            payload=payload,
        )

    def prepare(op, payload, actor=performer):
        c = command(
            op,
            dict(
                project_id=project_id,
                sources=[],
                reason="Continue the fixed G0 project arrangement",
                **payload,
            ),
        )
        before = counts()
        res = work.client.post(root + "/project-work/inputs", headers=headers(actor), json=c)
        assert res.status_code == 200, res.text
        assert counts() == before
        c["payload"] = res.json()["payload"]
        c["source_read_set"] = res.json()["required_source_read_set"]
        if op != "work.task.create":
            res = work.client.post(route + "/preview", headers=headers(actor), json=c)
            assert res.status_code == 200, res.text
            c = res.json()["command"]
        return c

    def execute(c, actor=performer):
        res = work.client.post(route, headers=headers(actor), json=c)
        assert res.status_code == 200, res.text
        receipt = res.json()
        with Session(work.admin) as s:
            row = s.get(WorkTaskVersion, UUID(receipt["subject_id"]))
            assert row and row.receipt_id == UUID(receipt["id"])
            assert row.actor_id == row.writer_id == row.requester_id == actor
            assert (
                len(list(s.scalars(select(Audit).where(Audit.receipt_id == row.receipt_id)))) == 1
            )
            assert (
                len(list(s.scalars(select(Outbox).where(Outbox.receipt_id == row.receipt_id)))) == 1
            )
        return receipt

    item = next(item for item in initial["g0_open_items"] if item["kind"] == "risk")
    origin = dict(id=item["id"], decision_id=item["decision_id"])
    create_payload = dict(
        title="Investigate the carried G0 risk",
        goal=item["note"],
        outcomes=[dict(key="finding", text="Named investigation evidence", required=True)],
        g0_open_item=origin,
    )
    wrong = command(
        "work.task.create",
        dict(
            project_id=project_id,
            sources=[],
            reason="A wrong fixed decision must fail",
            **{**create_payload, "g0_open_item": {**origin, "decision_id": str(uuid4())}},
        ),
    )
    before = counts()
    bad = work.client.post(root + "/project-work/inputs", headers=headers(performer), json=wrong)
    assert bad.status_code in (403, 409) and counts() == before
    c = prepare("work.task.create", create_payload)
    assert c["source_read_set"] == []
    before = counts()
    original = service.finalize_receipt

    def fail(*args, **kw):
        original(*args, **kw)
        raise DomainError("VERSION_CONFLICT", "Synthetic late UOW failure")

    with monkeypatch.context() as patch:
        patch.setattr(service, "finalize_receipt", fail)
        failed = work.client.post(route, headers=headers(performer), json=c)
        assert failed.status_code == 409 and counts() == before
    receipt = execute(c)
    tid = receipt["result"]["task_id"]
    after = counts()
    assert execute(c)["id"] == receipt["id"] and counts() == after
    duplicate = command(
        "work.task.create",
        dict(
            project_id=project_id,
            sources=[],
            reason="Cannot create a second task from the same G0 item",
            **create_payload,
        ),
    )
    res = work.client.post(
        root + "/project-work/inputs", headers=headers(performer), json=duplicate
    )
    assert res.status_code == 409 and counts() == after

    def current():
        return next(row for row in view()["tasks"] if row["id"] == tid)

    def ref():
        row = current()
        assert row["g0_open_item"] == origin
        return dict(id=tid, revision=row["revision"])

    assert current()["state"] == "proposed" and current()["assignee_id"] is None
    execute(
        prepare(
            "work.task.assign",
            dict(task=ref(), assignee_id=str(performer), recipient_id=str(work.human)),
            actor=work.human,
        ),
        actor=work.human,
    )
    assert current()["state"] == "assigned"
    attention = work.client.get("/v1/personal/attention?queue=receive", headers=headers(performer))
    assert attention.status_code == 200, attention.text
    assert any(x["source"]["id"] == tid for x in attention.json()["items"])
    # G0 assignment did not grant performer approval or read the private proposal.
    assert read(work, proposal_id, performer).status_code == 404
    execute(prepare("work.task.accept", dict(task=ref())))
    attention = work.client.get("/v1/personal/attention?queue=receive", headers=headers(performer))
    assert attention.status_code == 200, attention.text
    assert not any(x["source"]["id"] == tid for x in attention.json()["items"])
    execute(
        prepare(
            "work.task.start",
            dict(
                task=ref(),
                actual_at=(now() - timedelta(seconds=20)).isoformat(),
                original_timezone="Asia/Shanghai",
            ),
        )
    )
    line = (
        "Synthetic independent investigation result; the original risk needs its own disposition."
    )
    c = command(
        "evidence.artifact.register",
        dict(
            title="Synthetic investigation evidence",
            content=line,
            visibility="category",
            source_label="Synthetic human record",
        ),
    )
    res = work.client.post(route, headers=headers(performer), json=c)
    assert res.status_code == 200, res.text
    source = dict(
        id=res.json()["subject_id"],
        revision=1,
        kind="artifact",
        position="line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    )
    execute(
        prepare(
            "work.task.submit",
            dict(
                task=ref(),
                actual_at=(now() - timedelta(seconds=10)).isoformat(),
                original_timezone="Asia/Shanghai",
                results=[dict(key="finding", text=line, status="present", sources=[source])],
            ),
        )
    )
    execute(
        prepare(
            "work.task.review",
            dict(
                task=ref(),
                actual_at=now().isoformat(),
                original_timezone="Asia/Shanghai",
                decision="accepted",
                checks=[
                    dict(
                        key="finding",
                        decision="accepted",
                        reason="Received the actual investigation result",
                    )
                ],
            ),
            actor=work.human,
        ),
        actor=work.human,
    )
    final = view()
    risk = next(x for x in final["g0_open_items"] if x["id"] == item["id"])
    assert risk["task"] == dict(id=tid, revision=6, state="completed") and risk["kind"] == "risk"
    assert len(final["tasks"]) == 1 and not final["commitments"]
    with Session(work.admin) as s:
        original = s.get(ProjectOpenItem, UUID(item["id"]))
        assert original.status == "open" and str(original.g0_decision_id) == item["decision_id"]
    assert (
        work.client.get(
            root + f"/project-work?project_id={project_id}", headers=headers(work.other_human)
        ).status_code
        == 403
    )
    print(
        "G0 native: one task/6 versions; risk remains open; private proposal hidden; "
        "exact replay/duplicate rejection/late rollback passed"
    )
