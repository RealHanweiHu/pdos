"""Replay labelled utterances through the fixed proposal expressions (P121 第 9 项, D476).

Measures, for the owner's own words only and with no model, database or provider:

* 误放行 (false admit): a message labelled "must not open a proposal" that the
  fixed expressions would let through if the model proposed it;
* 漏 (miss): a message labelled "should open a proposal" that they refuse.

This is the gate's own error. It is an upper bound on false proposals, because
the model must also choose to propose and the owner must still confirm, and it
is exactly the miss rate of the path, because a refused trigger can never
become a candidate.

Two lists are compared on the same utterances: ``v1`` is the literal list M2a
shipped (closed) with, ``v2`` is ``pdos_next.agent.memory.triggers``.

    server/.venv/bin/python tools/xiaopai_memory_proposal_replay.py \
        --output-dir docs/reports/evidence/<topic>/trigger-replay
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from pdos_next.agent.memory import triggers  # noqa: E402

CASES = ROOT / "docs/evaluations/xiaopai-memory-v0/proposal-triggers.json"
# The literal list in candidates.NOTE_INTENT before P121 第 9 项 (commit fbcda6bc).
V1_NOTE_INTENT = (
    "记住", "记一下", "记下来", "帮我记", "以后都", "以后一律", "以后请", "每次都", "别忘了",
    "我说的", "我说“", "我说\"", "我习惯", "我一般",
)


def _v1(text):
    return any(expression in text for expression in V1_NOTE_INTENT)


RULES = {
    # group: {list version: predicate or None when that list had no such check}
    "remember": {"v1": _v1, "v2": lambda text: triggers.remember(text, text)},
    "alias": {"v1": _v1,
              "v2": lambda text: triggers.alias(text, text) or triggers.remember(text, text)},
    # v1 accepted any two quotes as "corrections" and had no discussion rule.
    "correction": {"v1": lambda _text: True, "v2": triggers.correction},
    "discussion": {"v1": None, "v2": triggers.discussion},
}


def evaluate(items):
    result = {}
    for group, rules in RULES.items():
        rows = [item for item in items if item["group"] == group]
        positive = [item for item in rows if item["label"]]
        negative = [item for item in rows if not item["label"]]
        result[group] = {"should_open": len(positive), "should_not_open": len(negative)}
        for version, rule in rules.items():
            if rule is None:
                result[group][version] = None
                continue
            false_admit = [item["id"] for item in negative if rule(item["text"])]
            missed = [item["id"] for item in positive if not rule(item["text"])]
            result[group][version] = {
                "false_admit": len(false_admit), "missed": len(missed),
                "false_admit_rate": round(len(false_admit) / max(len(negative), 1), 3),
                "miss_rate": round(len(missed) / max(len(positive), 1), 3),
                "false_admit_ids": false_admit, "missed_ids": missed,
            }
    return result


def report(cases):
    return {
        "schema": "xiaopai-memory-proposal-replay/v1",
        "triggers_version": triggers.VERSION,
        "case_file": {"version": cases["version"], "status": cases["status"],
                      "synthetic": cases["synthetic"]},
        "provider_calls": 0, "database_operations": 0,
        "splits": {name: evaluate([item for item in cases["items"] if item["split"] == name])
                   for name in sorted({item["split"] for item in cases["items"]})},
    }


def _cell(value):
    if value is None:
        return "无此规则"
    return (f"误放行 {value['false_admit']}（{value['false_admit_rate']:.1%}），"
            f"漏 {value['missed']}（{value['miss_rate']:.1%}）")


def markdown(result, cases):
    texts = {item["id"]: item["text"] for item in cases["items"]}
    names = {"remember": "对话提议（记住、以后……）", "alias": "个人叫法",
             "correction": "纠正（主动提议的引用）", "discussion": "“这只是讨论，不算决定”"}
    splits = {"tuning": "调参集（规则作者自己写的）",
              "dev": "开发集（独立写的第一份留出集，看过一次后并入调参）",
              "heldout": "留出集（独立写的第二份，规则冻结后只测一次）"}
    lines = ["# 提议触发说法回放（无模型）", "",
             f"规则版本 `{result['triggers_version']}`；合成语句，未经人工确认；"
             "provider 与数据库调用均为 0。", "",
             "误放行 = 标注为“不该出提议”的语句里，固定说法会放行的；"
             "漏 = 标注为“该出提议”的语句里，固定说法拒掉的。", ""]
    for split, groups in result["splits"].items():
        lines += [f"## {splits.get(split, split)}", "",
                  "| 规则 | 该出 | 不该出 | 原词表（v1） | 收窄后（v2） |",
                  "| --- | ---: | ---: | --- | --- |"]
        for group, value in groups.items():
            lines.append(f"| {names[group]} | {value['should_open']} | "
                         f"{value['should_not_open']} | {_cell(value['v1'])} | "
                         f"{_cell(value['v2'])} |")
        lines.append("")
        for group, value in groups.items():
            current = value["v2"]
            for label, key in (("收窄后仍误放行", "false_admit_ids"), ("收窄后漏掉", "missed_ids")):
                if current[key]:
                    lines.append(f"- {names[group]}，{label}："
                                 + "；".join(f"{identity}「{texts[identity]}」"
                                            for identity in current[key]))
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    result = report(cases)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "replay.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        (args.output_dir / "result.md").write_text(markdown(result, cases))
    summary = {split: {group: {version: (None if value[version] is None else
                                         [value[version]["false_admit"], value[version]["missed"]])
                               for version in ("v1", "v2")}
                       for group, value in groups.items()}
               for split, groups in result["splits"].items()}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
