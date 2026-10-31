from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.inbox.models import Conversation, InboxState, Message
from pdos_next.inbox.service import NewConversation, create
from pdos_next.models import Grant, now

ROOT = "/v1/personal/inbox"


def body(setup, **changes):
    return {
        "category_id": str(setup.category),
        "title": "合成协作",
        "recipients": [str(setup.peer)],
        "body": "合成首条消息",
        "request_key": str(uuid4()),
        **changes,
    }


def auth(setup, person):
    return {"Authorization": f"Bearer {setup.tokens[person]}"}


def test_conversation_messages_paging_exact_retry_and_private_states(setup):
    request = body(setup)
    first = setup.client.post(ROOT + "/conversations", headers=setup.headers, json=request)
    assert first.status_code == 201, first.text
    identity = first.json()["conversation_id"]
    assert (
        setup.client.post(ROOT + "/conversations", headers=setup.headers, json=request).json()
        == first.json()
    )
    assert (
        setup.client.post(
            ROOT + "/conversations", headers=setup.headers, json={**request, "title": "different"}
        ).status_code
        == 409
    )
    path = f"{ROOT}/conversations/{identity}/messages"
    reply = {"body": "合成回复", "request_key": str(uuid4())}
    second = setup.client.post(path, headers=auth(setup, setup.peer), json=reply)
    assert second.status_code == 201, second.text
    assert (
        setup.client.post(path, headers=auth(setup, setup.peer), json=reply).json() == second.json()
    )
    assert second.json()["sequence"] == 2
    newest = setup.client.get(path, headers=setup.headers, params={"page_size": 1}).json()
    assert [m["sequence"] for m in newest["items"]] == [2] and newest["next_before"] == 2
    older = setup.client.get(
        path, headers=setup.headers, params={"page_size": 1, "before": 2}
    ).json()
    assert [m["sequence"] for m in older["items"]] == [1] and older["next_before"] is None
    state = {
        "kind": "conversation",
        "target_id": identity,
        "expected_revision": 0,
        "observed_token": "2",
        "mark_read": True,
        "archived": True,
        "followed": True,
        "request_key": str(uuid4()),
    }
    saved = setup.client.post(ROOT + "/states", headers=setup.headers, json=state)
    assert saved.status_code == 200, saved.text
    assert saved.json()["read_through"] == "2"
    assert (
        setup.client.post(ROOT + "/states", headers=setup.headers, json=state).json()
        == saved.json()
    )
    assert setup.client.get(ROOT + "/states", headers=auth(setup, setup.peer)).json()["items"] == []
    assert (
        setup.client.post(
            ROOT + "/states", headers=setup.headers, json={**state, "request_key": str(uuid4())}
        ).status_code
        == 409
    )
    assert (
        setup.client.post(
            path,
            headers=auth(setup, setup.peer),
            json={"body": "第三条", "request_key": str(uuid4())},
        ).status_code
        == 201
    )
    # A new message reappears as unread: stored read token cannot cover an unseen sequence.
    listing = setup.client.get(ROOT + "/conversations", headers=setup.headers).json()
    assert listing["items"][0]["latest"]["sequence"] == 3
    assert (
        setup.client.post(
            ROOT + "/states",
            headers=setup.headers,
            json={**state, "expected_revision": 1, "request_key": str(uuid4())},
        ).status_code
        == 409
    )


def test_revoke_tenant_audience_and_agent_boundaries(setup):
    created = setup.client.post(
        ROOT + "/conversations", headers=setup.headers, json=body(setup)
    ).json()
    path = f"{ROOT}/conversations/{created['conversation_id']}/messages"
    assert setup.client.get(path, headers=auth(setup, setup.other_human)).status_code == 403
    assert (
        setup.client.get(ROOT + "/conversations", headers=auth(setup, setup.other_human)).json()[
            "items"
        ]
        == []
    )
    assert (
        setup.client.post(
            ROOT + "/conversations",
            headers=setup.headers,
            json=body(setup, recipients=[str(setup.agent)]),
        ).status_code
        == 403
    )
    assert (
        setup.client.post(
            ROOT + "/conversations",
            headers=setup.headers,
            json=body(setup, recipients=[str(setup.other_human)]),
        ).status_code
        == 403
    )
    assert (
        setup.client.post(
            ROOT + "/conversations",
            headers=setup.headers,
            json=body(setup, recipients=[str(setup.peer), str(setup.peer)]),
        ).status_code
        == 422
    )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human
    ) as session:
        with pytest.raises(DomainError):
            create(
                session,
                replace(setup.ctx, category_id=None, actor_id=setup.agent),
                NewConversation.model_validate(body(setup)),
            )
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.peer
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    assert setup.client.get(path, headers=auth(setup, setup.peer)).status_code == 403
    assert (
        setup.client.get(ROOT + "/conversations", headers=auth(setup, setup.peer)).json()["items"]
        == []
    )
    assert (
        setup.client.post(
            path,
            headers=auth(setup, setup.peer),
            json={"body": "blocked", "request_key": str(uuid4())},
        ).status_code
        == 403
    )


def test_database_append_only_and_no_agent_grants(setup):
    result = setup.client.post(ROOT + "/conversations", headers=setup.headers, json=body(setup))
    assert result.status_code == 201, result.text
    for table in (Conversation.__tablename__, Message.__tablename__, InboxState.__tablename__):
        with Session(setup.admin) as session:
            assert not session.execute(
                text("SELECT has_table_privilege('pdos_agent',:table,'INSERT')"), {"table": table}
            ).scalar_one()
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as session:
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE inbox_messages SET body='overwrite'"))
    with Session(setup.admin) as session:
        with pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE inbox_conversations SET title='overwrite' WHERE id=CAST(:id AS uuid)"),
                {"id": result.json()["conversation_id"]},
            )
