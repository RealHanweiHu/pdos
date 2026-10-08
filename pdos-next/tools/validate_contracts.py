"""Checks the reconstructed implementation catalog, not runtime acceptance."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "docs/design/2026-10-02-pdos-complete-target-architecture-v1.md"
source = SOURCE.read_text()
items = {}
for name, count in [("operations", 66), ("events", 65), ("acceptance", 48)]:
    data = json.loads((ROOT / "contracts" / f"{name}.json").read_text())
    assert data["provenance"]["sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert data["provenance"]["original_contract_package_received"] is False
    assert len(data["items"]) == count
    assert all(i["stage"] in {f"G{n}" for n in range(6)} for i in data["items"])
    items[name] = data["items"]
operations = {o["operation"]: o for o in items["operations"]}
assert len(operations) == 66
for op, tier, _ai, event in re.findall(
    r"\| `([^`]+)` \| (READ|T[012]) \| ([^|]+) \| ([^|]+) \|", source
):
    assert operations[op]["write_tier"] == tier
    assert operations[op]["event"] == (None if tier == "READ" else event.strip())
assert {a["id"] for a in items["acceptance"]} == {f"AT-{n:02}" for n in range(1, 49)}
assert {e["type"] for e in items["events"]} == {
    o["event"] for o in operations.values() if o["event"]
}
print("Catalog/source coverage passed: 66 operations, 65 events, 48 acceptance IDs.")
print("This is design coverage only; no runtime, model or manufacturing qualification inferred.")
