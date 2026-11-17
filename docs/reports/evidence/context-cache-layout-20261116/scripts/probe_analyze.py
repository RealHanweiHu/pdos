"""汇总 probe_run.py 的逐次记录，按 probe-plan.md 的判据输出。用法：python probe_analyze.py <calls.jsonl>"""
import json, statistics as st, sys

P_IN, P_OUT, P_CACHE = 0.313773, 1.255091, 0.062755  # 与 s4 相同的价卡，美元 / 百万 token
STABLE_HIT = 37_000
rows = [json.loads(l) for l in open(sys.argv[1])]
rows = [r for r in rows if r["phase"] != "smoke"]
med = lambda xs: st.median(xs) if xs else None

print("== 总量")
ok = [r for r in rows if r.get("prompt_tokens")]
inp = sum(r["prompt_tokens"] for r in ok); cached = sum(r["cached_tokens"] or 0 for r in ok)
out = sum(((r.get("usage") or {}).get("completion_tokens") or 0) for r in ok)
cost = ((inp - cached) * P_IN + cached * P_CACHE + out * P_OUT) / 1e6
print(f"调用 {len(rows)} 次，成功 {len(ok)} 次，失败 {len(rows) - len(ok)} 次；输入 {inp:,}，缓存读取 {cached:,}（{cached / inp:.1%}），输出 {out:,}，按价卡约 ${cost:.2f}")
for r in rows:
    if r.get("error"):
        print("  失败", r["seq"], r["group"], r["phase"], r["error"][:120])

print("\n== 预热")
for r in rows:
    if r["phase"] == "preheat":
        print(f"  C0 prompt={r['prompt_tokens']} cached={r['cached_tokens']}")

rounds = [r for r in rows if r["phase"] == "round" and r.get("prompt_tokens")]
print("\n== 各组 12 轮（稳定命中 = 至少 10 轮命中 >= 37,000）")
print("组 | 命中>=3.7万 | 前6轮 | 后6轮 | 命中中位数 | 命中最大 | 输入中位数 | 与上一轮同组共同前缀（字节中位数 / 请求字节中位数）")
summary = {}
for g in "ABCD":
    rs = sorted((r for r in rounds if r["group"] == g), key=lambda r: r["round"])
    hits = [r for r in rs if (r["cached_tokens"] or 0) >= STABLE_HIT]
    h1 = sum(1 for r in hits if r["round"] <= 6); h2 = len(hits) - h1
    cps = [r["common_prefix_bytes_vs_prev_same_group"] for r in rs if r["common_prefix_bytes_vs_prev_same_group"] is not None]
    summary[g] = (len(hits), h1, h2, med([r["cached_tokens"] or 0 for r in rs]))
    print(f"{g} | {len(hits)}/{len(rs)} | {h1}/6 | {h2}/6 | {med([r['cached_tokens'] or 0 for r in rs])} | "
          f"{max((r['cached_tokens'] or 0) for r in rs) if rs else None} | {med([r['prompt_tokens'] for r in rs])} | "
          f"{med(cps)} / {med([r['request_bytes'] for r in rs])}")
    print("    逐轮 cached:", [(r["round"], r["cached_tokens"], "新" if r["fresh_connection"] else "复用") for r in rs])

print("\n== 交叉检验：前 6 轮与后 6 轮各自的排序（按命中轮数，再按命中中位数）")
def rank(half):
    sc = {}
    for g in "ABCD":
        rs = [r for r in rounds if r["group"] == g and ((r["round"] <= 6) == (half == 1))]
        sc[g] = (sum(1 for r in rs if (r["cached_tokens"] or 0) >= STABLE_HIT), med([r["cached_tokens"] or 0 for r in rs]) or 0)
    return sorted("ABCD", key=lambda g: sc[g], reverse=True), sc
r1, s1 = rank(1); r2, s2 = rank(2)
print("  前半", r1, s1); print("  后半", r2, s2); print("  排序一致" if r1 == r2 else "  排序不一致")

print("\n== 首字时间：同组内命中与未命中（命中 = cached >= 37,000）")
for g in "ABCD":
    rs = [r for r in rounds if r["group"] == g and r.get("ttft_ms")]
    hit = [r["ttft_ms"] for r in rs if (r["cached_tokens"] or 0) >= STABLE_HIT]
    miss = [r["ttft_ms"] for r in rs if (r["cached_tokens"] or 0) < STABLE_HIT]
    pairs = min(len(hit), len(miss))
    verdict = ""
    if pairs < 8:
        verdict = "样本少于 8 对，只报告“未见差别”"
    elif abs(med(hit) - med(miss)) / med(miss) < 0.10:
        verdict = "相差不到 10%，未见差别"
    else:
        verdict = f"命中快 {(med(miss) - med(hit)) / med(miss):.0%}"
    print(f"  {g} 命中 n={len(hit)} 中位 {med(hit)} ms；未命中 n={len(miss)} 中位 {med(miss)} ms；{verdict}")
allr = [r for r in rows if r.get("ttft_ms") and r.get("prompt_tokens")]
hit = [r["ttft_ms"] for r in allr if (r["cached_tokens"] or 0) >= STABLE_HIT]
miss = [r["ttft_ms"] for r in allr if (r["cached_tokens"] or 0) < STABLE_HIT]
print(f"  全部调用：命中 n={len(hit)} 中位 {med(hit)} ms；未命中 n={len(miss)} 中位 {med(miss)} ms")

print("\n== 连接：新建 vs 复用（全部轮次）")
for fresh in (True, False):
    rs = [r for r in rounds if r["fresh_connection"] == fresh]
    print(f"  {'新建' if fresh else '复用'} n={len(rs)} 命中>=3.7万 {sum(1 for r in rs if (r['cached_tokens'] or 0) >= STABLE_HIT)}")

print("\n== 留存（重发第 12 轮的同一请求）")
for r in rows:
    if r["phase"] == "retention":
        print(f"  {r['group']} {r['note']}: prompt={r['prompt_tokens']} cached={r['cached_tokens']} ttft={r.get('ttft_ms')}")

print("\n== 并发（4 个 A 组请求同时发出）")
for r in rows:
    if r["phase"] == "concurrent":
        print(f"  {r['note']}: prompt={r['prompt_tokens']} cached={r['cached_tokens']} ttft={r.get('ttft_ms')}")
