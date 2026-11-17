"""Personal notes on the unified item contract (P121 第 6 项后半, D512; 目标架构 §5.7).

替代按生效时间判断, 补录的旧信息只进历史, the contract fields on the page API, their
use in the Run envelope and ``memory.search``, migrated rows unchanged, purge still
clears every version, and the AI identity still cannot write. No model calls; real
roles and row-level security of the isolated pdos_test database.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import assemble, notes
from pdos_next.agent.memory.models import (
    NOTE_CONFIRMATIONS,
    NOTE_EVIDENCE_SOURCES,
    NOTE_EVIDENCE_STANCES,
    NOTE_RELATIONS,
    MemoryNote,
    MemoryNoteDeletion,
    MemoryNoteVersion,
)
from pdos_next.core.database import tenant_session
from pdos_next.domain.knowledge.scope_notes import models as scope_models
from tests.agent.memory.support import scope, start
from tests.agent.memory.test_memory_notes_pg import BASE, frozen_notes, listing, peer, search

NOW = datetime.now(UTC)


def at(days):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def post(setup, path, body, *, status=200, headers=None):
    response = setup.client.post(f"{BASE}{path}", headers=headers or setup.headers, json=body)
    assert response.status_code == status, response.text
    return response.json()


def add(setup, text_value, *, kind="convention", conflict=None, status=200, headers=None,
        **extra):
    body = {"request_key": str(uuid4()),
            "note": {"kind": kind, "text": text_value, "scope": {"kind": "global"}, **extra}}
    if conflict is not None:
        body["conflict"] = conflict
    return post(setup, "/notes", body, status=status, headers=headers)


def revise(setup, note, *, status=200, **fields):
    body = {"request_key": str(uuid4()), "expected_revision": note["revision"],
            "note": {"kind": note["kind"], "text": note["text"],
                     "scope": {"kind": "global"}, **fields}}
    return post(setup, f"/notes/{note['note_id']}/revisions", body, status=status)


def replace(*olds):
    return {"resolution": "replace", "note_ids": [item["note_id"] for item in olds],
            "expected_revisions": [item["revision"] for item in olds]}


def by_id(setup):
    return {item["note_id"]: item for item in listing(setup)["notes"]}


def versions(setup, note_id):
    with Session(setup.admin) as session:
        return session.scalars(select(MemoryNoteVersion).where(
            MemoryNoteVersion.note_id == note_id).order_by(MemoryNoteVersion.revision)).all()


def usable_at(setup, run_id, when):
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        return {str(row.note_id): current for row, current in notes.usable(s, run, now=when)}


def run_text(setup, run_id):
    with Session(setup.admin) as session:
        return json.dumps(session.get(AgentRun, run_id).versions, ensure_ascii=False)


def test_values_are_the_scope_notes_values():
    """同名字段同一套取值: personal values are the scope contract's (or a stated subset)."""
    assert set(NOTE_CONFIRMATIONS) <= set(scope_models.CONFIRMATIONS)
    assert NOTE_EVIDENCE_SOURCES == scope_models.SOURCES
    assert NOTE_EVIDENCE_STANCES == scope_models.STANCES
    assert set(NOTE_RELATIONS) <= set(scope_models.RELATIONS)


def test_contract_fields_are_written_read_and_shown_to_the_owner_only(setup):
    run_id, _ = start(setup, goal="确认气泵报价口径")
    happened = at(-3)
    saved = add(setup, "气泵报价按含税价比较", occurred_at=happened, evidence=[
        {"source_type": "business_object", "source_kind": "category",
         "source_id": str(setup.category), "stance": "supports"},
        {"source_type": "run", "source_id": str(run_id), "locator": {"turn": 2},
         "quote": "以后报价都按含税价比", "stance": "supports"},
    ])["note"]
    assert saved["confirmation"] == "member_confirmed" and saved["confirmation_label"] == "本人确认"
    assert saved["occurred_at"][:19] == happened[:19]
    assert saved["valid_from"] == saved["confirmed_at"]  # 生效起点缺省为本人确认的时间
    category, conversation = saved["evidence"]
    assert (category["readable"], category["source_version"], category["quoted"]) == (
        True, 1, False)
    assert category["title"]
    assert (conversation["readable"], conversation["quoted"], conversation["locator"]) == (
        True, True, {"turn": 2})
    (stored,) = versions(setup, saved["note_id"])
    assert "含税价比" not in json.dumps(stored.evidence, ensure_ascii=False)  # digest only
    assert stored.evidence[1]["quote_sha256"] and stored.created_at == stored.valid_from
    # Nobody else reads the note or its links.
    assert listing(setup, headers=peer(setup))["notes"] == []
    assert setup.client.get(f"{BASE}/notes/{saved['note_id']}/history",
                            headers=peer(setup)).status_code == 404


