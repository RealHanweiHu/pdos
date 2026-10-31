"""Twelve native control observations; root alone runs the verified isolated PG.

Scenario tool prose is never inserted as a tool result. Every READ/citation is
issued by the registered production graph. Scripted summaries are not answers
under evaluation, measured model usage, or golden cases.
"""

import json
from copy import copy
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from g0_fixture import create_g0_project

from pdos_next.agent_kernel.work_state import STATE_TOKENS
from pdos_next.database import tenant_session
from pdos_next.models import Artifact
from tests.agent_kernel.eval_v0_ctx04_plan_support import (
    TITLES,
    assert_native_tasks,
    native_plan,
)
from tests.agent_kernel.eval_v0_history_state_support import (
    CASES,
    ScriptedProvider,
    assert_immutable_artifacts,
    change,
    choice,
    execute,
    finish,
    knowledge,
    materialized,
    observation,
    select_context,
)
from tests.agent_kernel.test_context_corrections_pg import read_state
from tests.agent_kernel.test_run_continuation import start
from tests.enterprise_search.test_retrieval_pg import register
from tests.preproject.test_g0 import post, request
from tests.work_management_pg import test_workflow as flow


def context_of(run):
    return json.loads(run["requests"][0][0]["content"])["context"]


def ctx01(setup, case, focus):
    turns, raw = materialized(case)
    assert len(turns) == 61 and raw["sha256"] == case["replay_input"]["input_measurement"]["sha256"]
    source = register(setup, "EVAL-C01-S1 B07试验记录", (
        "B07；样件L-42；密封圈EPDM；硬度70 Shore A；保压30秒；压降12 kPa；"
        "环境温度未记录；验收判据未提供。"))
    constraints = {0: ["全程只讨论 B07 轮次，不写业务对象。"], 8: ["不写客户姓名"],
        22: ["不要纳入 B08"], 24: ["简报不要写责任人"],
        28: ["以后单位都保留 kPa，不换算成 bar。"], 30: ["不要帮我生成发送动作"],
        54: ["无需写建议，只复盘原观察。"]}
    runs, ids, current, session_id = [], [], None, None
    for index_ in range(0, 60, 2):
        arguments = {"continue_from_run_id": str(current)} if current else {}
        if index_ == 2:
            arguments["sources"] = [{"artifact_id": str(source), "expected_revision": 1}]
        current, accepted = start(setup, goal=turns[index_]["content"], **arguments)
        session_id = accepted["session_id"]
        provider = ScriptedProvider(summary=turns[index_ + 1]["content"], constraints=[
            {"run_id": str(current), "text": text} for text in constraints.get(index_, ())])
        run = execute(setup, current, turns[index_]["content"], focus, provider)
        assert run["output"]["status"] == "completed", run["output"]
        assert provider.calls == 1 and run["output"]["summary"] == turns[index_ + 1]["content"]
        runs.append(run)
        ids.append(str(current))
    final, _ = start(setup, continue_from_run_id=str(current), goal=case["final_prompt"])
    # The script selects an actual old ancestor to test the authorized lookup
    # path. Locating that cursor semantically is deliberately not a model score.
    provider = ScriptedProvider(history={"before": ids[4], "page_size": 2})
    checked = execute(setup, final, case["final_prompt"], focus, provider)
    assert checked["output"]["status"] == "completed", checked["output"]
    initial = context_of(checked)["conversation"]
    assert len(initial["turns"]) == 10 and ids[2] not in str(initial)
    historical = next(value for value in checked["values"] if "turns" in value)
    old = {turn["run_id"]: turn for turn in historical["turns"]}
    assert ids[2] in old and ids[3] in old
    assert "L-42" in old[ids[2]]["goal"] and "12 kPa" in old[ids[3]]["goal"]
    assert any(row["tool"] == "conversation.history" for row in checked["reads"])
    assert all(row["execution_binding"]["kind"] == "read" for row in checked["reads"])
    assert sum(run["provider_dispatches"] for run in runs) == 30
    return observation(case, focus, [*runs, checked], {"source_type": "artifact",
        "source_id": str(source), "source_revision": 1, "session_id": session_id,
        "history_run_ids": ids, "history_rounds": 30, "final_run_id": str(final),
        "raw_material_measurement": raw, "raw_is_not_compiled_pressure": True,
        "early_read_run_ids": [ids[2], ids[3]],
        "history_selector_basis": "scripted native ancestor; cursor selection quality not scored",
        "controlled_read_bindings": [row["execution_binding"] for row in checked["reads"]]})


