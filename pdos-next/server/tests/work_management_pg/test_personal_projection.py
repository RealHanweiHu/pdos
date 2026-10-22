"""Actual two-category personal work projections; only root runs PG/HTTP.

Reuse the existing guarded original/G0 fixture and common work commands. No work
fact, Current, receipt or project summary is inserted directly. Grant expiry is
an explicit identity-boundary negative case; no business state is forged.
"""

import os
import re
from copy import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import event, update
from sqlalchemy.orm import Session
from test_project_first_plan import cmd

from pdos_next.database import tenant_session
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    STATUS,
    SUBMIT,
)
from pdos_next.models import Category, Grant, now
from pdos_next.safety import verify_test_target
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import (
    original_security_work,  # noqa: F401
)
from work_management_pg.test_workflow import work as work_case  # noqa: F401

QUEUES = ("receive", "verify", "tasks", "commitments")
_WHOLE_PRIVATE_COLUMNS = re.compile(
    r'\b[\w"]+\.(?:body|command|source_basis)\s*(?=,|as\b|from\b|$)', re.I
)
_ARTIFACT_BODY = re.compile(r"\bartifact_versions(?:_\d+)?\.content\b", re.I)


@pytest.fixture
def work(request):
    value = request.getfixturevalue("work_case")
    verify_test_target(value.setup.admin)
    verify_test_target(value.setup.engine)
    return value


def _no_wide_reads(statements):
    assert statements
    for statement in statements:
        assert not _WHOLE_PRIVATE_COLUMNS.search(statement), statement
        assert not _ARTIFACT_BODY.search(statement), statement
        assert " for update" not in statement.lower(), statement