def test_links_and_times_are_checked_by_the_server(setup):
    note = add(setup, "回答先给结论")["note"]
    theirs, _ = start(setup, headers=peer(setup), goal="同事的对话")
    refused = add(setup, "周报用表格", status=403, evidence=[
        {"source_type": "run", "source_id": str(theirs), "stance": "supports"}])
    assert refused["detail"]["reason_key"] == "memory_note_evidence_unreadable"
    refused = add(setup, "周报用表格", status=403, evidence=[
        {"source_type": "business_object", "source_kind": "product",
         "source_id": str(uuid4()), "stance": "context"}])
    assert refused["detail"]["reason_key"] == "memory_note_evidence_unreadable"
    their_note = add(setup, "同事自己的口径", headers=peer(setup))["note"]
    refused = add(setup, "周报用表格", status=404,
                  relations=[{"type": "conflicts", "note_id": their_note["note_id"]}])
    assert refused["detail"]["reason_key"] == "memory_note_relation_unknown"
    assert add(setup, "周报用表格", status=422, occurred_at=at(1))["detail"][
        "reason_key"] == "memory_note_occurred"
    assert add(setup, "周报用表格", status=422, valid_from=at(10), valid_until=at(5))["detail"][
        "reason_key"] == "memory_note_validity"
    # A relation type the contract does not give a personal note is refused by the model …
    assert add(setup, "周报用表格", status=422,
               relations=[{"type": "refines", "note_id": note["note_id"]}])
    # … and by the database for anyone writing the column directly.
    with pytest.raises(DBAPIError, match="memory_note_relations"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human) as session:
            session.execute(text(
                "INSERT INTO memory_note_versions(id,tenant_id,created_at,owner_id,note_id,"
                "revision,kind,text,scope_kind,status,origin,request_key,request_sha256,"
                "valid_from,confirmation,evidence,relations) VALUES (:id,:t,now(),:o,:n,2,"
                "'convention','x','global','active','manual',:k,repeat('a',64),now(),"
                "'member_confirmed','[]',CAST(:rel AS jsonb))"),
                {"id": uuid4(), "t": setup.tenant, "o": setup.human, "n": note["note_id"],
                 "k": uuid4(), "rel": json.dumps([{"type": "refines",
                                                   "note_id": note["note_id"]}])})


def test_a_note_starting_later_is_pending_and_never_brought_in(setup):
    later = add(setup, "周报改用文字形式", valid_from=at(3))["note"]
    assert later["state"] == "pending"
    run_id, _ = start(setup, goal="周报怎么写")
    assert frozen_notes(setup, run_id) is None
    assert search(setup, run_id, "周报", kinds=["note"])["notes"] == []
    assert usable_at(setup, run_id, datetime.now(UTC) + timedelta(days=4)) == {
        later["note_id"]: "active"}
    # Revising a pending note keeps its start unless a new one is given.
    revised = revise(setup, later, text="周报改用文字形式，先写结论")["note"]
    assert (revised["state"], revised["valid_from"]) == ("pending", later["valid_from"])


