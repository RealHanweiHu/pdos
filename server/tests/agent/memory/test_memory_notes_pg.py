"""M2a 本人记忆条目 (P86, AT-71, AT-72, AT-74): notes, conflicts, aliases, use, purge.

No model or embedding calls. Every write goes through the real roles and row-level
security of the isolated pdos_test database.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.context_budget import estimate_tokens
from pdos_next.agent.kernel.models import AgentRun, TenantAdministrator
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import assemble
from pdos_next.agent.memory.models import (
    MemoryNote,
    MemoryNoteDeletion,
    MemoryNoteVersion,
)
from pdos_next.agent.memory.notes import alias_expansions
from pdos_next.agent.memory.tool import memory_search
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Category, Grant, now
from pdos_next.errors import DomainError
from tests.agent.memory.support import finish, scope, start

BASE = "/v1/personal/memory"


def peer(setup):
    return {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}


def other_tenant(setup):
    return {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}


def add(setup, text_value, *, kind="convention", scope_value=None, headers=None, conflict=None,
        status=200, **extra):
    body = {"request_key": str(uuid4()), "note": {
        "kind": kind, "text": text_value, "scope": scope_value or {"kind": "global"}, **extra}}
    if conflict is not None:
        body["conflict"] = conflict
    response = setup.client.post(f"{BASE}/notes", headers=headers or setup.headers, json=body)
    assert response.status_code == status, response.text
    return response.json()


def listing(setup, headers=None):
    response = setup.client.get(f"{BASE}/notes", headers=headers or setup.headers)
    assert response.status_code == 200, response.text
    return response.json()


def category_scope(setup):
    return {"kind": "category", "id": str(setup.category)}


def frozen_notes(setup, run_id, *, personal=False):
    with KernelStore(setup.engine).transaction(scope(setup, run_id, personal=personal),
                                               lock=True) as (session, run):
        return assemble.frozen(session, run)


def search(setup, run_id, query, *, personal=False, **arguments):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id, personal=personal), {"query": query, **arguments})


def test_owner_writes_a_note_and_nobody_else_reads_it(setup):
    saved = add(setup, "回答先给结论，再列依据")
    note = saved["note"]
    assert note["kind"] == "convention" and note["kind_label"] == "口径"
    assert note["revision"] == 1 and note["state"] == "active" and note["origin"] == "manual"
    mine = listing(setup)
    assert [item["note_id"] for item in mine["notes"]] == [note["note_id"]]
    assert mine["enabled"] is True and mine["limit"] == 50 and "不是业务事实" in mine["note"]
    assert listing(setup, peer(setup))["notes"] == []
    assert listing(setup, other_tenant(setup))["notes"] == []
    assert setup.client.get(f"{BASE}/notes/{note['note_id']}/history",
                            headers=peer(setup)).status_code == 404
    # A peer can neither revise nor delete it.
    for path, body in ((f"{BASE}/notes/{note['note_id']}/revisions",
                        {"request_key": str(uuid4()), "expected_revision": 1,
                         "note": {"kind": "convention", "text": "改掉"}}),
                       (f"{BASE}/notes/{note['note_id']}/deletion",
                        {"request_key": str(uuid4()), "expected_revision": 1})):
        assert setup.client.post(path, headers=peer(setup), json=body).status_code == 404


@pytest.mark.parametrize("table", ["memory_notes", "memory_note_versions"])
def test_ai_identity_cannot_write_or_purge_a_note(setup, table):
    note = add(setup, "我负责充气泵品类")["note"]
    with Session(setup.admin) as session:
        version = session.scalar(select(MemoryNoteVersion).where(
            MemoryNoteVersion.note_id == note["note_id"]))
    statements = {
        "memory_notes": ("INSERT INTO memory_notes(id,tenant_id,created_at,owner_id) "
                         "VALUES (:id,:tenant,now(),:owner)"),
        "memory_note_versions": (
            "INSERT INTO memory_note_versions(id,tenant_id,created_at,owner_id,note_id,revision,"
            "kind,text,scope_kind,status,origin,request_key,request_sha256) VALUES (:id,:tenant,"
            "now(),:owner,:note,2,'convention','AI 写入','global','active','manual',:key,"
            "repeat('a',64))"),
    }
    values = {"id": uuid4(), "tenant": setup.tenant, "owner": setup.human,
              "note": note["note_id"], "key": uuid4()}
    with pytest.raises(DBAPIError, match="row-level security|permission denied"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text(statements[table]), values)
    # Purge as the AI identity removes nothing; update is refused for everyone.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                        requester_id=setup.human) as session:
        deleted = session.execute(text("DELETE FROM memory_note_versions WHERE id=:id"),
                                  {"id": version.id}).rowcount
    assert deleted == 0
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human) as session:
            session.execute(text("UPDATE memory_note_versions SET text='改写' WHERE id=:id"),
                            {"id": version.id})
    assert listing(setup)["notes"][0]["text"] == "我负责充气泵品类"


def test_similar_note_requires_merge_replace_or_keep_both(setup):
    first = add(setup, "报告一律用英文给客户")["note"]
    check = setup.client.post(f"{BASE}/notes/conflicts", headers=setup.headers, json={
        "kind": "convention", "text": "给客户的报告一律用中文"})
    assert check.status_code == 200, check.text
    assert [item["note_id"] for item in check.json()["conflicts"]] == [first["note_id"]]
    assert check.json()["choices"] == ["merge", "replace", "keep_both"]
    refused = add(setup, "给客户的报告一律用中文", status=409)
    assert refused["detail"]["reason_key"] == "memory_conflict_unresolved"
    body = {"request_key": str(uuid4()),
            "note": {"kind": "convention", "text": "给客户的报告一律用中文",
                     "scope": {"kind": "global"}},
            "conflict": {"resolution": "replace", "note_ids": [first["note_id"]],
                         "expected_revisions": [1]}}
    replaced = setup.client.post(f"{BASE}/notes", headers=setup.headers, json=body).json()
    replay = setup.client.post(f"{BASE}/notes", headers=setup.headers, json=body).json()
    assert replay["note"]["note_id"] == replaced["note"]["note_id"] != first["note_id"]
    notes = {item["note_id"]: item for item in listing(setup)["notes"]}
    assert notes[first["note_id"]]["state"] == "replaced"
    assert notes[first["note_id"]]["replaced_by"] == replaced["note"]["note_id"]
    assert notes[replaced["note"]["note_id"]]["state"] == "active"
    history = setup.client.get(f"{BASE}/notes/{first['note_id']}/history",
                               headers=setup.headers).json()
    assert [item["revision"] for item in history["versions"]] == [2, 1]
    # Merge appends a version to the old note with the owner's merged text.
    merged = add(setup, "给客户的报告用中文，附英文摘要", conflict={
        "resolution": "merge", "note_ids": [replaced["note"]["note_id"]],
        "expected_revisions": [1], "merged_text": "给客户的报告用中文，附英文摘要"})
    assert merged["resolution"] == "merge"
    assert merged["note"]["note_id"] == replaced["note"]["note_id"]
    assert merged["note"]["revision"] == 2 and merged["note"]["origin"] == "merge"
    kept = add(setup, "给客户的报告用中文，另附英文版", conflict={
        "resolution": "keep_both", "note_ids": [], "expected_revisions": []})
    assert kept["resolution"] == "keep_both"
    active = [item for item in listing(setup)["notes"] if item["state"] == "active"]
    assert len(active) == 2
    # A stale expected revision is refused.
    stale = add(setup, "给客户的报告一律中文", status=409, conflict={
        "resolution": "replace", "note_ids": [replaced["note"]["note_id"]],
        "expected_revisions": [1]})
    assert stale["code"] == "VERSION_CONFLICT"


def test_scope_must_be_readable_and_limits_hold(setup):
    hidden = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Category(id=hidden, tenant_id=setup.tenant, name="不可读品类",
                             purpose="合成", owner_id=setup.peer))
    refused = add(setup, "只在这个品类用", scope_value={"kind": "category", "id": str(hidden)},
                  status=403)
    assert refused["code"] == "FORBIDDEN_SCOPE"
    too_long = setup.client.post(f"{BASE}/notes", headers=setup.headers, json={
        "request_key": str(uuid4()), "note": {"kind": "convention", "text": "长" * 201}})
    assert too_long.status_code == 422
    scoped = add(setup, "本品类的价格带按出厂价算", scope_value=category_scope(setup))
    assert scoped["note"]["scope"] == {"kind": "category", "id": str(setup.category),
                                       "title": "汽车充气泵", "readable": True}


def test_aliases_go_to_the_envelope_and_expand_only_the_owners_search(setup):
    alias = add(setup, "", kind="alias", alias_term="气嘴", alias_canonical="气门嘴")["note"]
    assert alias["text"] == "我说“气嘴”指气门嘴"
    assert alias["alias"] == {"term": "气嘴", "means": {"kind": "term", "text": "气门嘴"}}
    add(setup, "回答先给结论", scope_value=category_scope(setup))
    add(setup, "我负责充气泵品类的成本核算", kind="background")
    run_id, _ = start(setup, goal="气嘴漏气的问题以前怎么处理的")
    value = frozen_notes(setup, run_id)
    assert value["aliases"][0]["term"] == "气嘴" and value["aliases"][0]["means"] == "气门嘴"
    assert [item["text"] for item in value["constraints"]] == ["回答先给结论"]
    assert [item["text"] for item in value["background"]] == ["我负责充气泵品类的成本核算"]
    assert value["zone_policy"] == {"constraints": "constraint", "aliases": "constraint",
                                    "background": "background"}
    assert "不是业务事实" in value["label"] and "不能作为依据引用" in value["label"]
    assert frozen_notes(setup, run_id) == value  # Frozen for the Run.
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        extra, applied = alias_expansions(s, run, "气嘴漏气", assemble.frozen_aliases(run))
        usage = run.versions["memory_usage"]["notes"]
    assert extra == "气门嘴" and applied[0]["term"] == "气嘴"
    assert {item["zone"] for item in usage} == {"aliases", "constraints", "background"}
    result = search(setup, run_id, "气嘴", kinds=["note"])
    assert result["retrieval"]["alias_expansion"][0]["expanded_with"] == ["气门嘴"]
    assert [item["note_kind"] for item in result["notes"]] == ["alias"]
    assert "不是业务事实" in result["notes_policy"]
    # The peer's Run never sees the owner's notes or aliases.
    peer_run, _ = start(setup, headers=peer(setup), goal="气嘴漏气")
    with KernelStore(setup.engine).transaction(scope(setup, peer_run, requester=setup.peer),
                                               lock=True) as (s, run):
        assert assemble.frozen(s, run) is None
        assert assemble.frozen_aliases(run) == []
    peer_result = memory_search(KernelStore(setup.engine))(
        scope(setup, peer_run, requester=setup.peer), {"query": "气嘴", "kinds": ["note"]})
    assert peer_result["notes"] == [] and "alias_expansion" not in peer_result["retrieval"]


def test_range_budget_and_switches_for_resident_notes(setup, monkeypatch):
    other = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Category(id=other, tenant_id=setup.tenant, name="吸尘器",
                             purpose="合成", owner_id=setup.human))
        session.flush()
        session.add(Grant(tenant_id=setup.tenant, category_id=other, principal_id=setup.human,
                          can_write=True, expires_at=now() + __import__("datetime").timedelta(
                              hours=1)))
    add(setup, "吸尘器只看欧标", scope_value={"kind": "category", "id": str(other)})
    add(setup, "本品类按出厂价算", scope_value=category_scope(setup))
    for index in range(12):
        add(setup, f"背景第{index}条：" + "充气泵客户关注噪音和体积" * 3, kind="background",
            conflict={"resolution": "keep_both", "note_ids": [], "expected_revisions": []})
    run_id, _ = start(setup, goal="继续")
    value = frozen_notes(setup, run_id)
    texts = [item["text"] for zone in ("constraints", "background") for item in value[zone]]
    assert "吸尘器只看欧标" not in texts and value["constraints"][0]["text"] == "本品类按出厂价算"
    assert value["omitted"] > 0
    assert estimate_tokens(json.dumps(value, ensure_ascii=False)) <= 1000
    # Personal runs carry only global notes.
    personal, _ = start(setup, personal=True, goal="继续")
    personal_value = frozen_notes(setup, personal, personal=True)
    assert all(item["scope"]["kind"] == "global" for zone in ("constraints", "background")
               for item in personal_value[zone])
    # 不进记忆: no notes are read at all.
    off, _ = start(setup, goal="继续", memory_off=True)
    assert frozen_notes(setup, off) is None
    with Session(setup.admin) as session:
        assert "memory_usage" not in session.get(AgentRun, off).versions
    # The administrator closes free-text notes tenant-wide.
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human,
                                        active=True))
    closed = setup.client.post("/v1/personal/memory-policy", headers=setup.headers, json={
        "expected_revision": 0, "request_key": str(uuid4()), "work_state_idle_days": 30,
        "notes_enabled": False})
    assert closed.status_code == 200, closed.text
    assert closed.json()["notes_enabled"] is False
    later, _ = start(setup, goal="继续")
    assert frozen_notes(setup, later) is None
    refused = add(setup, "关闭后不能新增", status=403)
    assert refused["detail"]["reason_key"] == "memory_notes_disabled"
    assert listing(setup)["enabled"] is False and listing(setup)["notes"]


def test_purge_removes_the_body_everywhere_and_leaves_a_tombstone(setup):
    note = add(setup, "气泵报价按含税价比较")["note"]
    run_id, _ = start(setup, goal="气泵报价")
    assert frozen_notes(setup, run_id)["constraints"][0]["note_id"] == note["note_id"]
    deleted = setup.client.post(f"{BASE}/notes/{note['note_id']}/deletion", headers=setup.headers,
                                json={"request_key": str(uuid4()), "expected_revision": 1})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True and deleted.json()["purged_versions"] == 1
    assert "最迟 30 天内随检查点清除" in deleted.json()["note"]  # P94 第 4 项
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(MemoryNoteVersion).where(
            MemoryNoteVersion.note_id == note["note_id"])) == 0
        assert session.scalar(select(func.count()).select_from(MemoryNoteDeletion).where(
            MemoryNoteDeletion.note_id == note["note_id"])) == 1
        assert session.get(MemoryNote, note["note_id"]) is not None  # Identity only.
        stored = json.dumps([row.body for row in session.execute(text(
            "SELECT to_jsonb(d) AS body FROM memory_note_deletions d")).all()], default=str)
    assert "含税价" not in stored
    assert listing(setup)["notes"] == [] and listing(setup)["deleted_count"] == 1
    # The Run that carried it stops before the next model call (AT-72 删除后不再被使用).
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        with pytest.raises(DomainError) as refused:
            assemble.recheck(s, run)
    assert refused.value.reason == "CONVERSATION_HISTORY_REVOKED"
    later, _ = start(setup, goal="气泵报价")
    assert frozen_notes(setup, later) is None
    assert search(setup, later, "含税价", kinds=["note"])["notes"] == []
    usage = setup.client.get(f"/v1/categories/{setup.category}/agent-runs/{run_id}/memory-usage",
                             headers=setup.headers)
    finish(setup, run_id)
    usage = setup.client.get(f"/v1/categories/{setup.category}/agent-runs/{run_id}/memory-usage",
                             headers=setup.headers).json()
    assert usage["notes"] == [{"note_id": note["note_id"], "deleted": True,
                               "zone": "constraints"}]


def test_administrator_sees_counts_only(setup):
    add(setup, "回答先给结论")
    add(setup, "我负责充气泵", kind="background", headers=peer(setup))
    gone = add(setup, "临时条目", kind="background")["note"]
    setup.client.post(f"{BASE}/notes/{gone['note_id']}/deletion", headers=setup.headers,
                      json={"request_key": str(uuid4()), "expected_revision": 1})
    path = "/v1/personal/memory-policy/statistics"
    assert setup.client.get(path, headers=setup.headers).status_code == 403
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human,
                                        active=True))
    value = setup.client.get(path, headers=setup.headers).json()
    assert value["active_notes"] == 2 and value["owners_with_notes"] == 2
    assert value["episode_vectors"] == {"enabled": False, "profile_version_id": None}
    assert "回答先给结论" not in json.dumps(value, ensure_ascii=False)
    # The statistics function refuses anyone but a current human administrator.
    with pytest.raises(DBAPIError, match="administrator"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text("SELECT * FROM memory_note_statistics(:t)"), {"t": setup.tenant})
