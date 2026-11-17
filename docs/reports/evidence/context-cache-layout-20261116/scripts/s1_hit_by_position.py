import pickle, sys, statistics as st
from collections import defaultdict
calls, tools = pickle.load(open(sys.argv[1], "rb"))
known = [c for c in calls if c["prompt"] and c["cached"] is not None]
seq = defaultdict(list)
for c in sorted(known, key=lambda c: c["started"] or c["at"]):
    seq[(c["batch"], c["run"], c["isolation"])].append(c)
rows = []
for key, items in seq.items():
    for i, c in enumerate(items):
        prev = items[i-1] if i else None
        c["idx"] = i
        c["prev_prompt"] = prev["prompt"] if prev else 0
        c["tools_changed"] = bool(prev and prev["tools_digest"] != c["tools_digest"])
        main = c["isolation"] == "main"
        c["cls"] = ("main" if main else "child") + ("_first" if i == 0 else "_later")
        if main and i == 0:
            c["cls"] += "_new" if not c["turn_index"] else "_cont"
        rows.append(c)
# anomaly: prompt tokens far above bytes
anom = [c for c in rows if c["bytes"] and c["prompt"] > c["bytes"] / 2.2]
print("anomalous prompt>bytes/2.2:", len(anom), sum(c["prompt"] for c in anom))
ok = [c for c in rows if c not in anom]
def line(name, cs):
    p = sum(c["prompt"] for c in cs); h = sum(c["cached"] for c in cs)
    print(f"{name:22s} n={len(cs):5d} input={p/1e6:7.2f}M cached={h/1e6:7.2f}M hit={h/p if p else 0:6.1%} uncached={(p-h)/1e6:6.2f}M")
for b in ("1101", "1105", None):
    print("== batch", b or "all (excl anomalies)")
    cs = [c for c in ok if b is None or c["batch"] == b]
    line("all", cs)
    for cls in sorted({c["cls"] for c in cs}):
        line(cls, [c for c in cs if c["cls"] == cls])
# decomposition of uncached tokens
print("== uncached decomposition (all, excl anomalies)")
tot_unc = sum(c["prompt"] - c["cached"] for c in ok)
parts = defaultdict(int)
for c in ok:
    unc = c["prompt"] - c["cached"]
    if c["idx"] == 0:
        parts[c["cls"]] += unc
    else:
        new = max(0, c["prompt"] - c["prev_prompt"])
        lost = max(0, unc - new)
        parts["later_new_content"] += min(unc, new)
        if lost > 500:
            parts["later_lost_tools_changed" if c["tools_changed"] else "later_lost_other"] += lost
        else:
            parts["later_new_content"] += lost
for k, v in sorted(parts.items(), key=lambda kv: -kv[1]):
    print(f"  {k:28s} {v/1e6:6.2f}M {v/tot_unc:6.1%}")
# first calls: distribution of cached
for cls in ("main_first_new", "main_first_cont", "child_first"):
    cs = [c for c in ok if c["cls"] == cls]
    if not cs: continue
    cached = sorted(c["cached"] for c in cs); prompt = st.median(c["prompt"] for c in cs)
    q = lambda p: cached[int(p * (len(cached) - 1))]
    print(cls, "n", len(cs), "median prompt", prompt, "cached p10/p50/p90", q(.1), q(.5), q(.9),
          "share with cached<1000:", round(sum(x < 1000 for x in cached) / len(cached), 3))
# later calls with loss
later = [c for c in ok if c["idx"] > 0]
lost = [c for c in later if (c["prompt"] - c["cached"]) - max(0, c["prompt"] - c["prev_prompt"]) > 500]
print("later calls", len(later), "with lost cache >500:", len(lost), "of which tools changed:", sum(c["tools_changed"] for c in lost),
      "cleanup applied:", sum(bool((c["budget"] or {}).get("cleanup", {}).get("applied")) for c in lost),
      "reductions:", sum(bool((c["budget"] or {}).get("reductions")) for c in lost))
tc = [c for c in later if c["tools_changed"]]
print("tools changed calls:", len(tc), "median cached", st.median(c["cached"] for c in tc) if tc else None,
      "median prev prompt", st.median(c["prev_prompt"] for c in tc) if tc else None)
pickle.dump(rows, open(sys.argv[1].replace("calls", "rows"), "wb"))
