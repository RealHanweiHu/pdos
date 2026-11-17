import pickle, sys, statistics as st
from collections import defaultdict
from datetime import datetime
rows = pickle.load(open(sys.argv[1], "rb")); lcp = pickle.load(open(sys.argv[1].replace("rows", "lcp"), "rb"))
ts = lambda s: datetime.fromisoformat(s).timestamp()
rows = [c for c in rows if c["started"]]
seq = defaultdict(list)
for c in sorted(rows, key=lambda c: c["started"]): seq[(c["batch"], c["run"], c["isolation"])].append(c)
print("== later calls: full-hit rate by gap since previous call finished (same run+isolation)")
buckets = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 120), (120, 300), (300, 600), (600, 1e9)]
agg = defaultdict(lambda: [0, 0, 0, 0])
for items in seq.values():
    for a, b in zip(items, items[1:]):
        if not a["finished"]: continue
        gap = ts(b["started"]) - ts(a["finished"])
        full = b["cached"] >= 0.9 * a["prompt"]
        for lo, hi in buckets:
            if lo <= gap < hi:
                k = (b["isolation"] == "main", lo, hi); agg[k][0] += 1; agg[k][1] += full; agg[k][2] += b["cached"]; agg[k][3] += a["prompt"]
for k in sorted(agg, key=lambda k: (not k[0], k[1])):
    n, f, cached, prev = agg[k]
    print(f"  {'main ' if k[0] else 'child'} gap {k[1]:>4.0f}-{k[2]:<6.0f}s n={n:4d} full-hit={f/n:6.1%} cached/prev_prompt={cached/prev:6.1%}")
print("== first calls of a run (main): cached vs gap since the most recent earlier main call (any run, same batch, same tools digest)")
mains = sorted((c for c in rows if c["isolation"] == "main"), key=lambda c: c["started"])
last = {}
res = defaultdict(lambda: [0, 0, 0])
detail = []
for c in mains:
    key = (c["batch"], c["tools_digest"])
    if c["idx"] == 0 and key in last and last[key]["finished"]:
        gap = ts(c["started"]) - ts(last[key]["finished"])
        for lo, hi in buckets:
            if lo <= gap < hi:
                res[(lo, hi)][0] += 1; res[(lo, hi)][1] += c["cached"] > 1000; res[(lo, hi)][2] += c["cached"]
        detail.append((c["cached"], round(lcp.get(c["id"], {}).get("sys_tools_msgs", (0,))[0]), round(gap), c["prompt"], c["cls"]))
    last[key] = c
for k in sorted(res):
    n, h, cached = res[k]
    print(f"  gap {k[0]:>4.0f}-{k[1]:<6.0f}s n={n:4d} share cached>1000: {h/n:6.1%} mean cached {cached/n:8.0f}")
print("== first calls with cached>1000: (cached, predicted_by_LCP, gap_s, prompt, cls)")
for d in sorted(detail, reverse=True)[:22]: print("  ", d)
print("== distribution of small cached values on first calls")
from collections import Counter
print(Counter(c["cached"] for c in rows if c["idx"] == 0).most_common(12))
