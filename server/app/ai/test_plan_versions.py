"""Explicit test-plan prompt variants; new output stays held for qualification."""

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.ai.capability_contract import CapabilityRollout
from app.ai.rollout_guard import CapabilityUnavailableError
from app.domain.test_plan_changes import TestPlanModelAssessment, WorkPackageTestPlanModelAssessment

DEFAULT_VERSION = "test-plan-change-v5"
WORK_PACKAGE_VERSION = "test-plan-change-v6"
VERSION_ROLLOUTS = MappingProxyType(
    {DEFAULT_VERSION: CapabilityRollout.LIVE, WORK_PACKAGE_VERSION: CapabilityRollout.SHADOW}
)


def contract(version: str | None = None) -> tuple[dict[str, Any], Any]:
    selected = version or DEFAULT_VERSION
    if selected not in VERSION_ROLLOUTS:
        raise CapabilityUnavailableError("TEST_PLAN_PROMPT_VERSION_UNKNOWN")
    filename = (
        "test_plan_change_v6.json"
        if selected == WORK_PACKAGE_VERSION
        else "test_plan_change_v5.json"
    )
    prompt = json.loads((Path(__file__).with_name("prompts") / filename).read_text())
    if prompt["version"] != selected:
        raise CapabilityUnavailableError("TEST_PLAN_PROMPT_VERSION_MISMATCH")
    return (
        prompt,
        WorkPackageTestPlanModelAssessment
        if selected == WORK_PACKAGE_VERSION
        else TestPlanModelAssessment,
    )


def require_version_live(version: str) -> None:
    rollout = VERSION_ROLLOUTS.get(version)
    if rollout is None:
        raise CapabilityUnavailableError("TEST_PLAN_PROMPT_VERSION_UNKNOWN")
    if rollout is not CapabilityRollout.LIVE:
        raise CapabilityUnavailableError(f"TEST_PLAN_PROMPT_{rollout.value.upper()}")


def version_from_run(purpose: str, run_context: dict[str, Any]) -> str | None:
    if purpose == "event_issue":
        from app.ai.issue_event_proposal import PROMPT

        if run_context.get("issue_event_prompt_version") != PROMPT.version:
            raise CapabilityUnavailableError("EVENT_ISSUE_PROMPT_VERSION_UNKNOWN")
        return PROMPT.version
    if purpose == "meeting_planning":
        from app.contracts.meeting_plan import PROMPT_VERSION as MEETING_PLANNING_VERSION

        if run_context.get("meeting_planning_prompt_version") != MEETING_PLANNING_VERSION:
            raise CapabilityUnavailableError("MEETING_PLANNING_PROMPT_VERSION_UNKNOWN")
        return MEETING_PLANNING_VERSION
    if purpose == "intake_organization":
        from app.contracts.intake_proposal import PROMPT_VERSION

        if run_context.get("intake_prompt_version") != PROMPT_VERSION:
            raise CapabilityUnavailableError("INTAKE_PROMPT_VERSION_UNKNOWN")
        return PROMPT_VERSION
    if purpose != "test_plan_suggestion":
        return None
    version = run_context.get("test_plan_prompt_version", DEFAULT_VERSION)
    if not isinstance(version, str) or version not in VERSION_ROLLOUTS:
        raise CapabilityUnavailableError("TEST_PLAN_PROMPT_VERSION_UNKNOWN")
    return version
