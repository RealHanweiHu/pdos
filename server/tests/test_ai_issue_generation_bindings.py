"""Pure capture/read contracts; no engine, database, provider, or credential access."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Connection, Insert
from sqlalchemy.dialects import postgresql

from app.ai.issue_event_proposal import OPERATION
from app.ai.issue_event_runs import receipt
from app.ai.write_policy import POLICY_VERSION
from app.domain import ai_issue_generation_bindings as b

NOW = datetime(2026, 9, 27, tzinfo=UTC)
TENANT, PROJECT, RUN, ACTOR, POLICY, PRINCIPAL, SCOPE = (UUID(int=i) for i in range(1, 8))


def facts() -> tuple[dict[str, Any], dict[str, Any]]:
    source = {
        "tenant_id": str(TENANT),
        "project_id": str(PROJECT),
        "event_row_id": 42,
        "event_id": "failure:original",
        "source_digest": "a" * 64,
        "source_kind": "test_failure",
        "source_key": "test_case:original",
    }
    row = {
        "id": RUN,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "requested_by_user_id": ACTOR,
        "request_id": str(UUID(int=8)),
        "context_version": "event-issue-request-v1",
        "created_at": NOW,
        "run_context": {"issue_event_source": source},
    }
    return row, source


def policy() -> dict[str, Any]:
    return {
        "id": POLICY,
        "principal_id": PRINCIPAL,
        "revision": 3,
        "mode": "tiered",
        "contract_version": POLICY_VERSION,
        "created_at": NOW,
        "operation_settings": {
            OPERATION: {
                "mode": "confirm",
                "minimum_confirmation_basis_points": 9000,
                "maximum_retraction_basis_points": 500,
            },
            "meeting.minutes.draft": {"private_other_setting": "DO_NOT_EXPOSE"},
        },
    }


def principal() -> dict[str, Any]:
    return {
        "id": PRINCIPAL,
        "principal_key": "pdos-agent",
        "principal_kind": "ai",
        "display_name": "PDOS Agent",
    }


def scope() -> dict[str, Any]:
    return {
        "id": SCOPE,
        "principal_id": PRINCIPAL,
        "revision": 2,
        "enabled": True,
        "operation_key": OPERATION,
        "created_at": NOW,
    }


def connection(values: list[Any]) -> MagicMock:
    c = MagicMock()
    answers = []
    for value in values:
        response = MagicMock()
        response.mappings.return_value.one_or_none.return_value = value
        answers.append(response)
    c.execute.side_effect = answers
    return c


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        ("valid", "trial_candidate"),
        ("automatic", "trial_candidate"),
        ("policy_missing", "policy_missing"),
        ("old_contract", "policy_contract_unknown"),
        ("legacy", "policy_not_tiered"),
        ("disabled", "operation_not_enabled"),
        ("missing_setting", "operation_not_enabled"),
        ("no_principal", "principal_unverified"),
        ("human_principal", "principal_unverified"),
        ("no_scope", "scope_not_enabled"),
        ("disabled_scope", "scope_not_enabled"),
        ("wrong_principal", "scope_not_enabled"),
        ("shadow", "rollout_not_live"),
        ("not_ready", "trial_not_ready"),
    ],
)
def test_capture_freezes_exact_original_material_and_never_promotes_missing_configuration(
    variant: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, actor, grant = policy(), principal(), scope()
    if variant == "old_contract":
        p["contract_version"] = "unknown"
    if variant == "legacy":
        p["mode"] = "legacy"
    if variant in {"disabled", "automatic"}:
        p["operation_settings"][OPERATION]["mode"] = variant
    if variant == "missing_setting":
        p["operation_settings"].pop(OPERATION)
    if variant == "human_principal":
        actor["principal_kind"] = "human"
    if variant == "disabled_scope":
        grant["enabled"] = False
    if variant == "wrong_principal":
        grant["principal_id"] = UUID(int=99)
    values = (
        [None, None, grant, None]
        if variant == "policy_missing"
        else [
            None,
            p,
            None if variant == "no_principal" else actor,
            None if variant == "no_scope" else grant,
            None,
        ]
    )
    c = connection(values)
    monkeypatch.setattr(
        b,
        "resolve_capability",
        lambda _: SimpleNamespace(
            rollout=SimpleNamespace(value="shadow" if variant == "shadow" else "live")
        ),
    )
    monkeypatch.setattr(
        b, "WRITE_OPERATIONS", {OPERATION: SimpleNamespace(trial_ready=variant != "not_ready")}
    )
    row, source = facts()
    saved = b.capture(cast(Connection, c), row, source, NOW)
    assert saved["reason_code"] == reason
    assert saved["capture_kind"] == (
        "trial_candidate" if reason == "trial_candidate" else "evidence_only"
    )
    assert saved["run_id"] == RUN and saved["event_row_id"] == 42
    assert saved["source_digest"] == source["source_digest"]
    assert saved["snapshot"]["version"] == b.VERSION
    if variant == "policy_missing":
        assert saved["snapshot"]["scope"]["id"] == str(SCOPE)
    if variant == "wrong_principal":
        assert saved["snapshot"]["scope"]["principal_id"] == str(UUID(int=99))
    assert "DO_NOT_EXPOSE" not in json.dumps(saved["snapshot"])
    assert "meeting.minutes.draft" not in json.dumps(b.summary(saved))
    assert isinstance(c.execute.call_args.args[0], Insert)
    for call in c.execute.call_args_list:
        if not isinstance(call.args[0], Insert) and "ai_write_scope_revisions" in str(call.args[0]):
            assert "principal_id =" not in str(call.args[0])
        call.args[0].compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]


def test_original_binding_replay_reads_no_current_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    row, source = facts()
    original = {
        "id": UUID(int=9),
        "event_row_id": 42,
        "source_digest": "a" * 64,
        "capture_kind": "evidence_only",
        "snapshot": {"policy": None},
    }
    c = connection([original])
    monkeypatch.setattr(
        b, "resolve_capability", lambda _: pytest.fail("must not requalify history")
    )
    assert b.capture(cast(Connection, c), row, source, NOW) == original
    assert c.execute.call_count == 1
    changed = deepcopy(source)
    changed["source_digest"] = "b" * 64
    row["run_context"]["issue_event_source"] = changed
    c = connection([original])
    with pytest.raises(ValueError, match="不得替换"):
        b.capture(cast(Connection, c), row, changed, NOW)
    assert c.execute.call_count == 1


def test_foreign_source_cannot_be_captured() -> None:
    row, source = facts()
    source["tenant_id"] = str(UUID(int=90))
    c = MagicMock()
    with pytest.raises(ValueError, match="不一致"):
        b.capture(cast(Connection, c), row, source, NOW)
    c.execute.assert_not_called()


def test_legacy_history_is_explicitly_unrecorded_without_invented_policy() -> None:
    assert b.summary(None)["status"] == "not_recorded"
    assert b.summary(None)["policy_id"] is None
    from tests.test_issue_event_runs import run

    assert receipt(run())["generation_binding"] == b.summary(None)


def test_read_binding_is_bound_to_actual_run_scope_and_requester() -> None:
    row, _ = facts()
    c = connection([None])
    assert b.read_for_run(cast(Connection, c), row) is None
    params = c.execute.call_args.args[0].compile().params
    assert {TENANT, PROJECT, RUN, ACTOR} <= set(params.values())
