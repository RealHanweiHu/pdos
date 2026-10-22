"""Synthetic, read-only planning v1 example; no business instance or authorization."""

import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[3]
sys.path.insert(0, str(ROOT / "pdos-next/server"))

planning = import_module("pdos_next.engines.planning")
ForecastInput = planning.ForecastInput
calculate_forecast = planning.calculate_forecast

reference = {"source_id": "synthetic-example-input", "version": "v1"}
zero_wait = {"minimum": 0, "maximum": 0, "measure": "total", "source": reference}
calendar = {
    "calendar_id": "synthetic-factory",
    "version": "v1",
    "timezone": "Asia/Shanghai",
    "weekly": [
        {
            "weekday": day,
            "intervals": [
                {"start_minute": 540, "end_minute": 720},
                {"start_minute": 780, "end_minute": 1020},
            ],
        }
        for day in range(5)
    ],
}


def node(key, minimum, maximum):
    return {
        "node_id": key,
        "calendar_id": calendar["calendar_id"],
        "work": {
            "minimum": minimum,
            "maximum": maximum,
            "measure": "total",
            "source": reference,
            "confidence": "medium",
        },
        "waiting": zero_wait,
        "allocation_basis": "Explicit synthetic single-unit assumption",
    }


request = {
    "snapshot_id": "synthetic-plan",
    "version": "v1",
    "as_of": datetime(2026, 10, 2, 1, tzinfo=UTC).isoformat(),
    "calendars": [calendar],
    "nodes": [
        node("engineering", 120, 240),
        node("npi-preparation", 60, 120),
        node("verification", 60, 60),
    ],
    "dependencies": [
        {
            "predecessor_id": left,
            "successor_id": right,
            "relation": "FS",
            "source": reference,
        }
        for left, right in [
            ("engineering", "verification"),
            ("npi-preparation", "verification"),
        ]
    ],
}
result = calculate_forecast(ForecastInput.model_validate(request))
payload = {
    "label": "Synthetic calculation only",
    "input": request,
    "result": result.model_dump(mode="json"),
}
(EVIDENCE / "example.json").write_text(
    json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
)
print(f"{result.status}; project finish {result.project_finish.model_dump_json()}")
print(f"Candidate SHA-256: {result.candidate_sha256}")
