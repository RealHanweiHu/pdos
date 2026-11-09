"""Task comments, work notifications and the P56 handover lane over real work commands (D37 ⑤).

One private G0 project: the owner assigns a task to the peer, who accepts and
starts it. Removing the peer then follows P56 end to end:
移出 → 交接期（只见本人未交接事项，可评论、可提交）→ 负责人验收 → 自动完全移出 → 零可见.
"""

# ruff: noqa: F811

from types import SimpleNamespace
from uuid import UUID

import pytest
from g0_fixture import add_category_human, create_g0_project
from sqlalchemy import select
from sqlalchemy.orm import Session
from team_fixture import remove_member

from pdos_next.core.database import tenant_session
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.team.models import ProjectMember
from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN, CREATE, REVIEW, START, SUBMIT
from pdos_next.domain.projects.work.models import WorkTaskCurrent
from projects.discussions_pg import helpers as h
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import original_security_work  # noqa: F401


@pytest.fixture
def private_work(request):
    """The work-loop fixture on a private project whose team is owner + peer (P55)."""
    from hashlib import sha256

    from originals.test_original_security import parsed, uploaded

    security = request.getfixturevalue("original_security_work")
    setup = security.setup
    prior_client = setup.client
    setup.client = security.client
    try:
        project = create_g0_project(
            setup, visibility="private", name="Synthetic private work", purpose="P56 handover"
        )
        original_id = uploaded(
            security, content=(flow.SOURCE_LINE + "\n").encode(), visibility="category"
        )
        artifact_id = parsed(security, original_id)
        source = {
            "kind": "artifact",
            "id": str(artifact_id),
            "revision": 1,
            "position": "line:1;quote_sha256:" + sha256(flow.SOURCE_LINE.encode()).hexdigest(),
        }
        yield SimpleNamespace(
            setup=setup,
            project_id=UUID(project.project_id),
            original_id=original_id,
            source=source,
            security=security,
            task_id=None,
            g0=project,
            artifact_id=artifact_id,
        )
    finally:
        setup.client = prior_client


def _send(work, operation, value, *, actor):
    """inputs → preview → command, without reading back as the actor (they may be in handover)."""
    command, _ = flow.inputs(work, operation, value, actor=actor)
    if operation != CREATE:
        command = flow.preview(work, command, actor=actor)
    response = flow.send(work, command, actor=actor)
    assert response.status_code == 200, response.text
    return response.json()


def _task(work, title="合成样机图纸"):
    created = _send(
        work,
        CREATE,
        flow.payload(
            work,
            title=title,
            goal="交付可核对的图纸",
            outcomes=[{"key": "drawing", "text": "图纸", "required": True}],
            plan_task=None,
        ),
        actor=work.setup.human,
    )
    work.task_id = UUID(created["result"]["task_id"])
    return work.task_id


def _sees(setup, person, model, identity):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=person, category_id=setup.category
    ) as s:
        return s.get(model, identity) is not None