def ctx04(setup, case, focus):
    source = register(setup, "S4 P8复验待办资料", case["turns"][1]["content"])
    p8 = create_g0_project(setup, visibility="category", name="松屿 P8",
        purpose="合成复验待办范围", source={"type": "artifact", "id": str(source), "version": 1,
            "line": 1, "quote": case["turns"][1]["content"]})
    p9_setup = copy(setup)
    p9 = create_g0_project(p9_setup, visibility="category", name="松屿 P9",
        purpose="相邻项目，非本题选定范围")
    work = SimpleNamespace(setup=setup, project_id=UUID(p8.project_id), source={
        "kind": "artifact", "id": str(source), "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(
            case["turns"][1]["content"].encode()).hexdigest()})
    plan = native_plan(work)
    task_ids, receipts, latest_receipts = [], [], {}
    for key, title in TITLES.items():
        _, receipt = flow.execute(work, flow.CREATE, flow.payload(work, title=title,
            goal="仅登记合成复验待办，不代表已接受承诺。",
            outcomes=[{"key": "review", "text": "复验记录", "required": True}],
            plan_task={"id": plan["tasks"][key]["id"], "revision": plan["revision"]}))
        task_ids.append(receipt["result"]["task_id"])
        receipts.append(receipt["id"])
        latest_receipts[key] = receipt
    work.task_id = UUID(task_ids[0])
    first_task = flow.task(work, "proposed")
    _, assigned = flow.execute(work, flow.ASSIGN, flow.payload(work, task=first_task,
        assignee_id=str(setup.peer), recipient_id=str(setup.human)))
    receipts.append(assigned["id"])
    latest_receipts["pressure"] = assigned
    current, accepted = start(setup, goal=case["turns"][0]["content"],
        product_id=p8.product_id, project_id=p8.project_id,
        sources=[{"artifact_id": str(source), "expected_revision": 1}])
    finish(setup, current, case["turns"][2]["content"], [
        "只看当前项目、只看当前有效记录", "按“待办/负责人/已登记日期/缺项”四列"])
    for turn_index in (3, 6):
        current, _ = start(setup, continue_from_run_id=str(current),
            goal=case["turns"][turn_index]["content"])
        summary = case["turns"][4]["content"] if turn_index == 3 else "原请求已记录，未猜测负责人。"
        finish(setup, current, summary,
            ["别帮我猜没人负责的那一行。"] if turn_index == 6 else ())
    final, _ = start(setup, continue_from_run_id=str(current), goal=case["final_prompt"])
    provider = ScriptedProvider(plan=[("category.read", {})])
    checked = execute(setup, final, case["final_prompt"], focus, provider)
    assert checked["output"]["status"] == "completed", checked["output"]
    context = context_of(checked)
    assert context["project"]["id"] == p8.project_id
    actual_input = json.dumps(checked["requests"], ensure_ascii=False)
    assert p9.project_id not in actual_input and "松屿 P9" not in actual_input
    assert "郑禾" not in actual_input and "2026-11-02" not in actual_input
    assert {row["text"] for row in context["work_state"]["constraints"]} == {
        "只看当前项目、只看当前有效记录", "按“待办/负责人/已登记日期/缺项”四列",
        "别帮我猜没人负责的那一行。"}
    facts = context["project"]["current_facts"]
    verified = assert_native_tasks(work, plan, latest_receipts, facts)
    assert {row["task_id"] for row in facts["tasks"]} == set(task_ids)
    return observation(case, focus, [checked], {"session_id": accepted["session_id"],
        "current_project_id": p8.project_id, "excluded_neighbor_project_id": p9.project_id,
        "task_ids": task_ids, "native_receipt_ids": receipts,
        "assignee_alias": {"周柯": str(setup.peer)}, "document_source_id": str(source),
        "native_plan": plan, "verified_current_facts": verified,
        "final_run_id": str(final)})


