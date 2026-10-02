"""A completed writer does not enable tenant preference, rollout or qualification."""

from app.ai.capability_contract import resolve_capability
from app.ai.issue_event_proposal import KEY, OPERATION
from app.ai.write_policy import (
    WRITE_OPERATIONS,
    OperationSetting,
    TenantWriteMode,
    WriteMode,
    decide_write,
    default_settings,
)


def test_issue_adapter_exists_but_default_rollout_and_tenant_mode_stay_closed() -> None:
    assert WRITE_OPERATIONS[OPERATION].adapter_ready is True
    assert WRITE_OPERATIONS[OPERATION].trial_ready is True
    assert resolve_capability(KEY).rollout.value == "shadow"
    result = decide_write(
        OPERATION,
        tenant_mode=TenantWriteMode.TIERED,
        setting=default_settings()[OPERATION],
        rollout_live=False,
        principal_scope_valid=True,
        sources_current=True,
        qualification_current=True,
    )
    assert result.route == "blocked" and result.reason == "operation_disabled"


def test_automatic_preference_does_not_bypass_rollout_or_qualification() -> None:
    for live, expected in ((False, "rollout_not_live"), (True, "qualification_required")):
        result = decide_write(
            OPERATION,
            tenant_mode=TenantWriteMode.TIERED,
            setting=OperationSetting(mode=WriteMode.AUTOMATIC),
            rollout_live=live,
            principal_scope_valid=True,
            sources_current=True,
            qualification_current=False,
        )
        assert result.reason == expected and result.route != "direct"
