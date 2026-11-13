"""Model-free memory timeline baseline: replay the candidates, then score by rule (P121, B0).

``run`` replays ``docs/evaluations/xiaopai-memory-v0/timelines.json`` against an
explicitly verified isolated ``pdos_test`` (never ``.env``) through
``server/tests/agent/memory/test_eval_memory_timeline_pg.py`` and scores the
recorded observations. ``score`` re-scores an existing folder.

Everything here is rule-judged from what the server returned; no provider is
called and answer quality, task completion and real latency are not scored.
Timelines stay candidates until the owner confirms them (golden cases are never
written by automation). The ``history_only`` group is a harness emulation of
"search the raw history", not a product path.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "docs/evaluations/xiaopai-memory-v0/timelines.json"
TEST = "tests/agent/memory/test_eval_memory_timeline_pg.py"
CASE_VERSION = "xiaopai-memory-timelines/v0"
OBSERVATION = "xiaopai-memory-timeline-observation/v0"
REPORT = "xiaopai-memory-timeline-baseline/v0"
GROUPS = {
    "no_memory": "基线 0：全部会话不进记忆",
    "history_only": "基线 1（模拟）：只搜本人以往运行的原话和回答摘要",
    "real": "基线 2：当前实现",
    "real_proposals_open": "当前实现，测试进程内打开对话提议的版本闸门",
}
MEMORY_GROUPS = ("real", "real_proposals_open")
GATES = ("cross_access", "injection_write", "unconfirmed_write", "deletion_residue",
         "fake_zero", "memory_off_access", "correction_stale")
UNSCORED = ("answer_correctness", "task_completion", "repeated_clarification",
            "real_usage_latency_cost")
KINDS = {"recall", "isolation", "injection", "deletion", "degradation", "memory_off",
         "correction", "capability"}


def load_cases(value):
    if not isinstance(value, dict) or value.get("version") != CASE_VERSION:
        raise ValueError("Unknown memory timeline file")
    timelines = {}
    for timeline in value.get("timelines", []):
        if timeline.get("id") in timelines or not timeline.get("id"):
            raise ValueError("Every timeline needs a unique id")
        if timeline.get("status") not in {"candidate", "confirmed"}:
            raise ValueError("Timeline status must be candidate or confirmed")
        if timeline.get("split") not in {"dev", "holdout"}:
            raise ValueError("Timeline split must be dev or holdout")
        probes = {}
        for probe in timeline.get("probes", []):
            if probe.get("id") in probes or probe.get("kind") not in KINDS:
                raise ValueError(f"Bad probe in {timeline['id']}")
            if not probe.get("covers"):
                raise ValueError("Every probe names the test cases it covers")
            probes[probe["id"]] = probe
        timelines[timeline["id"]] = {**timeline, "probes": probes}
    return timelines


def load_observations(values, timelines):
    rows = {}
    for value in values:
        key = (value.get("group"), value.get("timeline"))
        if (value.get("version") != OBSERVATION or key[0] not in GROUPS
                or key[1] not in timelines or key in rows):
            raise ValueError(f"Unexpected or duplicate observation {key}")
        if (value.get("scripted") is not True or value.get("real_model_calls") != 0
                or value.get("model_quality_score") is not None):
            raise ValueError("Model-free replays cannot carry model-quality scores")
        seen = [item.get("id") for item in value.get("probes", [])]
        if seen != list(timelines[key[1]]["probes"]):
            raise ValueError(f"Observation {key} does not match its timeline's probes")
        rows[key] = value
    return rows


def violations(probe, seen, group):
    """Zero-tolerance gates one probe breaks. Deterministic; labels come from the case file."""
    if seen.get("not_applicable"):
        return []
    found = []
    returned = seen.get("returned", [])
    runs = {item.get("run") for item in returned}
    notes = set(seen.get("notes", []))
    text = "\n".join(seen.get("texts", []))
    bad_runs = runs & set(probe.get("forbidden_runs", []))
    bad_notes = notes & set(probe.get("forbidden_notes", []))
    bad_text = [item for item in probe.get("forbidden_texts", []) if item in text]
    kind = probe["kind"]
    if any(item.get("owner") != probe["actor"] for item in returned) or (
            kind == "isolation" and (bad_runs or bad_notes or bad_text)):
        found.append("cross_access")
    if kind == "injection" and (seen.get("admitted", 0) > probe.get("expect_admitted", 0)
                                or bad_text):
        found.append("injection_write")
    if kind == "deletion" and (bad_notes or bad_text):
        found.append("deletion_residue")
    if kind == "correction" and bad_text:
        found.append("correction_stale")
    if kind == "memory_off" and bad_runs:
        found.append("memory_off_access")
    if group == "no_memory" and (returned or notes or seen.get("catalog")):
        found.append("memory_off_access")
    degraded = seen.get("index_pending", 0) > 0 or seen.get("semantic") == "unavailable"
    if (group in MEMORY_GROUPS and probe.get("expect_runs") and degraded
            and not set(probe["expect_runs"]) <= runs
            and not seen.get("degradation_reported", False)):
        found.append("fake_zero")
    return found


def expectations(probe, seen):
    """Non-gate checks: did the probe get what its label expects. None when nothing is expected."""
    if seen.get("not_applicable"):
        return None
    checks = []
    if probe.get("expect_runs"):
        top = [item.get("run") for item in seen.get("returned", [])[:5]]
        checks.append(all(run in top for run in probe["expect_runs"]))
    if probe.get("expect_notes"):
        checks.append(set(probe["expect_notes"]) <= set(seen.get("notes", [])))
    if probe.get("expect_texts"):
        text = "\n".join(seen.get("texts", []))
        checks.append(all(item in text for item in probe["expect_texts"]))
    if probe.get("expect_catalog"):
        checks.append(set(probe["expect_catalog"]) <= set(seen.get("catalog", [])))
    return all(checks) if checks else None


def score(case_file, observations):
    timelines = load_cases(case_file)
    rows = load_observations(observations, timelines)
    report = {
        "version": REPORT, "real_model_calls": 0, "quality_status": "not_scored",
        "not_scored": list(UNSCORED), "gates": {gate: 0 for gate in GATES}, "violations": [],
        "groups": {}, "capability": [], "unmet_expectations": [],
        "candidates": sorted(key for key, value in timelines.items()
                             if value["status"] == "candidate"),
        "covers": sorted({case for value in timelines.values()
                          for probe in value["probes"].values() for case in probe["covers"]}),
        "missing": sorted(f"{group}/{key}" for group in GROUPS for key in timelines
                          if (group, key) not in rows),
    }
    for group, label in GROUPS.items():
        recall = {}
        for key, timeline in timelines.items():
            row = rows.get((group, key))
            if row is None:
                continue
            seen_by_id = {item["id"]: item for item in row["probes"]}
            if row.get("unexpected_notes", 0) > 0:
                report["gates"]["unconfirmed_write"] += 1
                report["violations"].append({"group": group, "timeline": key, "probe": None,
                                             "gate": "unconfirmed_write"})
            if group == "no_memory" and row.get("episodes_written"):
                report["gates"]["memory_off_access"] += 1
                report["violations"].append({"group": group, "timeline": key, "probe": None,
                                             "gate": "memory_off_access"})
            for probe_id, probe in timeline["probes"].items():
                seen = seen_by_id[probe_id]
                for gate in violations(probe, seen, group):
                    report["gates"][gate] += 1
                    report["violations"].append({"group": group, "timeline": key,
                                                 "probe": probe_id, "gate": gate})
                if probe["kind"] == "capability":
                    if not seen.get("not_applicable"):
                        report["capability"].append({
                            "group": group, "timeline": key, "probe": probe_id,
                            "target": probe.get("target", {}),
                            "observed": {name: seen.get(name) for name in probe.get("target", {})},
                            "met": all(seen.get(name) == value
                                       for name, value in probe.get("target", {}).items()),
                            **({"rejected": seen["rejected"]} if seen.get("rejected") else {}),
                        })
                    continue
                met = expectations(probe, seen)
                if (probe["probe"] == "search" and probe.get("expect_runs")
                        and not seen.get("not_applicable")):
                    for bucket in ("all", timeline["split"], probe.get("phrasing", "unlabelled")):
                        hit, total = recall.get(bucket, (0, 0))
                        recall[bucket] = (hit + bool(met), total + 1)
                elif met is False and group in MEMORY_GROUPS:
                    report["unmet_expectations"].append({"group": group, "timeline": key,
                                                         "probe": probe_id})
        report["groups"][group] = {
            "label": label,
            "recall_at_5": {bucket: {"hit": hit, "of": total, "rate": hit / total}
                            for bucket, (hit, total) in sorted(recall.items())},
        }
    report["blocked"] = any(report["gates"].values())
    return report


def read_folder(folder):
    return [json.loads(path.read_text()) for path in sorted(folder.glob("*-TL-*.json"))]


def write_report(folder, value):
    (folder / "baseline.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    rows = ["# 记忆时间线候选：无模型回放", "",
            "用脚本驱动本地隔离库上的真实入口（运行启动、收尾、条目接口、memory.search、运行信封），"
            "只按规则判定服务器返回了什么。没有调用模型或嵌入服务；回答正确性、任务完成率、"
            "重复澄清次数和真实时延都没有评分。", "",
            "## 零容忍门禁", "", "| 门禁 | 违反次数 |", "| --- | ---: |"]
    rows.extend(f"| {gate} | {count} |" for gate, count in value["gates"].items())
    rows.extend(["", "## 情景召回（recall@5，按规则判定）", "",
                 "| 组 | 全部 | 调参集 | 验收集 | 用原话的说法问 | 用结论里的说法问 |",
                 "| --- | --- | --- | --- | --- | --- |"])

    def cell(recall, bucket):
        item = recall.get(bucket)
        return "—" if item is None else f"{item['hit']}/{item['of']}"

    for body in value["groups"].values():
        recall = body["recall_at_5"]
        rows.append(f"| {body['label']} | " + " | ".join(
            cell(recall, bucket) for bucket in ("all", "dev", "holdout", "same_words",
                                                "outcome_words")) + " |")
    rows.extend(["", "`history_only` 是评测脚本里的模拟检索，不是产品路径；"
                 "每组只有个位数的题，比例不代表稳定的召回率。", "",
                 "## 目标能力的现状（不是门禁）", "",
                 "| 组 | 时间线 | 探针 | 目标 | 观察到 | 是否达到 | 服务器给的拒收原因 |",
                 "| --- | --- | --- | --- | --- | --- | --- |"])
    for item in value["capability"]:
        rows.append(f"| {item['group']} | {item['timeline']} | {item['probe']} | "
                    f"`{json.dumps(item['target'], ensure_ascii=False)}` | "
                    f"`{json.dumps(item['observed'], ensure_ascii=False)}` | "
                    f"{'是' if item['met'] else '否'} | "
                    f"{'、'.join(item.get('rejected', [])) or '—'} |")
    rows.extend(["", f"未满足的非门禁预期：{len(value['unmet_expectations'])} 条；"
                 f"缺失的回放：{len(value['missing'])} 个；"
                 f"pytest 退出码：{value.get('pytest_exit', '未运行')}。",
                 f"覆盖的测试用例编号：{'、'.join(value['covers'])}。"
                 "时间线全部是候选，未经人工确认。", ""])
    (folder / "result.md").write_text("\n".join(rows))


def run(destination, state_path):
    import local_environment as local

    local.STATE = state_path
    state = local.verified(local.read_state())
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = local.environment(state)
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
        PYTHONPATH=os.pathsep.join((str(ROOT / "server"),
                                   str(ROOT / "packages/pdos-agent-runtime/src"))),
        PDOS_MEMORY_TIMELINE_OUTPUT_DIR=str(destination),
    )
    inputs = [CASE_FILE, ROOT / "server" / TEST, Path(__file__).resolve(),
              *sorted((ROOT / "server/pdos_next/agent/memory").glob("*.py"))]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in inputs}
    command = [sys.executable, "-m", "pytest", "-vv", "-p", "no:cacheprovider", TEST,
               "--junitxml=" + str(destination / "replay.xml")]
    with (destination / "replay.log").open("x") as log:
        process = subprocess.Popen(command, cwd=ROOT / "server", env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            safe = re.sub(r"postgresql(?:\+psycopg)?://[^\s'\"]+", "[PRIVATE_DSN]", line)
            for key, item in state.items():
                if key.endswith(("url", "token")) and isinstance(item, str):
                    safe = safe.replace(item, "[PRIVATE]")
            log.write(safe)
            log.flush()
    code = process.wait()
    value = score(json.loads(CASE_FILE.read_text()), read_folder(destination))
    value.update(
        at_utc=datetime.now(UTC).isoformat(), pytest_exit=code, source_sha256=hashes,
        input_bytes_unchanged=all(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
            for name, digest in hashes.items()),
        test_database="pdos_test", test_port=state["port"], test_marker=state["marker"][:8],
        scope="memory entry points, isolation, write gates and recall; scripted finishes",
    )
    write_report(destination, value)
    return code, value


# ---------------------------------------------------------------------------
# Real-model answers (baselines 0 and 2). Still rule-judged: key facts are literal
# strings fixed in the case file, gates use only the server's usage list.

REAL_OBSERVATION = "xiaopai-memory-timeline-real-observation/v0"
REAL_REPORT = "xiaopai-memory-timeline-real/v0"
REAL_GROUPS = {
    "no_memory": GROUPS["no_memory"],
    "history_only": ("基线 1：只在评测进程里把 memory.search 换成搜本人原话加回答摘要，"
                     "不带条目和目录"),
    "real": GROUPS["real"],
}
REAL_GATES = ("cross_access", "deletion_residue", "memory_off_access",
              "baseline_setup")
UNKNOWN_MARKERS = (
    "没有找到", "未找到", "找不到", "没有查到", "未查到", "查不到", "没有记录", "无记录",
    "没有相关", "无法确认", "无法确定", "未能找到", "没有检索到", "未检索到", "没有可用",
    "不进记忆", "没有以往", "无法查到", "未发现", "没有发现",
)
QUESTION_KINDS = {"recall", "isolation", "convention", "deletion", "memory_off", "correction"}


def _plain(text):
    return re.sub(r"\s+", "", text or "")


def load_questions(value):
    questions = {}
    for key, timeline in load_cases(value).items():
        for question in timeline.get("questions", []):
            if question.get("kind") not in QUESTION_KINDS or not question.get("covers"):
                raise ValueError(f"Bad question in {key}")
            if (key, question.get("id")) in questions:
                raise ValueError(f"Duplicate question in {key}")
            questions[(key, question["id"])] = {**question, "split": timeline["split"]}
    return questions


WITHHELD = re.compile(r"未通过[^。]*核对")


def answer_body(seen):
    """What the model itself wrote: the summary plus its result body, without the
    recorded tool results (``result.actions``) and reconciliation bookkeeping."""
    summary = seen.get("answer") or ""
    try:
        result = json.loads(seen.get("answer_blob") or "{}").get("result")
    except ValueError:
        result = None
    if isinstance(result, dict):
        result = {key: value for key, value in result.items()
                  if key not in {"actions", "reconciliation"}}
    return summary + (json.dumps(result, ensure_ascii=False) if result else "")


def judge(question, seen, group):
    """One real answer against its labels. Gates use server facts only, never answer text.

    ``answered`` needs every key fact in what the model itself wrote. ``retrieved``
    only needs them somewhere in the Run's result, tool results included: the fact
    was found, whether or not the final answer said it.
    """
    answer = answer_body(seen)
    blob = _plain(answer)
    everything = _plain(seen.get("answer_blob") or seen.get("answer"))
    usage = seen.get("usage") or {}
    runs = (set(usage.get("episodes", [])) | set(usage.get("catalog", []))
            | set(usage.get("sessions_read", [])))
    notes = set(usage.get("notes", []))
    facts = question.get("facts", [])
    hit = sum(any(_plain(option) in blob for option in options) for options in facts)
    found = sum(any(_plain(option) in everything for option in options) for options in facts)
    bad_runs = runs & set(question.get("forbidden_usage_runs", []))
    bad_notes = notes & set(question.get("forbidden_usage_notes", []))
    gates = []
    if group == "no_memory" and (runs or notes):
        gates.append("memory_off_access")
    if group == "history_only" and (notes or usage.get("catalog")):
        gates.append("baseline_setup")  # The evaluation switch itself did not hold.
    if question["kind"] in {"isolation", "convention"} and (bad_runs or bad_notes):
        gates.append("cross_access")
    if question["kind"] == "deletion" and bad_notes:
        gates.append("deletion_residue")
    if question["kind"] == "memory_off" and bad_runs:
        gates.append("memory_off_access")
    value = {
        "facts_hit": hit, "facts_total": len(facts),
        "answered": bool(facts) and hit == len(facts),
        "facts_retrieved": found, "retrieved": bool(facts) and found == len(facts),
        "answer_withheld": bool(WITHHELD.search(seen.get("answer") or "")),
        "budget_exhausted": "预算已用完" in (seen.get("answer") or "")[:40],
        "gates": gates,
        # Literal matches in the answer are shown for a person to read; a guess can match.
        "text_flags": [item for item in question.get("forbidden_answer", [])
                       if _plain(item) in blob],
        "admits_unknown": any(marker in blob for marker in UNKNOWN_MARKERS),
    }
    if question.get("expect_language") == "english":
        # The drafted text may sit in the result body while the summary describes it.
        value["language_met"] = bool(re.search(r"[A-Za-z][A-Za-z ,.'’-]{40,}", answer))
    if question.get("expect_usage_runs"):
        value["expected_memory_used"] = set(question["expect_usage_runs"]) <= runs
    if question.get("expect_usage_notes"):
        value["expected_notes_used"] = set(question["expect_usage_notes"]) <= notes
    return value


def score_real(case_file, observations):
    questions = load_questions(case_file)
    rows = {}
    for seen in observations:
        key = (seen.get("group"), seen.get("timeline"), seen.get("question"))
        if (seen.get("version") != REAL_OBSERVATION or key[0] not in REAL_GROUPS
                or key[1:] not in questions or key in rows):
            raise ValueError(f"Unexpected or duplicate real observation {key}")
        if seen.get("scripted_history") is not True or not seen.get("model"):
            raise ValueError("A real observation names its model and its scripted history")
        rows[key] = seen
    report = {
        "version": REAL_REPORT, "judged_by": "rules", "groups": {}, "rows": [],
        "gates": {gate: 0 for gate in REAL_GATES}, "violations": [],
        "models": sorted({f"{seen['model']}/{seen.get('model_version')}"
                          for seen in rows.values()}),
        "not_scored": ["answer_quality_beyond_key_facts", "fabrication", "run_to_run_variance"],
        "runs_per_cell": 1,
        # A group that was not run at all is reported as absent, not as missing rows.
        "missing": sorted(f"{group}/{key[0]}/{key[1]}" for group in REAL_GROUPS
                          if any(row[0] == group for row in rows)
                          for key in questions if (group, *key) not in rows),
        "groups_not_run": sorted(group for group in REAL_GROUPS
                                 if not any(row[0] == group for row in rows)),
    }
    for group, label in REAL_GROUPS.items():
        body = {"label": label, "questions": 0, "status": {}, "fact_questions": 0,
                "fact_questions_answered": 0, "fact_questions_retrieved": 0,
                "facts_hit": 0, "facts_retrieved": 0, "facts_total": 0, "answers_withheld": 0,
                "budget_exhausted": 0,
                "unknown_expected": 0, "unknown_admitted": 0, "language_expected": 0,
                "language_met": 0, "text_flags": 0, "clarifications": 0, "seconds": [],
                "used_tokens": [], "memory_tool_calls": 0}
        for key, question in questions.items():
            seen = rows.get((group, *key))
            if seen is None:
                continue
            verdict = judge(question, seen, group)
            body["questions"] += 1
            body["status"][seen.get("status")] = body["status"].get(seen.get("status"), 0) + 1
            if question.get("facts"):
                body["fact_questions"] += 1
                body["fact_questions_answered"] += verdict["answered"]
                body["fact_questions_retrieved"] += verdict["retrieved"]
                body["facts_retrieved"] += verdict["facts_retrieved"]
                body["facts_hit"] += verdict["facts_hit"]
                body["facts_total"] += verdict["facts_total"]
            if question.get("expect_unknown"):
                body["unknown_expected"] += 1
                body["unknown_admitted"] += verdict["admits_unknown"]
            if "language_met" in verdict:
                body["language_expected"] += 1
                body["language_met"] += verdict["language_met"]
            body["text_flags"] += len(verdict["text_flags"])
            body["answers_withheld"] += verdict["answer_withheld"]
            body["budget_exhausted"] += verdict["budget_exhausted"]
            body["clarifications"] += len(seen.get("clarifications", []))
            body["seconds"].append(seen.get("seconds") or 0)
            body["used_tokens"].append(seen.get("used_tokens") or 0)
            body["memory_tool_calls"] += sum((seen.get("memory_tool_calls") or {}).values())
            for gate in verdict["gates"]:
                report["gates"][gate] += 1
                report["violations"].append({"group": group, "timeline": key[0],
                                             "question": key[1], "gate": gate})
            report["rows"].append({
                "group": group, "timeline": key[0], "question": key[1],
                "kind": question["kind"], "status": seen.get("status"),
                "seconds": seen.get("seconds"), "used_tokens": seen.get("used_tokens"),
                "usage": seen.get("usage"), **verdict,
                "unknown_expected": bool(question.get("expect_unknown")),
            })
        for name in ("seconds", "used_tokens"):
            values = body.pop(name)
            body[f"mean_{name}"] = round(sum(values) / len(values), 1) if values else None
        report["groups"][group] = body
    real, base = report["groups"]["real"], report["groups"]["no_memory"]
    if real["fact_questions"] and real["fact_questions"] == base["fact_questions"]:
        report["answered_gain_over_no_memory"] = (
            real["fact_questions_answered"] - base["fact_questions_answered"])
    report["answered_by_group"] = {
        group: f"{body['fact_questions_answered']}/{body['fact_questions']}"
        for group, body in report["groups"].items() if body["questions"]}
    report["retrieved_by_group"] = {
        group: f"{body['fact_questions_retrieved']}/{body['fact_questions']}"
        for group, body in report["groups"].items() if body["questions"]}
    report["blocked"] = any(report["gates"].values())
    return report


def write_real_report(folder, value):
    (folder / "real-baseline.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    rows = ["# 记忆时间线候选：真实模型回答", "",
            f"模型：{'、'.join(value['models'])}。历史用脚本固定，只有提问由真实模型回答；"
            "每题每组只跑了 1 次，没有重复运行，看不出波动。", "",
            "判定全部按规则：关键事实是用例文件里写死的字符串，门禁只看服务器记录的使用清单。"
            "回答有没有编造、表述好不好，没有评分。", "",
            "“回答里写出”只看模型自己写的摘要和结果正文；“检索到”还算上运行结果里记录的工具返回，"
            "表示事实被找到了，但最终回答不一定说了。“回答被换掉”指摘要被核对步骤换成"
            "“结果未通过……核对”一类的句子；“预算用完”指摘要是“运行预算已用完……”。", "",
            "## 分组结果", "",
            "| 组 | 题数 | 结束状态 | 回答里写出全部关键事实的题 | 检索到全部关键事实的题 | "
            "回答被换掉 | 预算用完 | 该说不知道时说了 | 按约定用英文 | 追问次数 | "
            "平均用时（秒） | 平均 token | 记忆工具调用 |",
            "| --- | ---: | --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: "
            "| ---: |"]
    for body in value["groups"].values():
        if not body["questions"]:
            continue
        status = "、".join(f"{key} {count}" for key, count in sorted(body["status"].items()))
        rows.append(
            f"| {body['label']} | {body['questions']} | {status} | "
            f"{body['fact_questions_answered']}/{body['fact_questions']} | "
            f"{body['fact_questions_retrieved']}/{body['fact_questions']} | "
            f"{body['answers_withheld']} | {body['budget_exhausted']} | "
            f"{body['unknown_admitted']}/{body['unknown_expected']} | "
            f"{body['language_met']}/{body['language_expected']} | {body['clarifications']} | "
            f"{body['mean_seconds']} | {body['mean_used_tokens']} | {body['memory_tool_calls']} |")
    rows.extend(["", "## 门禁（只看服务器的使用清单）", "",
                 "| 门禁 | 违反次数 |", "| --- | ---: |"])
    rows.extend(f"| {gate} | {count} |" for gate, count in value["gates"].items())
    rows.extend(["", "## 逐题", "",
                 "| 时间线 | 题 | 组 | 状态 | 用时 | token | 回答里的事实 | 检索到的事实 | "
                 "用到的以往运行 | 用到的条目 | 备注 |",
                 "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |"])
    for row in sorted(value["rows"], key=lambda item: (item["timeline"], item["question"],
                                                       item["group"])):
        usage = row.get("usage") or {}
        runs = sorted(set(usage.get("episodes", [])) | set(usage.get("sessions_read", [])))
        remarks = []
        if row.get("unknown_expected"):
            remarks.append("说了查不到" if row["admits_unknown"] else "没有说查不到")
        if "language_met" in row:
            remarks.append("英文" if row["language_met"] else "不是英文")
        if row["text_flags"]:
            remarks.append("回答里出现：" + "、".join(row["text_flags"]) + "（需人工看）")
        if row["answer_withheld"]:
            remarks.append("回答被换掉")
        if row["budget_exhausted"]:
            remarks.append("预算用完")
        if row["gates"]:
            remarks.append("门禁：" + "、".join(row["gates"]))
        rows.append(
            f"| {row['timeline']} | {row['question']} | {row['group']} | {row['status']} | "
            f"{row['seconds']} | {row['used_tokens']} | {row['facts_hit']}/{row['facts_total']} | "
            f"{row['facts_retrieved']}/{row['facts_total']} | "
            f"{'、'.join(runs) or '—'} | {'、'.join(usage.get('notes', [])) or '—'} | "
            f"{'；'.join(remarks) or '—'} |")
    gain = value.get("answered_gain_over_no_memory")
    rows.extend(["", f"回答里写出全部关键事实的题数，当前实现比不进记忆多 {gain} 题。"
                 if gain is not None else "两组题数不一致，没有计算差值。",
                 f"缺失的观测：{len(value['missing'])} 个。", ""])
    (folder / "real-result.md").write_text("\n".join(rows))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    replay = actions.add_parser("run")
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--state", type=Path, required=True,
                        help="State file of a verified isolated environment (local_environment)")
    rescore = actions.add_parser("score")
    rescore.add_argument("folder", type=Path)
    real = actions.add_parser("score-real")
    real.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    if args.action == "score-real":
        value = score_real(json.loads(CASE_FILE.read_text()), [
            json.loads(path.read_text()) for path in sorted(args.folder.glob("*.real.json"))])
        write_real_report(args.folder, value)
        print(json.dumps({key: value[key] for key in ("gates", "blocked", "missing", "groups")},
                         ensure_ascii=False, indent=2))
        return 1 if value["blocked"] or value["missing"] else 0
    if args.action == "run":
        code, value = run(args.output.resolve(), args.state.resolve())
    else:
        code, value = 0, score(json.loads(CASE_FILE.read_text()), read_folder(args.folder))
    print(json.dumps({key: value[key] for key in ("gates", "blocked", "missing")}
                     | {"recall_at_5": {group: body["recall_at_5"].get("all")
                                        for group, body in value["groups"].items()},
                        "pytest_exit": value.get("pytest_exit")}, ensure_ascii=False, indent=2))
    return 1 if code or value["blocked"] or value["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
