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
    canonical = [item for item in data["items"] if not item.get("auxiliary", False)]
    assert len(canonical) == count
    if name != "events":
        assert canonical == data["items"]
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
assert len({e["type"] for e in items["events"]}) == len(items["events"])
assert {e["type"] for e in items["events"] if not e.get("auxiliary", False)} == {
    o["event"] for o in operations.values() if o["event"]
}
auxiliary = json.loads((ROOT / "contracts/auxiliary-operations.json").read_text())["items"]
auxiliary_by_name = {entry["operation"]: entry for entry in auxiliary}
assert len(auxiliary_by_name) == len(auxiliary)
assert not set(auxiliary_by_name) & set(operations)
for entry in items["events"]:
    if entry.get("auxiliary", False):
        assert entry["auxiliary"] is True
        declared = auxiliary_by_name[entry["operation"]]
        assert entry["type"] == declared["event"]
        assert declared["write_tier"] in {"READ", "T0", "T1", "T2"}
print(
    "v1.1 catalog/source coverage passed: "
    f"{len(items['operations'])} operations, {len(items['events'])} events, "
    f"{len(items['acceptance'])} acceptance IDs."
)
print("This is design coverage only; no runtime, model or manufacturing qualification inferred.")
