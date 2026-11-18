"""Inspect, compare, evaluate, activate and roll back versioned 小Pai prompt code."""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(ROOT / "packages/pdos-agent-runtime/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdos_next.agent.kernel.prompt_admin import (  # noqa: E402
    activate,
    create_draft,
    diff,
    register_draft,
    rollback,
)
from pdos_next.agent.kernel.prompts import PromptCatalog  # noqa: E402
from xiaopai_context_admission_baseline import evaluate as evaluate_admission  # noqa: E402

PACKAGE = SERVER / "pdos_next/agent/prompt_packages"
QUESTIONS = ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
EXPANDED = ROOT / "docs/reports/evidence/pdos-next-eval-v0-20261029/context-expanded-inputs.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(package, questions, expanded):
    paths = [
        Path(questions), Path(expanded), Path(__file__).resolve(),
        SERVER / "pdos_next/agent/kernel/graph.py",
        SERVER / "pdos_next/agent/kernel/gateway.py",
        SERVER / "pdos_next/agent/kernel/host.py",
        SERVER / "pdos_next/agent/kernel/execution.py",
        SERVER / "pdos_next/agent/kernel/policy.py",
        SERVER / "pdos_next/agent/kernel/skill_management.py",
        SERVER / "pdos_next/agent/kernel/skill_qualification.py",
        SERVER / "pdos_next/agent/kernel/prompts.py",
        SERVER / "pdos_next/agent/kernel/prompt_admin.py",
        SERVER / "pdos_next/agent/kernel/context_budget.py",
        SERVER / "pdos_next/agent/kernel/context_runtime.py",
        SERVER / "pdos_next/agent/kernel/disclosure.py",
        SERVER / "pdos_next/agent/kernel/tools.py",
        SERVER / "pdos_next/agent/kernel/registry.py",
        SERVER / "pdos_next/agent/kernel/types.py",
        SERVER / "pdos_next/agent/kernel/skills.py",
        SERVER / "pdos_next/agent/kernel/wire_layout.py",
        ROOT / "tools/xiaopai_context_admission_baseline.py",
    ]
    paths.extend((SERVER / "pdos_next/agent/skill_packages").rglob("*"))
    paths.extend(Path(package).rglob("*"))
    paths.extend((ROOT / "packages/pdos-agent-runtime/src").rglob("*.py"))

    def identity(path):
        if path.is_relative_to(ROOT):
            return str(path.relative_to(ROOT))
        if path.is_relative_to(Path(package)):
            return str(Path("__prompt_package__") / path.relative_to(package))
        if path == Path(questions):
            return "__questions__.json"
        if path == Path(expanded):
            return "__expanded_inputs__.json"
        raise ValueError(f"Evaluation input is outside the repository: {path}")

    return {
        identity(path): sha256(path)
        for path in sorted(set(paths))
        if path.is_file() and path.suffix in {".py", ".md", ".json"}
    }


def evaluate_ab(package, questions_path, expanded_path, baseline, candidate):
    if baseline == candidate:
        raise ValueError("A/B evaluation requires two different versions")
    questions_bytes = Path(questions_path).read_bytes()
    expanded_bytes = Path(expanded_path).read_bytes()
    questions, expanded = json.loads(questions_bytes), json.loads(expanded_bytes)
    catalog = PromptCatalog(package)
    first = evaluate_admission(questions, expanded, prompt=catalog.version(baseline))
    second = evaluate_admission(questions, expanded, prompt=catalog.version(candidate))
    first_prefix = first["production_fixed_prefix"]
    second_prefix = second["production_fixed_prefix"]
    for field in ("tool_definitions_sha256", "output_schema_sha256", "tool_count"):
        if first_prefix[field] != second_prefix[field]:
            raise ValueError("A/B inputs differ outside the prompt")
    baseline_cases = {case["case_id"]: case for case in first["cases"]}
    candidate_cases = {case["case_id"]: case for case in second["cases"]}
    if baseline_cases.keys() != candidate_cases.keys():
        raise ValueError("A/B case sets differ")
    cases, regressions = [], []
    for case_id in sorted(baseline_cases):
        before, after = baseline_cases[case_id], candidate_cases[case_id]
        if before["scenario_raw_input"]["sha256"] != after["scenario_raw_input"]["sha256"]:
            raise ValueError("A/B scenario inputs differ")
        before_status = {key: value["status"] for key, value in before["profiles"].items()}
        after_status = {key: value["status"] for key, value in after["profiles"].items()}
        changes = [
            {"focus": int(focus), "baseline": before_status[focus],
             "candidate": after_status[focus]}
            for focus in sorted(before_status, key=int)
            if before_status[focus] != after_status[focus]
        ]
        for change in changes:
            if (
                change["candidate"] == "CONTEXT_INCOMPLETE"
                and change["baseline"] != "CONTEXT_INCOMPLETE"
            ):
                regressions.append({"case_id": case_id, **change})
        cases.append({
            "case_id": case_id,
            "input_sha256": before["scenario_raw_input"]["sha256"],
            "baseline": before_status,
            "candidate": after_status,
            "changes": changes,
            "task_score": None,
            "model_quality": "not_run",
        })
    identities = []
    for result in (first, second):
        prefix = result["production_fixed_prefix"]
        identities.append({
            **prefix["prompt_identity"],
            "system_estimated_tokens": prefix["system_estimated_tokens"],
            "fixed_admission_tokens": prefix["fixed_admission_tokens"],
        })
    return {
        "schema": "xiaopai-prompt-ab/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "baseline": identities[0],
        "candidate": identities[1],
        "question_set": {
            "version": questions["version"],
            "status": questions["status"],
            "synthetic": questions["synthetic"],
            "trusted_root": questions["trusted_root"],
            "cases": len(cases),
        },
        "scope": (
            "Same native production-prefix admission controls; only the prompt version changes"
        ),
        "cases": cases,
        "regressions": regressions,
        "control_status": "failed" if regressions else "passed",
        "quality_status": "not_scored",
        "not_scored": ["answer_correctness", "citation_semantics", "real_usage_latency_cost"],
        "provider_calls": 0,
        "database_operations": 0,
        "diff": diff(package, baseline, candidate),
        "inputs": {"source_sha256": source_hashes(package, questions_path, expanded_path)},
        "limits": [
            "Admission controls are not native full-scene replay or answer-quality evidence.",
            "The candidate question set is synthetic and has not been promoted to a golden root.",
            "No provider, database, credential or real model was used.",
        ],
    }


