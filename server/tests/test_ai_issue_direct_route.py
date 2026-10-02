"""Pure routing over explicitly mocked trusted facts; never real qualification."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.ai import write_policy
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.domain import ai_issue_direct_route as route
from app.domain.product_workspace import digest

NOW = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    tenant, project, run, policy, scope, principal, protocol, collection = [
        uuid4() for _ in range(8)
    ]
    binding = IssueEvaluationBinding(
        provider="openai",
        model="fixture-model",
        model_version="fixture-revision",
        release_bundle_version="sha256:" + "a" * 64,
        suite_version="fixture-suite-v1",
        suite_digest="b" * 64,
        adapter_version="fixture-reader-v1",
        policy_version="fixture-policy-v1",
        policy_revision=1,
    )
    setting = {
        "id": policy,
        "principal_id": principal,
        "mode": "tiered",
        "operation_settings": {route.OPERATION: {"mode": "automatic"}},
    }
    grant = {"id": scope, "principal_id": principal, "enabled": True}
    raw = {
        "call": {
            "provider": binding.provider,
            "model": binding.model,
            "model_version": binding.model_version,
        },
        "generation": {
            "policy_id": str(policy),
            "scope_revision_id": str(scope),
            "principal_id": str(principal),
            "snapshot": {"policy": {"contract_version": binding.policy_version, "revision": 1}},
        },
        "manifest": {"body": {"release_bundle_version": binding.release_bundle_version}},
        "observation": {"bundle": {"compiled": {"reader": binding.adapter_version}}},
    }
    proof = {
        "provenance_verified": True,
        "provider_verified": True,
        "binding": binding.model_dump(mode="json"),
    }
    state = {
        "state": "current",
        "protocol_id": str(protocol),
        "checked_at": NOW.isoformat(),
        "latest_collection_id": str(collection),
        "original_result": {"status": "meets_candidate_criteria"},
        "fresh_result": {"status": "meets_candidate_criteria"},
    }
    config = {
        "sampling_basis_points": 10000,
        "maximum_retraction_basis_points": 500,
        "recovery_protocol_version": "fixture-recovery-v1",
        "recovery_conditions": "模拟恢复",
    }
    original = {
        "binding": binding.model_dump(mode="json"),
        "policy_id": str(policy),
        "scope_revision_id": str(scope),
        "principal_id": str(principal),
        "configuration": config,
    }
    c = MagicMock()
    c.execute.return_value.mappings.return_value.__iter__.return_value = iter([raw])
    c.execute.return_value.scalar_one_or_none.return_value = protocol
    monkeypatch.setattr(route, "policy", lambda *_: setting)
    monkeypatch.setattr(route, "latest_scope", lambda *_: grant)
    monkeypatch.setattr(
        route,
        "resolve_capability",
        lambda *_: SimpleNamespace(rollout=SimpleNamespace(value="live")),
    )
    operations = dict(write_policy.WRITE_OPERATIONS)
    operations[route.OPERATION] = operations[route.OPERATION].model_copy(
        update={"adapter_ready": True}
    )
    monkeypatch.setattr(write_policy, "WRITE_OPERATIONS", operations)
    publication = SimpleNamespace(
        publication=SimpleNamespace(
            evaluations=[
                SimpleNamespace(evaluation=SimpleNamespace(outcome="passed", binding=binding))
            ]
        )
    )
    monkeypatch.setattr(
        route, "configured_issue_evaluation_publication", lambda *a, **k: publication
    )
    monkeypatch.setattr(route, "collect_provenance", lambda *a, **k: {str(run): proof})
    monkeypatch.setattr(route, "read_protocol", lambda *a: original)
    monkeypatch.setattr(route, "check_current", lambda *a, **k: state)
    monitor = MagicMock(return_value={"stopped": False, "stop_id": None, "receipt": {}})
    monkeypatch.setattr(route, "quality_monitor", monitor)
    return dict(
        c=c,
        kwargs=dict(tenant_id=tenant, project_id=project, run_id=run, as_of=NOW),
        setting=setting,
        grant=grant,
        raw=raw,
        proof=proof,
        state=state,
        monitor=monitor,
        binding=binding,
        protocol=protocol,
        original=original,
    )


def test_direct_keeps_exact_original_binding_and_current_assessments(setup: dict[str, Any]) -> None:
    result = route.resolve_direct_route(setup["c"], **setup["kwargs"])
    assert result["route"] == "direct" and result["sampled"] is True
    assert result["version"] == "event-issue-write-execution-v1"
    assert result["run_id"] == str(setup["kwargs"]["run_id"])
    assert result["binding_digest"] == digest(setup["binding"].model_dump(mode="json"))
    assert result["readiness"]["qualification_state"] == setup["state"]
    assert result["readiness"]["provenance"] == setup["proof"]
    assert "qualification_granted" not in result
    setup["monitor"].assert_called_once()


@pytest.mark.parametrize(
    "case",
    [
        "provider",
        "chain",
        "generation",
        "scope",
        "confirm",
        "publication",
        "state",
        "original",
        "fresh",
        "protocol",
    ],
)
def test_unverified_or_changed_sources_never_route_direct(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    if case == "provider":
        setup["proof"]["provider_verified"] = False
    elif case == "chain":
        setup["proof"]["provenance_verified"] = False
    elif case == "generation":
        setup["raw"]["generation"]["scope_revision_id"] = str(uuid4())
    elif case == "scope":
        setup["grant"]["enabled"] = False
    elif case == "confirm":
        setup["setting"]["operation_settings"][route.OPERATION]["mode"] = "confirm"
    elif case == "publication":
        monkeypatch.setattr(route, "configured_issue_evaluation_publication", lambda *a, **k: None)
    elif case == "state":
        setup["state"]["state"] = "blocked"
    elif case == "original":
        setup["state"]["original_result"]["status"] = "insufficient_evidence"
    elif case == "fresh":
        setup["state"]["fresh_result"]["status"] = "does_not_meet_criteria"
    else:
        setup["state"]["protocol_id"] = str(uuid4())
    result = route.resolve_direct_route(setup["c"], **setup["kwargs"])
    assert result["route"] in {"confirm", "exception"} and result["sampled"] is False
    setup["monitor"].assert_not_called()


def test_latched_stop_falls_back_and_monitor_errors_propagate(setup: dict[str, Any]) -> None:
    setup["monitor"].return_value = {"stopped": True, "stop_id": str(uuid4()), "receipt": {}}
    result = route.resolve_direct_route(setup["c"], **setup["kwargs"])
    assert result["route"] == "confirm" and result["reason"] == "quality_stop"
    setup["c"].execute.return_value.mappings.return_value.__iter__.return_value = iter(
        [setup["raw"]]
    )
    setup["monitor"].side_effect = ValueError("event writer rejected stop")
    with pytest.raises(ValueError, match="event writer"):
        route.resolve_direct_route(setup["c"], **setup["kwargs"])


def test_database_failure_is_not_converted_to_successful_fallback(setup: dict[str, Any]) -> None:
    setup["c"].execute.side_effect = SQLAlchemyError("read failed")
    with pytest.raises(SQLAlchemyError):
        route.resolve_direct_route(setup["c"], **setup["kwargs"])


def test_protocol_query_selects_latest_exact_real_business_binding(setup: dict[str, Any]) -> None:
    query = route.protocol_query(
        tenant_id=setup["kwargs"]["tenant_id"],
        project_id=setup["kwargs"]["project_id"],
        policy_id=setup["setting"]["id"],
        scope_revision_id=setup["grant"]["id"],
        principal_id=setup["grant"]["principal_id"],
        binding=setup["binding"],
        as_of=NOW,
    )
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    for key in (
        "tenant_id",
        "project_id",
        "policy_id",
        "scope_revision_id",
        "principal_id",
        "evidence_kind",
        "protocol",
    ):
        assert key in sql
    assert "created_at DESC" in sql and ".id DESC" in sql and "LIMIT" in sql
    assert "real_business" in compiled.params.values()
    assert setup["binding"].model_dump(mode="json") in compiled.params.values()
    assert "passed" not in compiled.params.values()
