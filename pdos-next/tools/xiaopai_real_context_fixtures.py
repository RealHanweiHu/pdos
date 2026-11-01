"""Prepare V0 context fixtures; this module never dispatches a model or workflow.

The CLI is offline. ``prepare_case`` and ``apply_control`` are explicitly invoked
by the root's guarded isolated-DB runner. Actual turns must be posted to the
normal HTTP API and awaited through Temporal/LangGraph. Scenario assistant/tool
messages are source material, never messages injected into a model request.
"""

import argparse
import hashlib
import json
import os
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
FOCUS = (48000, 64000)
REUSE = {
    "history": "pdos-next/server/tests/agent_kernel/test_eval_v0_history_state_pg.py",
    "source": "pdos-next/server/tests/enterprise_search/test_eval_v0_source_context_pg.py",
    "candidate": "pdos-next/server/tests/agent_kernel/test_eval_v0_handle_candidate_pg.py",
}


class FixtureBlocked(RuntimeError):
    """A required native fact is absent; do not score a fabricated scenario."""


def cases():
    value = json.loads(QUESTIONS.read_text())
    if not value["synthetic"] or value["trusted_root"] or value["case_count"] != 12:
        raise ValueError("Expected the unchanged synthetic, non-golden V0 context set")
    return {row["id"]: row for row in value["cases"]}


