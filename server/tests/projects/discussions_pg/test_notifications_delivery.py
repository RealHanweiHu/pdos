"""Notification state (D73 稍后提醒), digest, live delivery (D74 SSE + 30 s polling) and
comments under a customer-private document, including the project export (D279).
"""

from datetime import timedelta
from uuid import UUID

from g0_fixture import create_g0_project
from sqlalchemy import text
from sqlalchemy.orm import Session

from pdos_next.core.clock import now
from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context
from pdos_next.domain.my_work.notifications import api as notification_api
from projects.discussions_pg import helpers as h
from projects.test_project_first_plan import cmd, post


def _mentioned(setup, project, times=1):
    topic = h.start_topic(setup, project, setup.human, "供应商沟通", "开始")
    for index in range(times):
        h.reply(
            setup,
            project,
            setup.human,
            topic["thread"]["id"],
            f"{h.mention(setup.peer, 'Synthetic peer')} 第 {index + 1} 次",
        )
    return topic


def test_snooze_returns_unread_and_digest_holds_follow_changes(setup):
    project = create_g0_project(setup, visibility="private")
    peer = setup.peer
    _mentioned(setup, project)
    [note] = h.notes(setup, peer)["items"]
    # D73: 稍后提醒 hides it until then, then it comes back unread.
    past_limit = h.note_state(
        setup, peer, "snooze", [note["id"]], snooze_until=(now() + timedelta(days=31)).isoformat()
    )
    assert past_limit.status_code == 422
    snoozed = h.note_state(
        setup, peer, "snooze", [note["id"]], snooze_until=(now() + timedelta(hours=3)).isoformat()
    )
    assert snoozed.status_code == 200, snoozed.text
    assert h.notes(setup, peer)["items"] == []
    assert h.notes(setup, peer)["unread"]["mention"] == 0
    assert [n["id"] for n in h.notes(setup, peer, view="snoozed")["items"]] == [note["id"]]
    before = h.notes(setup, peer)["cursor"]
    # A new mention while snoozed opens a fresh row instead of merging into the hidden one.
    h.reply(
        setup,
        project,
        setup.human,
        h.notes(setup, peer, view="snoozed")["items"][0]["thread_id"],
        f"{h.mention(peer, 'Synthetic peer')} 补充",
    )
    assert len(h.notes(setup, peer)["items"]) == 1
    with Session(setup.admin) as s, s.begin():
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(
            text("UPDATE notifications SET snoozed_until=now()-interval '1 minute' WHERE id=:id"),
            {"id": UUID(note["id"])},
        )
    back = h.notes(setup, peer)
    assert {n["id"] for n in back["items"]} >= {note["id"]}
    assert all(not n["read"] for n in back["items"])
    assert back["cursor"] != before  # the due snooze moves the live cursor
    # Archive and restore; read-all for one category.
    assert h.note_state(setup, peer, "archive", [note["id"]]).status_code == 200
    assert [n["id"] for n in h.notes(setup, peer, view="archived")["items"]] == [note["id"]]
    assert h.note_state(setup, peer, "restore", [note["id"]]).status_code == 200
    done = h.note_state(setup, peer, "read_all", category="mention")
    assert done.status_code == 200 and h.notes(setup, peer)["unread"]["mention"] == 0
    # Someone else's notification cannot be touched.
    other = h.note_state(setup, setup.human, "read", [note["id"]])
    assert other.status_code == 403

    # Digest: follow changes go to the daily digest (unread only), mentions stay instant.
    saved = setup.client.post(
        "/v1/personal/notification-preferences",
        headers=h.headers(setup, setup.human),
        json={
            "project_id": project.project_id,
            "level": "all",
            "muted": False,
            "digest": True,
            "expected_revision": 0,
        },
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    stale = setup.client.post(
        "/v1/personal/notification-preferences",
        headers=h.headers(setup, setup.human),
        json={
            "project_id": project.project_id,
            "level": "all",
            "muted": False,
            "digest": True,
            "expected_revision": 0,
        },
    )
    assert stale.status_code == 409
    thread_id = note["thread_id"]
    h.reply(setup, project, peer, thread_id, "收到")
    assert h.notes(setup, setup.human)["items"] == []
    digest = h.notes(setup, setup.human, view="digest")["items"]
    assert [(n["category"], n["delivery"]) for n in digest] == [("follow", "digest")]
    h.note_state(setup, setup.human, "read", [digest[0]["id"]])
    assert h.notes(setup, setup.human, view="digest")["items"] == []


def _events(lines, wanted):
    """Read the next `wanted` event names from one shared line iterator."""
    seen = []
    for line in lines:
        if line.startswith("event: "):
            seen.append(line[7:])
            if len(seen) >= wanted:
                break
    return seen


def test_sse_stream_and_thirty_second_polling_fallback(setup, monkeypatch):
    project = create_g0_project(setup, visibility="private")
    peer = setup.peer
    monkeypatch.setitem(notification_api.STREAM, "interval", 0.05)
    monkeypatch.setitem(notification_api.STREAM, "lifetime", 1.0)
    stream = "/v1/personal/notifications/stream"
    with setup.client.stream("GET", stream, headers=h.headers(setup, peer)) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert _events(response.iter_lines(), 1) == ["ready"]
    first = setup.client.get(
        "/v1/personal/notifications/changes", headers=h.headers(setup, peer)
    ).json()
    assert first["poll_seconds"] == 30 and first["changed"] is True
    since = first["cursor"]
    unchanged = setup.client.get(
        "/v1/personal/notifications/changes",
        headers=h.headers(setup, peer),
        params={"since": since},
    ).json()
    assert unchanged["changed"] is False
    topic = _mentioned(setup, project)
    # Polling fallback sees the change; the stream resumes and reports the gap at once.
    after = setup.client.get(
        "/v1/personal/notifications/changes",
        headers=h.headers(setup, peer),
        params={"since": since, "threads": topic["thread"]["id"]},
    ).json()
    assert after["changed"] is True and after["threads"][topic["thread"]["id"]] != "0"
    with setup.client.stream(
        "GET", stream, headers={**h.headers(setup, peer), "Last-Event-ID": since}
    ) as response:
        assert _events(response.iter_lines(), 2) == ["ready", "changed"]
    # A thread the reader cannot see never yields a token.
    outsider = setup.client.get(
        "/v1/personal/notifications/changes",
        headers=h.headers(setup, setup.other_human),
        params={"threads": topic["thread"]["id"]},
    )
    assert outsider.status_code in {200, 401}
    if outsider.status_code == 200:
        assert outsider.json()["threads"] == {}
    # The stream re-checks the session on every poll and closes once it ends. (The test
    # client buffers a whole stream, so the second check is made to fail directly.)
    from pdos_next.core.accounts import sign_in

    checks = []

    def ended_after_first(engine, token):
        checks.append(token)
        return len(checks) == 1

    with monkeypatch.context() as patch:
        patch.setattr(sign_in, "peek", ended_after_first)
        with setup.client.stream("GET", stream, headers=h.headers(setup, peer)) as response:
            assert _events(response.iter_lines(), 2) == ["ready", "closed"]
    # The check itself never counts as activity, so an open tab cannot defeat the idle timeout.
    from pdos_next.core.models import LoginSession
    from pdos_next.core.service import digest

    with Session(setup.admin) as s:
        seen = s.get(LoginSession, digest(setup.tokens[peer])).last_seen_at
    assert sign_in.peek(setup.auth, setup.tokens[peer]) is True
    with Session(setup.admin) as s, s.begin():
        row = s.get(LoginSession, digest(setup.tokens[peer]))
        assert row.last_seen_at == seen
        row.revoked = True
    assert sign_in.peek(setup.auth, setup.tokens[peer]) is False
    bad = setup.client.get(
        "/v1/personal/notifications/changes",
        headers=h.headers(setup, setup.human),
        params={"since": "x;drop"},
    )
    assert bad.status_code == 422


def test_customer_private_document_comments_follow_its_audience(setup):
    from pdos_next.domain.exports import views as export_views
    from pdos_next.domain.projects.discussions import service as discussions

    project = create_g0_project(setup, visibility="private")
    owner, peer = setup.human, setup.peer
    registered = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "合成客户输入（私有）",
                "content": "客户私有规格：仅负责人可见",
                "source_label": "本地合成样例",
                "visibility": "private",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    artifact_id = registered.json()["subject_id"]
    shared = h.start_topic(setup, project, owner, "公开讨论", "项目内都能看")
    first = h.comment(setup, project, owner, "artifact", artifact_id, "客户这条规格要再核对")
    assert first["subject"]["visibility"] == "private"
    # The peer is on the project but not in the document's audience (K5, I21).
    h.comments(setup, project, peer, "artifact", artifact_id, expect=403)
    h.thread(setup, project, peer, first["thread"]["id"], expect=403)
    refused = setup.client.post(
        h.project_root(setup, project) + f"/comments/artifact/{artifact_id}",
        headers=h.headers(setup, owner),
        json={"body": f"{h.mention(peer, 'Synthetic peer')} 看下", "request_key": str(UUID(int=9))},
    )
    assert (
        refused.status_code == 422 and refused.json()["detail"]["reason"] == "mention_not_visible"
    )

    def exported(person):
        ctx = Context(setup.tenant, person, person, category_id=setup.category)
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=person,
            category_id=setup.category,
            read_snapshot=True,
        ) as s:
            rows = discussions.export_rows(s, ctx, UUID(project.project_id))
            view = export_views.project(s, ctx, UUID(project.product_id), UUID(project.project_id))
        return rows, view

    owner_rows, owner_view = exported(owner)
    peer_rows, peer_view = exported(peer)
    assert {row["thread"] for row in owner_rows} == {
        "项目讨论：公开讨论",
        "文档：合成客户输入（私有）",
    }
    assert {row["thread"] for row in peer_rows} == {"项目讨论：公开讨论"}
    sheets = {sheet.name: sheet for sheet in owner_view.sheets}
    assert len(sheets["讨论与评论"].rows) == 2
    assert len({sheet.name: sheet for sheet in peer_view.sheets}["讨论与评论"].rows) == 1
    # Retracted content exports only as the placeholder (P41-7).
    message = shared["messages"][0]
    retracted = setup.client.post(
        h.project_root(setup, project)
        + f"/discussions/{shared['thread']['id']}/messages/{message['id']}/retract",
        headers=h.headers(setup, owner),
        json={"expected_revision": 1, "request_key": str(UUID(int=11))},
    )
    assert retracted.status_code == 200
    rows, _ = exported(peer)
    assert [(row["body"], row["state"]) for row in rows] == [("已撤回", "已撤回")]
