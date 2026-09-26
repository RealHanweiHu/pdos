"""Approved profile provenance and fail-closed operator configuration; no database."""

import json
from pathlib import Path

import pytest

from app.ai import budget_adoption
from app.ai.budget_adoption import (
    METER_DIGEST_KEY,
    METER_PATH_KEY,
    MODE_KEY,
    PROFILE_KEY,
    ApplicationBudgetConfiguration,
    BudgetConfigurationError,
    approved_budget_profile,
)


def settings() -> dict[str, str]:
    return {
        MODE_KEY: "budgeted",
        PROFILE_KEY: "short",
        METER_PATH_KEY: "/operator/meter.json",
        METER_DIGEST_KEY: "a" * 64,
    }


def test_packaged_profiles_match_approved_snapshot() -> None:
    root = Path(__file__).resolve().parents[2]
    frozen = json.loads(
        (
            root / "docs/contracts/pdos-runtime-v1/approved-draft.3/runtime-policy-defaults.json"
        ).read_text()
    )["budget_profiles"]
    assert json.loads(budget_adoption.PROFILE_PATH.read_bytes()) == frozen
    for raw in frozen:
        assert approved_budget_profile(raw["key"]).model_dump(mode="json") == raw


def test_default_legacy_and_explicit_budgeted_configuration() -> None:
    assert ApplicationBudgetConfiguration.from_environment({}) is None
    assert ApplicationBudgetConfiguration.from_environment({MODE_KEY: "legacy"}) is None
    configured = ApplicationBudgetConfiguration.from_environment(settings())
    assert configured is not None
    assert configured.profile == approved_budget_profile("short")
    assert configured.meter_path == Path("/operator/meter.json")


@pytest.mark.parametrize(
    "key,value",
    [
        (MODE_KEY, ""),
        (MODE_KEY, "auto"),
        (MODE_KEY, "legacy"),
        (PROFILE_KEY, ""),
        (PROFILE_KEY, "caller-policy"),
        (METER_PATH_KEY, ""),
        (METER_PATH_KEY, "relative.json"),
        (METER_DIGEST_KEY, ""),
        (METER_DIGEST_KEY, "not-a-sha256"),
    ],
)
def test_invalid_adoption_never_silently_selects_legacy(key: str, value: str) -> None:
    with pytest.raises(BudgetConfigurationError):
        ApplicationBudgetConfiguration.from_environment({**settings(), key: value})


def test_tampered_packaged_policy_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy.json"
    path.write_text(budget_adoption.PROFILE_PATH.read_text().replace("16000", "160000"))
    monkeypatch.setattr(budget_adoption, "PROFILE_PATH", path)
    with pytest.raises(BudgetConfigurationError, match="digest mismatch"):
        ApplicationBudgetConfiguration.from_environment(settings())


@pytest.mark.parametrize("key", ["short", "work_package", "research_discussion"])
def test_agent_dispatcher_and_executor_configuration_are_separate_from_application(
    key: str,
) -> None:
    from app.ai.budget_adoption import (
        AGENT_METER_DIGEST_KEY,
        AGENT_METER_PATH_KEY,
        AGENT_MODE_KEY,
        AGENT_PROFILE_KEY,
        agent_budget_configuration,
        event_budget_profile,
    )

    assert agent_budget_configuration(settings()) is None
    assert event_budget_profile(settings()) is None
    env = {AGENT_MODE_KEY: "budgeted", AGENT_PROFILE_KEY: key}
    assert event_budget_profile(env) == approved_budget_profile(key)
    with pytest.raises(BudgetConfigurationError):
        agent_budget_configuration(env)
    configured = agent_budget_configuration(
        {**env, AGENT_METER_PATH_KEY: "/meter.json", AGENT_METER_DIGEST_KEY: "a" * 64}
    )
    assert configured is not None
    assert configured.profile == approved_budget_profile(key)


@pytest.mark.parametrize(
    "mode,key",
    [("", ""), ("auto", "short"), ("budgeted", ""), ("legacy", "short"), ("budgeted", "unknown")],
)
def test_dispatcher_rejects_ambiguous_or_unapproved_budget(mode: str, key: str) -> None:
    from app.ai.budget_adoption import AGENT_MODE_KEY, AGENT_PROFILE_KEY, event_budget_profile

    with pytest.raises(BudgetConfigurationError):
        event_budget_profile({AGENT_MODE_KEY: mode, AGENT_PROFILE_KEY: key})