def test_task_comments_anchor_versions_and_work_notifications(private_work):
    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    task_id = _task(work)
    project = work.g0

    first = h.comment(setup, project, owner, "work_task", task_id, "先确认图纸版本")
    assert first["subject"]["revision"] == 1 and first["messages"][0]["subject_revision"] == 1
    _send(
        work,
        ASSIGN,
        flow.payload(
            work, task=flow.task(work, "proposed"), assignee_id=str(peer), recipient_id=str(owner)
        ),
        actor=owner,
    )
    # 分派给我: the assignee hears once, and now follows the task.
    peer_inbox = h.notes(setup, peer)["items"]
    assert [(n["category"], n["reason"], n["title"]) for n in peer_inbox] == [
        ("assigned", "task.assigned", "合成样机图纸")
    ]
    assert h.notes(setup, owner)["items"] == []
    second = h.comment(setup, project, peer, "work_task", task_id, "收到，按 v2 出图")
    # The comment records the task version it was written against (P41-6).
    assert [m["subject_revision"] for m in second["messages"]] == [1, 2]
    assert second["subject"]["revision"] == 2
    # The owner follows the task (created + commented), so a follow change arrives.
    assert [(n["category"], n["reason"]) for n in h.notes(setup, owner)["items"]] == [
        ("follow", "comment")
    ]
    _send(work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=peer)
    _send(
        work,
        START,
        flow.payload(work, task=flow.task(work, "accepted"), **flow.clock_fields()),
        actor=peer,
    )
    # Changes to the same task within 10 minutes merge into one follow notification.
    owner_follow = [n for n in h.notes(setup, owner)["items"] if n["subject_kind"] == "work_task"]
    assert len(owner_follow) == 1 and owner_follow[0]["event_count"] == 2
    assert owner_follow[0]["reason"] == "task.started"
    _send(
        work,
        SUBMIT,
        flow.payload(
            work,
            task=flow.task(work, "in_progress"),
            **flow.clock_fields(),
            results=[
                {"key": "drawing", "text": "图纸 v2", "status": "present", "sources": [work.source]}
            ],
        ),
        actor=peer,
    )
    decide = [n for n in h.notes(setup, owner)["items"] if n["category"] == "decide"]
    assert [(n["reason"], n["reason_label"]) for n in decide] == [
        ("task.submitted", "提交了成果，等你验收")
    ]

    # The level and mute settings only filter follow changes; decisions still arrive.
    pref = setup.client.post(
        "/v1/personal/notification-preferences",
        headers=h.headers(setup, peer),
        json={
            "project_id": str(work.project_id),
            "level": "mentions",
            "muted": True,
            "digest": False,
            "expected_revision": 0,
        },
    )
    assert pref.status_code == 200, pref.text
    assert pref.json()["muted"] is True and pref.json()["mute_scope"] == "follow_only"
    before = len(h.all_notifications(setup, peer))
    h.comment(setup, project, owner, "work_task", task_id, "收到成果，正在看")
    assert len(h.all_notifications(setup, peer)) == before
    h.comment(
        setup,
        project,
        owner,
        "work_task",
        task_id,
        f"{h.mention(peer, 'Synthetic peer')} 第 3 页尺寸？",
    )
    assert h.notes(setup, peer)["items"][0]["category"] == "mention"


