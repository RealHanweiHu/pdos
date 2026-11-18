"""Per-arm cache, latency and call totals from the runs' context_observed events.

Usage: python cache_summary.py <runtime.json> <evidence folder with A/ B/ observations>
Reads the isolated test database only; writes cache-summary.json into the folder.
"""
import glob
import json
import statistics
import sys

import psycopg

state, folder = json.load(open(sys.argv[1])), sys.argv[2]
cursor = psycopg.connect(state["admin_url"].replace("+psycopg", "")).cursor()
summary = {}
for arm in sorted(p.split("/")[-2] for p in glob.glob(folder + "/*/")):
    runs = [json.load(open(f)) for f in sorted(glob.glob(f"{folder}/{arm}/*-r*.json"))]
    if not runs or "run_id" not in runs[0]:
        continue
    firsts, first_reads, ttft, totals = [], [], [], {"calls": 0, "input": 0, "read": 0}
    cached_runs = 0
    for run in runs:
        cursor.execute(
            "select body from agent_run_events where run_id=%s and body->>'type'='context_observed'"
            " and body->>'isolation'='main' and body->>'call_state'='completed' order by sequence",
            (run["run_id"],))
        events = [row[0] for row in cursor.fetchall()]
        for index, event in enumerate(events):
            read = event["cache"].get("read_tokens") or 0
            ratio = event["cache"].get("read_hit_ratio") or 0
            actual = round(read / ratio) if ratio else None
            totals["calls"] += 1
            totals["read"] += read
            totals["input"] += actual or 0
            if index == 0:
                first_reads.append(read)
                if actual:
                    firsts.append(actual)
                if (event.get("latency") or {}).get("first_output_ms") is not None:
                    ttft.append(event["latency"]["first_output_ms"])
                stable = event["prefix"].get("stable_prefix_tokens") or 0
                cached_runs += bool(stable and read >= 0.8 * stable)
    summary[arm] = {
        "runs": len(runs),
        "main_calls_completed": totals["calls"],
        "first_call_cache_read_median": statistics.median(first_reads) if first_reads else None,
        "first_call_input_median": statistics.median(firsts) if firsts else None,
        "first_calls_mostly_cached": f"{cached_runs}/{len(runs)}",
        "cache_read_tokens": totals["read"],
        "input_tokens_where_reported": totals["input"],
        "cache_read_share": round(totals["read"] / totals["input"], 3) if totals["input"] else None,
        "first_call_ttft_median_ms": statistics.median(ttft) if ttft else None,
        "used_tokens": sum(run.get("used_tokens") or 0 for run in runs),
    }
json.dump(summary, open(folder + "/cache-summary.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
