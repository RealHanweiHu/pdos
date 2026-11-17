"""Counterfactual layouts on recorded first requests; key order learned on one batch, tested on the other."""
import json, os, pickle, sys, math, statistics as st
from collections import defaultdict
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
rows = [c for c in pickle.load(open(sys.argv[1], "rb")) if c["isolation"] == "main" and c["idx"] == 0 and c["req"] and os.path.exists(os.path.join(ROOT, c["req"]))]
def wide(ch):
    o = ord(ch); return 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF
def tok(s):
    w = sum(1 for ch in s if wide(ch)); return (w + math.ceil((len(s) - w) / 4)) * 1.1
def dumps(v): return json.dumps(v, ensure_ascii=False)
def load(c):
    body = json.load(open(os.path.join(ROOT, c["req"])))
    msgs = [m for m in body["messages"][1:] if m["role"] == "user"]
    try: env = json.loads(msgs[0]["content"])
    except Exception: return None
    if "context" not in env: return None
    return {"env": env, "skills": [m["content"] for m in msgs[1:] if not m["content"].startswith("Return the final response")], "c": c}
data = [x for x in (load(c) for c in sorted(rows, key=lambda c: c["started"])) if x]
by_session = defaultdict(list)
for x in data: by_session[(x["c"]["batch"], x["c"]["session"])].append(x)
pairs = {"1101": [], "1105": []}   # consecutive turns of one session
for (batch, _), items in by_session.items():
    for a, b in zip(items, items[1:]):
        if b["c"]["turn_index"]: pairs[batch].append((a, b))
cross = {"1101": [], "1105": []}   # first turns of different sessions, consecutive in time
for batch in pairs:
    firsts = [x for x in data if x["c"]["batch"] == batch and not x["c"]["turn_index"]]
    cross[batch] = list(zip(firsts, firsts[1:]))
def units(x):
    """(name, text) units of everything after system+tools."""
    env = x["env"]; ctx = env["context"]; out = {}
    for i, s in enumerate(x["skills"]): out[f"skill[{i}]"] = s
    for k, v in ctx.items():
        if k == "conversation" and isinstance(v, dict):
            out["conversation.meta"] = dumps({kk: vv for kk, vv in v.items() if kk != "turns"})
            out["conversation.turns"] = v.get("turns", [])
        elif k != "goal": out["context." + k] = dumps(v)
    out["goal"] = dumps(env.get("goal")); out["context_ref"] = dumps([env.get("context_ref"), env.get("omitted_fields")])
    for k, v in env.items():
        if k not in ("goal", "context", "context_ref", "omitted_fields"): out["env." + k] = dumps(v)
    return out
def stability(prs):
    same, size, n = defaultdict(int), defaultdict(float), defaultdict(int)
    for a, b in prs:
        ua, ub = units(a), units(b)
        for k in ub:
            n[k] += 1; size[k] += tok(dumps(ub[k]) if k == "conversation.turns" else ub[k])
            same[k] += k in ua and ua[k] == ub[k]
    return {k: (same[k] / n[k], size[k] / n[k], n[k]) for k in n}
def render(x, layout, order=None):
    u = units(x); turns = u.pop("conversation.turns", [])
    if layout == "L0":   # as sent: envelope (goal first), then skill bodies
        return [dumps(x["env"])] + x["skills"]
    skills = [u.pop(k) for k in sorted(k for k in u if k.startswith("skill["))]
    if layout == "L1":   # D160: skill bodies, then the envelope unchanged
        return skills + [dumps(x["env"])]
    tail = [u.pop("goal"), u.pop("context_ref")]
    keys = sorted(u, key=lambda k: (order.index(k) if k in order else len(order), k))
    stable = [k + "=" + u[k] for k in keys if k not in ("context.work_state",)]
    work = ["context.work_state=" + u["context.work_state"]] if "context.work_state" in u else []
    hist = [dumps(t) for t in (reversed(turns) if layout == "L3" else turns)]
    return skills + stable + hist + work + tail
def shared(a, b, layout, order=None):
    ra, rb = render(a, layout, order), render(b, layout, order)
    sa, sb = "\x1e".join(ra), "\x1e".join(rb)
    lo, hi = 0, min(len(sa), len(sb))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sa[:mid] == sb[:mid]: lo = mid
        else: hi = mid - 1
    return tok(sb[:lo]), tok(sb)
print("pairs (same session, consecutive turns):", {k: len(v) for k, v in pairs.items()}, " cross-session:", {k: len(v) for k, v in cross.items()})
stab = {b: stability(pairs[b]) for b in pairs}
print("== unit stability between consecutive turns of a session (share identical, mean tokens) — batch 1101 | 1105")
for k in sorted(set(stab["1101"]) | set(stab["1105"]), key=lambda k: -(stab["1101"].get(k, (0, 0, 0))[0])):
    a, b = stab["1101"].get(k), stab["1105"].get(k)
    f = lambda v: f"{v[0]:5.0%} {v[1]:6.0f}t n={v[2]:3d}" if v else "      —          "
    print(f"  {k:36s} {f(a)} | {f(b)}")
order = {b: [k for k, v in sorted(stab[b].items(), key=lambda kv: (-kv[1][0], kv[0]))] for b in stab}
print("== extra reusable prefix after system+tools on a run's first call (tokens, mean / median / share of the after-prefix part)")
for kind, sets in (("same session, next turn", pairs), ("different session", cross)):
    for train, test in (("1101", "1105"), ("1105", "1101")):
        for layout in ("L0", "L1", "L2", "L3"):
            vals = [shared(a, b, layout, order[train]) for a, b in sets[test]]
            if not vals: continue
            s = [v[0] for v in vals]; t = [v[1] for v in vals]
            print(f"  {kind:24s} order from {train} -> test {test}  {layout}: mean {st.mean(s):6.0f}  median {st.median(s):6.0f}  of {st.mean(t):6.0f} ({sum(s)/sum(t):5.1%})")
