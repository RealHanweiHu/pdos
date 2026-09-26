"""Frontend/backend enum contract synchronization guards (vNext V1-A1).

The finding-type and task-status enums live in three places (Python, DB CHECK,
TypeScript union) with no generator. These tests pin the TypeScript side to the
backend contract so a new enum value cannot ship on one side only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.ai.capability_contract import CAPABILITY_CONTRACTS
from app.ai.executor import FindingType
from app.domain.tasks import TASK_TRANSITIONS

WEB_COMPONENTS = Path(__file__).resolve().parents[2] / "web" / "src" / "components"


def _ts_const_string_array(source: str, name: str) -> set[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S)
    assert match is not None, f"{name} not found in TypeScript source"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def test_frontend_finding_types_match_backend_contract() -> None:
    source = (WEB_COMPONENTS / "ai" / "ai-types.ts").read_text(encoding="utf-8")
    frontend = _ts_const_string_array(source, "FINDING_TYPES")
    # The event worker's output remains narrower than the human review API.
    # Intake/meeting planning use their own project workflows; process template
    # review has a non-project scope and its own administration screen.
    dedicated_workflows = {"intake_organization", "meeting_plan", "process_template_configuration"}
    registered = {
        kind for contract in CAPABILITY_CONTRACTS.values() for kind in contract.finding_types
    }
    assert dedicated_workflows <= registered
    backend = registered - dedicated_workflows
    assert set(get_args(FindingType)) <= backend
    assert frontend == backend, (
        f"frontend FINDING_TYPES drifted: missing={sorted(backend - frontend)}, "
        f"extra={sorted(frontend - backend)}"
    )


def test_frontend_task_statuses_match_backend_contract() -> None:
    source = (WEB_COMPONENTS / "projects" / "project-work-item-types.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(r"export type TaskStatus =([^;]+);", source)
    assert match is not None, "TaskStatus union not found in TypeScript source"
    frontend = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    backend = set(TASK_TRANSITIONS)
    assert frontend == backend, (
        f"frontend TaskStatus drifted: missing={sorted(backend - frontend)}, "
        f"extra={sorted(frontend - backend)}"
    )