def markdown(report):
    baseline, candidate = report["baseline"], report["candidate"]
    lines = [
        "# 小Pai Prompt 同题 A/B 离线控制报告", "",
        f"- 基线：`{baseline['key']}@{baseline['version']}`，固定准入 "
        f"{baseline['fixed_admission_tokens']} tokens",
        f"- 候选：`{candidate['key']}@{candidate['version']}`，固定准入 "
        f"{candidate['fixed_admission_tokens']} tokens",
        f"- 控制结果：**{report['control_status']}**；答案质量：**not_scored**",
        f"- 题目：{report['question_set']['cases']} 道合成候选题；provider/数据库调用均为 0", "",
        "本报告只比较相同工具、输出 schema、题目和上下文准入逻辑。"
        "它不证明真实回答、引用、权限端到端或真人任务质量通过。", "",
        "| 场景 | 变化档数 | 结果 |",
        "| --- | ---: | --- |",
    ]
    regression_ids = {item["case_id"] for item in report["regressions"]}
    for case in report["cases"]:
        status = "新增准入失败" if case["case_id"] in regression_ids else (
            "有状态变化" if case["changes"] else "不变"
        )
        lines.append(f"| {case['case_id']} | {len(case['changes'])} | {status} |")
    lines.extend(["", f"新增准入失败：{len(report['regressions'])} 项。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=PACKAGE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("version")
    create = commands.add_parser("new")
    create.add_argument("version")
    create.add_argument("--source", required=True)
    register = commands.add_parser("register")
    register.add_argument("version")
    difference = commands.add_parser("diff")
    difference.add_argument("baseline")
    difference.add_argument("candidate")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--baseline", required=True)
    evaluation.add_argument("--candidate", required=True)
    evaluation.add_argument("--questions", type=Path, default=QUESTIONS)
    evaluation.add_argument("--expanded-inputs", type=Path, default=EXPANDED)
    evaluation.add_argument("--output-dir", type=Path, required=True)
    activation = commands.add_parser("activate")
    activation.add_argument("version")
    activation.add_argument("--expected-active", required=True)
    activation.add_argument("--evaluation", type=Path, required=True)
    activation.add_argument("--questions", type=Path, default=QUESTIONS)
    activation.add_argument("--expanded-inputs", type=Path, default=EXPANDED)
    activation.add_argument("--reviewer", required=True)
    restoration = commands.add_parser("rollback")
    restoration.add_argument("version")
    restoration.add_argument("--expected-active", required=True)
    restoration.add_argument("--reviewer", required=True)
    restoration.add_argument("--reason", required=True)
    args = parser.parse_args()
    package = args.package_dir.resolve()
    catalog = PromptCatalog(package)
    if args.command == "list":
        result = {"active": catalog.active_version, "versions": catalog.versions(),
                  "history": catalog.history}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "show":
        print(catalog.version(args.version).content, end="")
    elif args.command == "new":
        prompt = create_draft(package, args.version, source=args.source)
        print(json.dumps({"draft": prompt.version, "digest": prompt.digest}))
    elif args.command == "register":
        prompt = register_draft(package, args.version)
        print(json.dumps({"registered": prompt.version, "digest": prompt.digest}))
    elif args.command == "diff":
        print(diff(package, args.baseline, args.candidate), end="")
    elif args.command == "evaluate":
        report = evaluate_ab(
            package, args.questions, args.expanded_inputs, args.baseline, args.candidate,
        )
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, content in (
            ("report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
            ("result.md", markdown(report)),
            ("diff.patch", report["diff"]),
        ):
            with (args.output_dir / name).open("x") as stream:
                stream.write(content)
        print(json.dumps({
            "control_status": report["control_status"],
            "quality_status": report["quality_status"],
            "regressions": len(report["regressions"]),
            "provider_calls": 0,
            "output_dir": str(args.output_dir),
        }, ensure_ascii=False))
        return 0 if report["control_status"] == "passed" else 2
    elif args.command == "activate":
        report = json.loads(args.evaluation.read_text())
        prompt = activate(
            package, args.version, expected_active=args.expected_active,
            evaluation=report, reviewer=args.reviewer,
            current_sources=lambda: source_hashes(package, args.questions, args.expanded_inputs),
        )
        print(json.dumps({"active": prompt.version, "digest": prompt.digest}))
    elif args.command == "rollback":
        prompt = rollback(
            package, args.version, expected_active=args.expected_active,
            reviewer=args.reviewer, reason=args.reason,
        )
        print(json.dumps({"active": prompt.version, "digest": prompt.digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
