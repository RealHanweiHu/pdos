"""Hermetic model-provider environment for tests.

The model catalog reads provider configuration straight from the process
environment, so any test that asserts *which* models are eligible — including
"none are" — has to control that environment rather than inherit the
developer's shell. A real key in `.env` otherwise turns "model unavailable"
into a different test that still passes for the wrong reason, and a per-provider
override like `PDOS_LLM_MINIMAX_MODEL` silently replaces the model a fixture
thought it had configured.

The variable names are derived from `PROVIDER_SPECS` rather than listed by
hand, so adding a provider cannot leave a gap here.
"""

from __future__ import annotations

import pytest

from app.ai.model_catalog import PROVIDER_SPECS

GENERIC_KEYS = (
    "PDOS_LLM_PROVIDER",
    "PDOS_LLM_API_KEY",
    "PDOS_LLM_BASE_URL",
    "PDOS_LLM_MODEL",
    "PDOS_LLM_GOLDEN_QUALIFICATIONS_PATH",
    "PDOS_AI_DAILY_TOKEN_BUDGET",
)


def provider_environment_keys() -> tuple[str, ...]:
    keys: list[str] = list(GENERIC_KEYS)
    for spec in PROVIDER_SPECS:
        prefix = f"PDOS_LLM_{spec.name.value.upper()}"
        keys.extend(
            (
                spec.api_key_environment,
                f"{prefix}_API_KEY",
                f"{prefix}_BASE_URL",
                f"{prefix}_MODEL",
            )
        )
    return tuple(dict.fromkeys(keys))


def clear_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every provider variable so the test decides what is configured."""
    for name in provider_environment_keys():
        monkeypatch.delenv(name, raising=False)
