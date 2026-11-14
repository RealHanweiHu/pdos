"""M2b: team notes in the Run envelope and in memory.search (P87; P121 第 3 项; D481).

Real Runs, real roles and row-level security; no model or embedding calls.
"""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.context_budget import estimate_tokens
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import scope_assemble
from pdos_next.agent.memory.tool import memory_search
from pdos_next.core.models import Product
from pdos_next.errors import DomainError
from tests.agent.memory.support import scope, start
from tests.g0_fixture import create_g0_project
from tests.knowledge.scope_notes.support import RETIRE, anchor, commit, headers, save


def assemble(setup, run_id, *, requester=None, skills=()):
    with KernelStore(setup.engine).transaction(
            scope(setup, run_id, requester=requester), lock=True) as (session, run):
        return scope_assemble.frozen(session, run, skills=skills)


def recheck(setup, run_id, *, requester=None):
    with KernelStore(setup.engine).transaction(
            scope(setup, run_id, requester=requester)) as (session, run):
        scope_assemble.recheck(session, run)


def stored(setup, run_id):
    with Session(setup.admin) as session:
        return dict(session.get(AgentRun, run_id).versions)


def search(setup, run_id, query, *, personal=False, requester=None, **arguments):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id, personal=personal, requester=requester),
        {"query": query, "kinds": ["scope_note"], **arguments})


def peer_run(setup, goal="继续准备评审"):
    return start(setup, headers=headers(setup, setup.peer), goal=goal)[0]


def test_only_a_convention_constrains_and_the_run_row_keeps_no_text(setup):
    convention = save(setup, "给该客户的报告一律英文")
    save(setup, "客户评审必问跌落测试", kind="concern")
    save(setup, "噪音放宽是电话里同意的，正式变更待补", kind="decision_context")
    run_id, _ = start(setup, goal="起草评审材料")
    team, recent = assemble(setup, run_id)
    assert team["zone_policy"] == {"conventions": "constraint", "background": "background"}
    assert "不是业务事实" in team["label"] and "不能作为" in team["label"]
    assert [e["statement"] for e in team["conventions"]] == ["给该客户的报告一律英文"]
    assert {e["kind"] for e in team["background"]} == {"关注点", "决策背景"}
    assert team["conventions"][0]["confirmed"].startswith("Synthetic owner ")
    assert team["conventions"][0]["confirmed"].endswith(" 确认")
    context = next(e for e in team["background"] if e["kind"] == "决策背景")
    assert context["note"] == "未形成正式决定"
    # D481: IDs and revisions only on the Run row; the text is read each time.
    versions = stored(setup, run_id)
    frozen = versions[scope_assemble.KEY]
    assert {(item["note_id"], item["revision"], item["zone"]) for item in frozen["used"]} >= {
        (convention["subject_id"], 1, "constraint")}
    assert "英文" not in json.dumps(versions, ensure_ascii=False)
    assert "跌落" not in json.dumps(versions, ensure_ascii=False)
    assert len(versions["memory_usage"]["scope_notes"]) == 3
    # 范围近况 is computed at the Run's watermark and names changes, not note text.
    assert recent["zone"] == "background" and len(recent["note_changes"]) == 3
    assert {line["what"] for line in recent["note_changes"]} == {
        "新增约定", "新增关注点", "新增决策背景"}
    assert "英文" not in json.dumps(recent, ensure_ascii=False)
    # The same assembly again is identical (frozen per Run).
    assert assemble(setup, run_id) == (team, recent)


def test_a_retired_note_is_not_sent_again_and_leaves_no_copy(setup):
    """删除或撤回后运行里不留正文: nothing to purge, because nothing was stored."""
    kept = save(setup, "样件统一贴项目标签")
    stopped = save(setup, "评审会前一天发材料")
    run_id, _ = start(setup, goal="安排评审")
    assert len(assemble(setup, run_id)[0]["conventions"]) == 2
    commit(setup, RETIRE, {"note": {"id": stopped["subject_id"], "revision": 1},
                           "action": "withdraw", "reason": "记错了"})
    team, _recent = assemble(setup, run_id)
    assert [e["note_id"] for e in team["conventions"]] == [kept["subject_id"]]
    assert "评审会前一天" not in json.dumps(stored(setup, run_id), ensure_ascii=False)
    # The model already saw it once: the Run is stopped before its next model call.
    with pytest.raises(DomainError) as stop:
        recheck(setup, run_id)
    assert stop.value.reason == "CONVERSATION_HISTORY_REVOKED"
    assert stop.value.detail["scope_note_ids"] == [stopped["subject_id"]]
    # A new Run never loads it, and search never returns it.
    fresh, _ = start(setup, goal="再安排一次评审")
    assert [e["note_id"] for e in assemble(setup, fresh)[0]["conventions"]] == [
        kept["subject_id"]]
    recheck(setup, fresh)
    assert search(setup, fresh, "评审 材料")["scope_notes"] == []


