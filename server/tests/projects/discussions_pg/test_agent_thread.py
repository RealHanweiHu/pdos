"""@小Pai in shared threads and 小Pai's proactive mentions (D37 ⑥; P34-4/5, P52, P54, P62).

Over real G0 projects and the isolated pdos_test: the server binds the Run to the
thread's project and the requester's own Session; the reply reaches the thread only
when every source the Run read is visible to everyone who can see the thread, and
otherwise only a notice; people who cannot see the object can neither start a Run nor
read a reply; 小Pai's identity has no direct write anywhere here; a proactive mention
reaches a person once per cooldown.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from g0_fixture import add_category_human, create_g0_project
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentEvent, AgentRun
from pdos_next.agent.memory.models import MemorySessionSetting
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Artifact, ObjectAudience
from pdos_next.core.service import Context
from pdos_next.domain.my_work.notifications import agent_mentions
from pdos_next.domain.projects.discussions import agent_delivery
from pdos_next.domain.projects.discussions.models import (
    DiscussionAgentRequest,
    DiscussionMessage,
)
from projects.discussions_pg import helpers as h

XIAOPAI = "@[小Pai](agent)"


def post_topic(setup, project, person, body, *, title="样机评审", private=False, expect=201):
    response = setup.client.post(
        h.project_root(setup, project) + "/discussions",
        headers=h.headers(setup, person),
        json={"title": title, "body": body, "request_key": str(uuid4()), "agent_private": private},
    )
    assert response.status_code == expect, response.text
    return response.json()


def post(setup, project, person, thread_id, body, *, private=False, expect=201):
    response = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{thread_id}/messages",
        headers=h.headers(setup, person),
        json={"body": body, "request_key": str(uuid4()), "agent_private": private},
    )
    assert response.status_code == expect, response.text
    return response.json()


def requests(setup, thread_id):
    with Session(setup.admin) as s:
        return list(
            s.scalars(
                select(DiscussionAgentRequest)
                .where(DiscussionAgentRequest.thread_id == UUID(str(thread_id)))
                .order_by(DiscussionAgentRequest.created_at)
            )
        )


def finish(setup, run_id, summary, *, state="completed", read_sources=None, categories=None):
    """Test-only stand-in for the 小Pai workflow ending the Run (no model is called)."""
    values = {"state": state, "result": {"summary": summary}}
    if read_sources is not None:
        values["read_sources"] = read_sources
    if categories is not None:
        values["data_categories"] = categories
    with Session(setup.admin) as s, s.begin():
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(update(AgentRun).where(AgentRun.id == run_id).values(**values))


def deliver(setup, request_id):
    return agent_delivery.execute(
        setup.engine,
        setup.dispatch,
        {"tenant_id": str(setup.tenant), "request_id": str(request_id)},
    )


def artifact(setup, project, *, visibility):
    identity = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Artifact(
                id=identity,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=project.product_id,
                owner_id=setup.human,
                title="合成测试报告",
                source_label="synthetic",
                content="合成内容",
                content_hash="0" * 64,
                visibility=visibility,
                revision=1,
                status="active",
            )
        )
    return {
        "artifact_id": str(identity),
        "expected_revision": 1,
        "product_id": str(project.product_id),
    }


def reply(setup, project, person, thread_id, request_id, *, expect=200):
    response = setup.client.get(
        h.project_root(setup, project)
        + f"/discussions/{thread_id}/agent-requests/{request_id}/reply",
        headers=h.headers(setup, person),
    )
    assert response.status_code == expect, response.text
    return response.json()


def share(setup, project, person, thread_id, request_id, mode, *, acknowledged=False, expect=200):
    response = setup.client.post(
        h.project_root(setup, project)
        + f"/discussions/{thread_id}/agent-requests/{request_id}/share",
        headers=h.headers(setup, person),
        json={"mode": mode, "acknowledged": acknowledged, "request_key": str(uuid4())},
    )
    assert response.status_code == expect, response.text
    return response.json()


def test_mention_starts_a_bound_run_in_the_requesters_own_session(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    outsider = add_category_human(setup, name="合成品类成员")

    options = setup.client.get(
        h.project_root(setup, project) + "/mentionable", headers=h.headers(setup, owner)
    ).json()
    assert options["agent"]["available"] is True

    started = post_topic(setup, project, owner, f"{XIAOPAI} 帮我整理样机评审的待办")
    thread_id = started["thread"]["id"]
    message = started["messages"][0]
    assert message["mentions"] == [{"kind": "agent"}]
    card = message["agent_request"]
    assert card["own"] is True and card["label"] == "进行中" and card["delivery"] == "pending"

    [first] = requests(setup, thread_id)
    with Session(setup.admin) as s:
        run = s.get(AgentRun, first.run_id)
        # Scope is the server's: this project, this requester, 小Pai as the writer.
        assert (run.requester_id, run.writer_id, run.project_id) == (
            owner,
            setup.agent,
            UUID(str(project.project_id)),
        )
        assert run.trigger == "conversation" and run.state == "queued"
        assert run.goal == "帮我整理样机评审的待办"
        thread_context = run.versions["discussion_thread"]
        assert thread_context["zone"] == "background"
        assert [item["text"] for item in thread_context["messages"]] == [
            "@小Pai 帮我整理样机评审的待办"
        ]
        accepted = s.scalar(select(AgentEvent).where(AgentEvent.run_id == run.id))
        assert accepted.body["channel"] == "discussion"
        # Personal memory stays out of a shared thread (P34 §9, P85 第 5 项).
        setting = s.scalar(
            select(MemorySessionSetting).where(MemorySessionSetting.session_id == run.session_id)
        )
        assert setting is not None and setting.memory_off is True

    # Another member sees the card, not the Run; an outsider sees nothing.
    seen = h.thread(setup, project, peer, thread_id)["messages"][0]["agent_request"]
    assert (
        seen["own"] is False
        and "run_id" not in seen
        and seen["requester_name"] == "Synthetic owner"
    )
    h.thread(setup, project, outsider, thread_id, expect=403)

    # One request at a time per requester and thread.
    refused = post(setup, project, owner, thread_id, f"{XIAOPAI} 再补充一点", expect=409)
    assert "上一条" in refused["message"]

    # P52: the second member gets their own Session, never the first member's.
    post(setup, project, peer, thread_id, f"{XIAOPAI} 我负责的部分有哪些")
    _, second = requests(setup, thread_id)
    assert second.requester_id == peer and second.session_id != first.session_id

    # The same requester asking again continues their own Session.
    finish(setup, first.run_id, "已整理：样机数量待周五确认。")
    deliver(setup, first.id)
    post(setup, project, owner, thread_id, f"{XIAOPAI} 谁来确认数量")
    third = requests(setup, thread_id)[-1]
    with Session(setup.admin) as s:
        continued = s.get(AgentRun, third.run_id)
        assert continued.continued_from_id == first.run_id
        assert continued.session_id == first.session_id
        # The public reply is now common context; earlier human words are kept too.
        texts = [item["text"] for item in continued.versions["discussion_thread"]["messages"]]
        assert "已整理：样机数量待周五确认。" in texts


def test_reply_reaches_the_thread_only_when_every_source_is_visible_to_its_audience(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    shared = artifact(setup, project, visibility="category")
    hidden = artifact(setup, project, visibility="private")

    thread_id = post_topic(setup, project, owner, f"{XIAOPAI} 总结一下报告")["thread"]["id"]
    [public] = requests(setup, thread_id)
    finish(setup, public.run_id, "报告结论：三项通过。", read_sources=[shared])
    result = deliver(setup, public.id)
    assert result["verdict"] == "public"

    view = h.thread(setup, project, peer, thread_id)
    reply_message = view["messages"][-1]
    assert reply_message["author_kind"] == "agent" and reply_message["author_name"] == "小Pai"
    assert reply_message["body"] == "报告结论：三项通过。"
    assert reply_message["agent"]["kind"] == "reply"
    assert reply_message["agent"]["requested_by"] == "Synthetic owner"
    assert reply_message["can_edit"] is False and reply_message["can_retract"] is False
    assert view["messages"][0]["agent_request"]["label"] == "完成"
    with Session(setup.admin) as s:
        row = s.get(DiscussionAgentRequest, public.id)
        assert row.delivery == "public" and row.audience_check["audience_size"] == 2
        assert row.audience_check["uncovered_members"] == 0
    # Settled once: a second delivery changes nothing.
    assert deliver(setup, public.id)["state"] == "public"

    # One source the peer cannot read keeps the whole reply private (P34-4).
    post(setup, project, owner, thread_id, f"{XIAOPAI} 再看看私有那份")
    private = requests(setup, thread_id)[-1]
    finish(setup, private.run_id, "私有报告提到供应商 A 的单价。", read_sources=[shared, hidden])
    assert deliver(setup, private.id)["verdict"] == "private"
    view = h.thread(setup, project, peer, thread_id)
    notice = view["messages"][-1]
    assert (
        notice["author_kind"] == "agent"
        and notice["body"] == "小Pai 已回复发起人（只给发起人看）。"
    )
    assert notice["agent"]["kind"] == "notice"
    assert "供应商" not in str(view)
    card = next(
        m
        for m in view["messages"]
        if m["agent_request"] and m["agent_request"]["request_id"] == str(private.id)
    )
    assert card["agent_request"]["delivery"] == "private"
    assert card["agent_request"]["reason"] == "audience_not_covered"
    with Session(setup.admin) as s:
        check = s.get(DiscussionAgentRequest, private.id).audience_check
        assert check["uncovered_members"] == 1 and check["uncovered_source_kinds"] == ["artifact"]
    # The requester reads it; nobody else does.
    mine = reply(setup, project, owner, thread_id, private.id)
    assert mine["body"] == "私有报告提到供应商 A 的单价。"
    assert mine["share_modes"] == ["link", "body"] and mine["body_warning"]
    reply(setup, project, peer, thread_id, private.id, expect=403)

    # Sharing the body needs the acknowledgement (P62-2); it is then 小Pai's message.
    share(setup, project, owner, thread_id, private.id, "body", expect=422)
    share(setup, project, peer, thread_id, private.id, "body", acknowledged=True, expect=403)
    view = share(setup, project, owner, thread_id, private.id, "body", acknowledged=True)
    shared_message = view["messages"][-1]
    assert shared_message["agent"]["kind"] == "share" and shared_message["body"].startswith(
        "私有报告"
    )
    with Session(setup.admin) as s:
        receipt = s.get(DiscussionAgentRequest, private.id).share_receipt
        assert receipt["mode"] == "body" and receipt["acknowledged"] is True
        assert receipt["shared_by"] == str(owner) and receipt["uncovered_source_kinds"] == [
            "artifact"
        ]


def test_customer_derived_reply_shares_a_link_and_rechecks_each_reader(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    hidden = artifact(setup, project, visibility="audience")
    thread_id = post_topic(setup, project, owner, f"{XIAOPAI} 客户反馈怎么说")["thread"]["id"]
    [row] = requests(setup, thread_id)
    finish(
        setup,
        row.run_id,
        "客户反馈：包装受潮。",
        read_sources=[hidden],
        categories=["customer_original", "internal"],
    )
    assert deliver(setup, row.id)["verdict"] == "private"
    mine = reply(setup, project, owner, thread_id, row.id)
    assert mine["customer_derived"] is True and mine["share_modes"] == ["link"]
    # P62-1: link only.
    share(setup, project, owner, thread_id, row.id, "body", acknowledged=True, expect=403)
    view = share(setup, project, owner, thread_id, row.id, "link")
    assert "包装" not in str(view)
    card = next(
        m for m in h.thread(setup, project, peer, thread_id)["messages"] if m["agent_request"]
    )
    assert card["agent_request"]["can_open_link"] is True
    # Each reader opens it under their own access, rechecked on every read.
    refused = reply(setup, project, peer, thread_id, row.id, expect=403)
    assert "没有权限" in refused["message"]
    with Session(setup.admin) as s, s.begin():
        s.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type="artifact_versions",
                subject_id=UUID(hidden["artifact_id"]),
                owner_id=owner,
                principal_id=peer,
            )
        )
    assert reply(setup, project, peer, thread_id, row.id)["body"] == "客户反馈：包装受潮。"


def test_people_who_cannot_see_the_object_neither_start_nor_read_and_retraction_rules(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    outsider = add_category_human(setup, name="合成品类成员")
    thread_id = post_topic(setup, project, peer, f"{XIAOPAI} 帮我列一下风险")["thread"]["id"]
    [row] = requests(setup, thread_id)

    # Outside the project audience: no post, no card, no reply.
    post(setup, project, outsider, thread_id, f"{XIAOPAI} 我也想问", expect=403)
    reply(setup, project, outsider, thread_id, row.id, expect=403)
    # “只给我看” needs @小Pai; an edit never starts a Run.
    post(setup, project, owner, thread_id, "随便说一句", private=True, expect=422)
    plain = post(setup, project, owner, thread_id, "先不 @")["messages"][-1]
    refused = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{thread_id}/messages/{plain['id']}/edit",
        headers=h.headers(setup, owner),
        json={"body": f"{XIAOPAI} 改成 @", "expected_revision": 1, "request_key": str(uuid4())},
    )
    assert refused.status_code == 422 and refused.json()["detail"]["reason"] == "agent_mention_edit"
    # The requester's own choice keeps a covered reply private.
    post(setup, project, owner, thread_id, f"{XIAOPAI} 只给我看就行", private=True)
    mine = requests(setup, thread_id)[-1]
    assert mine.private_only is True
    finish(setup, mine.run_id, "只给负责人的答复。")
    finish(setup, row.run_id, "风险：模具延期。")
    assert deliver(setup, mine.id)["verdict"] == "private"
    assert deliver(setup, row.id)["verdict"] == "public"
    with Session(setup.admin) as s:
        assert s.get(DiscussionAgentRequest, mine.id).reason == "private_only"

    # Retraction of a 小Pai reply: its requester or the project owner (P54-3).
    view = h.thread(setup, project, owner, thread_id)
    public = next(m for m in view["messages"] if m["agent"] and m["agent"]["kind"] == "reply")
    assert public["can_retract"] is True  # the owner
    path = h.project_root(setup, project) + f"/discussions/{thread_id}/messages/{public['id']}"
    edit = setup.client.post(
        path + "/edit",
        headers=h.headers(setup, owner),
        json={"body": "改写", "expected_revision": 1, "request_key": str(uuid4())},
    )
    assert edit.status_code == 403
    third = add_category_human(setup, name="合成第三人")
    assert (
        setup.client.post(
            path + "/retract",
            headers=h.headers(setup, third),
            json={"expected_revision": 1, "request_key": str(uuid4())},
        ).status_code
        == 403
    )
    key = str(uuid4())
    done = setup.client.post(
        path + "/retract",
        headers=h.headers(setup, owner),
        json={"expected_revision": 1, "request_key": key},
    )
    assert done.status_code == 200, done.text
    again = setup.client.post(
        path + "/retract",
        headers=h.headers(setup, owner),
        json={"expected_revision": 1, "request_key": key},
    )
    assert again.status_code == 200, again.text  # same request, same result
    retracted = next(m for m in done.json()["messages"] if m["id"] == public["id"])
    assert retracted["retracted"] and retracted["placeholder"] == "已撤回"


def test_agent_identity_has_no_direct_write(setup):
    project = create_g0_project(setup, visibility="private")
    owner = setup.human
    thread_id = post_topic(setup, project, owner, f"{XIAOPAI} 说一下")["thread"]["id"]
    [row] = requests(setup, thread_id)
    finish(setup, row.run_id, "回复")

    with Session(setup.admin) as s:
        for role in ("pdos_agent", "pdos_next_auth", "pdos_next_dispatch"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not s.scalar(
                    text(
                        "SELECT has_table_privilege(:role, 'public.discussion_agent_requests', :p)"
                    ),
                    {"role": role, "p": privilege},
                ), (role, privilege)
        assert not s.scalar(
            text(
                "SELECT has_table_privilege('pdos_next_app', "
                "'public.discussion_agent_requests', 'UPDATE')"
            )
        )
        assert not s.scalar(
            text(
                "SELECT has_function_privilege('pdos_agent', "
                "'public.discussion_agent_deliver(uuid,uuid,text,text,jsonb,jsonb)', 'EXECUTE')"
            )
        )

    def as_agent():
        return tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=owner,
            category_id=setup.category,
        )

    thread = UUID(thread_id)
    # 小Pai as actor cannot insert a message, even with the delivery setting forged.
    with pytest.raises(DBAPIError), as_agent() as s:
        s.execute(
            text("SELECT set_config('pdos.discussion_agent_settle', :r, true)"), {"r": str(row.id)}
        )
        s.add(
            DiscussionMessage(
                tenant_id=setup.tenant,
                thread_id=thread,
                sequence=2,
                author_id=setup.agent,
                revision=1,
                state="posted",
                body="伪造",
                mentions=[],
                subject_revision=None,
                updated_at=datetime.now(UTC),
                change_seq=0,
                request_key=uuid4(),
                request_sha256="0" * 64,
            )
        )
        s.flush()
    # A human cannot post as 小Pai either.
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=owner,
            requester_id=owner,
            category_id=setup.category,
        ) as s,
    ):
        s.add(
            DiscussionMessage(
                tenant_id=setup.tenant,
                thread_id=thread,
                sequence=2,
                author_id=setup.agent,
                revision=1,
                state="posted",
                body="伪造",
                mentions=[],
                subject_revision=None,
                updated_at=datetime.now(UTC),
                change_seq=0,
                request_key=uuid4(),
                request_sha256="0" * 64,
            )
        )
        s.flush()
    # The delivery refuses anyone but the bound writer for the bound requester.
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=owner,
            requester_id=owner,
            category_id=setup.category,
        ) as s,
    ):
        s.execute(
            text("SELECT discussion_agent_deliver(:t, :r, 'public', NULL, '{}'::jsonb, NULL)"),
            {"t": setup.tenant, "r": row.id},
        )
    # The body is the Run's own summary; the caller cannot supply one.
    with as_agent() as s:
        s.execute(
            text("SELECT discussion_agent_deliver(:t, :r, 'public', NULL, '{}'::jsonb, NULL)"),
            {"t": setup.tenant, "r": row.id},
        )
    view = h.thread(setup, project, owner, thread_id)
    assert view["messages"][-1]["body"] == "回复"
    # Settled requests do not change again, not even through the delivery function.
    with as_agent() as s:
        s.execute(
            text("SELECT discussion_agent_deliver(:t, :r, 'private', 'x', '{}'::jsonb, NULL)"),
            {"t": setup.tenant, "r": row.id},
        )
    with Session(setup.admin) as s:
        assert s.get(DiscussionAgentRequest, row.id).delivery == "public"


def test_proactive_mention_reaches_a_person_once_per_cooldown(setup):
    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    outsider = add_category_human(setup, name="合成品类成员")

    def mention(recipient, reason, **latest):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=owner,
            category_id=setup.category,
        ) as s:
            ctx = Context(setup.tenant, setup.agent, owner, category_id=setup.category)
            return agent_mentions.notify(
                s,
                ctx,
                recipient,
                reason,
                project_id=project.project_id,
                kind="project",
                subject_id=project.project_id,
                latest=latest,
            )

    assert mention(peer, "agent.needs_info") is not None
    assert mention(peer, "agent.needs_info") is None  # same object, same reason
    assert mention(peer, "agent.rule_exception", rule_owner_id=str(owner)) is not None
    assert mention(outsider, "agent.needs_info") is None  # cannot see the project
    assert mention(owner, "agent.needs_info") is None  # the requester themself
    inbox = h.notes(setup, peer)
    reasons = sorted((n["category"], n["reason"], n["signature"]) for n in inbox["items"])
    assert reasons == [
        ("agent", "agent.needs_info", None),
        ("agent", "agent.rule_exception", "小Pai · 按Synthetic owner的规则"),
    ]
    # Read does not reopen it; only the end of the cooldown does.
    h.note_state(setup, peer, "read_all")
    assert mention(peer, "agent.needs_info") is None
    h.age_notifications(setup, peer, minutes=60 * 24 * 4)
    assert mention(peer, "agent.needs_info") is not None
    # Only 小Pai mentions proactively.
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=owner,
            requester_id=owner,
            category_id=setup.category,
        ) as s,
    ):
        agent_mentions.notify(
            s,
            Context(setup.tenant, owner, owner, category_id=setup.category),
            peer,
            "agent.needs_info",
            project_id=project.project_id,
            kind="project",
            subject_id=project.project_id,
        )


def test_cooldown_is_one_working_day_before_the_work_calendar():
    day = timedelta(days=1).total_seconds()
    shanghai = timedelta(hours=8)
    monday = datetime(2026, 11, 9, 2, tzinfo=UTC)  # Monday 10:00 in Shanghai
    assert agent_mentions.cooldown_seconds(monday) == 3 * day
    assert agent_mentions.cooldown_seconds(monday + timedelta(days=1)) == day
    assert agent_mentions.cooldown_seconds(monday - timedelta(days=1)) == 2 * day  # Sunday
    assert agent_mentions.cooldown_seconds(monday - shanghai + timedelta(hours=1)) == 3 * day


class _Client:
    def __init__(self):
        self.started = []

    async def start_workflow(self, run, reference, *, id, task_queue, id_reuse_policy):
        self.started.append((reference, id))


def test_dispatcher_starts_one_delivery_per_ended_run(setup):
    import asyncio

    project = create_g0_project(setup, visibility="private")
    thread_id = post_topic(setup, project, setup.human, f"{XIAOPAI} 看一下")["thread"]["id"]
    [row] = requests(setup, thread_id)
    client = _Client()
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="q")
    )
    assert client.started == []  # the Run has not ended
    finish(setup, row.run_id, "", state="failed")
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="q")
    )
    assert client.started == [
        (
            {"tenant_id": str(setup.tenant), "request_id": str(row.id)},
            agent_delivery.workflow_id(setup.tenant, row.id),
        )
    ]
    # A failed Run settles without any message; the card says so.
    assert deliver(setup, row.id)["verdict"] == "none"
    view = h.thread(setup, project, setup.human, thread_id)
    assert len(view["messages"]) == 1
    card = view["messages"][0]["agent_request"]
    assert card["label"] == "失败" and card["reason"] == "run_failed"
    client.started.clear()
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="q")
    )
    assert client.started == []


def test_thread_content_reaches_the_model_context_as_a_dynamic_field(setup):
    """The registered host appends the frozen thread after the fixed prefix; no memory."""
    from pdos_next.agent.kernel.bootstrap import Bootstrap
    from pdos_next.agent.kernel.host import BoundHost

    project = create_g0_project(setup, visibility="private")
    started = post_topic(setup, project, setup.human, "先说背景：模具延期两天")
    thread_id = started["thread"]["id"]
    post(setup, project, setup.peer, thread_id, f"{XIAOPAI} 延期影响哪些任务")
    [row] = requests(setup, thread_id)
    owner = Bootstrap(setup.engine)
    scope = owner.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.peer,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=row.run_id,
    )
    envelope = BoundHost(owner.store, owner.adapters()).skill_context(
        scope, "延期影响哪些任务", bindings=()
    )
    thread = envelope["context"]["discussion_thread"]
    assert [item["author"] for item in thread["messages"]] == ["Synthetic owner", "Synthetic peer"]
    assert thread["requested_by"] == "Synthetic peer" and thread["thread"]["kind"] == "项目讨论"
    assert "memory" not in envelope["context"] and "personal_memory" not in envelope["context"]
    assert envelope["omitted_fields"] == []


from projects.discussions_pg.test_handover_and_tasks import _task, private_work  # noqa: E402,F401
from projects.work_pg.test_workflow import original_security_work  # noqa: E402,F401


def test_xiaopai_assignment_reaches_the_assignee_once_per_cooldown(private_work):  # noqa: F811
    """§7.4 第 1 种 with P53: the assignee hears; the requester and owner do not."""
    from types import SimpleNamespace

    from pdos_next.domain.projects.work import notify
    from pdos_next.domain.projects.work.constants import ASSIGN

    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    task_id = _task(work)
    ctx = Context(
        setup.tenant, setup.agent, owner, category_id=setup.category, agent_run_id=uuid4()
    )

    def assign(revision):
        row = SimpleNamespace(
            project_id=work.project_id,
            task_id=task_id,
            revision=revision,
            state="assigned",
            body={"assignee_id": str(peer), "recipient_id": str(owner)},
        )
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=owner,
            category_id=setup.category,
        ) as s:
            notify.after_task(s, ctx, ASSIGN, row)

    assign(2)
    assign(3)  # 小Pai assigns the same task to the same person again
    inbox = h.notes(setup, peer)["items"]
    assert [(n["category"], n["reason"], n["event_count"]) for n in inbox] == [
        ("assigned", "task.assigned", 1)
    ]
    assert h.notes(setup, owner)["items"] == []


def _wait(setup, run_id, sequence):
    """Test-only stand-in for the graph pausing on a question (no model is called)."""
    with Session(setup.admin) as s, s.begin():
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(update(AgentRun).where(AgentRun.id == run_id).values(state="waiting_input"))
        s.add(
            AgentEvent(
                tenant_id=setup.tenant,
                run_id=run_id,
                sequence=sequence,
                body={
                    "type": "needs_input",
                    "questions": [{"id": "q", "question": "私密问题原文"}],
                },
            )
        )


def test_missing_information_mentions_the_person_bound_from_the_object(private_work):  # noqa: F811
    """P105: a task thread reaches its assignee or owner, with a link and no question."""
    import asyncio

    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    task_id = _task(work)
    project = work.g0
    h.comment(setup, project, peer, "work_task", task_id, f"{XIAOPAI} 这项要哪些资料")
    with Session(setup.admin) as s:
        row = s.scalar(
            select(DiscussionAgentRequest).where(DiscussionAgentRequest.requester_id == peer)
        )
    topic = post_topic(setup, project, peer, f"{XIAOPAI} 项目层面的问题")["thread"]["id"]
    [project_row] = requests(setup, topic)
    _wait(setup, row.run_id, 2)
    _wait(setup, project_row.run_id, 2)

    client = _Client()
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="q")
    )
    waits = sorted((ref["request_id"], ref.get("wait")) for ref, _ in client.started)
    assert waits == sorted([(str(row.id), 2), (str(project_row.id), 2)])
    for reference, _ in client.started:
        agent_delivery.execute(setup.engine, setup.dispatch, reference)
    # The task has no assignee: its owner hears; nobody else, and never the question.
    inbox = h.notes(setup, owner)["items"]
    assert [
        (n["category"], n["reason"], n["title"], n["snippet"])
        for n in inbox
        if n["category"] == "agent"
    ] == [("agent", "agent.needs_info", "任务「合成样机图纸」的评论", None)]
    assert "私密问题原文" not in str(inbox)
    assert [n for n in h.notes(setup, peer)["items"] if n["category"] == "agent"] == []
    # The same wait is not repeated; a new question within the cooldown is marked only.
    client.started.clear()
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="q")
    )
    assert client.started == []
    _wait(setup, row.run_id, 3)
    reference = {"tenant_id": str(setup.tenant), "request_id": str(row.id), "wait": 3}
    assert agent_delivery.execute(setup.engine, setup.dispatch, reference)["state"] == "marked"
    assert len(h.notes(setup, owner, category="agent")["items"]) == 1
