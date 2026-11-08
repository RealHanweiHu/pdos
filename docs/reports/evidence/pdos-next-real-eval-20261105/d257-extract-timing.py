"""D257: where an assistant.extract's time goes, from the 11-05 regression's local files.

Reads live/runs/*.json (kept local only) and both workers' provider observations.
For each model call it splits the time into: host work before the ledger claim (since
the previous model call ended), claim to HTTP start, and the HTTP call itself.

    python -I d257-extract-timing.py <path to live/>
"""

import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def nearest_rank(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(p * len(values)) - 1)] if values else None


def main(live):
    observed = {}
    for path in glob.glob(os.path.join(live, "runtime-worker-*", "provider-observations.jsonl")):
        for line in open(path):
            sample = json.loads(line)
            if sample.get("request_id"):
                observed[sample["request_id"]] = sample
    extracts, phases = [], defaultdict(lambda: defaultdict(list))
    for path in sorted(glob.glob(os.path.join(live, "runs", "*.json"))):
        run = json.load(open(path))
        if "tool_calls" not in run:
            continue
        calls = sorted(run["tool_calls"], key=lambda call: call["created_at"])
        match = re.search(r"-s(\d+)$", run["label"])
        turn = int(match.group(1)) if match else 0
        if "-ctx-CTX-01-" in run["label"]:
            group = "CTX-01 r0-5" if turn < 6 else "CTX-01 r6-17" if turn < 18 else "CTX-01 r18-24"
        elif "-rag-" in run["label"]:
            group = "RAG"
        else:
            group = None
        previous_end = None
        for index, call in enumerate(calls):
            isolation = call["execution_binding"].get("isolation")
            sample = observed.get(call.get("provider_request_id"))
            if group and call["tool"] == "model" and sample:
                claimed = datetime.fromisoformat(call["created_at"])
                started = datetime.fromisoformat(sample["started_at"])
                ended = datetime.fromisoformat(sample["finished_at"])
                key = f"{group} {isolation}"
                phases[key]["http_s"].append((ended - started).total_seconds())
                phases[key]["claim_to_http_s"].append((started - claimed).total_seconds())
                if previous_end:
                    phases[key]["host_before_claim_s"].append(
                        (claimed - previous_end).total_seconds())
                previous_end = ended
            if call["tool"] != "assistant.extract":
                continue
            following = next((c for c in calls[index + 1:]
                              if c["execution_binding"].get("isolation") == "main"), None)
            children = []
            for child in calls[index + 1:]:
                if child is following:
                    break
                if child["execution_binding"].get("isolation") == "assistant_extract":
                    children.append(child)
            models = [child for child in children if child["tool"] == "model"]
            if not models:
                continue
            result = call.get("result") or {}
            citations = sum(1 for row in result.get("coverage") or []
                            if row.get("kind") == "untrusted") + len(result.get("failures") or [])
            start = datetime.fromisoformat(call["created_at"])
            end = max(datetime.fromisoformat(child["created_at"])
                      + timedelta(milliseconds=child.get("elapsed_ms") or 0) for child in children)
            extracts.append({"wall_min": (end - start).total_seconds() / 60,
                             "citations": citations, "child_models": len(models)})
    walls = [row["wall_min"] for row in extracts]
    estimate = {}
    for limit in (1, 2, 3, 4):
        scaled = [row["wall_min"] * math.ceil(row["citations"] / limit) / row["citations"]
                  if row["citations"] else row["wall_min"] for row in extracts]
        estimate[limit] = {"p95_min": round(nearest_rank(scaled, .95), 1),
                           "max_min": round(max(scaled), 1)}
    print(json.dumps({
        "extracts_with_children": len(extracts),
        "untrusted_citations_per_extract": dict(sorted(
            Counter(row["citations"] for row in extracts).items())),
        "extract_wall_min": {"p50": round(nearest_rank(walls, .5), 1),
                             "p95": round(nearest_rank(walls, .95), 1),
                             "max": round(max(walls), 1)},
        "ideal_wall_by_limit": estimate,
        "model_call_phases_p50_p95": {
            key: {name: [round(nearest_rank(values, .5), 1), round(nearest_rank(values, .95), 1)]
                  for name, values in value.items()}
            for key, value in sorted(phases.items())},
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
