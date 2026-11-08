"""Measured admission floor for the character token estimate (D248, context §6.1).

Admission multiplies the estimate by max(floor, previous actual / estimate). The
floor per protocol, model and isolation class comes from context_calibration.json,
where each entry records the measurement it rests on. A route without an entry
uses the default 15% floor, and no entry may go below it or below its own
measured maximum, so a floor can only be as tight as the evidence shows.
"""

import json
from functools import cache
from pathlib import Path

CONFIGURATION = Path(__file__).resolve().parent / "context_calibration.json"
# Floor of every admission made before the floor was recorded per request (D248).
LEGACY_FLOOR = 1.15


def isolation_class(isolation):
    return "main" if isolation == "main" else "isolated"


def load(path=CONFIGURATION):
    value = json.loads(Path(path).read_text())
    if value.get("schema") != "pdos.context-estimate-calibration/v1":
        raise ValueError("Unknown context calibration schema")
    default = value["default_floor"]
    if not isinstance(default, int | float) or not 1.15 <= default <= 2:
        raise ValueError("The default floor keeps at least the 15% design margin")
    if not isinstance(value.get("default_source"), str) or not value["default_source"].strip():
        raise ValueError("The default floor needs its source")
    floors = {}
    for entry in value["routes"]:
        key = (entry["protocol"], entry["model"], entry["isolation"])
        floor, measured = entry["floor"], entry["measured"]
        if entry["isolation"] not in {"main", "isolated"} or key in floors:
            raise ValueError("Each protocol, model and isolation class appears once")
        if not isinstance(floor, int | float) or not default <= floor <= 2:
            raise ValueError("A measured floor never goes below the default floor")
        if floor < measured["max"]:
            raise ValueError("A floor must cover its own measured maximum")
        if not all(isinstance(entry.get(k), str) and entry[k].strip()
                   for k in ("decided", "evidence")) or measured["calls"] < 1:
            raise ValueError("A measured floor names its decision, evidence and sample")
        floors[key] = float(floor)
    return float(default), floors


@cache
def _configured():
    return load()


def floor_for(route, isolation):
    default, floors = _configured()
    return floors.get((route.protocol, route.model, isolation_class(isolation)), default)