def materialized(case):
    """Reproduce the frozen expansion only to select original user turns/docs."""
    turns = deepcopy(case["turns"])
    replay = case.get("replay_input")
    if replay:
        rule = replay["expansion_rule"]
        records = {row["record_id"]: row for row in replay["records"]}
        if (replay["repeat_each_record"] != 1
                or rule["operation"] != "append_to_existing_turn_content"
                or len(records) != len(replay["record_order"])
                or set(records) != set(replay["record_order"])):
            raise ValueError("Expansion identity/order changed")
        for identity in replay["record_order"]:
            row = records[identity]
            turns[row[rule["target_index_field"]]]["content"] += (
                rule["prefix"] + rule["line_joiner"].join(row["lines"]) + rule["suffix"])
    turns.append({"role": "user", "content": case["final_prompt"]})
    if replay:
        encoded = json.dumps(turns, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != replay["input_measurement"]["sha256"]:
            raise ValueError("Frozen materialized input SHA256 changed")
    return turns


def run_spec(case_id, focus):
    """An unbound, inspectable plan; no assistant/tool scenario replay exists."""
    if focus not in FOCUS:
        raise ValueError("Only the paired F48000/F64000 profiles are authorized here")
    case = cases()[case_id]
    steps = [{"turn_index": index, "goal": row["content"],
              "phase": "final" if index == len(case["turns"]) else "history",
              "before": [], "after": []}
             for index, row in enumerate(materialized(case)) if row["role"] == "user"]
    controls = {
        "CTX-05": [(0, "after", "select_old_focus"), (1, "before", "select_new_focus")],
        "CTX-06": [(0, "after", "exclude_old_source"), (1, "before", "remove_old_exclusion")],
        "CTX-07": [(0, "after", "publish_current_knowledge")],
        "CTX-08": [(0, "after", "revoke_private_audience")],
        "CTX-10": [(0, "after", "require_all_24_constraints")],
        "CTX-11": [(1, "after", "require_old_pending_candidate")],
    }
    # CTX11 needs the ordinary explicit source-read -> work-followup entry first.
    if case_id == "CTX-11":
        steps.insert(0, {"turn_index": None, "phase": "binding_precondition",
                        "goal": "只读取明确选择的S11-A复验记录，不保存或指派任务。",
                        "before": [], "after": []})
    for ordinal, timing, action in controls.get(case_id, ()):
        steps[ordinal][timing].append(action)
    source_family = "source" if case_id in {"CTX-02", "CTX-03", "CTX-08", "CTX-12"} else (
        "candidate" if case_id in {"CTX-09", "CTX-11"} else "history")
    return {
        "version": "xiaopai-real-context-fixture/v1", "case_id": case_id,
        "title": case["title"], "f_budget_tokens": focus,
        "route_metadata": {"context_window_tokens": focus + 6048, "max_output_tokens": 2048},
        "question_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(),
        "setup_reuse": REUSE[source_family], "bindings": {}, "steps": steps,
        "api_scope": "category",
        "binding_status": "partial" if case_id == "CTX-09" else "pending_native_setup",
        "execution_class": ("control_only" if case_id == "CTX-10" else
                            "unbound_scenario_control" if case_id == "CTX-09" else
                            "answer_evaluation"),
        "dispatch_contract": "normal HTTP -> Temporal workflow -> Activity -> registered LangGraph",
        "history_contract": "original user turns only; each is a separate continued Run",
        "assistant_transcript_injected": False, "scenario_tool_messages_injected": False,
        "actual_model_calls": 0, "model_quality_score": None,
        "pairing_requirement": ("same model/prompt/tools/schema/ACL/material and sampling; "
                                "record actual history/state digests"),
        "limits": (["Original exact 3->6/9 result.read scenario remains "
                    "partial/needs_case_revision; "
                    "natural 9-item directory fits a single tool result. No failure is injected."]
                   if case_id == "CTX-09" else []),
        "evidence_required": ["HTTP acceptance", "Temporal execution reference", "actual Run IDs",
                              "READ bindings and citations",
                              "actual provider usage/cache/latency/cost",
                              "context snapshots/budgets/reductions", "native control outcomes"],
    }


def require_isolated_target(setup):
    """No .env fallback, no connection, no credentials in the error message."""
    explicit = os.environ.get("TEST_DATABASE_URL", "")
    target = urlsplit(explicit.replace("postgresql+psycopg://", "postgresql://", 1))
    actual_url = setup.engine.url.render_as_string(hide_password=False)
    actual = urlsplit(actual_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if (target.scheme != "postgresql" or target.hostname not in {"localhost", "127.0.0.1", "::1"}
            or target.path != "/pdos_test"
            or (target.hostname, target.port or 5432, target.path)
            != (actual.hostname, actual.port or 5432, actual.path)):
        raise FixtureBlocked(
            "Root must bind explicit TEST_DATABASE_URL to its verified local pdos_test")


def prepare_case(setup, case_id, focus):
    """Root-only native synthetic setup; never creates an AgentRun or answer.

    ``setup`` is the existing isolated ``IsolatedFixture`` (server/tests on
    PYTHONPATH). Commands retain Human actor and ordinary domain validation.
    Only CTX08 reuses the old fixture's isolated ObjectAudience seed/control.
    """
    require_isolated_target(setup)
    # The existing G0 helper advances setup.product for subsequent native commands.
    # Keep that mutation local to this fixture, not the root's runtime identity.
    setup = copy(setup)
    spec, case = run_spec(case_id, focus), cases()[case_id]
    bindings = spec["bindings"]
    if case_id in {"CTX-02", "CTX-03", "CTX-08", "CTX-12"}:
        from tests.enterprise_search.test_eval_v0_source_context_pg import register_sources

        sources, audience = register_sources(setup, case)
        bindings.update(sources=sources, private_audience_id=str(audience) if audience else None)
        if case_id == "CTX-12":
            from tests.enterprise_search.test_eval_v0_source_context_pg import ctx12_queries

            bindings["diagnostic_full_span_queries"] = list(ctx12_queries(case))
            bindings["selection_variant"] = "category_scoped_read_without_fixed_pins"
            spec["limits"].append("Eight explicit fixed source pins can exceed STATE_TOKENS=1500; "
                                  "use category-scoped reads and preserve the ordinary state cap.")
        if case_id in {"CTX-03", "CTX-08"}:
            spec["limits"].append(
                "This batch uses category-scoped HTTP Runs for fixture isolation; "
                "the old scripted control used personal scope. Record the variant.")
    elif case_id in {"CTX-05", "CTX-06", "CTX-07"}:
        from tests.agent_kernel.eval_v0_history_state_support import knowledge

        if case_id == "CTX-05":
            first = knowledge(setup, "A-17 v1；空载噪声78 dB。", label="S5-A")
            old_second = knowledge(setup, "A-71 v1；空载噪声尚未记录。", label="A-71初版")
            current = knowledge(setup, "A-71，版本2，空载噪声82 dB。",
                                previous=old_second, label="S5-B")
            bindings.update(old_focus=first, new_focus=current)
        elif case_id == "CTX-06":
            from tests.preproject.test_g0 import post, request

            first = knowledge(setup, "EVALCTX06扭矩；三月工艺0.6 N·m。", label="S6-A")
            middle = knowledge(setup, "EVALCTX06扭矩；过渡版未选作比较。",
                               previous=first, label="过渡版")
            current = knowledge(setup, "EVALCTX06扭矩；九月现行工艺0.8 N·m。",
                                previous=middle, label="S6-B")
            response = post(setup, request(setup, "evidence.artifact.register", {
                "title": "S6-C私有夹具标记", "content": "S6-C_PRIVATE_BODY_NEVER_VISIBLE",
                "source_label": "仅作普通RLS负例", "visibility": "private"}), actor=setup.peer)
            if response.status_code != 200:
                raise FixtureBlocked("Native private negative source registration failed")
            bindings.update(history_source=first, current_source=current,
                            private_negative_source_id=response.json()["subject_id"])
        else:
            bindings["old_source"] = knowledge(setup, "S7-A；复验观察窗口30秒。", label="S7-A v1")
    elif case_id in {"CTX-01", "CTX-04", "CTX-11"}:
        from tests.enterprise_search.test_retrieval_pg import index, register

        body = {"CTX-01": "B07；样件L-42；密封圈EPDM；硬度70 Shore A；保压30秒；压降12 kPa；"
                          "环境温度未记录；验收判据未提供。",
                "CTX-04": case["turns"][1]["content"],
                "CTX-11": "\n".join([f"合成复验记录目录行{n}" for n in range(1, 8)]
                                      + ["湿热复验原件尚未归档"])}[case_id]
        title = {"CTX-01": "EVAL-C01-S1 B07试验记录", "CTX-04": "S4 P8复验待办资料",
                 "CTX-11": "S11-A 合成复验记录"}[case_id]
        identity = register(setup, title, body)
        index(setup, identity)
        bindings["source"] = {"artifact_id": str(identity), "expected_revision": 1}
        if case_id in {"CTX-04", "CTX-11"}:
            from g0_fixture import create_g0_project

            project = create_g0_project(setup, visibility="category",
                name="松屿 P8" if case_id == "CTX-04" else "合成当前项目 P11",
                purpose="隔离合成上下文评测；不代表生产资格")
            bindings.update(project_id=project.project_id, product_id=project.product_id)
        if case_id == "CTX-04":
            _ctx04_tasks(setup, spec, body)
    elif case_id == "CTX-09":
        from tests.agent_kernel.eval_v0_ctx09_directory_support import native_directory

        bindings["directory"] = native_directory(setup, case)
    if case_id != "CTX-09":
        spec["binding_status"] = "setup_ready_preconditions_unverified"
    return spec


def _ctx04_tasks(setup, spec, body):
    from g0_fixture import create_g0_project
    from tests.agent_kernel.eval_v0_ctx04_plan_support import TITLES, native_plan
    from tests.work_management_pg import test_workflow as flow

    bindings = spec["bindings"]
    work = SimpleNamespace(setup=setup, project_id=UUID(bindings["project_id"]), source={
        "kind": "artifact", "id": bindings["source"]["artifact_id"], "revision": 1,
        "position": "line:1;quote_sha256:" + hashlib.sha256(body.encode()).hexdigest()})
    plan = native_plan(work)
    tasks, receipts = {}, []
    for key, title in TITLES.items():
        _, receipt = flow.execute(work, flow.CREATE, flow.payload(work, title=title,
            goal="仅登记合成复验待办，不代表已接受承诺。",
            outcomes=[{"key": "review", "text": "复验记录", "required": True}],
            plan_task={"id": plan["tasks"][key]["id"], "revision": plan["revision"]}))
        tasks[key] = receipt["result"]["task_id"]
        receipts.append(receipt["id"])
    work.task_id = UUID(tasks["pressure"])
    _, receipt = flow.execute(work, flow.ASSIGN, flow.payload(work,
        task=flow.task(work, "proposed"), assignee_id=str(setup.peer),
        recipient_id=str(setup.human)))
    receipts.append(receipt["id"])
    other = create_g0_project(copy(setup), visibility="category", name="松屿 P9",
                              purpose="相邻项目，非本题选定范围")
    bindings.update(native_plan=plan, task_ids=tasks, native_receipt_ids=receipts,
                    excluded_neighbor_project_id=other.project_id,
                    assignee_alias={"周柯": str(setup.peer)})


def run_payload(spec, ordinal, previous=None, *, context_revision=None):
    """Build one ordinary API payload; root supplies the actual previous Run."""
    step, bindings = spec["steps"][ordinal], spec["bindings"]
    payload = {"goal": step["goal"]}
    if previous is not None:
        payload["continue_from_run_id"] = previous["run_id"]
    elif ordinal:
        raise FixtureBlocked("A continued turn needs the actual previous Run")
    elif "project_id" in bindings:
        payload.update(project_id=bindings["project_id"], product_id=bindings["product_id"])
    if context_revision is not None:
        payload["context_revision"] = context_revision
    case_id = spec["case_id"]
    if ((case_id == "CTX-01" and step["turn_index"] == 2)
            or (case_id == "CTX-04" and ordinal == 0) or case_id == "CTX-11"):
        payload["sources"] = [bindings["source"]]
    if case_id in {"CTX-02"} and ordinal == 0:
        payload["sources"] = [{"artifact_id": row["artifact_id"],
                               "expected_revision": row["artifact_snapshot_revision"]}
                              for row in bindings["sources"].values()]
    if case_id == "CTX-12" and step["phase"] == "final":
        payload["lookup_depth"] = "deep"
    if case_id == "CTX-11" and ordinal:
        output = (previous or {}).get("output", {})
        ids = output.get("result", {}).get("assistant", {}).get("citation_ids", [])
        if not ids:
            raise FixtureBlocked("work_followup_action needs actual preceding verified citations")
        payload["work_followup_action"] = {"project_id": bindings["project_id"],
                                            "citation_ids": ids, "assignment": None}
    return payload


def apply_control(setup, spec, action, previous):
    """Apply only native fixture controls between completed actual Runs.

    Root supplies previously collected evidence in ``previous``: run_id,
    session_id, read_source_ids, carried_source_ids, citation_source_ids, issued_citations,
    output and candidates. Missing evidence blocks only the dependent scenario.
    No Run/ToolCall/READ/result/constraint/candidate rows are written here.
    """
    require_isolated_target(setup)
    from tests.agent_kernel.eval_v0_history_state_support import (
        change,
        choice,
        knowledge,
        select_context,
    )
    from tests.agent_kernel.test_context_corrections_pg import read_state

    bindings = spec["bindings"]
    session_id = previous["session_id"]
    if action in {"select_old_focus", "select_new_focus"}:
        key = "old_focus" if action == "select_old_focus" else "new_focus"
        before, after = select_context(setup, session_id, "replace_focus", [choice(bindings[key])])
        if after["constraints"] != before["constraints"]:
            raise FixtureBlocked("Focus correction changed unrelated constraints")
        return {"action": action, "before": before, "after": after,
                "context_revision": after["revision"]}
    if action == "exclude_old_source":
        state = read_state(setup, session_id)
        source = bindings["history_source"]
        visible = {row["citation_id"] for row in state["citations"]}
        citation = next((row.get("origin_citation_id", row["citation_id"])
                         for row in previous.get("issued_citations", [])
                         if row.get("source_id") == source["source_id"]
                         and row.get("origin_citation_id", row["citation_id"]) in visible), None)
        if citation is None:
            raise FixtureBlocked(
                "CTX06 needs a real carried historical-source citation before exclusion")
        before, after = change(setup, session_id, "exclude_source", item_id=citation)
        bindings["excluded_citation_id"] = citation
        return {"action": action, "before": before, "after": after,
                "context_revision": after["revision"]}
    if action == "remove_old_exclusion":
        identity = bindings.get("excluded_citation_id")
        if not identity:
            raise FixtureBlocked("CTX06 exclusion was not established")
        before, after = change(setup, session_id, "remove_exclusion", item_id=identity)
        if any(row["id"] == identity for row in after["exclusions"]):
            raise FixtureBlocked("Native exclusion deletion not observed")
        return {"action": action, "before": before, "after": after,
                "context_revision": after["revision"]}
    if action == "publish_current_knowledge":
        source = bindings["old_source"]
        if source["source_id"] not in previous.get("read_source_ids", []):
            raise FixtureBlocked("CTX07 requires actual v1 READ before v2 is added")
        bindings["new_source"] = knowledge(setup,
            "S7-A；复验观察窗口45秒；生效日期2026-10-21。", previous=source, label="S7-A v2")
        return {"action": action, "old_source": source, "new_source": bindings["new_source"]}
    if action == "revoke_private_audience":
        from pdos_next.models import ObjectAudience
        from sqlalchemy.orm import Session

        private = bindings["sources"]["S8-B"]["artifact_id"]
        public = bindings["sources"]["S8-A"]["artifact_id"]
        actual_reads = set(previous.get("read_source_ids", []))
        if (not {private, public} <= actual_reads
                or private not in previous.get("carried_source_ids", [])
                or private in previous.get("citation_source_ids", [])):
            raise FixtureBlocked("CTX08 needs actual private READ/carried without final citation")
        if "SYNT-LANTERN-47" not in json.dumps(previous.get("output", {}), ensure_ascii=False):
            raise FixtureBlocked("CTX08 requires the actual private-derived historical answer")
        with Session(setup.admin) as session, session.begin():
            row = session.get(ObjectAudience, UUID(bindings["private_audience_id"]))
            if row is None or row.tenant_id != setup.tenant or row.principal_id != setup.human:
                raise FixtureBlocked("CTX08 isolated audience seed does not match requester")
            session.delete(row)
        return {"action": action, "private_source_id": private,
                "audience_id": bindings["private_audience_id"], "withdrawn": True,
                "basis": "same isolated synthetic ObjectAudience fixture as old native controls"}
    if action == "require_all_24_constraints":
        from pdos_next.agent_kernel.work_state import STATE_TOKENS

        state = read_state(setup, session_id)
        expected = cases()["CTX-10"]["turns"][0]["content"].splitlines()[1:]
        if ([row["text"] for row in state["constraints"]] != expected
                or state["estimated_tokens"] <= STATE_TOKENS or not state["context_incomplete"]):
            raise FixtureBlocked(
                "CTX10 needs all 24 verbatim native constraints above STATE_TOKENS")
        return {"action": action, "state": state, "expected_final_model_dispatches": 0}
    if action == "require_old_pending_candidate":
        candidates = previous.get("candidates", [])
        old = next((row for row in candidates if row["state"] == "pending"
                    and row.get("receipt") is None and row["command"]["payload"]["title"]
                    == "补齐湿热复验原件"), None)
        if old is None:
            raise FixtureBlocked("CTX11 needs a real unadopted pending old-title candidate")
        bindings["old_candidate"] = deepcopy(old)
        return {"action": action, "old_candidate": old}
    raise ValueError("Unknown control action")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    plans = [run_spec(identity, focus) for identity in cases() for focus in FOCUS]
    with (args.output_dir / "run-specs.json").open("x") as stream:
        json.dump({"version": "xiaopai-real-context-preparation/v1", "actual_model_calls": 0,
                   "database_connections": 0, "plans": plans}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"planned_pairs": 12, "planned_cells": len(plans),
                      "actual_model_calls": 0, "database_connections": 0}))


if __name__ == "__main__":
    main()