def ctx05(setup, case, focus):
    first = knowledge(setup, "A-17 v1；空载噪声78 dB。", label="S5-A")
    old_second = knowledge(setup, "A-71 v1；空载噪声尚未记录。", label="A-71初版")
    second = knowledge(setup, "A-71，版本2，空载噪声82 dB。", previous=old_second, label="S5-B")
    parent, accepted = start(setup, goal=case["turns"][0]["content"])
    finish(setup, parent, case["turns"][2]["content"], [
        "噪声上限仍用80 dB", "不要写通过结论"])
    _, initial = select_context(setup, accepted["session_id"], "replace_focus", [choice(first)])
    _, changed = select_context(setup, accepted["session_id"], "replace_focus", [choice(second)])
    assert initial["context_selection"]["focus"]["source_id"] == first["source_id"]
    assert changed["context_selection"]["focus"]["source_id"] == second["source_id"]
    assert changed["constraints"] == initial["constraints"]
    corrected, _ = start(setup, continue_from_run_id=str(parent),
        goal=case["turns"][3]["content"], context_revision=changed["revision"])
    finish(setup, corrected, case["turns"][5]["content"])
    final, _ = start(setup, continue_from_run_id=str(corrected), goal=case["final_prompt"])
    provider = ScriptedProvider(extract=True, plan=[("assistant.search", {"query": "空载噪声",
        "source_types": ["knowledge"], "include_history": True})])
    checked = execute(setup, final, case["final_prompt"], focus, provider)
    assert checked["output"]["status"] == "completed", checked["output"]
    state = context_of(checked)["work_state"]
    assert state["context_selection"]["focus"]["source_id"] == second["source_id"]
    assert {row["text"] for row in state["constraints"]} == {
        "噪声上限仍用80 dB", "不要写通过结论"}
    searched = next(value for value in checked["values"] if "items" in value)
    assert {row["source_id"] for row in searched["items"]} == {second["source_id"]}
    assert "82 dB" in str(next(value["rows"] for value in checked["values"] if "rows" in value))
    assert_immutable_artifacts(setup, [first, old_second, second])
    return observation(case, focus, [checked], {"source_family": "knowledge",
        "old_focus": first, "new_focus": second, "state_before": initial,
        "state_after": changed, "final_run_id": str(final)})


