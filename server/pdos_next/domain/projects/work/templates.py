"""Read the approved CEHub manifest directly; no inferred spreadsheet or Gate state."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from pdos_next.errors import DomainError


@lru_cache(maxsize=1)
def catalog():
    path = Path(__file__).resolve().parents[5] / "assets/cehub/deliverable-guide-manifest.json"
    raw = path.read_bytes()
    manifest = json.loads(raw)
    fingerprint = hashlib.sha256(raw).hexdigest()
    tasks = {}
    for deliverable, value in manifest["deliverables"].items():
        for context in value["contexts"]:
            key = (context["projectType"], context["phaseId"], context["taskId"])
            # Gate checklists remain references, never create a Gate decision or approval.
            if context.get("isGate"):
                continue
            row = tasks.setdefault(
                key,
                {
                    "reference": {
                        "manifest_sha256": fingerprint,
                        "project_type": key[0],
                        "phase_id": key[1],
                        "task_id": key[2],
                        "phase_code": context["phaseCode"],
                        "phase_name": context["phaseName"],
                    },
                    "title": context["taskName"],
                    "goal": context.get("description") or context["taskName"],
                    "deliverables": [],
                    "checks": [],
                },
            )
            if deliverable not in row["deliverables"]:
                row["deliverables"].append(deliverable)
            for item in value.get("checkItems", []):
                if any(
                    (binding["projectType"], binding["phaseId"], binding["taskId"]) == key
                    for binding in item["bindings"]
                ):
                    check = {"key": item["id"], "text": item["requirement"], "required": True}
                    if check not in row["checks"]:
                        row["checks"].append(check)
    return {
        "manifest_sha256": fingerprint,
        "template_versions": manifest["templateVersions"],
        "items": sorted(
            tasks.values(),
            key=lambda row: (
                row["reference"]["project_type"],
                row["reference"]["phase_code"],
                row["reference"]["task_id"],
            ),
        ),
    }


def validate(reference):
    value = reference.model_dump(mode="json") if hasattr(reference, "model_dump") else reference
    actual = next((row for row in catalog()["items"] if row["reference"] == value), None)
    if actual is None:
        raise DomainError("VERSION_CONFLICT", "NPI 模板已变化或引用不完整，请重新选择任务。")
    return actual