def test_replace_takes_effect_at_the_new_notes_start(setup):
    old = add(setup, "周报用表格形式")["note"]
    starts = at(5)
    new = add(setup, "周报用文字形式", valid_from=starts, conflict=replace(old))
    assert new["effect"] == "replaces" and new["note"]["state"] == "pending"
    notes_now = by_id(setup)
    # The old note stays in effect until the new one starts, and says who replaces it.
    assert notes_now[old["note_id"]]["state"] == "active"
    assert notes_now[old["note_id"]]["valid_until"][:19] == starts[:19]
    assert [(item["type"], item["note_id"]) for item in notes_now[old["note_id"]]["relations"]] \
        == [("superseded_by", new["note"]["note_id"])]
    run_id, _ = start(setup, goal="周报怎么写")
    assert [item["text"] for item in frozen_notes(setup, run_id)["constraints"]] == ["周报用表格形式"]
    later = usable_at(setup, run_id, datetime.now(UTC) + timedelta(days=6))
    assert later == {new["note"]["note_id"]: "active"}


def test_backfilled_older_information_only_enters_history(setup):
    current = add(setup, "周报用表格形式")["note"]
    older = {"kind": "convention", "text": "周报用文字形式", "scope": {"kind": "global"},
             "valid_from": at(-30)}
    found = post(setup, "/notes/conflicts", older)
    assert [item["replace_effect"] for item in found["conflicts"]] == ["history_only"]
    saved = add(setup, "周报用文字形式", valid_from=at(-30), conflict=replace(current))
    assert saved["effect"] == "history_only" and "只记入历史" in saved["note_text"]
    backfilled = saved["note"]
    assert backfilled["state"] == "replaced" and backfilled["replaced_by"] == current["note_id"]
    assert backfilled["valid_until"] == current["valid_from"]
    # The current note is untouched: same revision, still in effect, now listed as the one
    # that superseded the older information.
    mine = by_id(setup)
    assert (mine[current["note_id"]]["revision"], mine[current["note_id"]]["state"]) == (1, "active")
    assert [(item["type"], item["note_id"]) for item in mine[current["note_id"]]["relations"]] == [
        ("supersedes", backfilled["note_id"])]
    assert [row.revision for row in versions(setup, current["note_id"])] == [1]
    run_id, _ = start(setup, goal="周报怎么写")
    assert [item["text"] for item in frozen_notes(setup, run_id)["constraints"]] == ["周报用表格形式"]
    assert [card["text"] for card in search(setup, run_id, "周报", kinds=["note"])["notes"]] == [
        "周报用表格形式"]
    # For the time it covered, the back-filled note answers as_of, as background.
    then = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
    (card,) = search(setup, run_id, "周报", kinds=["note"], as_of=then)["notes"]
    assert (card["text"], card["zone"], card["current"]["state"]) == (
        "周报用文字形式", "background", "replaced")


def test_a_back_dated_replacement_ends_the_old_note_at_its_own_start(setup):
    old = add(setup, "报价按未税价比较", valid_from=at(-20))["note"]
    new = add(setup, "报价按含税价比较", valid_from=at(-10), conflict=replace(old))
    assert new["effect"] == "replaces" and new["note"]["state"] == "active"
    run_id, _ = start(setup, goal="报价口径")

    def then(days):
        day = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        return [card["text"] for card in search(setup, run_id, "报价", kinds=["note"],
                                                as_of=day)["notes"]]

    assert then(15) == ["报价按未税价比较"]
    assert then(5) == ["报价按含税价比较"]
    assert then(25) == []


def test_kept_side_by_side_as_conflicting_both_drop_to_background(setup):
    first = add(setup, "回答先给结论再列依据")["note"]
    second = add(setup, "回答先列依据再给结论", conflict={
        "resolution": "keep_both", "note_ids": [], "expected_revisions": []},
        relations=[{"type": "conflicts", "note_id": first["note_id"]}])["note"]
    mine = by_id(setup)
    assert [(item["type"], item["direction"]) for item in mine[first["note_id"]]["relations"]] == [
        ("conflicts", "in")]
    assert [(item["type"], item["direction"]) for item in mine[second["note_id"]]["relations"]] == [
        ("conflicts", "out")]
    run_id, _ = start(setup, goal="回答的顺序")
    context = frozen_notes(setup, run_id)
    assert context["constraints"] == []
    assert {item["note_id"] for item in context["background"]} == {
        first["note_id"], second["note_id"]}
    assert all("冲突" in item["note"] for item in context["background"])
    cards = search(setup, run_id, "结论 依据", kinds=["note"])["notes"]
    assert {card["zone"] for card in cards} == {"background"}
    # Removing the relation on the page puts the 口径 back into the constraint zone.
    revise(setup, mine[second["note_id"]], relations=[])
    later, _ = start(setup, goal="回答的顺序")
    assert len(frozen_notes(setup, later)["constraints"]) == 2