def ctx06(setup, case, focus):
    first = knowledge(setup, "EVALCTX06扭矩；三月工艺0.6 N·m。", label="S6-A")
    middle = knowledge(setup, "EVALCTX06扭矩；过渡版未选作比较。", previous=first, label="过渡版")
    current = knowledge(setup, "EVALCTX06扭矩；九月现行工艺0.8 N·m。",
                        previous=middle, label="S6-B")
    denied = post(setup, request(setup, "evidence.artifact.register", {
        "title": "S6-C私有夹具标记", "content": "S6-C_PRIVATE_BODY_NEVER_VISIBLE",
        "source_label": "仅作普通RLS负例", "visibility": "private",
    }), actor=setup.peer)
    assert denied.status_code == 200, denied.text
    hidden_id = UUID(denied.json()["subject_id"])
    parent, accepted = start(setup, goal=case["turns"][0]["content"])
    provider = ScriptedProvider(extract=True, plan=[("assistant.search", {"query": "EVALCTX06扭矩",
        "source_types": ["knowledge"], "include_history": True})],
        summary=case["turns"][2]["content"])
    initial_run = execute(setup, parent, case["turns"][0]["content"], focus, provider)
    assert initial_run["output"]["status"] == "completed", initial_run["output"]
    found = next(value for value in initial_run["values"] if "items" in value)
    citation = next(row["citation_id"] for row in found["items"]
                    if row["source_id"] == first["source_id"])
    _, excluded = change(setup, accepted["session_id"], "exclude_source", item_id=citation)
    assert any(row["id"] == citation for row in excluded["exclusions"])
    _, removed = change(setup, accepted["session_id"], "remove_exclusion", item_id=citation)
    assert not removed["exclusions"] and removed["revision"] == excluded["revision"] + 1
    parent2, _ = start(setup, continue_from_run_id=str(parent),
        goal=case["turns"][3]["content"], context_revision=removed["revision"])
    finish(setup, parent2, "本人排除条目已按实际工作状态删除；权限未扩大。")
    parent3, _ = start(setup, continue_from_run_id=str(parent2), goal=case["turns"][5]["content"])
    finish(setup, parent3, "九月版本的当前性以原生版本指针为准。")
    final, _ = start(setup, continue_from_run_id=str(parent3), goal=case["final_prompt"])
    provider2 = ScriptedProvider(extract=True, plan=[("assistant.search", {"query": "EVALCTX06扭矩",
        "source_types": ["knowledge"], "include_history": True})])
    checked = execute(setup, final, case["final_prompt"], focus, provider2)
    assert checked["output"]["status"] == "completed", checked["output"]
    items = next(value for value in checked["values"] if "items" in value)["items"]
    by_id = {row["source_id"]: row for row in items}
    assert first["source_id"] in by_id and current["source_id"] in by_id
    assert not by_id[first["source_id"]]["is_current"] and by_id[current["source_id"]]["is_current"]
    extracted = next(value["rows"] for value in checked["values"] if "rows" in value)
    assert "0.6 N·m" in str(extracted) and "0.8 N·m" in str(extracted)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        assert session.get(Artifact, hidden_id) is None
    assert str(hidden_id) not in str(checked["requests"]) + str(initial_run["requests"])
    assert "S6-C_PRIVATE_BODY_NEVER_VISIBLE" not in str(checked["requests"])
    assert not context_of(checked)["work_state"]["exclusions"]
    assert_immutable_artifacts(setup, [first, middle, current])
    return observation(case, focus, [initial_run, checked], {"source_family": "knowledge",
        "history_source": first, "current_source": current, "excluded_citation_id": citation,
        "exclusion_revision": excluded["revision"], "removed_revision": removed["revision"],
        "private_negative_source_id": str(hidden_id), "private_read_requests": 0,
        "final_run_id": str(final)})


