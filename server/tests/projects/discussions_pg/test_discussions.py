"""Project discussions, @mentions and notification noise rules over real G0 projects (D37 ⑤).

Covers P34-2/3/7 and their 判据: audience inheritance, mention only of people who can
see the object, mention follows the thread, operator never notified, repeats merged
within 10 minutes (P41-9), edits keep versions, retraction leaves a placeholder, and
小Pai's identity can neither post nor mention.
"""

from uuid import UUID, uuid4

from g0_fixture import add_category_human, create_g0_project
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.core.database import tenant_session
from pdos_next.domain.projects.discussions.models import (
    DiscussionFollow,
    DiscussionMessage,
    DiscussionMessageVersion,
    DiscussionThread,
)
from projects.discussions_pg import helpers as h

DISCUSSION_TABLES = (
    "discussion_threads",
    "discussion_messages",
    "discussion_message_versions",
    "discussion_follows",
    "notifications",
    "notification_preferences",
)


def test_topic_inherits_audience_and_mentions_notify_only_those_who_see_it(setup):
    project = create_g0_project(setup, visibility="private")
    outsider = add_category_human(setup, name="合成品类成员")
    owner, peer = setup.human, setup.peer

    # A category member outside the private project cannot be mentioned (P34-3).
    refused = setup.client.post(
        h.project_root(setup, project) + "/discussions",
        headers=h.headers(setup, owner),
        json={
            "title": "样机评审安排",
            "body": f"请 {h.mention(outsider, '合成品类成员')} 看一下",
            "request_key": str(uuid4()),
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["reason"] == "mention_not_visible"
    assert refused.json()["detail"]["blocked"] == [
        {"principal_id": str(outsider), "name": "合成品类成员"}
    ]

    started = h.start_topic(
        setup, project, owner, "样机评审安排", f"{h.mention(peer, 'Synthetic peer')} 周五前确认样机数量"
    )
    thread_id = started["thread"]["id"]
    assert started["thread"]["following"] is True
    assert started["messages"][0]["mentions"] == [{"kind": "person", "id": str(peer)}]
    assert "不构成决定" in started["note"]

    # The outsider sees neither the topics nor the thread; the project is private.
    h.topics(setup, project, outsider, expect=403)
    h.thread(setup, project, outsider, thread_id, expect=403)

    # The mentioned peer: one "提及我", and follows this thread only.
    inbox = h.notes(setup, peer)
    assert [(n["category"], n["reason"], n["event_count"]) for n in inbox["items"]] == [
        ("mention", "mention", 1)
    ]
    assert inbox["items"][0]["title"] == "样机评审安排"
    assert "周五前确认样机数量" in inbox["items"][0]["snippet"]
    assert inbox["unread"]["mention"] == 1
    # The operator never hears about their own action.
    assert h.notes(setup, owner)["items"] == []
    with Session(setup.admin) as s:
        follows = {
            (row.principal_id, row.target_kind, row.reason)
            for row in s.scalars(
                select(DiscussionFollow).where(DiscussionFollow.tenant_id == setup.tenant)
            )
        }
    assert follows == {(owner, "thread", "created"), (peer, "thread", "mentioned")}

    # The peer replies twice within ten minutes: the owner gets one merged change.
    h.reply(setup, project, peer, thread_id, "数量 3 台，周四给出")
    h.reply(setup, project, peer, thread_id, "补充：含 1 台备用")
    owner_inbox = h.notes(setup, owner)["items"]
    assert [(n["category"], n["reason"], n["event_count"]) for n in owner_inbox] == [
        ("follow", "comment", 2)
    ]
    assert owner_inbox[0]["snippet"] == "补充：含 1 台备用"
    assert owner_inbox[0]["actors"] == ["Synthetic peer"]
    assert h.notes(setup, peer)["items"][0]["category"] == "mention"  # no self-notice

    # After the window a new change opens a new notification.
    h.age_notifications(setup, owner, 11)
    h.reply(setup, project, peer, thread_id, "已安排送样")
    assert [n["event_count"] for n in h.notes(setup, owner)["items"]] == [1, 2]

    # Reading and marking read: 已读不等于完成, the row stays.
    first = h.notes(setup, owner)["items"][0]
    assert h.note_state(setup, owner, "read", [first["id"]]).status_code == 200
    assert h.notes(setup, owner, unread="true")["items"][0]["id"] != first["id"]

    # Removing the peer hides the discussion and the notification at once.
    from team_fixture import remove_member

    remove_member(setup, project.project_id, peer)
    h.thread(setup, project, peer, thread_id, expect=403)
    assert h.notes(setup, peer)["items"] == []
    view = h.thread(setup, project, owner, thread_id)
    assert {m["author_name"] for m in view["messages"]} == {"Synthetic owner", "Synthetic peer"}


def test_roles_all_and_agent_mentions(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    team = setup.client.get(
        h.project_root(setup, project) + "/team", headers=h.headers(setup, owner)
    ).json()
    changed = setup.client.post(
        h.project_root(setup, project) + "/team",
        headers=h.headers(setup, owner),
        json={
            "expected_revision": team["revision"],
            "request_key": str(uuid4()),
            "changes": [
                {"action": "set_roles", "principal_id": str(peer), "roles": [{"key": "quality"}]}
            ],
        },
    )
    assert changed.status_code == 200, changed.text
    topic = h.start_topic(setup, project, owner, "品质周会", "@[品质](role:quality) 请准备数据")
    assert topic["messages"][0]["mentions"] == [
        {"kind": "role", "key": "quality", "member_ids": [str(peer)]}
    ]
    assert [n["category"] for n in h.notes(setup, peer)["items"]] == ["mention"]
    empty = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{topic['thread']['id']}/messages",
        headers=h.headers(setup, owner),
        json={"body": "@[电池安全](role:battery_safety) 在吗", "request_key": str(uuid4())},
    )
    assert empty.status_code == 422 and empty.json()["detail"]["reason"] == "mention_role_empty"
    # @全体 only for the project owner.
    denied = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{topic['thread']['id']}/messages",
        headers=h.headers(setup, peer),
        json={"body": "@[全体](all) 注意", "request_key": str(uuid4())},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["reason"] == "mention_all_owner_only"
    # @小Pai in a shared thread is W6 ⑥; the interface refuses it clearly for now.
    agent = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{topic['thread']['id']}/messages",
        headers=h.headers(setup, owner),
        json={"body": "@[小Pai](agent:xiaopai) 帮我总结", "request_key": str(uuid4())},
    )
    assert agent.status_code == 422 and agent.json()["detail"]["reason"] == "agent_mention_pending"
    mentionable = setup.client.get(
        h.project_root(setup, project) + "/mentionable", headers=h.headers(setup, owner)
    ).json()
    people = {p["principal_id"]: p for p in mentionable["people"]}
    assert people[str(peer)]["can_see"] is True and people[str(peer)]["roles"] == ["品质"]
    assert mentionable["can_mention_all"] is True and mentionable["agent"]["available"] is False


def test_edit_keeps_versions_and_retraction_leaves_placeholder(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    topic = h.start_topic(setup, project, owner, "BOM 讨论", "初稿：电机选 A 型")
    thread_id, message = topic["thread"]["id"], topic["messages"][0]
    root = h.project_root(setup, project) + f"/discussions/{thread_id}/messages/{message['id']}"

    # Only the author edits or retracts.
    other = setup.client.post(
        root + "/edit",
        headers=h.headers(setup, peer),
        json={"body": "改成 B 型", "expected_revision": 1, "request_key": str(uuid4())},
    )
    assert other.status_code == 403 and other.json()["detail"]["reason"] == "author_only"
    edited = setup.client.post(
        root + "/edit",
        headers=h.headers(setup, owner),
        json={
            "body": f"修订：电机选 B 型，{h.mention(peer, 'Synthetic peer')} 确认",
            "expected_revision": 1,
            "request_key": str(uuid4()),
        },
    )
    assert edited.status_code == 200, edited.text
    current = edited.json()["messages"][0]
    assert current["edited"] is True and current["revision"] == 2
    # An edit tells only the newly mentioned person.
    assert [n["reason"] for n in h.notes(setup, peer)["items"]] == ["mention"]
    stale = setup.client.post(
        root + "/retract",
        headers=h.headers(setup, owner),
        json={"expected_revision": 1, "request_key": str(uuid4())},
    )
    assert stale.status_code == 409
    retracted = setup.client.post(
        root + "/retract",
        headers=h.headers(setup, owner),
        json={"expected_revision": 2, "request_key": str(uuid4())},
    )
    assert retracted.status_code == 200, retracted.text
    shown = h.thread(setup, project, peer, thread_id)["messages"][0]
    assert shown["retracted"] and shown["body"] == "" and shown["placeholder"] == "已撤回"
    assert shown["mentions"] == []
    again = setup.client.post(
        root + "/edit",
        headers=h.headers(setup, owner),
        json={"body": "再改", "expected_revision": 3, "request_key": str(uuid4())},
    )
    assert again.status_code == 409
    # Audit keeps every version; others cannot read the retracted history.
    with Session(setup.admin) as s:
        versions = list(
            s.scalars(
                select(DiscussionMessageVersion.body)
                .where(DiscussionMessageVersion.message_id == UUID(message["id"]))
                .order_by(DiscussionMessageVersion.revision)
            )
        )
    assert versions[0] == "初稿：电机选 A 型" and versions[1].startswith("修订") and versions[2] == ""
    with tenant_session(setup.engine, setup.tenant, actor_id=peer, category_id=setup.category) as s:
        assert s.scalar(select(func.count()).select_from(DiscussionMessageVersion)) == 0
    with tenant_session(
        setup.engine, setup.tenant, actor_id=owner, category_id=setup.category
    ) as s:
        assert s.scalar(select(func.count()).select_from(DiscussionMessageVersion)) == 3


def test_idempotent_post_and_database_guards(setup):
    project = create_g0_project(setup, visibility="private")
    owner = setup.human
    topic = h.start_topic(setup, project, owner, "重放", "第一条")
    thread_id = topic["thread"]["id"]
    key = uuid4()
    first = h.reply(setup, project, owner, thread_id, "幂等消息", key=key)
    second = h.reply(setup, project, owner, thread_id, "幂等消息", key=key)
    assert len(first["messages"]) == len(second["messages"]) == 2
    conflict = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{thread_id}/messages",
        headers=h.headers(setup, owner),
        json={"body": "另一份内容", "request_key": str(key)},
    )
    assert conflict.status_code == 409

    # 小Pai's identity: no grant at all, and a run identity cannot pass the policies.
    with Session(setup.admin) as s:
        grants = s.execute(
            text(
                "SELECT table_name FROM information_schema.role_table_grants "
                "WHERE grantee='pdos_agent' AND table_name = ANY(:names)"
            ),
            {"names": list(DISCUSSION_TABLES)},
        ).all()
        assert grants == []
        message = s.scalar(select(DiscussionMessage).where(DiscussionMessage.thread_id == UUID(thread_id)))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=owner,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(DiscussionThread)) == 0
    try:
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.agent, requester_id=owner,
            category_id=setup.category,
        ) as s:
            s.add(
                DiscussionMessage(
                    tenant_id=setup.tenant, thread_id=UUID(thread_id), sequence=3,
                    author_id=setup.agent, revision=1, state="posted", body="AI 冒充发言",
                    mentions=[], subject_revision=None, updated_at=message.updated_at,
                    change_seq=0, request_key=uuid4(), request_sha256="0" * 64,
                )
            )
            s.flush()
        raise AssertionError("agent identity wrote a discussion message")
    except DBAPIError as error:
        # Refused by the author guard (author = actor = requester) before RLS even runs.
        assert "Invalid discussion message" in str(error.orig) or "row-level security" in str(
            error.orig
        )
    # History is append-only: no hard delete even for the author.
    try:
        with tenant_session(
            setup.engine, setup.tenant, actor_id=owner, category_id=setup.category
        ) as s:
            s.execute(text("DELETE FROM discussion_messages WHERE id=:id"), {"id": message.id})
        raise AssertionError("message deleted")
    except DBAPIError:
        pass
    with Session(setup.admin) as s:
        assert s.scalar(
            select(func.count()).select_from(DiscussionMessage).where(
                DiscussionMessage.thread_id == UUID(thread_id)
            )
        ) == 2