def test_after_access_is_narrowed_the_note_is_neither_returned_nor_loaded(setup):
    """撤权后不返回且不带入: the note points at an object the peer can no longer read."""
    target = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Product(id=target, tenant_id=setup.tenant, category_id=setup.category,
                            name="Synthetic shared product", purpose="Scope note subject",
                            owner_id=setup.human, visibility="category"))
    pointed = save(setup, "这个型号的规格书以英文版为准",
                   subject={"kind": "product", "id": str(target)})
    open_note = save(setup, "周报每周五发")
    run_id = peer_run(setup)
    team, _recent = assemble(setup, run_id, requester=setup.peer)
    assert {e["note_id"] for e in team["conventions"]} == {pointed["subject_id"],
                                                          open_note["subject_id"]}
    assert len(search(setup, run_id, "规格书 英文", requester=setup.peer)["scope_notes"]) == 1
    with Session(setup.admin) as session, session.begin():
        session.get(Product, target).visibility = "private"
    team, _recent = assemble(setup, run_id, requester=setup.peer)
    assert [e["note_id"] for e in team["conventions"]] == [open_note["subject_id"]]
    assert search(setup, run_id, "规格书 英文", requester=setup.peer)["scope_notes"] == []
    with pytest.raises(DomainError) as stop:
        recheck(setup, run_id, requester=setup.peer)
    assert stop.value.detail["scope_note_ids"] == [pointed["subject_id"]]
    later = peer_run(setup, "新的一次")
    assert [e["note_id"] for e in assemble(setup, later, requester=setup.peer)[0][
        "conventions"]] == [open_note["subject_id"]]
    usage = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{run_id}/memory-usage",
        headers=headers(setup, setup.peer)).json()
    assert [n["note_id"] for n in usage["scope_notes"]] == [open_note["subject_id"]]
    # The owner still reads both.
    mine, _ = start(setup, goal="负责人自己的运行")
    assert len(assemble(setup, mine)[0]["conventions"]) == 2


def test_customer_tagged_notes_load_only_for_the_same_customer(setup):
    """AT-73: 带客户标签的备忘不进其他客户的项目."""
    tagged = save(setup, "这家客户的外箱要加贴防潮标", customer="客户A")
    plain = save(setup, "外箱唛头按订单语言印", kept=[tagged["subject_id"]])
    run_id, _ = start(setup, goal="准备出货")
    team, _recent = assemble(setup, run_id)
    assert [e["note_id"] for e in team["conventions"]] == [plain["subject_id"]]
    assert search(setup, run_id, "外箱 防潮标")["scope_notes"] == []
    # A Run's customer binding is set by the server from its proposal and cannot be
    # changed afterwards, so the same-customer side is checked on the selection itself.
    with KernelStore(setup.engine).transaction(scope(setup, run_id)) as (session, run):
        same = SimpleNamespace(
            tenant_id=run.tenant_id, category_id=run.category_id, product_id=run.product_id,
            proposal_id=run.proposal_id, project_id=None, customer_identities=["客户A"])
        other = SimpleNamespace(**{**vars(same), "customer_identities": ["客户B"]})
        assert {str(row.note_id) for row, _l, _z in scope_assemble.candidates(session, same)} == {
            tagged["subject_id"], plain["subject_id"]}
        assert {str(row.note_id) for row, _l, _z in scope_assemble.candidates(
            session, other)} == {plain["subject_id"]}


def test_budget_keeps_pinned_first_and_counts_what_was_left_out(setup):
    topics = ["包装", "标签", "报告", "样件", "评审", "交期", "认证", "测试", "模具", "物流",
              "付款", "验货"]
    saved = []
    for index, topic in enumerate(topics):
        text = f"{topic}{index}：" + (f"{topic}{index}统一按清单{index}办理，" * 12)
        saved.append(save(setup, text[:290], kind="concern" if index % 2 else "convention",
                          kept=[row["subject_id"] for row in saved]))
    pinned = save(setup, "所有对外文件先过法务", pinned=True,
                  kept=[row["subject_id"] for row in saved])
    run_id, _ = start(setup, goal="整理约定")
    team, _recent = assemble(setup, run_id)
    assert estimate_tokens(json.dumps(team, ensure_ascii=False)) <= scope_assemble.NOTES_TOKENS
    assert team["conventions"][0]["note_id"] == pinned["subject_id"]
    carried = len(team["conventions"]) + len(team["background"])
    assert team["omitted"] > 0 and carried + team["omitted"] == len(topics) + 1
    assert "memory.search" in team["how_to_use"]


