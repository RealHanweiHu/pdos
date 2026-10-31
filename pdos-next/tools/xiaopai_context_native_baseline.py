"""Run model-free native context controls; answer quality remains unscored."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT.parent / "docs/evaluations/xiaopai-v0/context-questions.json"
TESTS = (
    "tests/agent_kernel/test_eval_v0_history_state_pg.py",
    "tests/enterprise_search/test_eval_v0_source_context_pg.py",
    "tests/agent_kernel/test_eval_v0_handle_candidate_pg.py",
)
UNSCORED = {"answer_correctness", "citation_semantics", "real_usage_latency_cost"}


def summarize(folder, questions):
    """Keep fixture checks, incomplete bindings and model-quality evidence distinct."""
    expected = {(case["id"], focus) for case in questions["cases"]
                for focus in case["f_budget_tokens"]}
    observations = {}
    for path in sorted(folder.glob("CTX-*-F*.json")):
        value = json.loads(path.read_text())
        if type(value.get("f_budget_tokens")) is not int:
            raise ValueError("Context focus budget must be an integer")
        key = (value.get("case_id"), value.get("f_budget_tokens"))
        if key not in expected or key in observations:
            raise ValueError("Unexpected or duplicate context observation")
        if path.name != f"{key[0]}-F{key[1]}.json":
            raise ValueError("Context observation filename does not match its case")
        if (value.get("version") != "context-native-observation/v1"
                or value.get("scripted_provider") is not True
                or type(value.get("real_model_calls")) is not int
                or value["real_model_calls"] != 0
                or value.get("model_quality_score") is not None
                or not UNSCORED <= set(value.get("not_scored", []))):
            raise ValueError("Model-free controls cannot provide model-quality scores")
        if value.get("native_binding_status") not in {"bound", "partial", "not_executable"}:
            raise ValueError("Missing explicit native binding status")
        if (type(value.get("provider_dispatches")) is not int
                or value["provider_dispatches"] < 0
                or not isinstance(value.get("context_budget"), list)
                or not isinstance(value.get("bindings"), dict)
                or not isinstance(value.get("status"), str)):
            raise ValueError("Missing native control evidence")
        observations[key] = value
    missing = sorted(expected - observations.keys())
    bindings = Counter(value["native_binding_status"] for value in observations.values())
    statuses = Counter(value["status"] for value in observations.values())
    return {
        "version": "context-native-baseline/v1",
        "expected_observations": len(expected),
        "recorded_observations": len(observations),
        "missing": [{"case_id": case, "f_budget_tokens": focus} for case, focus in missing],
        "binding_counts": dict(bindings), "control_status_counts": dict(statuses),
        "all_cases_natively_bound": not missing and bindings.get("bound", 0) == len(expected),
        "quality_status": "not_scored", "not_scored": sorted(UNSCORED),
        "real_model_calls": 0,
        "observations": [observations[key] for key in sorted(observations)],
    }


def write_report(folder, value):
    (folder / "baseline.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    rows = ["# 上下文候选原生控制回放", "",
            "使用脚本端驱动实际本地状态与注册图；任务分、答案/引用语义及真实计量未评分。", "",
            "| 题目 | F | 原生绑定 | 控制状态 | 脚本派发 |",
            "| --- | ---: | --- | --- | ---: |"]
    for item in value["observations"]:
        rows.append(f"| {item['case_id']} | {item['f_budget_tokens']} | "
                    f"{item['native_binding_status']} | {item['status']} | "
                    f"{item['provider_dispatches']} |")
    for item in value["missing"]:
        rows.append(f"| {item['case_id']} | {item['f_budget_tokens']} | missing | 未完成 | — |")
    rows.extend(["", f"pytest退出码：{value['pytest_exit']}。绑定状态按实际输出保留，"
                 "partial/not_executable不计为完整场景通过。",
                 "没有真实模型/embedding调用，也不以脚本输出评价模型正确率。", ""])
    (folder / "result.md").write_text("\n".join(rows))


def run(destination):
    import local_environment as local

    state = local.verified(local.read_state())
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    questions_bytes = QUESTIONS.read_bytes()
    questions = json.loads(questions_bytes)
    env = local.environment(state)
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
        PYTHONPATH=os.pathsep.join((str(ROOT / "server"),
                                   str(ROOT.parent / "packages/pdos-agent-runtime/src"))),
        PDOS_CONTEXT_NATIVE_OUTPUT_DIR=str(destination),
    )
    paths = [ROOT / "server" / name for name in TESTS]
    paths.extend((ROOT / "server/pdos_next").rglob("*.py"))
    paths.extend(path for path in (ROOT / "server/pdos_next/skill_packages").rglob("*")
                 if path.suffix in {".json", ".md"})
    paths.extend((ROOT.parent / "packages/pdos-agent-runtime/src").rglob("*.py"))
    paths.extend((ROOT / "server/tests").rglob("*eval_v0*.py"))
    paths.extend((Path(__file__).resolve(), ROOT / "tools/xiaopai_context_admission_baseline.py"))
    source_hashes = {
        str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    question_hash = hashlib.sha256(questions_bytes).hexdigest()
    source_hashes[str(QUESTIONS.relative_to(ROOT.parent))] = question_hash
    command = [sys.executable, "-m", "pytest", "-vv", *TESTS,
               "--junitxml=" + str(destination / "native.xml")]
    with (destination / "native.log").open("x") as log:
        process = subprocess.Popen(command, cwd=ROOT / "server", env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            safe = re.sub(r"postgresql(?:\+psycopg)?://[^\s'\"]+", "[PRIVATE_DSN]", line)
            for key, value in state.items():
                if key.endswith(("url", "token")) and isinstance(value, str):
                    safe = safe.replace(value, "[PRIVATE]")
            log.write(safe)
            log.flush()
    code = process.wait()
    value = summarize(destination, questions)
    unchanged = all(hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == digest
                    for name, digest in source_hashes.items())
    value.update(
        at_utc=datetime.now(UTC).isoformat(), pytest_exit=code,
        source_sha256=source_hashes, input_bytes_unchanged=unchanged,
        test_database="pdos_test", test_port=state["port"],
        scope="native bindings, context admission and authorization; scripted providers",
    )
    write_report(destination, value)
    brief = {key: value[key] for key in (
        "pytest_exit", "recorded_observations", "expected_observations", "binding_counts",
        "all_cases_natively_bound", "quality_status", "input_bytes_unchanged")}
    print(json.dumps(brief, ensure_ascii=False))
    return code or (0 if unchanged and not value["missing"] else 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    return run(args.output_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
