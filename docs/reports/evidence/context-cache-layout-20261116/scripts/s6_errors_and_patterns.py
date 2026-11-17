"""Repeated failures, same-tool streaks and turn-to-turn status in the recorded runs."""
import glob, json, os
from collections import Counter, defaultdict
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..")
BASE = os.path.join(ROOT, "docs/reports/evidence/pdos-next-real-eval-2026110")
runs, seen, status = [], set(), {}
for b in ("1", "5"):
    for f in sorted(glob.glob(f"{BASE}{b}/live/runs/*.json")):
        d = json.load(open(f))
        status[(b, d.get("run_id") or d.get("id"))] = (d.get("continued_from_id"), (d.get("output") or {}).get("status") or d.get("status"))
        calls = [c for c in d.get("tool_calls", []) if (b, c["id"]) not in seen]
        seen.update((b, c["id"]) for c in calls)
        byrun = defaultdict(list)
        for c in sorted(calls, key=lambda c: c["created_at"]): byrun[c["run_id"]].append(c)
        runs += [((d.get("output") or {}).get("status"), cs) for cs in byrun.values()]
tot = err = rep = 0; streaks = []; errtools = Counter(); reptools = Counter(); after = Counter()
for ostatus, cs in runs:
    tools = [c for c in cs if c["tool"] != "model" and (c.get("execution_binding") or {}).get("isolation", "main") == "main"]
    seen_err = Counter(); best = cur = 0; prev = None
    for i, c in enumerate(tools):
        tot += 1; cur = cur + 1 if c["tool"] == prev else 1; prev = c["tool"]; best = max(best, cur)
        e = c.get("error_code")
        if e:
            err += 1; errtools[(c["tool"], e)] += 1
            if seen_err[(c["tool"], e)]: rep += 1; reptools[(c["tool"], e)] += 1
            seen_err[(c["tool"], e)] += 1
            nxt = tools[i + 1] if i + 1 < len(tools) else None
            after["same tool again" if nxt and nxt["tool"] == c["tool"] else "other tool" if nxt else "no further tool"] += 1
    if tools: streaks.append((best, ostatus))
print("runs", len(runs), "main-loop tool calls", tot, "failed", err, f"{err/tot:.1%}")
print("failures that repeat an earlier same tool + same code in the run:", rep, f"{rep/err:.1%}")
print("after a failure, the next tool call:", dict(after))
print("most repeated:", reptools.most_common(5)); print("most failed:", errtools.most_common(8))
s = sorted(x[0] for x in streaks)
print("longest same-tool streak per run: p50", s[len(s)//2], "p90", s[int(.9*len(s))], "max", s[-1], "| runs with streak>=5:", sum(x >= 5 for x in s), "of", len(s),
      "| their status:", dict(Counter(x[1] for x in streaks if x[0] >= 5)))
c = Counter(); tot2 = Counter()
for (b, rid), (prev, st) in status.items():
    if prev and (b, prev) in status: c[(status[(b, prev)][1], st)] += 1; tot2[status[(b, prev)][1]] += 1
print("status of a turn given the previous turn of the same session (correlation only):")
for (p, s2), n in sorted(c.items(), key=lambda kv: str(kv[0])): print(f"  prev={p} -> now={s2}: {n} ({n/tot2[p]:.0%})")
