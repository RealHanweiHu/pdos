"""M2b 范围条目 (P87; P121 第 3、4、6 项; AT-72–AT-74): commands, audience, history.

No model or embedding calls. Every write goes through the public preview/commit
command pair with the real roles and row-level security of the isolated
pdos_test database.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.core.database import tenant_session
from pdos_next.core.models import Product, Receipt
from pdos_next.domain.knowledge.scope_notes.models import (
    ScopeNote,
    ScopeNoteRelation,
    ScopeNoteVersion,
)
from tests.knowledge.scope_notes.support import (
    OBSERVE,
    RETIRE,
    SAVE,
    anchor,
    body,
    commit,
    envelope,
    headers,
    item,
    listing,
    preview,
    private_product,
    save,
)


def test_member_saves_a_note_with_one_confirmation_and_a_receipt(setup):
    prepared = preview(setup, SAVE, {"anchor": anchor(setup),
                                     "body": body("给该客户的报告一律英文")})
    review = prepared["review"]
    assert review["kind_label"] == "约定" and review["zone"] == "constraint"
    assert "品类成员都能看到" in review["audience"]["text"] and "不是业务事实" in review["note"]
    # Nothing is written before the person confirms.
    assert listing(setup)["notes"] == []
    unconfirmed = envelope(setup, SAVE, {"anchor": anchor(setup),
                                         "body": body("没有确认的备忘")})
    refused = setup.client.post(f"/v1/categories/{setup.category}/commands",
                                headers=headers(setup), json=unconfirmed)
    assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
    done = setup.client.post(f"/v1/categories/{setup.category}/commands",
                             headers=headers(setup), json=prepared["command"])
    assert done.status_code == 200, done.text
    receipt = done.json()
    assert receipt["operation"] == SAVE and receipt["subject_type"] == "scope_note"
    assert receipt["agent_run_id"] is None and "statement" not in str(receipt["result"])
    view = listing(setup)
    assert view["can_write"] is True and len(view["notes"]) == 1
    note = view["notes"][0]
    assert note["note_id"] == receipt["subject_id"] and note["revision"] == 1
    assert note["statement"] == "给该客户的报告一律英文" and note["zone"] == "constraint"
    assert note["state"] == "active" and note["flags"] == []
    assert note["confirmation"] == "member_confirmed" and note["generated_by"] == "human"
    assert note["source_authority"] == "human_statement"
    assert note["confirmed_by"]["id"] == str(setup.human) and not note["author"]["departed"]
    with Session(setup.admin) as session:
        row = session.scalar(select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id == receipt["subject_id"]))
        stored = session.get(Receipt, row.receipt_id)
    assert str(stored.id) == receipt["id"] and row.review_due_at > row.created_at


def test_four_kinds_and_only_a_convention_constrains(setup):
    save(setup, "本项目样件编号按 项目-批次-序号", kind="convention")
    save(setup, "客户 A 评审必问跌落测试", kind="concern")
    save(setup, "噪音放宽 3dB 是 10-12 电话里同意的", kind="decision_context")
    save(setup, "最近三批气嘴来料毛刺偏多", kind="observation")
    notes = {entry["kind"]: entry for entry in listing(setup)["notes"]}
    assert set(notes) == {"convention", "concern", "decision_context", "observation"}
    assert {kind: entry["zone"] for kind, entry in notes.items()} == {
        "convention": "constraint", "concern": "background", "decision_context": "background",
        "observation": "background"}
    # 决策背景 with no formal decision says so (P121 第 3 项).
    assert notes["decision_context"]["flags"] == ["no_formal_decision"]
    assert notes["decision_context"]["formal"] is None
    assert notes["decision_context"]["confirmation"] == "member_confirmed"


def test_decision_context_linked_to_a_formal_object_binds_its_version(setup):
    receipt = save(setup, "目标价口径按含税出厂价", kind="decision_context",
                   formal={"kind": "product", "id": str(setup.product)})
    note = item(setup, receipt["subject_id"])["note"]
    assert note["confirmation"] == "formal_linked" and note["flags"] == []
    assert note["formal"] == {"kind": "product", "id": str(setup.product), "version": 1,
                              "title": "Synthetic product", "updated": False}
    with Session(setup.admin) as session, session.begin():
        session.get(Product, setup.product).revision = 2
    moved = item(setup, receipt["subject_id"])["note"]
    assert moved["flags"] == ["object_updated"] and moved["formal"]["updated"] is True
    # A convention that points at an older object version drops to the background zone.
    pinned = save(setup, "规格书一律引用当前基线", kind="convention",
                  subject={"kind": "product", "id": str(setup.product)})
    assert item(setup, pinned["subject_id"])["note"]["zone"] == "constraint"
    with Session(setup.admin) as session, session.begin():
        session.get(Product, setup.product).revision = 3
    stale = item(setup, pinned["subject_id"])["note"]
    assert stale["flags"] == ["object_updated"] and stale["zone"] == "background"


def test_people_outside_the_attached_object_never_see_its_notes(setup):
    """AT-73: 范围外的人看不到；挂靠对象受众收窄后随之收窄."""
    hidden = private_product(setup)
    shared = save(setup, "品类口径：价格带按出厂价")
    private = save(setup, "这个型号的客户只收英文报告", at=anchor(setup, "product", hidden),
                   product=hidden)
    assert [n["note_id"] for n in listing(setup, "product", hidden)["notes"]] == [
        private["subject_id"]]
    # The peer has the category but not the private product.
    assert [n["note_id"] for n in listing(setup, person=setup.peer)["notes"]] == [
        shared["subject_id"]]
    assert listing(setup, "product", hidden, person=setup.peer, status=403)["detail"][
        "reason_key"] == "scope_note_anchor_unreadable"
    assert item(setup, private["subject_id"], person=setup.peer, status=404)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                        requester_id=setup.peer, category_id=setup.category) as session:
        assert session.scalars(select(ScopeNoteVersion.statement)).all() == [
            "品类口径：价格带按出厂价"]
        assert session.scalar(select(ScopeNote.id).where(
            ScopeNote.id == private["subject_id"])) is None
    # Another tenant sees nothing at all.
    assert listing(setup, person=setup.other_human, status=403)
    # Narrowing the object narrows its notes at once: no audience copy is stored.
    open_product = private_product(setup, visibility="category")
    visible = save(setup, "这个型号的样件先发深圳", at=anchor(setup, "product", open_product),
                   product=open_product)
    assert len(listing(setup, "product", open_product, person=setup.peer)["notes"]) == 1
    with Session(setup.admin) as session, session.begin():
        session.get(Product, open_product).visibility = "private"
    assert listing(setup, "product", open_product, person=setup.peer, status=403)
    assert item(setup, visible["subject_id"], person=setup.peer, status=404)
    assert len(listing(setup, "product", open_product)["notes"]) == 1


def test_a_member_without_write_permission_cannot_save(setup):
    from pdos_next.core.models import Grant

    with Session(setup.admin) as session, session.begin():
        session.scalar(select(Grant).where(Grant.principal_id == setup.peer)).can_write = False
    assert listing(setup, person=setup.peer)["can_write"] is False
    refused = preview(setup, SAVE, {"anchor": anchor(setup), "body": body("只读成员想记一条")},
                      person=setup.peer, status=403)
    assert refused["code"] == "FORBIDDEN_SCOPE"


def test_revise_keeps_history_and_identity_is_fixed(setup):
    first = save(setup, "评审材料提前两天发")
    note_id = first["subject_id"]
    payload = {"anchor": anchor(setup), "note": {"id": note_id, "revision": 1},
               "body": body("评审材料提前三个工作日发", pinned=True)}
    second, _ = commit(setup, SAVE, payload, person=setup.peer)
    assert second["subject_id"] == note_id and second["subject_revision"] == 2
    view = item(setup, note_id)
    assert view["note"]["statement"] == "评审材料提前三个工作日发" and view["note"]["pinned"]
    assert view["note"]["confirmed_by"]["id"] == str(setup.peer)
    assert view["note"]["author"]["id"] == str(setup.human)
    assert [(v["revision"], v["action"], v["statement"]) for v in view["versions"]] == [
        (2, "revise", "评审材料提前三个工作日发"), (1, "create", "评审材料提前两天发")]
    # A stale page cannot overwrite the newer version.
    stale = preview(setup, SAVE, {**payload, "body": body("过期页面的修改")}, status=409)
    assert stale["detail"]["reason_key"] == "scope_note_moved"
    fixed = preview(setup, SAVE, {"anchor": anchor(setup), "note": {"id": note_id, "revision": 2},
                                  "body": body("评审材料提前三个工作日发", kind="concern")},
                    status=422)
    assert fixed["detail"]["reason_key"] == "scope_note_identity_fixed"


def test_retire_and_withdraw_stop_use_but_never_delete(setup):
    kept = save(setup, "样件统一贴项目标签")
    wrong = save(setup, "客户接受 4.5 bar 上限", kind="concern")
    retired, _ = commit(setup, RETIRE, {"note": {"id": kept["subject_id"], "revision": 1},
                                        "action": "retire", "reason": "项目已结束"})
    assert retired["operation"] == RETIRE and retired["result"]["status"] == "retired"
    commit(setup, RETIRE, {"note": {"id": wrong["subject_id"], "revision": 1},
                           "action": "withdraw", "reason": "客户没有这样说过"},
           person=setup.peer)
    view = listing(setup)
    assert view["notes"] == [] and view["inactive_count"] == 2
    states = {n["note_id"]: (n["state"], n["reason"])
              for n in listing(setup, everything=True)["notes"]}
    assert states == {kept["subject_id"]: ("retired", "项目已结束"),
                      wrong["subject_id"]: ("withdrawn", "客户没有这样说过")}
    # Stopped notes can be read but not changed, and no row is ever removed or updated.
    again = preview(setup, RETIRE, {"note": {"id": kept["subject_id"], "revision": 2},
                                    "reason": "再停一次"}, status=409)
    assert again["detail"]["reason_key"] == "scope_note_inactive"
    with Session(setup.admin) as session:
        version = session.scalar(select(ScopeNoteVersion.id).where(
            ScopeNoteVersion.note_id == kept["subject_id"], ScopeNoteVersion.revision == 1))
    for statement in ("DELETE FROM scope_note_versions WHERE id=:id",
                      "UPDATE scope_note_versions SET statement='改写' WHERE id=:id"):
        with pytest.raises(DBAPIError), tenant_session(
                setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human,
                category_id=setup.category) as session:
            session.execute(text(statement), {"id": version})
    with Session(setup.admin) as session:
        assert len(session.scalars(select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id == kept["subject_id"])).all()) == 2


def test_similar_notes_must_be_resolved_and_supersede_follows_effective_time(setup):
    """P121 第 6 项: 替代按生效时间判断，补录的旧信息只进历史."""
    old = save(setup, "跌落测试高度按 1.0 米执行", valid_from="2026-06-01T00:00:00Z")
    unresolved = preview(setup, SAVE, {"anchor": anchor(setup),
                                       "body": body("跌落测试高度按 1.2 米执行")}, status=409)
    assert unresolved["detail"]["reason_key"] == "scope_note_similar_unresolved"
    assert [n["note_id"] for n in unresolved["detail"]["similar"]] == [old["subject_id"]]
    duplicate = preview(setup, SAVE, {"anchor": anchor(setup),
                                      "body": body("跌落测试高度按 1.0 米执行"),
                                      "request_ref": str(uuid4())}, status=409)
    assert duplicate["detail"]["reason_key"] == "scope_note_duplicate"
    newer = save(setup, "跌落测试高度按 1.2 米执行", valid_from="2026-09-01T00:00:00Z",
                 relations=[{"type": "supersedes",
                             "note": {"id": old["subject_id"], "revision": 1}}])
    replaced = item(setup, old["subject_id"])["note"]
    assert replaced["state"] == "superseded" and replaced["valid_to"].startswith("2026-09-01")
    assert item(setup, newer["subject_id"])["note"]["state"] == "active"
    # A backfilled older statement does not replace the current one: it only enters history.
    backfill = save(setup, "跌落测试高度曾按 0.8 米执行", valid_from="2026-01-01T00:00:00Z",
                    relations=[{"type": "supersedes",
                                "note": {"id": newer["subject_id"], "revision": 1}}])
    assert backfill["result"]["action"] == "backfill"
    past = item(setup, backfill["subject_id"])["note"]
    assert past["state"] == "superseded" and past["valid_to"].startswith("2026-09-01")
    assert item(setup, newer["subject_id"])["note"]["state"] == "active"
    assert [n["note_id"] for n in listing(setup)["notes"]] == [newer["subject_id"]]
    with Session(setup.admin) as session:
        links = {(str(r.from_note_id), str(r.to_note_id)) for r in session.scalars(
            select(ScopeNoteRelation).where(ScopeNoteRelation.type == "supersedes",
                                            ScopeNoteRelation.tenant_id == setup.tenant))}
    assert links == {(newer["subject_id"], old["subject_id"]),
                     (newer["subject_id"], backfill["subject_id"])}


def test_conflict_is_a_relation_and_both_drop_to_background(setup):
    first = save(setup, "外箱唛头只印英文")
    second = save(setup, "外箱唛头中英文都印",
                  relations=[{"type": "conflicts",
                              "note": {"id": first["subject_id"], "revision": 1}}])
    for note_id in (first["subject_id"], second["subject_id"]):
        note = item(setup, note_id)["note"]
        assert note["state"] == "active" and note["flags"] == ["disputed"]
        assert note["zone"] == "background"
    third = save(setup, "外箱唛头按客户订单语言印", kept=[first["subject_id"],
                                                 second["subject_id"]])
    assert item(setup, third["subject_id"])["note"]["zone"] == "constraint"


def test_verified_needs_a_business_record_or_two_independent_sources(setup):
    one = [{"source_type": "business_object", "source_kind": "product",
            "source_id": str(setup.product), "quote": "目标价含税"}]
    refused = preview(setup, SAVE, {"anchor": anchor(setup),
                                    "body": body("目标价按含税口径", epistemic="verified")},
                      status=422)
    assert refused["detail"]["reason_key"] == "scope_note_verified_requires_sources"
    receipt = save(setup, "目标价按含税口径", epistemic="verified", evidence=one)
    view = item(setup, receipt["subject_id"])["note"]
    assert view["epistemic"] == "verified" and view["source_authority"] == "business_record"
    assert view["evidence"] == [{
        **view["evidence"][0], "source_type": "business_object", "source_kind": "product",
        "source_version": 1, "has_quote": True, "stance": "supports", "by_xiaopai": False}]
    # The quoted passage itself is never stored.
    with Session(setup.admin) as session:
        assert session.scalar(text(
            "SELECT count(*) FROM scope_note_evidence WHERE to_jsonb(scope_note_evidence)::text "
            "LIKE '%目标价含税%'")) == 0
    unreadable = preview(setup, SAVE, {
        "anchor": anchor(setup), "body": body("引用了读不到的对象"),
        "evidence": [{"source_type": "business_object", "source_kind": "product",
                      "source_id": str(uuid4())}]}, status=403)
    assert unreadable["detail"]["reason_key"] == "scope_note_object_unreadable"


@pytest.mark.parametrize("table", ["scope_notes", "scope_note_versions", "scope_note_evidence"])
def test_ai_identity_cannot_write_scope_note_tables_directly(setup, table):
    """AT-72: AI 身份写记忆表被拒 — no receipt of a registered command, no row."""
    note = save(setup, "团队约定只由成员确认")
    with Session(setup.admin) as session:
        version = session.scalar(select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id == note["subject_id"]))
    values = {"id": uuid4(), "t": setup.tenant, "c": setup.category, "agent": setup.agent,
              "human": setup.human, "note": version.note_id, "receipt": version.receipt_id,
              "command": version.command_id, "digest": version.request_digest}
    statements = {
        "scope_notes": (
            "INSERT INTO scope_notes(id,tenant_id,created_at,category_id,anchor_kind,kind,"
            "claim_key,author_id) VALUES (:id,:t,now(),:c,'category','convention',"
            "repeat('a',64),:agent)"),
        "scope_note_versions": (
            "INSERT INTO scope_note_versions(id,tenant_id,created_at,category_id,anchor_kind,"
            "kind,note_id,revision,action,lifecycle,statement,sensitivity,source_authority,"
            "epistemic,confirmation,generated_by,valid_from,review_due_at,pinned,writer_id,"
            "requester_id,confirmed_by,origin,operation,command_id,receipt_id,request_digest) "
            "VALUES (:id,:t,now(),:c,'category','convention',:note,2,'revise','active',"
            "'AI 直接改写的约定','normal','human_statement','stated','member_confirmed','human',"
            "now(),now()+interval '90 days',false,:agent,:human,:human,'{}'::jsonb,"
            "'scope_note.save',:command,:receipt,:digest)"),
        "scope_note_evidence": (
            "INSERT INTO scope_note_evidence(id,tenant_id,created_at,category_id,note_id,"
            "revision,source_type,source_id,locator,root_source_id,stance,writer_id,receipt_id) "
            "VALUES (:id,:t,now(),:c,:note,1,'run',:id,'{}'::jsonb,:id,'supports',:agent,"
            ":receipt)"),
    }
    with pytest.raises(DBAPIError), tenant_session(
            setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human,
            category_id=setup.category) as session:
        session.execute(text(statements[table]), values)
        session.flush()
    with Session(setup.admin) as session:
        assert session.scalar(select(ScopeNoteVersion.revision).where(
            ScopeNoteVersion.note_id == version.note_id).order_by(
            ScopeNoteVersion.revision.desc())) == 1


def test_a_person_cannot_write_a_version_without_the_command_receipt(setup):
    note = save(setup, "备忘只经领域命令写入")
    with Session(setup.admin) as session:
        version = session.scalar(select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id == note["subject_id"]))
    with pytest.raises(DBAPIError), tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human,
            category_id=setup.category) as session:
        session.execute(text(
            "INSERT INTO scope_note_versions(id,tenant_id,created_at,category_id,anchor_kind,"
            "kind,note_id,revision,action,lifecycle,statement,sensitivity,source_authority,"
            "epistemic,confirmation,generated_by,valid_from,review_due_at,pinned,writer_id,"
            "requester_id,confirmed_by,origin,operation,command_id,receipt_id,request_digest) "
            "VALUES (:id,:t,now(),:c,'category','convention',:note,2,'revise','active',"
            "'绕过命令的改写','normal','human_statement','stated','member_confirmed','human',"
            "now(),now()+interval '90 days',false,:human,:human,:human,'{}'::jsonb,"
            "'scope_note.save',:command,:receipt,:digest)"),
            {"id": uuid4(), "t": setup.tenant, "c": setup.category, "human": setup.human,
             "note": version.note_id, "receipt": version.receipt_id, "command": uuid4(),
             "digest": version.request_digest})


def test_a_person_records_an_observation_only_with_a_confirmation(setup):
    payload = {"mode": "observation", "anchor": anchor(setup), "statement": "气嘴来料毛刺偏多",
               "inferred": True}
    direct = setup.client.post(f"/v1/categories/{setup.category}/commands",
                               headers=headers(setup), json=envelope(setup, OBSERVE, payload))
    assert direct.status_code == 409 and direct.json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, prepared = commit(setup, OBSERVE, payload)
    assert prepared["review"]["written_by"] == "person"
    note = item(setup, receipt["subject_id"])["note"]
    assert note["kind"] == "observation" and note["epistemic"] == "inferred"
    assert note["generated_by"] == "human" and note["confirmation"] == "member_confirmed"
    assert note["zone"] == "background"
