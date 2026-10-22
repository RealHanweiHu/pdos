"""Export actual implemented payloads; catalog entries alone are never callable tools."""

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from pdos_next.api import create_app  # noqa: E402
from pdos_next.contracts import PAYLOADS, Command  # noqa: E402

schemas = {
    "command_envelope": Command.model_json_schema(),
    "operation_payloads": {op: payload.model_json_schema() for op, payload in PAYLOADS.items()},
    "scope": "implemented local domain slices; real AI qualification and formal exits are separate",
}
ENDPOINTS = {
    "ai.work.start": "/v1/categories/{category_id}/agent-runs",
    "ai.run.cancel": "/v1/categories/{category_id}/agent-runs/{run_id}/cancel",
    "category.create": "/v1/categories",
    "category.member.grant": "/v1/categories/{category_id}/members",
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
    elif entry["operation"] == "project.create":
        entry["implementation"] = "g0_atomic_materialization_only"
        entry.pop("payload_schema", None)
        entry.pop("api_binding", None)
        entry["note"] = (
            "Only proposal.g0.decide creates a project atomically with the named Human "
            "G0 decision. No independent executable command; Xiaopai may prepare materials."
        )
    elif entry["operation"] in ENDPOINTS:
        entry["implementation"] = "implemented_local_endpoint"
        entry["payload_schema"] = "openapi.json"
        entry["api_binding"] = {"method": "POST", "path": ENDPOINTS[entry["operation"]]}
        if entry["operation"].startswith("ai."):
            entry["note"] = (
                "Current Xiaopai durable run endpoint, with AgentEvent trace; "
                "retired SourceWork command payload is not callable. "
                "AI domain writes still require current qualification and authorization."
            )
data["pending_code_alignment"] = [
    value for value in data["pending_code_alignment"] if not value.startswith("project.create:")
]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
path = ROOT / "contracts/acceptance.json"
data = json.loads(path.read_text())
for item in data["items"]:
    item.pop("evidence_status", None)
    item["definition_only"] = True
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
# Configure the actual host against a real Engine interface, with connection
# attempts explicitly forbidden. Schema export needs no environment credentials.
engine = create_engine("postgresql+psycopg://export-only@127.0.0.1:1/pdos_schema_export")


@event.listens_for(engine, "do_connect")
def forbid_connection(*_args):
    raise RuntimeError("Offline contract export forbids database connections")


try:
    app = create_app(engine=engine, auth_engine=engine)
    actual = app.openapi()
    for operation, endpoint in ENDPOINTS.items():
        assert "post" in actual["paths"][endpoint], f"Missing actual endpoint: {operation}"
    (ROOT / "contracts/openapi.json").write_text(
        json.dumps(actual, ensure_ascii=False, indent=2) + "\n"
    )
finally:
    engine.dispose()
print(f"Exported {len(PAYLOADS)} implemented payload schemas and actual OpenAPI routes.")
