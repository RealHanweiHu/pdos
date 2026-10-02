"""Synthetic persisted-chain fixtures only; no provider or SQL execution."""

from copy import deepcopy
from datetime import timedelta
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from app.ai.issue_event_runs import model_context
from app.ai.observations import digest
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.domain.ai_issue_trial_provenance import collect_provenance, provenance_query
from tests.test_ai_write_trial_collection import CUTOFF, PROJECT, START, TENANT, receipt, uid


def original() -> dict[str, Any]:
    row = receipt(kind="event_issue")
    old = row.pop("draft")
    row.pop("policy")
    row.pop("confirmed_at")
    row.pop("edited_at")
    row.pop("withdrawn_at")
    source = dict(
        tenant_id=str(TENANT),
        project_id=str(PROJECT),
        event_row_id=1,
        source_digest="a" * 64,
        entity_id=uid(80),
    )
    source["context"] = dict(
        question="核对原失败",
        source_kind="test_failure",
        current_state="current",
        existing_issue_id=None,
        references=[],
    )
    row["run"] = dict(
        id=old["run_id"],
        tenant_id=str(TENANT),
        project_id=str(PROJECT),
        agent_key="quality_intelligence",
        status="succeeded",
        context_version="event-issue-request-v1",
        created_at=START.isoformat(),
        requested_by_user_id=uid(70),
        request_id=uid(71),
        run_context={"issue_event_source": source},
    )
    policy = dict(
        id=old["policy_id"],
        principal_id=old["principal_id"],
        operation_key="event.issue.create",
        contract_version="dc11-write-policy.v1",
        revision=1,
        created_at=START.isoformat(),
    )
    row["generation"] = dict(
        id=uid(72),
        tenant_id=str(TENANT),
        project_id=str(PROJECT),
        run_id=old["run_id"],
        requested_by_user_id=uid(70),
        policy_id=old["policy_id"],
        principal_id=old["principal_id"],
        created_at=START.isoformat(),
        event_row_id=1,
        source_digest="a" * 64,
        snapshot=dict(
            version="event-issue-generation-binding-v1",
            operation_key="event.issue.create",
            tenant_id=str(TENANT),
            project_id=str(PROJECT),
            run_id=old["run_id"],
            requested_by_user_id=uid(70),
            request_id=uid(71),
            policy=policy,
            event_row_id=1,
            source_digest="a" * 64,
            run_created_at=START.isoformat(),
        ),
    )
    proposal = {
        "disposition": "insufficient_evidence",
        "open_questions": ["需独立核实"],
        "citations": [],
    }
    row["result"] = dict(
        id=uid(73),
        tenant_id=str(TENANT),
        project_id=str(PROJECT),
        run_id=old["run_id"],
        created_at=(START + timedelta(minutes=8)).isoformat(),
        model_invocation_id=row["call"]["id"],
        event_row_id=1,
        source_digest="a" * 64,
        source_snapshot=source,
        proposal=proposal,
    )
    row["call"]["agent_key"] = "quality_intelligence"
    o, m = row["observation"], row["manifest"]["body"]
    o["bundle"]["compiled"]["purpose"] = "event_issue"
    o["bundle"]["compiled"]["reader"] = "event_issue-source-adapter.v1"
    o["metadata"]["allowed_purpose"] = "event_issue"
    o["metadata"]["tool_version"] = "event_issue-source-adapter.v1"
    o["context_body"]["context"] = model_context(source)
    o["metadata"]["input_digest"] = digest(model_context(source))
    o["output_body"] = source
    o["metadata"]["output_digest"] = digest(source)
    m["release_bundle_version"] = "sha256:" + digest(o["bundle"])
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    row["checkpoint"]["body"]["output"] = proposal
    for index, name in enumerate(
        ("observation", "admission", "manifest", "call", "checkpoint"), start=1
    ):
        row[name]["created_at"] = (START + timedelta(minutes=index)).isoformat()
    return row


def binding(row: dict[str, Any]) -> IssueEvaluationBinding:
    return IssueEvaluationBinding.model_validate(
        dict(
            provider="openai",
            model="fixture-model",
            model_version="fixture-revision-1",
            release_bundle_version=row["manifest"]["body"]["release_bundle_version"],
            suite_version="gateway-fixture.v1",
            suite_digest="c" * 64,
            adapter_version="event_issue-source-adapter.v1",
            policy_version="dc11-write-policy.v1",
            policy_revision=1,
        )
    )


