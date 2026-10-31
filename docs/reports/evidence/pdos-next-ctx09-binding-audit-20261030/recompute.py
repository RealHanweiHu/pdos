#!/usr/bin/env python3
"""Recompute CTX-09's frozen natural-result size; no DB, network or model.

The estimator, serializer and chunker are loaded as AST function definitions from
the production sources, without importing the application or its configuration.
"""

import ast
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
INPUT = Path(
    "docs/reports/evidence/pdos-next-context-fixture-completion-20261029/"
    "native-normalized-20261030/CTX-09-F48000.json"
)


def functions(path, names, namespace):
    parsed = ast.parse((ROOT / path).read_text())
    selected = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                and node.name in names]
    if {node.name for node in selected} != set(names):
        raise RuntimeError(f"Missing production function in {path}")
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)


def main():
    manifest = json.loads((HERE / "source-sha256.json").read_text())
    mismatches = [path for path, expected in manifest.items()
                  if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected]
    if mismatches:
        raise RuntimeError(f"Frozen source SHA mismatch: {mismatches}")
    namespace = {"json": json, "math": math}
    functions(
        Path("pdos-next/server/pdos_next/agent_kernel/context_budget.py"),
        {"_is_wide", "estimate_tokens"}, namespace,
    )
    functions(
        Path("pdos-next/server/pdos_next/agent_kernel/result_continuation.py"),
        {"serialized", "_chunks"}, namespace,
    )
    estimate, serialize = namespace["estimate_tokens"], namespace["serialized"]
    observation = json.loads((ROOT / INPUT).read_text())
    control = observation["bindings"]["natural_single_binding_control"]
    call = next(row for row in observation["bindings"]["calls"]
                if row["id"] == control["original_read_call_id"])
    assert call["tool"] == "category.knowledge.list"
    raw = call["result"]
    full = {**raw, "execution_ref": {
        "call_id": call["id"], "read_kind": call["binding"]["read_kind"],
    }}
    text = serialize(full)
    fragments = namespace["_chunks"](text, 3936)
    decoder = json.JSONDecoder()
    start = text.index('"items": [') + len('"items": [')
    position, endpoints = start, []
    for _ in raw["items"]:
        while text[position].isspace() or text[position] == ",":
            position += 1
        _, position = decoder.raw_decode(text, position)
        endpoints.append(position)
    output = {
        "input": str(INPUT),
        "control_json_path": "$.bindings.natural_single_binding_control",
        "call_lookup": "$.bindings.calls[?id == control.original_read_call_id]",
        "run_id": control["run_id"],
        "original_read_call_id": call["id"],
        "native_binding_status": observation["native_binding_status"],
        "scenario_status": "needs_case_revision",
        "result_total_items": len(raw["items"]),
        "characters": len(text),
        "estimated_tokens": estimate(text),
        "production_tool_cap": 4000,
        "continuation_page_cap": 3936,
        "fragment_payload_budget": 3716,
        "chunks_if_serialized_for_paging": len(fragments),
        "prefixes_through_complete_item": {
            str(n): {"characters": endpoints[n - 1],
                     "estimated_tokens": estimate(text[:endpoints[n - 1]])}
            for n in (3, 6, 9)
        },
        "per_item_estimated_tokens": [estimate(serialize(row)) for row in raw["items"]],
        "source_sha_verified": True,
        "database_calls": 0,
        "network_calls": 0,
        "model_calls": 0,
    }
    assert output["characters"] == 9325
    assert output["estimated_tokens"] == 2451
    assert len(raw["items"]) == 9 and len(fragments) == 1
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
