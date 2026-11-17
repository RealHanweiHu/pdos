import json, glob, os, pickle, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
BATCHES = {"1101": "docs/reports/evidence/pdos-next-real-eval-20261101/live/runs",
           "1105": "docs/reports/evidence/pdos-next-real-eval-20261105/live/runs"}
def load():
    calls, tools, seen = [], [], set()
    for batch, rel in BATCHES.items():
        for f in sorted(glob.glob(os.path.join(ROOT, rel, "*.json"))):
            d = json.load(open(f))
            for c in d.get("tool_calls", []):
                key = (batch, c["id"])
                if key in seen:
                    continue
                seen.add(key)
                base = {"batch": batch, "file": os.path.basename(f), "case": d.get("case_id"),
                        "suite": d.get("suite"), "focus": d.get("focus"),
                        "session": d.get("session_id"), "run": c["run_id"],
                        "turn_index": d.get("turn_index"), "id": c["id"], "tool": c["tool"],
                        "state": c["state"], "error": c.get("error_code"), "at": c["created_at"]}
                if c["tool"] != "model":
                    tools.append({**base, "arguments": None})
                    continue
                po = c.get("provider_observation") or {}
                ru = c.get("raw_usage") or po.get("raw_usage") or {}
                eb = c.get("execution_binding") or {}
                res = c.get("result") or {}
                calls.append({**base, "isolation": eb.get("isolation"),
                    "tools_digest": eb.get("tool_definitions_digest"),
                    "skills": [s.get("key") for s in eb.get("loaded_skills", [])],
                    "prompt": ru.get("prompt_tokens"),
                    "cached": (ru.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    "output": ru.get("completion_tokens"),
                    "elapsed": c.get("elapsed_ms") or po.get("elapsed_ms"),
                    "started": po.get("started_at"), "finished": po.get("finished_at"),
                    "req": po.get("private_request_path"), "bytes": po.get("request_bytes"),
                    "budget": res.get("context_budget"),
                    "ncalls": [x.get("name") for x in res.get("calls", [])]})
    return calls, tools
if __name__ == "__main__":
    calls, tools = load()
    pickle.dump((calls, tools), open(sys.argv[1], "wb"))
    print(len(calls), len(tools))
    known = [c for c in calls if c["prompt"]]
    print("with usage", len(known), "with req file", sum(bool(c["req"]) and os.path.exists(os.path.join(ROOT, c["req"])) for c in calls))
    for b in BATCHES:
        k = [c for c in known if c["batch"] == b]
        print(b, len(k), sum(c["prompt"] for c in k), sum(c["cached"] or 0 for c in k))
