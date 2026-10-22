"""Actual current Task/Promise/G0 actions drive a side-effect-free personal inbox."""

# ruff: noqa: F811 - imported fixtures intentionally register their dependency tree

from uuid import UUID

from g0_fixture import read_proposal, run_command
from sqlalchemy import event
from work_fulfillment_pg import test_workflow as fulfillment
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import (
    original_security_work,  # noqa: F401
    work,  # noqa: F401
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


def page(work, queue, *, actor=None, cursor=None, size=20, status=200):
    before, statements = fulfillment.snapshots(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        params = {"queue": queue, "page_size": size}
        if cursor:
            params["cursor"] = cursor
        response = work.setup.client.get(
            "/v1/personal/attention",
            params=params,
            headers=flow.headers(work, actor),
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert response.status_code == status, response.text
    assert fulfillment.snapshots(work) == before
    assert not any(
        s.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for s in statements
    )
    if status != 200:
        return response.json()
    value = response.json()
    assert value["principal_id"] == str(actor or work.setup.human)
    assert value["queue"] == queue and value["total_records"] >= len(value["items"])
    assert all(item["responsible"]["id"] == value["principal_id"] for item in value["items"])
    return value


def test_actual_task_receipt_and_promise_fulfillment_disappear_independently(work):
    def step(operation, *, actor=None, **fields):
        return flow.execute(work, operation, flow.payload(work, **fields), actor=actor)[1]

    created = step(
        CREATE,
        title="Synthetic attention work",
        goal="Deliver named traceable drawing",
        outcomes=[{"key": "drawing", "text": "Actual drawing", "required": True}],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = step(
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(work.setup.peer),
        recipient_id=str(work.setup.human),
    )
    first = page(work, "receive", actor=work.setup.peer, size=1)
    assert first["total_records"] == 1 and first["items"][0]["source"]["id"] == str(work.task_id)
    assert page(work, "receive")["total_records"] == 0
    accepted = step(ACCEPT, task=fulfillment._task_ref(assigned), actor=work.setup.peer)
    assert page(work, "receive", actor=work.setup.peer)["total_records"] == 0
    promised = step(
        COMMIT,
        task=fulfillment._task_ref(accepted),
        actor=work.setup.peer,
        recipient_id=str(work.setup.human),
        outcome_keys=["drawing"],
        promised_at=None,
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        replaces=None,
    )
    assert page(work, "verify")["total_records"] == 0
    started = step(
        START, task=fulfillment._task_ref(accepted), actor=work.setup.peer, **flow.clock_fields()
    )
    submitted = step(
        SUBMIT,
        task=fulfillment._task_ref(started),
        actor=work.setup.peer,
        **flow.clock_fields(),
        results=[
            {
                "key": "drawing",
                "text": "Actual drawing",
                "status": "present",
                "sources": [work.source],
            }
        ],
    )
    current = page(work, "verify", size=1)
    assert current["total_records"] == 2 and current["next_cursor"]
    rest = page(work, "verify", cursor=current["next_cursor"], size=1)
    assert rest["total_records"] == 2 and rest["next_cursor"] is None
    assert len({current["items"][0]["id"], rest["items"][0]["id"]}) == 2
    page(work, "receive", cursor=current["next_cursor"], status=422)
    completed = step(
        REVIEW,
        task=fulfillment._task_ref(submitted),
        decision="accepted",
        **flow.clock_fields(),
        checks=fulfillment._checks("drawing"),
    )
    pending = page(work, "verify")
    assert pending["total_records"] == 1
    assert pending["items"][0]["kind"] == "promise_review"
    assert pending["items"][0]["source"]["version_id"] == promised["subject_id"]
    assert pending["items"][0]["due_at"] is None
    fulfillment._save(
        work,
        fulfillment._declaration(
            work,
            fulfillment._ref(promised),
            fulfillment._task_ref(completed),
            fulfillment._ref(submitted),
            checks=fulfillment._checks("drawing"),
        ),
    )
    assert page(work, "verify")["total_records"] == 0
    page(work, "verify", cursor=current["next_cursor"], status=403)


def test_named_current_g0_review_joins_and_leaves_with_original_decision(work):
    setup = work.setup
    created, _ = run_command(
        setup,
        "proposal.create",
        {
            "title": "Synthetic attention G0",
            "entry_kind": "new_product",
            "brief": "Named decision inbox",
            "groups": {
                "items": [
                    {"kind": "section", "content": {"key": "worth_it", "text": "Actual review"}},
                    {"kind": "option", "content": {"name": "Develop", "kind": "new"}},
                    {"kind": "option", "content": {"name": "Keep current", "kind": "do_nothing"}},
                ]
            },
        },
    )
    identity = created["subject_id"]
    before = read_proposal(setup, identity)
    run_command(
        setup,
        "proposal.g0.submit",
        {
            "proposal_id": identity,
            "expected_revision": before["revision"],
            "reviewer_id": str(setup.peer),
        },
        revision=before["revision"],
    )
    pending = page(work, "decide", actor=setup.peer)
    assert pending["total_records"] == 1
    item = pending["items"][0]
    source = read_proposal(setup, identity, actor=setup.peer)
    assert item["source"]["id"] == identity
    assert item["source"]["version_id"] == source["submission"]["id"]
    assert item["project"] is item["product"] is None
    assert page(work, "decide")["total_records"] == 0
    run_command(
        setup,
        "proposal.g0.decide",
        {
            "proposal_id": identity,
            "submission_id": source["submission"]["id"],
            "expected_revision": source["revision"],
            "outcome": "returned",
            "rationale": "Named reviewer requires a more complete option basis",
            "dispositions": [],
        },
        actor=setup.peer,
        revision=source["revision"],
    )
    assert page(work, "decide", actor=setup.peer)["total_records"] == 0
