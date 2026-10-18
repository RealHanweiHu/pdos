"""Checks the reconstructed implementation catalog, not runtime acceptance."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md"
source = SOURCE.read_text()
items = {}
for name, count in [("operations", 87), ("events", 86), ("acceptance", 63)]:
    data = json.loads((ROOT / "contracts" / f"{name}.json").read_text())
    assert data["provenance"]["sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert data["provenance"]["original_contract_package_received"] is False
    assert len(data["items"]) == count
    assert all(i["stage"] in {f"S{n}" for n in range(6)} for i in data["items"])
    items[name] = data["items"]
operations = {o["operation"]: o for o in items["operations"]}
assert len(operations) == 87
appendix = source.split("# 附录 A", 1)[1].split("# 附录 B", 1)[0]
for op, tier, _ai, event in re.findall(
    r"\| `([^`]+)`[^|]*\| (READ|T[012]) \| ([^|]+) \| ([^|]+) \|", appendix
):
    assert operations[op]["write_tier"] == tier
    assert operations[op]["event"] == (None if tier == "READ" else event.strip())
assert {a["id"] for a in items["acceptance"]} == {f"AT-{n:02}" for n in range(1, 64)}
assert {e["type"] for e in items["events"]} == {
    o["event"] for o in operations.values() if o["event"]
}
print(
    "v1.1 catalog/source coverage passed: "
    f"{len(items['operations'])} operations, {len(items['events'])} events, "
    f"{len(items['acceptance'])} acceptance IDs."
)
print("This is design coverage only; no runtime, model or manufacturing qualification inferred.")
