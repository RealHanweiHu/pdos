"""M2b: notes on proposals and projects, customer tags, scope recency, departed authors.

Real proposals and a real G0-created project through the public commands; no
model or embedding calls (P87 第 2、5、7、9 项; AT-73).
"""

from datetime import timedelta
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.core.models import Grant, Principal, now
from tests.g0_fixture import add_category_human, create_g0_project, run_command
from tests.knowledge.scope_notes.support import (
    SAVE,
    anchor,
    body,
    commit,
    headers,
    item,
    listing,
    preview,
    save,
)


def private_proposal(setup, *, customers=()):
    created, _ = run_command(setup, "proposal.create", {
        "title": "Synthetic customer request", "entry_kind": "customer_request",
        "brief": "Scope note audience", "customer_identities": list(customers),
        "groups": {"items": [{"kind": "section",
                              "content": {"key": "worth_it", "text": "Synthetic"}}]},
    })
    return created["subject_id"]


def test_proposal_notes_follow_the_proposal_audience_and_its_customer_tags(setup):
    proposal = private_proposal(setup, customers=["客户A"])
    at = anchor(setup, "proposal", proposal)
    view = listing(setup, "proposal", proposal)
    assert view["customers"] == ["客户A"] and view["audience"]["kind"] == "restricted"
    saved = save(setup, "这家客户评审必问跌落测试", kind="concern", at=at, customer="客户A")
    note = item(setup, saved["subject_id"])["note"]
    assert note["tags"]["customer"] == "客户A" and note["sensitivity"] == "customer_private"
    assert note["anchor"]["kind"] == "proposal"
    # A customer tag the proposal does not carry is refused: tags are not free text here.
    unknown = preview(setup, SAVE, {"anchor": at, "body": body("别的客户的要求", customer="客户B")},
                      status=422)
    assert unknown["detail"]["reason_key"] == "scope_note_customer_unknown"
    # The peer has the category but is not in this private proposal's audience.
    assert listing(setup, "proposal", proposal, person=setup.peer, status=403)
    assert item(setup, saved["subject_id"], person=setup.peer, status=404)
    assert listing(setup, person=setup.peer)["notes"] == []


def test_project_notes_follow_the_project_audience_and_feed_scope_recency(setup):
    project = create_g0_project(setup, visibility="private", name="Synthetic pump project")
    at = anchor(setup, "project", project.project_id)
    saved = save(setup, "本项目样件编号按 项目-批次-序号", at=at, product=project.product_id)
    view = listing(setup, "project", project.project_id)
    assert [n["note_id"] for n in view["notes"]] == [saved["subject_id"]]
    assert view["anchor"]["product_id"] == project.product_id
    assert view["notes"][0]["anchor"]["title"] == "Synthetic pump project"
    # A command bound to another model cannot attach a note to this project.
    wrong = preview(setup, SAVE, {"anchor": at, "body": body("挂错型号的备忘")},
                    product=setup.category, status=403)
    assert wrong["code"] == "FORBIDDEN_SCOPE"
    # G0 put the reviewer in the private project's audience; another category member is not.
    assert len(listing(setup, "project", project.project_id, person=setup.peer)["notes"]) == 1
    outsider = add_category_human(setup)
    assert listing(setup, "project", project.project_id, person=outsider, status=403)
    assert item(setup, saved["subject_id"], person=outsider, status=404)
    assert listing(setup, person=outsider)["notes"] == []
    recent = setup.client.get(
        f"/v1/categories/{setup.category}/scope-recent/project/{project.project_id}",
        headers=headers(setup))
    assert recent.status_code == 200, recent.text
    value = recent.json()
    assert value["version"] == "scope-recent/v1" and value["zone"] == "background"
    assert value["scope"] == {"kind": "project", "title": "Synthetic pump project"}
    assert [(line["what"], line["note_id"]) for line in value["note_changes"]] == [
        ("新增约定", saved["subject_id"])]
    assert "样件编号" not in recent.text  # recency names changes, never note text
    assert all(set(line) >= {"at", "what"} for line in value["activity"])
    again = setup.client.get(
        f"/v1/categories/{setup.category}/scope-recent/project/{project.project_id}",
        headers=headers(setup)).json()
    assert {k: v for k, v in again.items() if k != "as_of"} == {
        k: v for k, v in value.items() if k != "as_of"}
    assert setup.client.get(
        f"/v1/categories/{setup.category}/scope-recent/project/{project.project_id}",
        headers=headers(setup, outsider)).status_code == 403


