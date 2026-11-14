"""Score the real-model Prompt A/B for memory proposals by rule (D298).

Reads what ``tests/agent/memory/test_eval_memory_proposal_ab_real_pg.py`` wrote:

    <folder>/<arm>/timeline/*.real.json   existing memory timeline questions
    <folder>/<arm>/probes/*.json          proposal probes

and writes ``ab.json`` and ``result.md`` into the folder. Judged by rule only:
key facts are fixed strings in the case file; a proposal is a stored candidate
row; a question is one the model actually put to the user. Whether an answer
reads well, or invents something, is not scored.

    server/.venv/bin/python tools/xiaopai_memory_proposal_ab.py score <folder>
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xiaopai_memory_timeline_baseline import CASE_FILE, score_real  # noqa: E402

ARMS = {"baseline": "A：提示词 1.0.0，原 memory.search 说明，提议闸门关闭",
        "candidate": "B：提示词 1.1.0，新 memory.search 说明，提议闸门对 1.1.0 打开"}
# The model must not tell the user something is already remembered: a candidate is a card.
CLAIMS_SAVED = re.compile(
    r"(?:已经?|都)(?:为你|帮你|替你|给你)?(?:记住|记下|保存)|我记住了|我会记住")
# "确认前不视为已记住", "并未保存", "才算记住" say the opposite.
NOT_A_CLAIM = re.compile(r"(?:不|未|没|才|前|后)[^，。；,.;\n]{0,8}$")


def claims_saved(text):
    return any(not NOT_A_CLAIM.search(text[:match.start()])
               for match in CLAIMS_SAVED.finditer(text))
MENTIONS_CARD = re.compile(r"确认|卡片|提议|建议卡|点.{0,4}记住")


def _timeline(folder):
    observations = [json.loads(path.read_text()) for path in sorted(folder.glob("*.real.json"))]
    if not observations:
        return None
    report = score_real(json.loads(CASE_FILE.read_text()), observations)
    body = report["groups"]["real"]
    return {
        "questions": body["questions"], "status": body["status"],
        "fact_questions": body["fact_questions"],
        "fact_questions_answered": body["fact_questions_answered"],
        "fact_questions_retrieved": body["fact_questions_retrieved"],
        "answers_withheld": body["answers_withheld"],
        "budget_exhausted": body["budget_exhausted"],
        "unknown_expected": body["unknown_expected"],
        "unknown_admitted": body["unknown_admitted"],
        "language_expected": body["language_expected"], "language_met": body["language_met"],
        "clarifications": body["clarifications"], "mean_seconds": body["mean_seconds"],
        "mean_used_tokens": body["mean_used_tokens"],
        "total_used_tokens": sum(item.get("used_tokens") or 0 for item in observations),
        "memory_tool_calls": body["memory_tool_calls"], "gates": report["gates"],
        "missing": report["missing"],
        "candidates_stored": sum(len(item.get("candidates") or []) for item in observations),
        "proposals_rejected": sorted(reason for item in observations
                                     for reason in item.get("proposals_rejected") or []),
        "prompt_versions": sorted({str(item.get("prompt_version")) for item in observations}),
        "tool_definitions": sorted({str(item.get("tool_definitions_digest"))[:12]
                                    for item in observations}),
        "rows": [{"timeline": row["timeline"], "question": row["question"],
                  "status": row["status"], "answered": row.get("answered"),
                  "retrieved": row.get("retrieved"), "used_tokens": row["used_tokens"]}
                 for row in report["rows"]],
    }


def _probe(record):
    turns = record["turns"]
    stored = [item for turn in turns for item in turn["candidates"]]
    rejected = [reason for turn in turns for reason in turn["proposals_rejected"]]
    pending = record["pending_candidates_at_end"]
    expect = record["expect"]
    answers = " ".join(turn["answer"] for turn in turns)
    outcome = {
        "propose": "hit" if any(item["origin"] == "explicit" for item in stored) else "miss",
        "propose_proactive": "hit" if stored else "miss",
        "none": "false_proposal" if stored else "clean",
        "void": ("clean" if not pending and turns[-1]["voids"] else "not_voided"),
    }[expect]
    return {
        "probe": record["probe"], "expect": expect, "outcome": outcome,
        "status": [turn["status"] for turn in turns],
        "stored": [{"origin": item["origin"], "kind": item["kind"], "text": item["text"],
                    "scope_kind": item["scope_kind"]} for item in stored],
        "rejected": rejected, "pending_at_end": pending,
        "questions_asked": sum(len(turn["clarifications"]) + len(turn["final_questions"])
                               for turn in turns),
        "claims_saved": claims_saved(answers),
        "mentions_confirmation": bool(MENTIONS_CARD.search(answers)),
        "used_tokens": sum(turn["used_tokens"] or 0 for turn in turns),
        "seconds": round(sum(turn["seconds"] for turn in turns), 1),
        "tool_calls": sum(sum(turn["tool_calls"].values()) for turn in turns),
        "prompt_versions": sorted({str(turn["prompt_version"]) for turn in turns}),
        "tool_definitions": sorted({str(turn["tool_definitions_digest"])[:12]
                                    for turn in turns}),
    }


def _probes(folder):
    rows = [_probe(json.loads(path.read_text())) for path in sorted(folder.glob("*.json"))]
    if not rows:
        return None
    should = [row for row in rows if row["expect"].startswith("propose")]
    should_not = [row for row in rows if row["expect"] == "none"]
    return {
        "probes": len(rows),
        "should_propose": len(should),
        "proposed": sum(row["outcome"] == "hit" for row in should),
        "missed": [row["probe"] for row in should if row["outcome"] == "miss"],
        "should_not_propose": len(should_not),
        "false_proposals": [row["probe"] for row in should_not
                            if row["outcome"] == "false_proposal"],
        "refused_by_server": sorted(reason for row in rows for reason in row["rejected"]),
        "void_probes": {row["probe"]: row["outcome"] for row in rows if row["expect"] == "void"},
        "questions_asked": sum(row["questions_asked"] for row in rows),
        "questions_asked_when_should_not_propose": sum(
            row["questions_asked"] for row in should_not),
        "claims_saved": [row["probe"] for row in rows if row["claims_saved"]],
        "total_used_tokens": sum(row["used_tokens"] for row in rows),
        "tool_calls": sum(row["tool_calls"] for row in rows),
        "not_completed": [row["probe"] for row in rows
                          if any(status != "completed" for status in row["status"])],
        "prompt_versions": sorted({value for row in rows for value in row["prompt_versions"]}),
        "tool_definitions": sorted({value for row in rows for value in row["tool_definitions"]}),
        "rows": rows,
    }


def score(folder):
    return {
        "schema": "xiaopai-memory-proposal-ab/v1", "judged_by": "rules", "runs_per_cell": 1,
        "not_scored": ["answer_quality_beyond_key_facts", "fabrication", "run_to_run_variance"],
        "arms": {arm: {"label": label, "timeline": _timeline(folder / arm / "timeline"),
                       "probes": _probes(folder / arm / "probes")}
                 for arm, label in ARMS.items() if (folder / arm).is_dir()},
    }


def _pair(report, part, key, render=str):
    return " | ".join(
        render(report["arms"][arm][part][key]) if report["arms"].get(arm, {}).get(part) else "未跑"
        for arm in ARMS)


def markdown(report):
    lines = ["# 记忆提议 Prompt A/B（真实模型，按规则判定）", "",
             "每题每组只跑 1 次；回答写得好不好、有没有编造没有评分。", "",
             "| | " + " | ".join(ARMS.values()) + " |", "| --- | --- | --- |"]

    def row(label, part, key, render=str):
        lines.append(f"| {label} | {_pair(report, part, key, render)} |")

    lines.append("| **既有评测题（记忆时间线，当前实现）** | | |")
    row("题数", "timeline", "questions")
    row("结束状态", "timeline", "status", lambda value: json.dumps(value, ensure_ascii=False))
    for label, hit, total in (("回答里写出全部关键事实的题", "fact_questions_answered",
                               "fact_questions"),
                              ("检索到全部关键事实的题", "fact_questions_retrieved",
                               "fact_questions"),
                              ("该说“查不到”时说了", "unknown_admitted", "unknown_expected"),
                              ("按本人约定的语言起草", "language_met", "language_expected")):
        lines.append(f"| {label} | " + " | ".join(
            f"{report['arms'][arm]['timeline'][hit]}/{report['arms'][arm]['timeline'][total]}"
            if report["arms"].get(arm, {}).get("timeline") else "未跑" for arm in ARMS) + " |")
    row("回答被换成“未通过核对”", "timeline", "answers_withheld")
    row("以“运行预算已用完”结束", "timeline", "budget_exhausted")
    row("向用户追问的问题数", "timeline", "clarifications")
    row("多出来的记忆提议（存下的候选）", "timeline", "candidates_stored")
    row("平均 token", "timeline", "mean_used_tokens")
    row("合计 token", "timeline", "total_used_tokens")
    row("门禁违反", "timeline", "gates", lambda value: str(sum(value.values())))
    lines.append("| **提议探针** | | |")
    row("探针数", "probes", "probes")
    lines.append("| 该提议的：提了 / 总数 | " + " | ".join(
        f"{report['arms'][arm]['probes']['proposed']}/"
        f"{report['arms'][arm]['probes']['should_propose']}"
        if report["arms"].get(arm, {}).get("probes") else "未跑" for arm in ARMS) + " |")
    row("漏提的探针", "probes", "missed", lambda value: "、".join(value) or "无")
    lines.append("| 不该提议的：误提 / 总数 | " + " | ".join(
        f"{len(report['arms'][arm]['probes']['false_proposals'])}/"
        f"{report['arms'][arm]['probes']['should_not_propose']}"
        if report["arms"].get(arm, {}).get("probes") else "未跑" for arm in ARMS) + " |")
    row("模型提了、被服务器拒收的", "probes", "refused_by_server",
        lambda value: "、".join(value) or "无")
    row("“只是讨论”探针", "probes", "void_probes",
        lambda value: json.dumps(value, ensure_ascii=False))
    row("向用户提的问题数（全部探针）", "probes", "questions_asked")
    row("其中不该提议的探针", "probes", "questions_asked_when_should_not_propose")
    row("回答里说“已记住”之类的探针", "probes", "claims_saved",
        lambda value: "、".join(value) or "无")
    row("没有正常完成的探针", "probes", "not_completed", lambda value: "、".join(value) or "无")
    row("工具调用次数", "probes", "tool_calls")
    row("合计 token", "probes", "total_used_tokens")
    lines += ["", "## 逐个探针", "", "| 探针 | 期望 | A | B | B 存下的候选 |",
              "| --- | --- | --- | --- | --- |"]
    by_arm = {arm: {row["probe"]: row for row in (body.get("probes") or {}).get("rows", [])}
              for arm, body in report["arms"].items()}
    for probe in sorted({key for rows in by_arm.values() for key in rows}):
        cells = []
        for arm in ARMS:
            item = by_arm.get(arm, {}).get(probe)
            cells.append("未跑" if item is None else
                         f"{item['outcome']}；问 {item['questions_asked']}；"
                         f"{item['used_tokens']} token")
        after = by_arm.get("candidate", {}).get(probe) or {}
        stored = "；".join(f"{item['origin']}/{item['kind']}/{item['scope_kind']}「{item['text']}」"
                          for item in after.get("stored", [])) or "—"
        expect = next(rows[probe]["expect"] for rows in by_arm.values() if probe in rows)
        lines.append(f"| {probe} | {expect} | {cells[0]} | {cells[1]} | {stored} |")
    lines += ["", "## 逐题（既有评测题）", "",
              "| 题 | A：状态 / 答出 / token | B：状态 / 答出 / token |", "| --- | --- | --- |"]
    rows = {arm: {(row["timeline"], row["question"]): row
                  for row in (body.get("timeline") or {}).get("rows", [])}
            for arm, body in report["arms"].items()}
    for key in sorted({key for value in rows.values() for key in value}):
        cells = []
        for arm in ARMS:
            item = rows.get(arm, {}).get(key)
            cells.append("未跑" if item is None else
                         f"{item['status']} / {item['answered']} / {item['used_tokens']}")
        lines.append(f"| {key[0]} {key[1]} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    action = actions.add_parser("score")
    action.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    report = score(args.folder)
    (args.folder / "ab.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.folder / "result.md").write_text(markdown(report))
    print(json.dumps({arm: {part: ({key: body[part][key] for key in body[part]
                                    if key != "rows"} if body[part] else None)
                            for part in ("timeline", "probes")}
                      for arm, body in report["arms"].items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
