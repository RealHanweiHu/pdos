"""Explicit application-process budget configuration, never request/model policy.

The bundled profiles reproduce the approved N0-02 values. Meter publication and
tenant admission remain separate prerequisites; this module grants neither.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.contracts.runtime_policy import RunBudgetProfile

PROFILE_PATH = Path(__file__).with_name("policies") / "run-budget-v1.json"
PROFILE_SHA256 = "fd4b8f5c7a9d367480c48359137f539b7f6a60218617ec90d285d884e0b61974"
MODE_KEY = "PDOS_APPLICATION_MODEL_BUDGET_MODE"
PROFILE_KEY = "PDOS_APPLICATION_MODEL_BUDGET_PROFILE"
METER_PATH_KEY = "PDOS_APPLICATION_MODEL_METER_PATH"
METER_DIGEST_KEY = "PDOS_APPLICATION_MODEL_METER_SHA256"


class BudgetConfigurationError(ValueError):
    """Invalid adoption must fail before a model call, without legacy fallback."""


def approved_budget_profile(key: str) -> RunBudgetProfile:
    raw = PROFILE_PATH.read_bytes()
    if sha256(raw).hexdigest() != PROFILE_SHA256:
        raise BudgetConfigurationError("bundled budget policy digest mismatch")
    profiles = [RunBudgetProfile.model_validate(value) for value in json.loads(raw)]
    for profile in profiles:
        if profile.key == key:
            return profile
    raise BudgetConfigurationError("unknown approved budget profile")


@dataclass(frozen=True)
class ApplicationBudgetConfiguration:
    profile: RunBudgetProfile
    meter_path: Path
    meter_sha256: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str]
    ) -> ApplicationBudgetConfiguration | None:
        mode = environment.get(MODE_KEY, "legacy").strip()
        extras = [
            environment.get(key, "").strip()
            for key in (PROFILE_KEY, METER_PATH_KEY, METER_DIGEST_KEY)
        ]
        if mode == "legacy":
            if any(extras):
                raise BudgetConfigurationError("budget settings require explicit budgeted mode")
            return None
        if mode != "budgeted":
            raise BudgetConfigurationError("application budget mode must be legacy or budgeted")
        profile_key, path, digest = extras
        if not all(extras):
            raise BudgetConfigurationError("budgeted mode requires profile, meter path and digest")
        if not Path(path).is_absolute():
            raise BudgetConfigurationError("meter publication path must be absolute")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise BudgetConfigurationError("meter publication requires a SHA-256 digest")
        return cls(approved_budget_profile(profile_key), Path(path), digest)


AGENT_MODE_KEY = "PDOS_AGENT_MODEL_BUDGET_MODE"
AGENT_PROFILE_KEY = "PDOS_AGENT_MODEL_BUDGET_PROFILE"
AGENT_METER_PATH_KEY = "PDOS_AGENT_MODEL_METER_PATH"
AGENT_METER_DIGEST_KEY = "PDOS_AGENT_MODEL_METER_SHA256"


def event_budget_profile(environment: Mapping[str, str]) -> RunBudgetProfile | None:
    """Dispatcher needs only trusted policy; it does not load models or meter assets."""
    mode = environment.get(AGENT_MODE_KEY, "legacy").strip()
    key = environment.get(AGENT_PROFILE_KEY, "").strip()
    if mode == "legacy" and not key:
        return None
    if mode != "budgeted" or not key:
        raise BudgetConfigurationError("Agent budget mode requires an explicit approved profile")
    return approved_budget_profile(key)


def agent_budget_configuration(
    environment: Mapping[str, str],
) -> ApplicationBudgetConfiguration | None:
    """Separate Agent process settings; application settings cannot enable this plane."""
    renamed = {
        app_key: environment[agent_key]
        for app_key, agent_key in (
            (MODE_KEY, AGENT_MODE_KEY),
            (PROFILE_KEY, AGENT_PROFILE_KEY),
            (METER_PATH_KEY, AGENT_METER_PATH_KEY),
            (METER_DIGEST_KEY, AGENT_METER_DIGEST_KEY),
        )
        if agent_key in environment
    }
    return ApplicationBudgetConfiguration.from_environment(renamed)