def _get(work, path, *, actor=None, expected=200, params=None):
    before, statements = flow.snapshots(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        response = work.setup.client.get(path, params=params, headers=flow.headers(work, actor))
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert response.status_code == expected, response.text
    assert flow.snapshots(work) == before
    _no_wide_reads(statements)
    return response.json()


def _page(work, queue, *, actor=None, cursor=None, page_size=20, expected=200):
    actor = actor or work.setup.human
    params = {"queue": queue, "page_size": page_size}
    if cursor is not None:
        params["cursor"] = str(cursor)
    value = _get(work, "/v1/personal/project-work", actor=actor, params=params, expected=expected)
    if expected != 200:
        assert value["code"] == "FORBIDDEN_SCOPE" and "items" not in value
        return value
    assert set(value) == {
        "version",
        "principal_id",
        "as_of",
        "queue",
        "total_records",
        "items",
        "next_cursor",
    }
    assert value["version"] == "personal-project-work/v1"
    assert value["principal_id"] == str(actor) and value["queue"] == queue
    assert datetime.fromisoformat(value["as_of"]).utcoffset() is not None
    assert value["total_records"] >= len(value["items"])
    for item in value["items"]:
        assert set(item) == {
            "id",
            "category",
            "product",
            "project",
            "task",
            "assignee",
            "recipient",
            "recorded_at",
            "commitment",
            "timing",
        }
        assert set(item["task"]) == {"id", "version_id", "revision", "state", "title"}
        assert all(set(item[key]) == {"id", "name"} for key in ("category", "product", "project"))
        assert datetime.fromisoformat(item["recorded_at"]).utcoffset() is not None
        assert item["timing"] in {None, "unknown", "pending", "overdue"}
        if queue == "commitments":
            assert item["commitment"] is not None
            assert item["id"] == item["commitment"]["id"]
            assert item["commitment"]["promisor_id"] == str(actor)
        else:
            assert item["id"] == item["task"]["id"] and item["commitment"] is None
    if value["next_cursor"] is not None:
        assert value["items"] and value["next_cursor"] == value["items"][-1]["id"]
    return value


def _ids(value):
    return {row["id"] for row in value["items"]}


def _all_pages(work, queue, expected_ids, *, actor):
    seen, cursor = [], None
    for _ in range(len(expected_ids) + 2):
        value = _page(work, queue, actor=actor, cursor=cursor, page_size=1)
        assert value["total_records"] == len(expected_ids)
        seen.extend(row["id"] for row in value["items"])
        if value["next_cursor"] is None:
            break
        assert value["next_cursor"] != cursor
        cursor = value["next_cursor"]
    else:
        pytest.fail("Actual personal pagination did not terminate")
    assert len(seen) == len(set(seen)) and set(seen) == expected_ids


def _second_category(work):
    setup = copy(work.setup)
    category = {
        "key": "personal-work-" + uuid4().hex,
        "name": "Synthetic second work category",
        "purpose": "Actual cross-category personal work projection",
        "idempotency_key": str(uuid4()),
        "deidentified_confirmed": True,
    }
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=category)
    assert preview.status_code == 200, preview.text
    category["confirmation_token"] = preview.json()["confirmation_token"]
    created = setup.client.post("/v1/categories", headers=setup.headers, json=category)
    assert created.status_code == 201, created.text
    setup.category = UUID(created.json()["subject_id"])
    setup.ctx = replace(setup.ctx, category_id=setup.category)
    granted = setup.client.post(
        f"/v1/categories/{setup.category}/members",
        headers=setup.headers,
        json={
            "principal_id": str(setup.peer),
            "can_write": True,
            "product_manager": True,
            "expires_at": (now() + timedelta(minutes=45)).isoformat(),
            "expected_revision": 1,
            "idempotency_key": str(uuid4()),
            "decision": "批准",
        },
    )
    assert granted.status_code == 200, granted.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as session:
        current = session.get(Category, setup.category)
        assert current is not None and current.tenant_id == setup.tenant
        assert current.owner_id == setup.human and current.status == "active"
        category_revision = current.revision

    client = setup.client
    route = f"/v1/categories/{setup.category}/commands"

    class InitialProposalRevisionClient:
        def post(self, path, **kwargs):
            command = kwargs.get("json")
            if (
                path in {route, route + "/preview"}
                and isinstance(command, dict)
                and command.get("operation") == "proposal.create"
                and command.get("category_id") == str(setup.category)
                and command.get("product_id") is None
            ):
                kwargs["json"] = {**command, "expected_revision": category_revision}
            return client.post(path, **kwargs)

        def __getattr__(self, name):
            return getattr(client, name)

    # The frozen G0 helper assumes a brand-new category; membership changed its
    # revision. Keep the real preview/commit guard bound to the revision read above.
    setup.client = InitialProposalRevisionClient()
    try:
        g0 = create_g0_project(setup, visibility="category", name="Synthetic second work project")
    finally:
        setup.client = client
    line = "Synthetic exact second-category task evidence; no physical release qualification."
    response = flow.send(
        SimpleNamespace(setup=setup),
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Second category work original",
                "content": line,
                "source_label": "Isolated personal work projection",
                "visibility": "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    source = {
        "kind": "artifact",
        "id": response.json()["subject_id"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }
    return SimpleNamespace(setup=setup, project_id=UUID(g0.project_id), source=source)


def _save(work, operation, *, actor=None, **values):
    _, receipt = flow.execute(work, operation, flow.payload(work, **values), actor=actor)
    return receipt


def _task_ref(receipt):
    return {"id": receipt["result"]["task_id"], "revision": receipt["subject_revision"]}


def _assigned(work, title, assignee, recipient):
    created = _save(
        work,
        CREATE,
        title=title,
        goal="Preserve individual drawing and inspection evidence",
        outcomes=[
            {"key": key, "text": key + " actual outcome", "required": True}
            for key in ("drawing", "inspection")
        ],
        plan_task=None,
    )
    return _save(
        work,
        ASSIGN,
        task=_task_ref(created),
        assignee_id=str(assignee),
        recipient_id=str(recipient),
    )


def _status_summary(work, project_id, *, actor=None):
    listed = _get(work, "/v1/personal/projects", actor=actor, params={"page_size": 50})
    selected = [
        row["project"] for row in listed["items"] if row["project"]["id"] == str(project_id)
    ]
    assert len(selected) == 1
    direct = _get(work, f"/v1/personal/projects/{project_id}", actor=actor)
    assert len(direct["items"]) == 1
    assert (
        selected[0]["latest_status_update"] == direct["items"][0]["project"]["latest_status_update"]
    )
    return selected[0]["latest_status_update"]


def test_actual_personal_queues_follow_named_work_across_categories_and_current_grants(work):
    setup, other = work.setup, _second_category(work)
    core = _assigned(work, "Personal core work", setup.peer, setup.human)
    cross = _assigned(other, "Cross-category peer work", setup.peer, setup.human)
    own = _assigned(other, "Owner is the named assignee", setup.human, setup.peer)
    core_ref, cross_ref, own_ref = map(_task_ref, (core, cross, own))
    received = _page(work, "receive", actor=setup.peer)
    assert _ids(received) == {core_ref["id"], cross_ref["id"]}
    assert {row["category"]["id"] for row in received["items"]} == {
        str(setup.category),
        str(other.setup.category),
    }
    assert _ids(_page(work, "receive")) == {own_ref["id"]}
    _all_pages(work, "receive", {core_ref["id"], cross_ref["id"]}, actor=setup.peer)
    _page(work, "receive", cursor=core_ref["id"], expected=403)
    _page(work, "receive", actor=setup.peer, cursor=own_ref["id"], expected=403)
    _page(work, "receive", actor=setup.peer, cursor=uuid4(), expected=403)
    for queue in QUEUES:
        assert _page(work, queue, actor=setup.other_human)["items"] == []
    _page(work, "receive", actor=setup.other_human, cursor=core_ref["id"], expected=403)
    accepted = _save(work, ACCEPT, actor=setup.peer, task=core_ref)
    current = _task_ref(accepted)
    assert _ids(_page(work, "receive", actor=setup.peer)) == {cross_ref["id"]}
    assert _ids(_page(work, "tasks", actor=setup.peer)) == {core_ref["id"]}
    _page(work, "receive", actor=setup.peer, cursor=core_ref["id"], expected=403)
    promised = (now() + timedelta(days=1)).astimezone(ZoneInfo("Asia/Shanghai"))
    commitments = []
    for recipient, at in ((setup.human, None), (setup.peer, promised.isoformat())):
        commitments.append(
            _save(
                work,
                COMMIT,
                actor=setup.peer,
                task=current,
                recipient_id=str(recipient),
                outcome_keys=["drawing", "inspection"],
                promised_at=at,
                original_timezone="Asia/Shanghai",
                calendar_id=None,
                replaces=None,
            )
        )
    promise_page = _page(work, "commitments", actor=setup.peer)
    assert _ids(promise_page) == {row["subject_id"] for row in commitments}
    assert _page(work, "commitments")["items"] == []
    by_recipient = {row["commitment"]["recipient_id"]: row for row in promise_page["items"]}
    null = by_recipient[str(setup.human)]
    bounded = by_recipient[str(setup.peer)]
    assert null["commitment"]["promised_at"] is None and null["timing"] == "unknown"
    assert bounded["timing"] == "pending"
    assert datetime.fromisoformat(bounded["commitment"]["promised_at"]).astimezone(
        UTC
    ) == promised.astimezone(UTC)
    assert all(
        row["commitment"]["original_timezone"] == "Asia/Shanghai"
        and row["commitment"]["calendar_id"] is None
        and row["commitment"]["task_revision"] == 3
        for row in promise_page["items"]
    )
    _all_pages(work, "commitments", _ids(promise_page), actor=setup.peer)
    _page(work, "commitments", cursor=commitments[0]["subject_id"], expected=403)
    # The caller loses only one category; another category's active task remains.
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == other.setup.category,
                Grant.principal_id == setup.peer,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    assert _page(work, "receive", actor=setup.peer)["items"] == []
    assert _ids(_page(work, "tasks", actor=setup.peer)) == {core_ref["id"]}
    _page(work, "receive", actor=setup.peer, cursor=cross_ref["id"], expected=403)
    started = _save(work, START, actor=setup.peer, task=current, **flow.clock_fields())
    current = _task_ref(started)
    partial = _save(
        work,
        SUBMIT,
        actor=setup.peer,
        task=current,
        **flow.clock_fields(),
        results=[
            {
                "key": "drawing",
                "text": "Drawing present",
                "status": "present",
                "sources": [work.source],
            },
            {
                "key": "inspection",
                "text": "Inspection unknown/partial remains explicit",
                "status": "partial",
                "sources": [work.source],
            },
        ],
    )
    current = _task_ref(partial)
    verify = _page(work, "verify")
    assert _ids(verify) == {core_ref["id"]}
    assert verify["items"][0]["task"]["version_id"] == partial["subject_id"]
    assert verify["items"][0]["task"]["revision"] == current["revision"]
    assert _page(work, "verify", actor=setup.peer)["items"] == []
    assert _ids(_page(work, "tasks", actor=setup.peer)) == {core_ref["id"]}
    returned = _save(
        work,
        REVIEW,
        task=current,
        decision="returned",
        **flow.clock_fields(),
        checks=[
            {"key": "drawing", "decision": "accepted", "reason": "Individually present"},
            {
                "key": "inspection",
                "decision": "unknown",
                "reason": "Still partial, keep the unknown basis",
            },
        ],
    )
    current = _task_ref(returned)
    assert _page(work, "verify")["items"] == []
    assert _page(work, "tasks", actor=setup.peer)["items"][0]["task"]["state"] == "in_progress"
    _page(work, "verify", cursor=core_ref["id"], expected=403)
    submitted = _save(
        work,
        SUBMIT,
        actor=setup.peer,
        task=current,
        **flow.clock_fields(),
        results=[
            {
                "key": key,
                "text": "Actually complete " + key,
                "status": "present",
                "sources": [work.source],
            }
            for key in ("drawing", "inspection")
        ],
    )
    current = _task_ref(submitted)
    assert _ids(_page(work, "verify")) == {core_ref["id"]}
    completed = _save(
        work,
        REVIEW,
        task=current,
        decision="accepted",
        **flow.clock_fields(),
        checks=[
            {"key": key, "decision": "accepted", "reason": "Actual complete result accepted"}
            for key in ("drawing", "inspection")
        ],
    )
    final_ref = _task_ref(completed)
    assert final_ref["revision"] == 8
    for queue in ("tasks", "verify"):
        assert _page(work, queue, actor=setup.peer)["items"] == []
    assert _page(work, "verify")["items"] == []
    _page(work, "tasks", actor=setup.peer, cursor=core_ref["id"], expected=403)
    # Task acceptance does not silently fulfill or close independent promises.
    retained_promises = _page(work, "commitments", actor=setup.peer)
    assert _ids(retained_promises) == _ids(promise_page)
    assert all(
        row["task"]["state"] == "completed"
        and row["task"]["revision"] == 8
        and row["commitment"]["task_revision"] == 3
        for row in retained_promises["items"]
    )
    assert {row["id"]: row["commitment"] for row in retained_promises["items"]} == {
        row["id"]: row["commitment"] for row in promise_page["items"]
    }
    assert (
        _page(work, "commitments", actor=setup.peer, cursor=commitments[0]["subject_id"])[
            "total_records"
        ]
        == 2
    )
    assert len(flow.workspace(work)["commitments"]) == 2
    # Latest named updates are a separate metadata projection with fixed refs.
    assert _status_summary(work, work.project_id) is None
    original = _save(
        work,
        STATUS,
        fact_summary="Actual complete work with returned history retained",
        next_steps="Keep bounded original evidence",
        task_refs=[final_ref],
    )
    summary = _status_summary(work, work.project_id)
    assert summary["id"] == original["subject_id"] and summary["revision"] == 1
    assert summary["actor"]["id"] == str(setup.human) and summary["task_refs"] == [final_ref]
    latest = _save(
        work,
        STATUS,
        fact_summary="A later named update keeps the same fixed task revision",
        next_steps="Prepare the next separately authorized action",
        task_refs=[final_ref],
    )
    summary = _status_summary(work, work.project_id)
    assert summary["id"] == latest["subject_id"] and summary["id"] != original["subject_id"]
    assert summary["task_refs"] == [final_ref]
    assert len(flow.workspace(work)["updates"]) == 2
    if os.environ.get("PDOS_PERSONAL_WORK_BROWSER_SEED") == "1":
        from work_management_pg.personal_browser_seed import run

        run(work, other, final_ref["id"], latest["subject_id"])
    # Expired category membership hides the project and any old cached summary.
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    listed = _get(work, "/v1/personal/projects", params={"page_size": 50})
    assert str(work.project_id) not in {row["project"]["id"] for row in listed["items"]}
    assert str(other.project_id) in {row["project"]["id"] for row in listed["items"]}
    denied = _get(work, f"/v1/personal/projects/{work.project_id}", expected=404)
    assert "items" not in denied and latest["subject_id"] not in str(denied)
    assert _ids(_page(work, "receive")) == {own_ref["id"]}