def test_revisions_keep_what_is_left_out_and_never_move_an_active_note_later(setup):
    run_id, _ = start(setup, goal="确认口径")
    note = add(setup, "报价按含税价比较", occurred_at=at(-2), evidence=[
        {"source_type": "run", "source_id": str(run_id), "quote": "按含税价", "stance": "supports"}
    ])["note"]
    kept = revise(setup, note, text="报价一律按含税价比较")["note"]
    assert (kept["occurred_at"], len(kept["evidence"]), kept["evidence"][0]["quoted"]) == (
        note["occurred_at"], 1, True)
    # The page re-sends the links it shows without the quote: the digest stays.
    resent = revise(setup, kept, evidence=[{key: kept["evidence"][0][key] for key in (
        "source_type", "source_id", "locator", "stance")}])["note"]
    assert resent["evidence"][0]["quoted"] is True
    cleared = revise(setup, resent, evidence=[], occurred_at=None)["note"]
    assert cleared["evidence"] == [] and cleared["occurred_at"] is None
    refused = revise(setup, cleared, status=422, valid_from=at(2))
    assert refused["detail"]["reason_key"] == "memory_note_future_start"
    earlier = revise(setup, cleared, valid_from=at(-7))["note"]
    assert earlier["valid_from"][:10] == at(-7)[:10]


def test_merge_keeps_both_notes_links(setup):
    run_id, _ = start(setup, goal="确认口径")
    old = add(setup, "报价按含税价比较", evidence=[
        {"source_type": "business_object", "source_kind": "category",
         "source_id": str(setup.category), "stance": "context"}])["note"]
    merged = add(setup, "报价按含税价比较并注明税率", conflict={
        "resolution": "merge", "note_ids": [old["note_id"]], "expected_revisions": [1],
        "merged_text": "报价按含税价比较，并注明税率"}, evidence=[
        {"source_type": "run", "source_id": str(run_id), "stance": "supports"}])
    assert merged["resolution"] == "merge"
    note = merged["note"]
    assert (note["note_id"], note["revision"]) == (old["note_id"], 2)
    assert [item["source_type"] for item in note["evidence"]] == ["business_object", "run"]


def test_migrated_rows_behave_as_before(setup):
    """Rows exactly as s0_0897 fills them (valid_from = record time; a replaced marker copies
    the start of the version it closes) answer listing, use and as_of as s0_0896 did."""
    base = datetime.now(UTC) - timedelta(days=20)
    a, b = uuid4(), uuid4()

    def row(note, revision, created, text_value, **extra):
        values = {"id": uuid4(), "tenant_id": setup.tenant, "created_at": created,
                  "owner_id": setup.human, "note_id": note, "revision": revision,
                  "kind": "convention", "text": text_value, "scope_kind": "global",
                  "status": "active", "origin": "manual", "request_key": uuid4(),
                  "request_sha256": "0" * 64, "valid_from": created,
                  "confirmation": "member_confirmed", "evidence": "[]", "relations": "[]",
                  "valid_until": None, "replaced_by": None}
        values.update(extra)
        return values

    rows = [
        row(a, 1, base, "周报用表格形式"),
        row(a, 2, base + timedelta(days=12), "周报用文字形式"),
        row(b, 1, base + timedelta(hours=1), "周报抄送项目经理"),
        row(b, 2, base + timedelta(days=15), "周报抄送项目经理", status="replaced",
            valid_from=base + timedelta(hours=1), valid_until=base + timedelta(days=15),
            replaced_by=a),
    ]
    with Session(setup.admin) as session, session.begin():
        for note in (a, b):
            session.add(MemoryNote(id=note, tenant_id=setup.tenant, owner_id=setup.human))
        session.flush()
        for values in rows:
            session.execute(text(
                f"INSERT INTO memory_note_versions ({', '.join(values)}) VALUES ("
                + ", ".join(f"CAST(:{key} AS jsonb)" if key in {"evidence", "relations"}
                            else f":{key}" for key in values) + ")"), values)
    mine = by_id(setup)
    assert (mine[str(a)]["state"], mine[str(a)]["revision"]) == ("active", 2)
    assert (mine[str(b)]["state"], mine[str(b)]["revision"]) == ("replaced", 2)
    run_id, _ = start(setup, goal="周报怎么写")
    assert [item["text"] for item in frozen_notes(setup, run_id)["constraints"]] == ["周报用文字形式"]

    def then(days):
        day = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        return sorted((card["text"], card["revision"]) for card in search(
            setup, run_id, "周报", kinds=["note"], as_of=day)["notes"])

    # Same answers as by record time: a's first version, b before it was replaced.
    assert then(10) == [("周报抄送项目经理", 1), ("周报用表格形式", 1)]
    assert then(2) == [("周报用文字形式", 2)]
    assert then(25) == []


