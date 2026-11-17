"""Which rendering order explains the provider's cached_tokens? LCP with earlier requests."""
import bisect, json, os, pickle, sys, statistics as st
from datetime import datetime
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
rows = pickle.load(open(sys.argv[1], "rb"))
rows = [c for c in rows if c["req"] and os.path.exists(os.path.join(ROOT, c["req"])) and c["started"]]
def parts(body):
    msgs = body["messages"]
    def enc(m):
        extra = "".join(json.dumps(m[k], ensure_ascii=False) for k in ("tool_calls", "tool_call_id", "reasoning_content") if m.get(k))
        c = m.get("content")
        return "<" + m["role"] + ">" + (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)) + extra
    system = enc(msgs[0]) if msgs and msgs[0]["role"] == "system" else ""
    rest = "".join(enc(m) for m in msgs[1:])
    tools = json.dumps(body.get("tools", []), ensure_ascii=False)
    return system, tools, rest
ORDERS = {"sys_tools_msgs": (0, 1, 2), "tools_sys_msgs": (1, 0, 2), "sys_msgs_tools": (0, 2, 1)}
def lcp(a, b):
    lo, hi = 0, min(len(a), len(b))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if a[:mid] == b[:mid]: lo = mid
        else: hi = mid - 1
    return lo
ts = lambda s: datetime.fromisoformat(s).timestamp()
out = {}
for batch in ("1101", "1105"):
    cs = sorted((c for c in rows if c["batch"] == batch), key=lambda c: c["started"])
    for name, order in ORDERS.items():
        keys, meta = [], []
        for c in cs:
            p = parts(json.load(open(os.path.join(ROOT, c["req"]))))
            s = "".join(p[i] for i in order).encode()
            i = bisect.bisect_left(keys, s)
            best, who = 0, None
            for j in (i - 1, i):
                if 0 <= j < len(keys):
                    v = lcp(s, keys[j])
                    if v > best: best, who = v, meta[j]
            pred = best / len(s) * c["prompt"]
            out.setdefault(c["id"], {})[name] = (pred, (ts(c["started"]) - who[0]) if who else None, who[1] == c["run"] if who else None, len(s))
            keys.insert(i, s); meta.insert(i, (ts(c["finished"] or c["started"]), c["run"]))
        print(batch, name, "done", file=sys.stderr)
pickle.dump(out, open(sys.argv[1].replace("rows", "lcp"), "wb"))
byid = {c["id"]: c for c in rows}
for name in ORDERS:
    for cls in ("main_first_new", "main_first_cont", "child_first", "main_later", "child_later"):
        xs = [(out[i][name][0], byid[i]["cached"], byid[i]["prompt"]) for i in out if byid[i]["cls"] == cls]
        pred = sum(x[0] for x in xs); act = sum(x[1] for x in xs); tot = sum(x[2] for x in xs)
        err = st.median(abs(x[0] - x[1]) for x in xs)
        under = sum(1 for x in xs if x[1] > x[0] + 300)
        print(f"{name:15s} {cls:16s} n={len(xs):4d} predicted_hit={pred/tot:6.1%} actual_hit={act/tot:6.1%} median|err|={err:8.0f} actual>pred+300: {under}")
