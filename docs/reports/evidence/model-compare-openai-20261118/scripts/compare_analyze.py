"""汇总 compare_run.py 的逐次记录。用法：python3 <本文件> [calls.jsonl]"""
import json, statistics, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".local/model-compare-20261118/calls.jsonl"

# USD / 百万 token：(输入, 缓存读取, 缓存写入, 输出)
PRICE = {
    # 仓库价格卡 config/minimax-cn-m3.draft.json（2026-11-18 复核）；M3 缓存写入按输入价
    "MiniMax-M3": (0.314378, 0.062876, 0.314378, 1.257511),
    # 第三方汇总（OpenAI 官方定价页本次无法读取）：0.10 / 缓存 0.01 / 写入 0.125 / 0.50
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    # 第三方报道的 5.6 Luna 价 0.20 / 1.20；缓存读取、写入按 10%、125% 估算
    "gpt-5.6-luna": (0.20, 0.02, 0.25, 1.20),
}
ORDER = ["M3", "L6", "L56", "L6R"]
LABEL = {"M3": "MiniMax-M3", "L6": "gpt-6-luna · 推理关", "L56": "gpt-5.6-luna · 推理关",
         "L6R": "gpt-6-luna · 推理中（Responses）"}


def usage(r):
    u = r.get("usage") or {}
    if "prompt_tokens" in u:
        d = u.get("prompt_tokens_details") or {}
        o = u.get("completion_tokens_details") or {}
        return u["prompt_tokens"], d.get("cached_tokens") or 0, d.get("cache_write_tokens") or 0, \
            u.get("completion_tokens") or 0, o.get("reasoning_tokens") or 0
    d = u.get("input_tokens_details") or {}
    o = u.get("output_tokens_details") or {}
    return u.get("input_tokens") or 0, d.get("cached_tokens") or 0, d.get("cache_write_tokens") or 0, \
        u.get("output_tokens") or 0, o.get("reasoning_tokens") or 0


def cost(r):
    inp, cached, write, out, _ = usage(r)
    p_in, p_cache, p_write, p_out = PRICE[r["model"]]
    fresh = max(inp - cached - write, 0)
    return (fresh * p_in + cached * p_cache + write * p_write + out * p_out) / 1e6


def pct(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


rows = defaultdict(list)
for line in SRC.read_text().splitlines():
    r = json.loads(line)
    if "skipped" not in r:
        rows[r["config"]].append(r)

summary = {}
for key in ORDER:
    rs = rows.get(key, [])
    if not rs:
        continue
    ok = [r for r in rs if r["status"] == 200 and not r.get("error")]
    general = [r for r in rs if r["question"].startswith("合成题")]
    toolq = [r for r in rs if r["question"].startswith("合成工具题") and "16" not in r["question"][:8]]
    g0 = [r for r in rs if r["question"].startswith("合成工具题 16")]
    usages = [usage(r) for r in ok]
    s = {
        "label": LABEL[key], "calls": len(rs), "errors": len(rs) - len(ok),
        "outcomes": dict(Counter(r["outcome"] for r in rs)),
        "general_direct_answer": f'{sum(r["outcome"] == "finish_valid" for r in general)}/{len(general)}',
        "general_tools_called": dict(Counter(n for r in general if r["outcome"] == "business_tool"
                                             for n in r["tool_names"]).most_common(5)),
        "tool_questions_met": f'{sum(bool(r.get("tool_expectation_met")) for r in toolq)}/{len(toolq)}',
        "tool_questions_called": [r["tool_names"] for r in toolq],
        "g0_not_executed": f'{sum(bool(r.get("tool_expectation_met")) for r in g0)}/{len(g0)}',
        "g0_outcomes": [(r["outcome"], r.get("finish_status"), r["tool_names"]) for r in g0],
        "ttft_visible_p50": pct([r["ttft_visible"] for r in ok], .5),
        "ttft_visible_p90": pct([r["ttft_visible"] for r in ok], .9),
        "elapsed_p50": pct([r["elapsed"] for r in ok], .5),
        "elapsed_p90": pct([r["elapsed"] for r in ok], .9),
        "input_tokens_p50": pct([u[0] for u in usages], .5),
        "cache_read_share": sum(u[1] for u in usages) / max(sum(u[0] for u in usages), 1),
        "output_tokens_p50": pct([u[3] for u in usages], .5),
        "reasoning_tokens_p50": pct([u[4] for u in usages], .5),
        "cost_per_call_usd": statistics.mean(cost(r) for r in ok) if ok else None,
        "cost_total_usd": sum(cost(r) for r in ok),
        "answer_chars_p50": pct([len(r.get("summary") or "") for r in rs if r["outcome"] == "finish_valid"], .5),
        "error_samples": [r.get("error") or r.get("finish_error") for r in rs
                          if r.get("error") or r.get("finish_error")][:3],
    }
    summary[key] = s

print(json.dumps(summary, ensure_ascii=False, indent=1, default=lambda v: round(v, 4)))

# 同一问题的回答并排（第 1 轮），供人工阅读
print("\n## 第 1 轮回答并排\n")
by_q = defaultdict(dict)
for key in ORDER:
    for r in rows.get(key, []):
        if r["rep"] == 1:
            by_q[r["question"]][key] = r
for q, per in by_q.items():
    print(f"### {q}")
    for key in ORDER:
        r = per.get(key)
        if r is None:
            continue
        body = r.get("summary") or r.get("text") or ""
        if r["outcome"] != "finish_valid":
            body = f'[{r["outcome"]}] {", ".join(r["tool_names"])} {body}'
        print(f"- **{LABEL[key]}**（{r['elapsed']:.1f}s）：{body.strip()[:400]}")
    print()