def test_purge_still_clears_every_version_and_relations_to_it_drop(setup):
    run_id, _ = start(setup, goal="确认口径")
    gone = add(setup, "报价按含税价比较", occurred_at=at(-1), evidence=[
        {"source_type": "run", "source_id": str(run_id), "quote": "按含税价", "stance": "supports"}
    ])["note"]
    gone = revise(setup, gone, text="报价一律按含税价比较")["note"]
    other = add(setup, "供应商报价单要写明币种", relations=[
        {"type": "duplicates", "note_id": gone["note_id"]}])["note"]
    assert other["relations"][0]["note_id"] == gone["note_id"]
    deleted = post(setup, f"/notes/{gone['note_id']}/deletion",
                   {"request_key": str(uuid4()), "expected_revision": gone["revision"]})
    assert deleted["purged_versions"] == 2
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(MemoryNoteVersion).where(
            MemoryNoteVersion.note_id == UUID(gone["note_id"]))) == 0
        tombstone = session.execute(text(
            "SELECT to_jsonb(d) AS body FROM memory_note_deletions d WHERE note_id=:n"),
            {"n": gone["note_id"]}).scalar_one()
        assert session.scalar(select(func.count()).select_from(MemoryNoteDeletion).where(
            MemoryNoteDeletion.note_id == UUID(gone["note_id"]))) == 1
    assert "含税价" not in json.dumps(tombstone, ensure_ascii=False)
    assert by_id(setup)[other["note_id"]]["relations"] == []


def test_ai_identity_cannot_write_a_version_with_contract_fields(setup):
    note = add(setup, "我负责充气泵品类", kind="background")["note"]
    with pytest.raises(DBAPIError, match="row-level security|permission denied"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text(
                "INSERT INTO memory_note_versions(id,tenant_id,created_at,owner_id,note_id,"
                "revision,kind,text,scope_kind,status,origin,request_key,request_sha256,"
                "valid_from,occurred_at,confirmation,evidence,relations) VALUES (:id,:t,now(),"
                ":o,:n,2,'background','AI 写入','global','active','manual',:k,repeat('a',64),"
                "now(),now(),'member_confirmed','[]','[]')"),
                {"id": uuid4(), "t": setup.tenant, "o": setup.human, "n": note["note_id"],
                 "k": uuid4()})
    assert [row.text for row in versions(setup, note["note_id"])] == ["我负责充气泵品类"]


def test_the_run_keeps_no_note_words_or_dates(setup):
    note = add(setup, "十月起我调到质量部", kind="background", occurred_at=at(-20))["note"]
    run_id, _ = start(setup, goal="我负责哪块")
    (entry,) = frozen_notes(setup, run_id)["background"]
    assert entry["occurred_on"] == note["occurred_at"][:10]
    stored = run_text(setup, run_id)
    assert note["note_id"] in stored
    assert "质量部" not in stored and note["occurred_at"][:10] not in stored
    # Re-read for the next model call: the words and the date come from the version.
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        (again,) = assemble.frozen(s, run)["background"]
    assert again["occurred_on"] == note["occurred_at"][:10] and again["text"] == "十月起我调到质量部"
