"""Offline production-prefix admission lower bound; never a native replay or quality score.

Run with the server venv and PYTHONPATH=pdos-next/server:packages/pdos-agent-runtime/src.
No provider, database, credentials, environment file, receipts or READ bindings are used.
"""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from pdos_next.agent_kernel.context_budget import estimate_tokens, fit_messages, measure
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import WireAgentOutput
from pdos_next.errors import DomainError

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
EXPANDED = ROOT / "docs/reports/evidence/pdos-next-eval-v0-20261029/context-expanded-inputs.json"
FOCUS_PROFILES = (8192, 16384, 48000, 64000)
OUTPUT_TOKENS = 2048


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def materialize(case):
    """Expand scenario records exactly, without treating tool-role prose as trusted data."""
    turns = deepcopy(case["turns"])
    replay = case.get("replay_input")
    if replay:
        if replay["repeat_each_record"] != 1:
            raise ValueError("Only the recorded once-per-record expansion is supported")
        rule = replay["expansion_rule"]
        if rule["operation"] != "append_to_existing_turn_content":
            raise ValueError("Unsupported replay expansion")
        records = {row["record_id"]: row for row in replay["records"]}
        if len(records) != len(replay["records"]) or set(records) != set(replay["record_order"]):
            raise ValueError("Expansion record identity/order mismatch")
        if len(replay["record_order"]) != len(records):
            raise ValueError("An expansion record must be applied exactly once")
        for identity in replay["record_order"]:
            record = records[identity]
            turns[record[rule["target_index_field"]]]["content"] += (
                rule["prefix"] + rule["line_joiner"].join(record["lines"]) + rule["suffix"]
            )
    return [*turns, {"role": "user", "content": case["final_prompt"]}]


def raw_measurement(case, expanded):
    turns = materialize(case)
    if turns != expanded:
        raise ValueError(f"{case['id']}: materialized scenario differs from expanded input")
    serialized = encoded(turns)
    value = {
        "characters": len(serialized), "utf8_bytes": len(serialized.encode()),
        "current_estimator_tokens": estimate_tokens(serialized),
        "sha256": sha256(serialized.encode()), "messages": len(turns),
        "tool_role_scenario_records": sum(row["role"] == "tool" for row in turns),
        "expanded_input_matches": True,
    }
    expected = case.get("replay_input", {}).get("input_measurement", {})
    for field in ("characters", "utf8_bytes", "current_estimator_tokens", "sha256"):
        if field in expected and value[field] != expected[field]:
            raise ValueError(f"{case['id']}: recorded {field} differs from scenario")
    value["recorded_long_input_measurement_matches"] = True if expected else None
    return value


def question_only_messages(case):
    """A structural lower bound, not a signed server context or a provider request.

    Omit all scenario history, tool records, native-looking IDs and derived facts.
    Even successful admission of this probe proves nothing about a full native run.
    """
    return [{"role": "user", "content": json.dumps(
        {"goal": case["final_prompt"], "context": {}}, ensure_ascii=False,
    )}]


def probe(focus, system, tools, schema, messages):
    route = SimpleNamespace(
        context_window_tokens=focus + OUTPUT_TOKENS + 4000,
        max_output_tokens=OUTPUT_TOKENS,
    )
    try:
        _, budget = fit_messages(
            route, system, tools, messages, schema, allow_envelope=True,
        )
        return {"status": "admitted_lower_bound_only", "reason_key": "within_focus",
                "context_budget": budget}
    except DomainError as error:
        if error.reason != "CONTEXT_INCOMPLETE":
            raise
        return {"status": error.reason, "reason_key": error.detail["reason_key"],
                "context_budget": error.detail["context_budget"],
                "missing": error.detail["missing"], "recovery": error.recovery}