def test_recipe_is_the_union_of_loaded_skills_capped_by_the_server(setup):
    def skill(value):
        return SimpleNamespace(metadata={"context_schema": {"x-memory": value}})

    assert scope_assemble.recipe(()) == scope_assemble.DEFAULT_RECIPE
    one = skill({"scope_notes": {"anchors": ["project"], "budget_tokens": 300,
                                 "pinned_only": True}})
    two = skill({"scope_notes": {"anchors": ["category"], "budget_tokens": 5000},
                 "scope_recent": {"budget_tokens": 9000}})
    merged = scope_assemble.recipe((one, two))
    assert merged["scope_notes"] == {"anchors": ["project", "category"],
                                     "customer_tag": "same_only", "pinned_only": False,
                                     "budget_tokens": 800}
    assert merged["scope_recent"] == {"budget_tokens": 400}
    # A recipe that names no team notes loads none: the model cannot ask for more.
    save(setup, "只在声明了配方的场景带入")
    pin = save(setup, "置顶的约定总是先带", pinned=True)
    run_id, _ = start(setup, goal="没有声明团队备忘的技能")
    assert assemble(setup, run_id, skills=(skill({"personal": ["notes"]}),)) == (None, None)
    pinned_only, _ = start(setup, goal="只带置顶")
    team, _recent = assemble(setup, pinned_only, skills=(one, skill(
        {"scope_notes": {"anchors": ["category"], "pinned_only": True}})))
    assert [e["note_id"] for e in team["conventions"]] == [pin["subject_id"]]


def test_memory_search_finds_team_notes_in_the_run_scope_only(setup):
    found = save(setup, "跌落测试高度按 1.2 米执行")
    save(setup, "周报每周五发")
    run_id, _ = start(setup, goal="跌落测试怎么做")
    result = search(setup, run_id, "跌落测试 高度")
    assert result["unavailable_kinds"] == [] and "kinds_note" not in result
    assert result["scope_notes_status"] == "completed" and "不是业务事实" in result[
        "scope_notes_policy"]
    assert [card["note_id"] for card in result["scope_notes"]] == [found["subject_id"]]
    card = result["scope_notes"][0]
    assert card["kind"] == "scope_note" and card["zone"] == "constraint"
    assert card["statement"] == "跌落测试高度按 1.2 米执行"
    assert stored(setup, run_id)["memory_usage"]["scope_notes"][-1] == {
        "note_id": found["subject_id"], "revision": 1, "zone": "search"}
    # 不进记忆模式: team notes are business context and are still searched.
    off, _ = start(setup, goal="跌落测试", memory_off=True)
    quiet = search(setup, off, "跌落测试")
    assert quiet["status"] == "memory_off"
    assert [card["note_id"] for card in quiet["scope_notes"]] == [found["subject_id"]]
    # A personal Run has no business scope; another tenant's person has nothing to find.
    personal, _ = start(setup, personal=True, goal="跌落测试")
    alone = search(setup, personal, "跌落测试", personal=True)
    assert alone["scope_notes"] == [] and alone["scope_notes_status"] == "personal_scope"


def test_a_project_run_loads_its_project_and_category_notes_with_scope_recency(setup):
    project = create_g0_project(setup, visibility="category", name="Synthetic pump project")
    category_note = save(setup, "品类口径：价格带按出厂价")
    project_note = save(setup, "本项目样件编号按 项目-批次-序号",
                        at=anchor(setup, "project", project.project_id),
                        product=project.product_id)
    run_id, _ = start(setup, goal="安排样件", product_id=project.product_id,
                      project_id=project.project_id)
    team, recent = assemble(setup, run_id)
    # The most specific scope comes first within a zone; both levels are on the chain.
    assert [e["note_id"] for e in team["conventions"]] == [project_note["subject_id"],
                                                         category_note["subject_id"]]
    assert [e["scope"]["kind"] for e in team["conventions"]] == ["project", "category"]
    assert recent["scope"] == {"kind": "project", "title": "Synthetic pump project"}
    assert [line["note_id"] for line in recent["note_changes"]] == [project_note["subject_id"]]
    assert isinstance(recent["activity"], list)
    assert estimate_tokens(json.dumps(recent, ensure_ascii=False)) <= scope_assemble.RECENT_TOKENS
    found = search(setup, run_id, "样件 编号")
    assert [card["note_id"] for card in found["scope_notes"]] == [project_note["subject_id"]]
    # A category Run does not reach down into the project's notes.
    wide, _ = start(setup, goal="品类里的问题")
    assert [e["note_id"] for e in assemble(setup, wide)[0]["conventions"]] == [
        category_note["subject_id"]]
    assert search(setup, wide, "样件 编号")["scope_notes"] == []