def test_review_duty_moves_to_the_object_owner_when_the_author_leaves(setup):
    """作者离开或被移出后，备忘保留，作者标“已离开”，复核责任转给对象负责人."""
    saved = save(setup, "周会纪要当天发出", person=setup.peer)
    note = item(setup, saved["subject_id"])["note"]
    assert note["author"]["id"] == str(setup.peer) and note["author"]["departed"] is False
    assert note["review_owner"]["id"] == str(setup.peer)
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.principal_id == setup.peer))
        grant.expires_at = now() - timedelta(minutes=1)
    moved = item(setup, saved["subject_id"])["note"]
    assert moved["state"] == "active" and moved["author"]["departed"] is True
    assert moved["review_owner"]["id"] == str(setup.human)  # the category owner
    with Session(setup.admin) as session, session.begin():
        session.get(Principal, setup.peer).active = False
    assert item(setup, saved["subject_id"])["note"]["author"]["departed"] is True
    assert [n["note_id"] for n in listing(setup)["notes"]] == [saved["subject_id"]]


def test_sharing_a_personal_note_is_the_owners_own_explicit_command(setup):
    """分享到项目: only the owner, only by this command; the personal note is untouched."""
    mine = setup.client.post("/v1/personal/memory/notes", headers=headers(setup), json={
        "request_key": str(uuid4()),
        "note": {"kind": "convention", "text": "对外报告先给结论", "scope": {"kind": "global"}}})
    assert mine.status_code == 200, mine.text
    personal = mine.json()["note"]["note_id"]
    stolen = preview(setup, SAVE, {"anchor": anchor(setup), "body": body("对外报告先给结论"),
                                   "shared_from_note": personal}, person=setup.peer, status=403)
    assert stolen["detail"]["reason_key"] == "scope_note_share_not_owner"
    receipt, _prepared = commit(setup, SAVE, {
        "anchor": anchor(setup), "body": body("对外报告先给结论"), "shared_from_note": personal})
    team = item(setup, receipt["subject_id"])["note"]
    assert team["statement"] == "对外报告先给结论" and team["generated_by"] == "human"
    # The team sees the new note; the personal note stays the owner's alone.
    assert len(listing(setup, person=setup.peer)["notes"]) == 1
    assert setup.client.get("/v1/personal/memory/notes",
                            headers=headers(setup, setup.peer)).json()["notes"] == []
    assert [n["note_id"] for n in setup.client.get(
        "/v1/personal/memory/notes", headers=headers(setup)).json()["notes"]] == [personal]


def test_a_product_scope_reuses_the_product_activity_list_and_others_carry_notes_only(setup):
    """D506: 范围近况 for a product reuses the product page's 实际活动 receipts."""
    from datetime import UTC, datetime

    from tests.categories.preproject.test_g0 import post, request

    project = create_g0_project(setup, visibility="category", name="Synthetic pump project")
    before = datetime.now(UTC)
    registered = request(setup, "evidence.artifact.register", {
        "title": "型号资料", "content": "RECENT-BODY-MARKER", "source_label": "合成",
        "visibility": "category"})
    registered["product_id"] = project.product_id
    assert post(setup, registered).status_code == 200
    save(setup, "型号资料以英文版为准", at=anchor(setup, "product", project.product_id),
         product=project.product_id)
    path = f"/v1/categories/{setup.category}/scope-recent/product/{project.product_id}"
    value = setup.client.get(path, headers=headers(setup)).json()
    assert value["scope"]["kind"] == "product" and value["activity"]
    assert value["activity"][0]["what"] == "evidence.artifact.register"
    assert value["activity"][0]["who"] == "Synthetic owner"
    assert not any(line["what"].startswith("scope_note.") for line in value["activity"])
    assert [line["what"] for line in value["note_changes"]] == ["新增约定"]
    assert "RECENT-BODY-MARKER" not in json.dumps(value, ensure_ascii=False)
    assert "英文版" not in json.dumps(value, ensure_ascii=False)
    # The watermark holds: nothing recorded after it is listed.
    from pdos_next.core.service import Context
    from pdos_next.core.database import tenant_session
    from pdos_next.domain.knowledge.scope_notes import reads, recent

    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category,
                        read_snapshot=True) as session:
        ctx = Context(setup.tenant, setup.human, setup.human, category_id=setup.category)
        found = reads.resolve(session, setup.tenant, "product", UUID(project.product_id))
        early = recent.build(session, ctx, found, as_of=before)
        assert all(line["what"] != "evidence.artifact.register" for line in early["activity"])
        assert early["note_changes"] == []
        # Category and proposal scopes have no activity feed to reuse: notes only.
        category = reads.resolve(session, setup.tenant, "category", setup.category)
        assert recent.build(session, ctx, category)["activity"] == []
        proposal = reads.resolve(session, setup.tenant, "proposal", UUID(project.proposal_id))
        assert recent.build(session, ctx, proposal)["activity"] == []