def evaluate(questions, expanded):
    registry = default_registry()
    kernel = AgentKernel(None, registry)
    tools = disclosure(registry, "main", ())
    schema = WireAgentOutput.model_json_schema()
    empty = question_only_messages({"final_prompt": ""})
    prefix = measure(
        SimpleNamespace(context_window_tokens=70048, max_output_tokens=OUTPUT_TOKENS),
        kernel.system, tools, empty, schema,
    )
    cases = []
    for case in questions["cases"]:
        cases.append({
            "case_id": case["id"],
            "scenario_raw_input": raw_measurement(case, expanded[case["id"]]),
            "question_only_messages_sha256": sha256(encoded(question_only_messages(case)).encode()),
            "profiles": {str(focus): probe(
                focus, kernel.system, tools, schema, question_only_messages(case),
            ) for focus in FOCUS_PROFILES},
            "native_provider_input_status": "blocked_missing_native_fixture_bindings",
            "native_replay_admission": None,
            "full_completion": None, "task_score": None, "model_quality": "not_run",
            "actual_input_tokens": None, "actual_output_tokens": None,
        })
    return {
        "version": "xiaopai-context-admission-lower-bound/v1", "synthetic": True,
        "trusted_root": False,
        "scope": "Production fit_messages on fixed production prefix plus current question only",
        "limits": [
            "Scenario transcripts are raw replay material, not trusted provider inputs.",
            "Tool-role prose establishes no READ, citation, receipt, revocation or candidate fact.",
            "Question-only envelopes are unsigned lower-bound probes; none are sent to a provider.",
            "No history/state projection, ACL recheck, skill preload or native binding ran.",
            "Lower-bound admission is not a full-case pass, provider support or model quality.",
        ],
        "production_fixed_prefix": {
            "source": "AgentKernel(None, default_registry()).system; disclosure(main, ())",
            "loaded_skills": [], "tool_count": len(tools),
            "system_sha256": sha256(kernel.system.encode()),
            "tool_definitions_sha256": sha256(encoded(tools).encode()),
            "output_schema_sha256": sha256(encoded(schema).encode()),
            "system_estimated_tokens": prefix["segments"]["system"],
            "tools_and_output_schema_estimated_tokens": prefix["segments"]["tools"],
            "fixed_admission_tokens": prefix["fixed_admission_tokens"],
            "calibration": "first_call_estimate_with_production_15_percent_margin",
        },
        "profiles": [{"focus": focus, "window": focus + 6048,
                      "max_output_tokens": OUTPUT_TOKENS} for focus in FOCUS_PROFILES],
        "provider_calls": 0, "database_operations": 0, "cases": cases,
    }


def report(value):
    fixed = value["production_fixed_prefix"]
    lines = [
        "# 小Pai v0：离线固定前缀准入下界", "",
        f"生产固定系统提示估算 {fixed['system_estimated_tokens']} tokens，初始 "
        f"{fixed['tool_count']} 工具与输出 schema 估算 "
        f"{fixed['tools_and_output_schema_estimated_tokens']} tokens。"
        f"生产 15% 余量后的固定下界为 {fixed['fixed_admission_tokens']} tokens。", "",
        "原 F=8192/16384 的固定前缀已经超窗，不能用这两档比较长会话模型质量。"
        "F=48000/64000 的当前问题下界可准入，仅建议作为后续原生回放的候选；"
        "未验证服务商窗口、已加载技能、完整历史与工具结果准入。", "",
        "| 场景 | 原始材料估算 | F8192 | F16384 | F48000 | F64000 | 原生回放 |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for case in value["cases"]:
        cells = ["固定前缀超窗" if case["profiles"][str(focus)]["status"] == "CONTEXT_INCOMPLETE"
                 else "仅下界准入" for focus in FOCUS_PROFILES]
        lines.append(f"| {case['case_id']} | "
                     f"{case['scenario_raw_input']['current_estimator_tokens']} | "
                     + " | ".join(cells) + " | 缺原生绑定，未运行 |")
    lines += [
        "", "原始材料只按题集规则物化并核对 SHA/字符/字节/估算；"
        "历史 assistant/tool 是场景描述，不能证明实际 READ 或权限。"
        "尤其 CTX-08 不能把撤权前正文直接带入模型；CTX-09 示例句柄、"
        "CTX-11 候选标识也不能当生产事实。", "",
        "每题实际调用生产 fit_messages 的输入仅为固定前缀、生产初始披露、"
        "WireAgentOutput schema 及 final_prompt 的空 context 信封。"
        "没有伪造上下文签名、工具调用或领域绑定；该结构探针不是实际 provider 输入。"
        "准入成功只证明此下界未超窗，失败则证明完整输入不可能容纳于相同 F。", "",
        "完整原生场景准入、模型任务分、事实/引用正确率、实际 tokens/时延/费用均未测。"
        "模型/embedding/数据库/外发调用均为零。原始长材料也不能直接用新 F 的下界准入"
        "冒充已完成生产历史分层、工作状态投影、权限复核与工具分页。", "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--expanded-inputs", type=Path, default=EXPANDED)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    questions_bytes = args.questions.read_bytes()
    expanded_bytes = args.expanded_inputs.read_bytes()
    value = evaluate(json.loads(questions_bytes), json.loads(expanded_bytes))
    production_files = [
        "context_budget.py", "context_runtime.py", "graph.py", "disclosure.py", "tools.py",
        "registry.py", "types.py", "skills.py",
    ]
    value["inputs"] = {
        "questions_sha256": sha256(questions_bytes),
        "expanded_inputs_sha256": sha256(expanded_bytes),
        "production_source_sha256": {name: sha256((
            ROOT / "pdos-next/server/pdos_next/agent_kernel" / name
        ).read_bytes()) for name in production_files},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("baseline.json", json.dumps(value, ensure_ascii=False, indent=2) + "\n"),
        ("result.md", report(value)),
        ("questions.snapshot.json", questions_bytes.decode()),
    ):
        with (args.output_dir / name).open("x") as stream:
            stream.write(content)
    print(json.dumps({"case_count": len(value["cases"]), "provider_calls": 0,
                      "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
