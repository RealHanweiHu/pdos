"""Current policy/scope decisions with isolated mock connections, never SQL execution."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.issue_event_proposal import KEY, OPERATION
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.write_policy import POLICY_VERSION
from app.auth.roles import Action
from app.domain import ai_issue_write_access as access
from app.domain.ai_meeting_drafts import ScopeChange
from app.domain.ai_write_policy import WritePolicyError
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import digest


def result(value: Any = None) -> MagicMock:
    response = MagicMock()
    response.first.return_value = value
    response.scalar_one_or_none.return_value = value
    response.scalar_one.return_value = value
    response.mappings.return_value.one_or_none.return_value = value
    return response


@pytest.fixture
def controls(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    c, context, project = MagicMock(), MagicMock(), uuid4()
    context.tenant.id, context.user.id = uuid4(), uuid4()
    principal = uuid4()
    policy = {
        "id": uuid4(),
        "mode": "tiered",
        "contract_version": POLICY_VERSION,
        "principal_id": principal,
        "operation_settings": {OPERATION: {"mode": "confirm"}},
    }
    scope = {"id": uuid4(), "revision": 2, "enabled": True, "principal_id": principal}
    policy_reader = MagicMock(return_value=policy)
    scope_reader = MagicMock(return_value=scope)
    live = MagicMock()
    monkeypatch.setattr(access, "policy", policy_reader)
    monkeypatch.setattr(access, "latest_scope", scope_reader)
    monkeypatch.setattr(access, "require_live_key", live)
    c.execute.return_value = result({"id": principal})
    return c, context, project, policy, scope, policy_reader, scope_reader, live


@pytest.mark.parametrize("write", [False, True])
def test_authorize_checks_current_scope_and_each_required_action(
    controls: Any, monkeypatch: pytest.MonkeyPatch, write: bool
) -> None:
    c, context, project, *_ = controls
    check = MagicMock()
    monkeypatch.setattr(KnowledgeCorrectionService, "_authorize", check)
    access.authorize(c, context, project, write=write)
    expected = (*access.READ_ACTIONS, *((Action.WORK_ITEM_EDIT,) if write else ()))
    assert [call.args[-1] for call in check.call_args_list] == list(expected)
    assert all(
        call.args[:4] == (c, context.tenant.id, context.user.id, project)
        for call in check.call_args_list
    )
    check.side_effect = KnowledgeAccessError("权限已撤销")
    with pytest.raises(KnowledgeAccessError):
        access.authorize(c, context, project, write=write)


def test_unavailable_project_rejected_before_permissions(controls: Any) -> None:
    c, context, project, *_ = controls
    c.execute.return_value = result(None)
    with pytest.raises(LookupError):
        access.authorize(c, context, project, write=True)


@pytest.mark.parametrize("mode", ["confirm", "automatic"])
def test_settings_only_return_current_matching_controls(controls: Any, mode: str) -> None:
    c, context, project, policy, scope, policy_reader, scope_reader, live = controls
    policy["operation_settings"][OPERATION]["mode"] = mode
    assert access.write_settings(c, context.tenant.id, project) == (policy, scope)
    policy_reader.assert_called_once_with(c, context.tenant.id)
    scope_reader.assert_called_once_with(c, context.tenant.id, project, OPERATION)
    live.assert_called_once_with(KEY)
    # Qualification is deliberately absent: automatic preference is not a grant.
    assert "qualification" not in policy


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("no_policy", "AI_ISSUE_POLICY_REQUIRED"),
        ("legacy", "AI_ISSUE_POLICY_REQUIRED"),
        ("old_contract", "AI_ISSUE_POLICY_REQUIRED"),
        ("disabled", "AI_ISSUE_POLICY_DISABLED"),
        ("no_operation", "AI_ISSUE_POLICY_DISABLED"),
        ("no_scope", "AI_ISSUE_SCOPE_REQUIRED"),
        ("scope_disabled", "AI_ISSUE_SCOPE_REQUIRED"),
        ("other_principal", "AI_ISSUE_SCOPE_REQUIRED"),
        ("missing_principal", "AI_ISSUE_PRINCIPAL_UNAVAILABLE"),
    ],
)
def test_settings_fail_closed(controls: Any, mutation: str, code: str) -> None:
    c, context, project, policy, scope, policy_reader, scope_reader, live = controls
    if mutation == "no_policy":
        policy_reader.return_value = None
    elif mutation == "legacy":
        policy["mode"] = "legacy"
    elif mutation == "old_contract":
        policy["contract_version"] = "obsolete"
    elif mutation == "disabled":
        policy["operation_settings"][OPERATION]["mode"] = "disabled"
    elif mutation == "no_operation":
        policy["operation_settings"] = {}
    elif mutation == "no_scope":
        scope_reader.return_value = None
    elif mutation == "scope_disabled":
        scope["enabled"] = False
    elif mutation == "other_principal":
        scope["principal_id"] = uuid4()
    elif mutation == "missing_principal":
        c.execute.return_value = result(None)
    with pytest.raises(WritePolicyError) as failure:
        access.write_settings(c, context.tenant.id, project)
    assert failure.value.code == code
    live.assert_not_called()


def test_disabled_rollout_never_becomes_a_write_grant(controls: Any) -> None:
    c, context, project, *_, live = controls
    live.side_effect = CapabilityUnavailableError("CAPABILITY_SHADOW")
    with pytest.raises(CapabilityUnavailableError):
        access.write_settings(c, context.tenant.id, project)


def scope_environment(controls: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    c, context, project, policy, scope, *_ = controls
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = c
    monkeypatch.setattr(access, "authorize", MagicMock())
    governance = MagicMock()
    monkeypatch.setattr(KnowledgeCorrectionService, "_authorize", governance)
    monkeypatch.setattr(access, "lock_project_write_scope", MagicMock(return_value=True))
    writer = MagicMock()
    monkeypatch.setattr(access, "EventAuditWriter", writer)
    change = ScopeChange(
        request_id=uuid4(), expected_revision=2, enabled=True, reason="事件建单试运行"
    )
    return c, context, project, policy, scope, engine, writer, change, governance


def test_scope_change_records_only_event_issue_revision(
    controls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, context, project, policy, scope, engine, writer, change, governance = scope_environment(
        controls, monkeypatch
    )
    c.execute.side_effect = [
        result("active"),
        result(None),
        result({"id": policy["principal_id"]}),
        result(datetime.now(UTC)),
        result(),
    ]
    assert access.ScopeService(engine).change(context, project, change) == {
        "revision": 3,
        "reused": False,
    }
    governance.assert_called_once_with(
        c, context.tenant.id, context.user.id, project, Action.MODEL_GOVERNANCE_MANAGE
    )
    saved = c.execute.call_args_list[-1].args[0].compile().params
    assert saved["operation_key"] == OPERATION
    assert saved["principal_id"] == policy["principal_id"]
    assert saved["revision"] == 3 and saved["actor_user_id"] == context.user.id
    event, audit = writer.return_value.record.call_args.args
    assert event.payload["operation_key"] == OPERATION
    assert audit.context["policy_id"] == str(policy["id"])


def test_scope_replay_does_not_write_or_rebind_to_new_policy(
    controls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, context, project, policy, scope, engine, writer, change, _ = scope_environment(
        controls, monkeypatch
    )
    original = {
        "request_digest": digest(
            {
                "operation_key": OPERATION,
                "project_id": str(project),
                **change.model_dump(mode="json", exclude={"request_id"}),
            }
        ),
        "operation_key": OPERATION,
        "project_id": project,
        "revision": 3,
    }
    c.execute.side_effect = [result("active"), result(original)]
    assert access.ScopeService(engine).change(context, project, change) == {
        "revision": 3,
        "reused": True,
    }
    writer.assert_not_called()
    controls[5].assert_not_called()


def test_scope_revision_conflict_preserves_history(
    controls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, context, project, policy, scope, engine, writer, change, _ = scope_environment(
        controls, monkeypatch
    )
    scope["revision"] = 3
    c.execute.side_effect = [result("active"), result(None), result({"id": policy["principal_id"]})]
    with pytest.raises(WritePolicyError) as failure:
        access.ScopeService(engine).change(context, project, change)
    assert failure.value.code == "AI_ISSUE_SCOPE_CHANGED"
    writer.assert_not_called()