def test_p56_handover_lane_to_zero_visibility(private_work):
    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    project = work.g0
    task_id = _task(work, "合成交接任务")
    other_task = _task(work, "合成他人任务")
    work.task_id = task_id
    _send(
        work,
        ASSIGN,
        flow.payload(
            work, task=flow.task(work, "proposed"), assignee_id=str(peer), recipient_id=str(owner)
        ),
        actor=owner,
    )
    _send(work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=peer)
    _send(
        work,
        START,
        flow.payload(work, task=flow.task(work, "accepted"), **flow.clock_fields()),
        actor=peer,
    )
    topic = h.start_topic(setup, project, owner, "交接前的讨论", "项目讨论内容")
    h.comment(setup, project, owner, "work_task", other_task, "他人任务的评论")
    h.comment(setup, project, owner, "work_task", task_id, "本人任务的评论")

    # 移出: membership ends now and so does the project audience (P56-1).
    departed = remove_member(setup, work.project_id, peer)
    assert departed["handover_pending"] is True
    assert departed["pending"] == {"tasks": 1, "commitments": 0, "external_waits": 0}
    assert [item["label"] for item in departed["pending_detail"]] == ["合成交接任务"]
    assert not _sees(setup, peer, Project, work.project_id)
    with tenant_session(setup.engine, setup.tenant, actor_id=peer, category_id=setup.category) as s:
        assert s.scalar(select(WorkTaskCurrent).where(WorkTaskCurrent.task_id == task_id)) is None
    workspace = setup.client.get(
        flow.root(work) + f"/project-work?project_id={work.project_id}",
        headers=h.headers(setup, peer),
    )
    assert workspace.status_code in {403, 404}

    # 交接期: project discussion and other objects are invisible; own items stay.
    h.topics(setup, project, peer, expect=403)
    h.thread(setup, project, peer, topic["thread"]["id"], expect=403)
    h.comments(setup, project, peer, "work_task", other_task, expect=403)
    own = h.comments(setup, project, peer, "work_task", task_id)
    assert [m["body"] for m in own["messages"]] == ["本人任务的评论"]
    assert own["full_project"] is False
    mine = setup.client.get("/v1/personal/handover", headers=h.headers(setup, peer))
    assert mine.status_code == 200, mine.text
    [entry] = mine.json()["items"]
    assert entry["project"]["name"] == "Synthetic private work"
    assert [(i["kind"], i["label"]) for i in entry["items"]] == [("work_task", "合成交接任务")]
    assert [t["title"] for t in entry["tasks"]] == ["合成交接任务"]
    # The owner can still mention the person on that task; not on the project topic.
    h.comment(
        setup, project, owner, "work_task", task_id, f"{h.mention(peer, 'Synthetic peer')} 请先提交"
    )
    assert any(n["category"] == "mention" for n in h.notes(setup, peer)["items"])
    blocked = setup.client.post(
        h.project_root(setup, project) + f"/discussions/{topic['thread']['id']}/messages",
        headers=h.headers(setup, owner),
        json={
            "body": f"{h.mention(peer, 'Synthetic peer')} 看这里",
            "request_key": str(UUID(int=7)),
        },
    )
    assert (
        blocked.status_code == 422 and blocked.json()["detail"]["reason"] == "mention_not_visible"
    )
    # Still able to handle the own item: comment and submit it.
    h.comment(setup, project, peer, "work_task", task_id, "已完成，提交成果")
    h.reply(setup, project, peer, topic["thread"]["id"], "试图在项目讨论发言", expect=403)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=owner, category_id=setup.category
    ) as s:
        started = s.scalar(select(WorkTaskCurrent).where(WorkTaskCurrent.task_id == task_id))
        ref = {"id": str(task_id), "revision": started.revision}
    _send(
        work,
        SUBMIT,
        flow.payload(
            work,
            task=ref,
            **flow.clock_fields(),
            results=[
                {
                    "key": "drawing",
                    "text": "交接前提交",
                    "status": "present",
                    "sources": [work.source],
                }
            ],
        ),
        actor=peer,
    )
    # Not a lane for anything else: the other task cannot be started by the peer.
    other_ref = {"id": str(other_task), "revision": 1}
    refused = setup.client.post(
        flow.root(work) + "/project-work/inputs",
        headers=h.headers(setup, peer),
        json=flow.cmd(
            setup,
            ASSIGN,
            flow.payload(work, task=other_ref, assignee_id=str(peer), recipient_id=str(owner)),
        ),
    )
    assert refused.status_code in {403, 404}, refused.text

    # 负责人验收 → handover complete → removal settles by itself (P56-2).
    _send(
        work,
        REVIEW,
        flow.payload(
            work,
            task=flow.task(work, "submitted"),
            decision="accepted",
            **flow.clock_fields(),
            checks=[{"key": "drawing", "decision": "accepted", "reason": "图纸齐全"}],
        ),
        actor=owner,
    )
    with Session(setup.admin) as s:
        stint = s.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == work.project_id, ProjectMember.principal_id == peer
            )
        )
        assert stint.left_at is not None and stint.handover_pending is False
    # 零可见: no lane, no comments, no handover entry, no notification.
    assert (
        setup.client.get("/v1/personal/handover", headers=h.headers(setup, peer)).json()["items"]
        == []
    )
    h.comments(setup, project, peer, "work_task", task_id, expect=403)
    assert h.notes(setup, peer)["items"] == []
    assert not _sees(setup, peer, Project, work.project_id)
    team = setup.client.get(
        h.project_root(setup, project) + "/team", headers=h.headers(setup, owner)
    )
    assert team.json()["departed"][0]["handover_pending"] is False
    # History keeps the departed person's name on what they said.
    authors = {
        m["author_name"]
        for m in h.comments(setup, project, owner, "work_task", task_id)["messages"]
    }
    assert authors == {"Synthetic owner", "Synthetic peer"}


def test_deactivated_member_leaves_a_handover_card_for_the_owner(private_work):
    from pdos_next.agent.kernel.models import TenantAdministrator

    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    admin = add_category_human(setup, name="合成管理员")
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=admin))
    task_id = _task(work, "停用前的任务")
    _send(
        work,
        ASSIGN,
        flow.payload(
            work, task=flow.task(work, "proposed"), assignee_id=str(peer), recipient_id=str(owner)
        ),
        actor=owner,
    )
    _send(work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=peer)
    stopped = setup.client.post(f"/v1/accounts/{peer}/deactivate", headers=h.headers(setup, admin))
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["handover_cards"] == 1
    # P56-3: the person loses all access; the owner gets a card listing what is left.
    assert (
        setup.client.get("/v1/personal/notifications", headers=h.headers(setup, peer)).status_code
        == 401
    )
    card = [n for n in h.notes(setup, owner)["items"] if n["subject_kind"] == "member_handover"]
    assert [(c["category"], c["title"], c["snippet"]) for c in card] == [
        ("decide", "Synthetic peer 的待接事项", "任务 1")
    ]
    team = setup.client.get(
        h.project_root(setup, work.g0) + "/team", headers=h.headers(setup, owner)
    ).json()
    member = next(m for m in team["members"] if m["principal_id"] == str(peer))
    assert member["active_person"] is False
    assert [item["label"] for item in member["pending_detail"]] == ["停用前的任务"]
    assert task_id
