"""Export actual implemented payloads; catalog entries alone are never callable tools."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from pdos_next.api import create_app  # noqa: E402
from pdos_next.contracts import PAYLOADS, Command  # noqa: E402

schemas = {
    "command_envelope": Command.model_json_schema(),
    "operation_payloads": {op: payload.model_json_schema() for op, payload in PAYLOADS.items()},
    "scope": "implemented local domain slices; real AI qualification and formal exits are separate",
}
(ROOT / "contracts/payloads.schema.json").write_text(
    json.dumps(schemas, ensure_ascii=False, indent=2) + "\n"
)
path = ROOT / "contracts/operations.json"
data = json.loads(path.read_text())
for entry in data["items"]:
    if entry["operation"] in PAYLOADS:
        entry["implementation"] = "implemented_local_slice"
        entry["payload_schema"] = "payloads.schema.json"
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
path = ROOT / "contracts/acceptance.json"
data = json.loads(path.read_text())
for item in data["items"]:
    item.pop("evidence_status", None)
    item["definition_only"] = True
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
# Engines are never connected by OpenAPI generation. No session/config secrets in the document.
app = create_app(engine=object(), auth_engine=object())
(ROOT / "contracts/openapi.json").write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
)
print(f"Exported {len(PAYLOADS)} implemented payload schemas and actual OpenAPI routes.")