def collect(rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    c = MagicMock()
    c.execute.return_value.mappings.return_value = rows
    value = collect_provenance(
        cast(Connection, c),
        TENANT,
        PROJECT,
        [UUID(uid(2))],
        CUTOFF,
        expected_binding=kwargs.get("expected_binding", binding(original())),
    )
    c.execute.assert_called_once()
    assert c.execute.call_args.args[0].is_select
    return value[uid(2)]


def codes(result: dict[str, Any]) -> set[str]:
    return {item["code"] for item in result["reasons"]}


def test_complete_synthetic_chain_proves_persistence_never_real_provider() -> None:
    row = original()
    result = collect([row])
    assert result["provenance_verified"] is True
    assert result["provider_verified"] is False
    assert result["binding"] == binding(row).model_dump(mode="json")
    assert codes(result) == {"provider_unverified"}
    assert result["references"] == dict(
        result_id=uid(73),
        invocation_id=uid(3),
        observation_id=uid(6),
        checkpoint_id=uid(8),
        manifest_id=uid(9),
        admission_id=uid(10),
    )
    assert result["original_result_at"] == row["result"]["created_at"]


@pytest.mark.parametrize(
    ("part", "field", "value", "reason"),
    [
        ("call", "model_version", "unknown", "model_version_unknown"),
        ("call", "usage_status", "partial", "usage_unverified"),
        ("call", "total_tokens", 99, "usage_unverified"),
        ("call", "project_id", uid(99), "scope_mismatch"),
        ("observation", "tenant_id", uid(99), "scope_mismatch"),
        ("checkpoint", "run_id", uid(99), "scope_mismatch"),
        ("checkpoint", "invocation_id", uid(99), "identity_mismatch"),
        ("manifest", "admission_id", uid(99), "identity_mismatch"),
        ("result", "model_invocation_id", uid(99), "identity_mismatch"),
        ("result", "source_digest", "f" * 64, "generation_unverified"),
        ("result", "created_at", START.isoformat(), "time_unverified"),
        ("call", "created_at", (CUTOFF + timedelta(seconds=1)).isoformat(), "time_unverified"),
    ],
)
def test_mismatched_originals_remain_unverified(
    part: str, field: str, value: Any, reason: str
) -> None:
    row = original()
    row[part][field] = value
    result = collect([row])
    assert result["binding"] is None
    assert result["provenance_verified"] is False
    assert result["provider_verified"] is False
    assert reason in codes(result)


@pytest.mark.parametrize(
    ("part", "field", "value", "reason"),
    [
        ("manifest", "digest", "0" * 64, "manifest_unverified"),
        ("manifest", "release_bundle_version", "sha256:" + "0" * 64, "bundle_unverified"),
        (
            "manifest",
            "model_qualification_version",
            "sha256:" + "0" * 64,
            "suite_binding_unverified",
        ),
        ("checkpoint", "output", {"unexpected": True}, "result_unverified"),
    ],
)
def test_body_digests_and_exact_output(part: str, field: str, value: Any, reason: str) -> None:
    row = original()
    row[part]["body"][field] = value
    assert reason in codes(collect([row]))


def test_observation_digest_and_frozen_policy_not_current_configuration() -> None:
    row = original()
    row["observation"]["metadata"]["output_digest"] = "0" * 64
    assert "observation_unverified" in codes(collect([row]))
    row = original()
    row["generation"]["snapshot"]["policy"]["revision"] = 2
    result = collect([row])
    assert result["binding"]["policy_revision"] == 2
    row["generation"]["snapshot"]["policy"]["id"] = uid(99)
    assert "generation_unverified" in codes(collect([row]))


@pytest.mark.parametrize(
    "part", ["generation", "result", "call", "observation", "checkpoint", "manifest", "admission"]
)
def test_missing_original_is_preserved(part: str) -> None:
    row = original()
    row[part] = None
    result = collect([row])
    assert part + "_missing" in codes(result)
    assert result["provenance_verified"] is False


def test_failed_or_absent_run_is_not_filtered_and_no_suite_is_not_filled() -> None:
    row = original()
    row["run"]["status"] = "degraded"
    row["result"] = None
    assert {"run_unfinished", "result_missing"} <= codes(collect([row]))
    assert "run_missing" in codes(collect([]))
    assert "suite_binding_unverified" in codes(collect([original()], expected_binding=None))
    changed = binding(original()).model_copy(update={"suite_version": "gateway-changed.v2"})
    assert "suite_binding_unverified" in codes(collect([original()], expected_binding=changed))


def test_duplicate_identical_join_dedup_but_ambiguous_does_not_pick_success() -> None:
    row = original()
    assert collect([row, deepcopy(row)])["provenance_verified"]
    bad = deepcopy(row)
    bad["call"]["usage_status"] = "unknown"
    assert "ambiguous_originals" in codes(collect([row, bad]))


def test_batch_query_keeps_population_and_does_not_filter_success() -> None:
    q = provenance_query(TENANT, PROJECT, [UUID(uid(2))])
    sql = str(q.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert sql.count("LEFT OUTER JOIN") == 7
    where = sql.split("WHERE", 1)[1]
    assert "agent_runs.tenant_id" in where and "agent_runs.project_id" in where
    assert "status" not in where and " LIMIT " not in sql
    c = MagicMock()
    assert collect_provenance(cast(Connection, c), TENANT, PROJECT, [], CUTOFF) == {}
    c.execute.assert_not_called()


@pytest.mark.parametrize("field", ["input_digest", "output_digest"])
def test_observation_digests_cannot_be_relabelled(field: str) -> None:
    row = original()
    row["observation"]["metadata"][field] = "0" * 64
    result = collect([row])
    assert "observation_unverified" in codes(result)
    assert result["binding"] is None


def test_later_model_revision_is_reported_from_original_not_expected() -> None:
    row = original()
    row["call"]["model_version"] = "fixture-revision-2"
    result = collect([row])
    assert result["provenance_verified"] is True
    assert result["binding"]["model_version"] == "fixture-revision-2"
    assert result["binding"] != binding(original()).model_dump(mode="json")
    assert result["provider_verified"] is False


def test_changed_model_input_cannot_reuse_otherwise_valid_output_chain() -> None:
    row = original()
    row["observation"]["context_body"]["context"]["question"] = "different source"
    assert "observation_unverified" in codes(collect([row]))