def ctx07(setup, case, focus):
    first = knowledge(setup, "S7-A；复验观察窗口30秒。", label="S7-A v1")
    parent, accepted = start(setup, goal=case["turns"][0]["content"])
    provider = ScriptedProvider(extract=True, plan=[("assistant.search", {"query": "复验观察窗口",
        "source_types": ["knowledge"]})], summary=case["turns"][2]["content"])
    old = execute(setup, parent, case["turns"][0]["content"], focus, provider)
    assert old["output"]["status"] == "completed", old["output"]
    assert "30秒" in str(next(value["rows"] for value in old["values"] if "rows" in value))
    second = knowledge(setup, "S7-A；复验观察窗口45秒；生效日期2026-10-21。",
                       previous=first, label="S7-A v2")
    current, _ = start(setup, continue_from_run_id=str(parent), goal=case["turns"][4]["content"])
    finish(setup, current, "需要重读实际v2；没有把历史30秒改成45秒。")
    final, _ = start(setup, continue_from_run_id=str(current), goal=case["final_prompt"])
    provider2 = ScriptedProvider(extract=True, plan=[("assistant.search", {"query": "复验观察窗口",
        "source_types": ["knowledge"]})])
    checked = execute(setup, final, case["final_prompt"], focus, provider2)
    assert checked["output"]["status"] == "completed", checked["output"]
    past = next(row for row in context_of(checked)["conversation"]["turns"]
                if row["run_id"] == str(parent))
    assert past["outcome_state"] == "updated"
    assert past["historical_outcome"]["summary"] == case["turns"][2]["content"]
    assert "45秒" not in past["historical_outcome"]["summary"]
    items = next(value for value in checked["values"] if "items" in value)["items"]
    assert {row["source_id"] for row in items} == {second["source_id"]}
    assert "45秒" in str(next(value["rows"] for value in checked["values"] if "rows" in value))
    assert second["lineage_id"] == first["lineage_id"] and second["version"] == 2
    assert_immutable_artifacts(setup, [first, second])
    return observation(case, focus, [old, checked], {"source_family": "knowledge",
        "same_logical_lineage": first["lineage_id"], "old_source": first, "new_source": second,
        "old_read_bindings": [row["execution_binding"] for row in old["reads"]],
        "current_read_bindings": [row["execution_binding"] for row in checked["reads"]],
        "historical_outcome_state": past["outcome_state"], "session_id": accepted["session_id"],
        "scenario_read_date_is_not_runtime_clock": True, "final_run_id": str(final)})


def ctx10(setup, case, focus):
    constraints = case["turns"][0]["content"].splitlines()[1:]
    assert len(constraints) == 24 and len(set(constraints)) == 24
    parent, accepted = start(setup, goal=case["turns"][0]["content"])
    finish(setup, parent, case["turns"][1]["content"], constraints)
    state = read_state(setup, accepted["session_id"])
    assert [row["text"] for row in state["constraints"]] == constraints
    assert state["estimated_tokens"] > STATE_TOKENS and state["context_incomplete"]
    current, _ = start(setup, continue_from_run_id=str(parent), goal=case["turns"][3]["content"])
    finish(setup, current, "尚未查工位记录，等待必要条件能够完整携带。")
    final, _ = start(setup, continue_from_run_id=str(current), goal=case["final_prompt"])
    provider = ScriptedProvider()
    checked = execute(setup, final, case["final_prompt"], focus, provider)
    output = checked["output"]
    assert output["status"] == "partial" and output["result"]["context_incomplete"]
    assert output["result"]["missing"] and provider.calls == 0
    assert not checked["context_budget"] and not checked["reads"]
    actual_state = checked["work_state"]
    assert len(actual_state["constraints"]) == 24
    assert actual_state["estimated_tokens"] > STATE_TOKENS
    preflight = {"stage": "registered_graph_required_work_state", "context_incomplete": True,
        "missing": output["result"]["missing"],
        "state_estimated_tokens": actual_state["estimated_tokens"],
        "state_limit_tokens": STATE_TOKENS, "state_constraint_count": 24,
        "output": output, "window": focus + 2048 + 4000}
    checked["context_budget"].append(preflight)
    return observation(case, focus, [checked], {"session_id": accepted["session_id"],
        "constraint_origin_run_id": str(parent), "constraint_count": 24,
        "first_registered_state_revision": state["revision"],
        "work_state_revision": actual_state["revision"], "final_run_id": str(final),
        "preflight_stage": preflight["stage"], "model_ledger_count": 0})


@pytest.mark.parametrize("focus", [48000, 64000], ids=["F48000", "F64000"])
@pytest.mark.parametrize("case_id", ["CTX-01", "CTX-04", "CTX-05", "CTX-06", "CTX-07", "CTX-10"])
def test_eval_v0_history_state_native_controls(setup, case_id, focus):
    builders = {"CTX-01": ctx01, "CTX-04": ctx04, "CTX-05": ctx05,
                "CTX-06": ctx06, "CTX-07": ctx07, "CTX-10": ctx10}
    builders[case_id](setup, CASES[case_id], focus)
