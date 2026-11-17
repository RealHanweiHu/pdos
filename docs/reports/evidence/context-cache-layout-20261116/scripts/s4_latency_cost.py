"""Latency vs uncached/cached/output tokens, cross-validated across the two batches."""
import pickle, sys, statistics as st

class _NP:
    pass
def _solve(X, y):
    n = len(X[0])
    A = [[sum(r[i]*r[j] for r in X) for j in range(n)] for i in range(n)]
    b = [sum(r[i]*v for r, v in zip(X, y)) for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(A[k][i])); A[i], A[p] = A[p], A[i]; b[i], b[p] = b[p], b[i]
        for k in range(i+1, n):
            f = A[k][i]/A[i][i]
            for j in range(i, n): A[k][j] -= f*A[i][j]
            b[k] -= f*b[i]
    x = [0]*n
    for i in reversed(range(n)):
        x[i] = (b[i]-sum(A[i][j]*x[j] for j in range(i+1, n)))/A[i][i]
    return x
rows = [c for c in pickle.load(open(sys.argv[1], "rb")) if c["elapsed"] and c["output"] is not None and c["state"] == "completed"]
def design(cs):
    X = [[1, (c["prompt"] - c["cached"]) / 1000, c["cached"] / 1000, c["output"] / 1000] for c in cs]
    y = [c["elapsed"] / 1000 for c in cs]
    return X, y
def fit(cs):
    X, y = design(cs); return _solve(X, y)
def score(beta, cs):
    X, y = design(cs); p = [sum(a*b for a, b in zip(r, beta)) for r in X]; m = sum(y)/len(y)
    return 1 - sum((a-b)**2 for a, b in zip(y, p)) / sum((a-m)**2 for a in y), st.median(abs(a-b) for a, b in zip(y, p))
for iso in ("main", None):
    cs = [c for c in rows if iso is None or c["isolation"] == iso]
    a = [c for c in cs if c["batch"] == "1101"]; b = [c for c in cs if c["batch"] == "1105"]
    print("== isolation", iso or "all", "n", len(a), len(b))
    for name, tr, te in (("fit 1101 -> test 1105", a, b), ("fit 1105 -> test 1101", b, a)):
        beta = fit(tr); r2, mae = score(beta, te)
        print(f"  {name}: base={beta[0]:.2f}s  uncached={beta[1]*1000:.0f}ms/1k  cached={beta[2]*1000:.0f}ms/1k  output={beta[3]:.1f}s/1k   out-of-sample R2={r2:.2f} median|err|={mae:.1f}s")
    beta = fit(cs); print(f"  pooled: base={beta[0]:.2f}s uncached={beta[1]*1000:.0f}ms/1k cached={beta[2]*1000:.0f}ms/1k output={beta[3]:.1f}s/1k")
# direct paired comparison on main first calls: hit vs miss, similar prompt size and output
first = [c for c in rows if c["isolation"] == "main" and c["idx"] == 0 and 36000 < c["prompt"] < 48000]
hit = [c for c in first if c["cached"] > 30000]; miss = [c for c in first if c["cached"] < 1000]
for name, cs in (("first call, prefix hit ", hit), ("first call, prefix miss", miss)):
    e = sorted(c["elapsed"] / 1000 for c in cs); o = st.median(c["output"] for c in cs)
    print(f"{name}: n={len(cs)} elapsed p25/p50/p75 = {e[len(e)//4]:.1f}/{st.median(e):.1f}/{e[3*len(e)//4]:.1f}s  median output={o}")
# cost at the price card
P_IN, P_OUT, P_CACHE = 0.313773, 1.255091, 0.062755
allc = [c for c in pickle.load(open(sys.argv[1], "rb"))]
inp = sum(c["prompt"] for c in allc); cached = sum(c["cached"] for c in allc); out = sum(c["output"] or 0 for c in allc)
cost = ((inp - cached) * P_IN + cached * P_CACHE + out * P_OUT) / 1e6
print(f"actual: input {inp/1e6:.1f}M cached {cached/inp:.1%} output {out/1e6:.2f}M cost ${cost:.2f} (input side ${((inp-cached)*P_IN+cached*P_CACHE)/1e6:.2f})")
firsts = [c for c in allc if c["isolation"] == "main" and c["idx"] == 0]
stable = sum(min(c["prompt"], 37504) - min(c["cached"], 37504) for c in firsts if c["prompt"] > 37504)
c2 = cached + stable
cost2 = ((inp - c2) * P_IN + c2 * P_CACHE + out * P_OUT) / 1e6
print(f"if every run's first call reused tools+system (37.5k): cached {c2/inp:.1%} cost ${cost2:.2f} ({(cost-cost2)/cost:.1%} lower); tokens moved {stable/1e6:.2f}M")
skills = sum(3800 for c in firsts)
c3 = c2 + skills; cost3 = ((inp - c3) * P_IN + c3 * P_CACHE + out * P_OUT) / 1e6
print(f"  plus skill bodies ahead of the envelope (3.8k per run): cached {c3/inp:.1%} cost ${cost3:.2f} (further {(cost2-cost3)/cost:.1%})")
