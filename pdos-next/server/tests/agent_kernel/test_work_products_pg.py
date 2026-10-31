"""Actual private work-product persistence; synthetic runs, no model calls."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentWorkProduct
from pdos_next.models import Grant
from tests.agent_kernel.test_run_continuation import finish, start


def create(setup, run_id, *, kind="document", key=None, title=None):
    response = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={
            "run_id": str(run_id),
            "kind": kind,
            "title": title,
            "request_key": str(key or uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def revise(setup, current, *, title="人工修订标题", body="人工修订正文", key=None, expected=None):
    response = setup.client.post(
        f"/v1/personal/work-products/{current['id']}/revisions",
        headers=setup.headers,
        json={
            "expected_revision": expected or current["revision"],
            "title": title,
            "body": body,
            "request_key": str(key or uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_actual_run_document_revision_replay_and_permission_boundaries(setup):
    parent, original = start(setup)
    with Session(setup.admin) as session, session.begin():
        run = session.get(AgentRun, parent)
        run.state = "completed"
        run.result = {
            "summary": "## 方案 A\n\n真实回复正文，保留未知条件。",
            "unfinished": [],
            "result": {},
        }
    key = uuid4()
    first = create(setup, parent, key=key, title="真实方案")
    assert first["body"] == "## 方案 A\n\n真实回复正文，保留未知条件。"
    assert (
        first["origin"] == "ai_draft" and first["revision"] == 1 and first["root_id"] == first["id"]
    )
    replay = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={
            "run_id": str(parent),
            "kind": "document",
            "title": "真实方案",
            "request_key": str(key),
        },
    )
    assert replay.status_code == 201 and replay.json()["id"] == first["id"]
    revision_key = uuid4()
    second = revise(setup, first, key=revision_key)
    assert second["root_id"] == first["root_id"] and second["supersedes_id"] == first["id"]
    assert second["revision"] == 2 and second["origin"] == "human"
    replay_revision = revise(setup, first, key=revision_key, expected=1)
    assert replay_revision["id"] == second["id"]
    stale = setup.client.post(
        f"/v1/personal/work-products/{first['id']}/revisions",
        headers=setup.headers,
        json={
            "expected_revision": 1,
            "title": "过期修改",
            "body": "不应写入",
            "request_key": str(uuid4()),
        },
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    peer = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json={"run_id": str(parent), "kind": "document", "request_key": str(uuid4())},
    )
    assert peer.status_code == 403
    page = setup.client.get(
        f"/v1/personal/work-products?session_id={original['session_id']}", headers=setup.headers
    )
    assert page.status_code == 200 and [row["id"] for row in page.json()["items"]] == [
        first["id"],
        second["id"],
    ]
    conflict = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
            json={
                "run_id": str(parent),
                "kind": "document",
                "title": "不同方案",
                "request_key": str(key),
            },
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    with Session(setup.admin) as session:
        assert session.scalar(
            select(func.count()).where(AgentWorkProduct.root_id == first["root_id"])
        ) == 2
    with pytest.raises(DBAPIError):
        with Session(setup.admin) as session, session.begin():
            session.execute(
                text("UPDATE agent_work_products SET body='tampered' WHERE id=:id"),
                {"id": second["id"]},
            )


def test_table_uses_actual_markdown_and_revoked_category_stops_reads(setup):
    parent, _ = start(setup)
    with Session(setup.admin) as session, session.begin():
        run = session.get(AgentRun, parent)
        run.state = "completed"
        run.result = {
            "summary": "| 方案 | 日期 |\n| --- | --- |\n| A | 11-01 |\n| B | 11-02 |",
            "unfinished": [],
            "result": {},
        }
    table = create(setup, parent, kind="table")
    assert table["kind"] == "table" and table["revision"] == 1
    other, _ = start(setup)
    finish(setup, other)
    rejected = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={"run_id": str(other), "kind": "table", "request_key": str(uuid4())},
    )
    assert rejected.status_code == 422 and rejected.json()["code"] == "VALIDATION_FAILED"
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        session.delete(grant)
    denied = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={"run_id": str(parent), "kind": "document", "request_key": str(uuid4())},
    )
    assert denied.status_code == 403
    hidden = setup.client.get(f"/v1/personal/work-products/{table['id']}", headers=setup.headers)
    assert hidden.status_code == 403
