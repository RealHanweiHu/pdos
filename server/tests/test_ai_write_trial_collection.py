from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection, Select
from sqlalchemy.dialects import postgresql

from app.ai.observations import digest
from app.contracts.ai_write_qualification import QualificationBinding
from app.domain.ai_write_trial_collection import TrialCollection, collect_trial, trial_query

START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=1)
CUTOFF = END + timedelta(hours=1)
TENANT, PROJECT = UUID(int=5000), UUID(int=5001)


def uid(index: int) -> str:
    return str(UUID(int=index))


def receipt(index: int = 0, kind: str = "minutes") -> dict[str, Any]:
    """Contract fixtures only: no provider calls, database writes or qualification."""
    offset = index * 100
    ids = {
        key: uid(offset + number)
        for number, key in enumerate(
            (
                "draft",
                "run",
                "call",
                "policy",
                "model_call",
                "observation",
                "authorization",
                "checkpoint",
                "manifest",
                "admission",
                "attempt",
                "principal",
            ),
            start=1,
        )
    }
    common = dict(tenant_id=str(TENANT), run_id=ids["run"], created_at=START.isoformat())
    bundle: dict[str, Any] = dict(
        version="application-domain-bundle.v1",
        source_sha256={"server/app/ai/application_domain_context.py": "a" * 64},
        compiled=dict(
            reader=f"meeting_{kind}-source-adapter.v1",
            purpose=f"meeting_{kind}",
            prompt={"version": f"meeting-{kind}-test.v1"},
            schema={"type": "object"},
        ),
    )
    output = {"fixture": "controlled synthetic row used only in pure tests"}
    metadata: dict[str, Any] = dict(
        id=ids["observation"],
        tenant_id=str(TENANT),
        run_id=ids["run"],
        tool_call_id=uid(90 + offset),
        parent_observation_id=None,
        sequence=1,
        tool_version=f"meeting_{kind}-source-adapter.v1",
        status="completed",
        sources=[],
        observed_at=START.isoformat(),
        as_of=START.isoformat(),
        fresh_until=None,
        acl_policy_version="application-policy.v1",
        allowed_purpose=f"meeting_{kind}",
        taint="untrusted_external",
        input_digest="d" * 64,
        output_digest=digest(output),
        shown_count=1,
        total_count=1,
        truncated=False,
        continuation=None,
    )
    admission = dict(
        **common,
        id=ids["admission"],
        attempt_id=ids["attempt"],
        call_kind="model",
        reservation_status="reserved",
        request_binding=dict(
            qualification_ref="fixture-meter-publication.v1",
            meter_version="fixture-meter.v1",
            model_call_id=ids["model_call"],
            provider="openai",
            model="fixture-model",
            protocol="openai-compatible",
        ),
    )
    manifest = dict(
        id=ids["manifest"],
        tenant_id=str(TENANT),
        run_id=ids["run"],
        authorization_id=ids["authorization"],
        revision_no=1,
        parent_revision_id=None,
        goal_revision=1,
        release_bundle_version="sha256:" + digest(bundle),
        capability_version="capability.v1",
        prompt_version=f"meeting-{kind}-test.v1",
        skill_versions=[],
        toolset_version="tools.v1",
        projection_version="projection.v1",
        model_qualification_version="sha256:"
        + digest(
            dict(
                qualification=dict(
                    provider="openai",
                    model="fixture-model",
                    status="passed",
                    suite_version="gateway-fixture.v1",
                    suite_digest="sha256:" + "c" * 64,
                ),
                meter_ref="fixture-meter-publication.v1",
                meter_version="fixture-meter.v1",
            )
        ),
        output_schema_version="sha256:" + digest(bundle["compiled"]["schema"]),
        policy_version="application-policy.v1",
        observation_ids=[ids["observation"]],
        event_watermark=0,
        selected_sources=[],
        omission_reasons=[],
        estimated_input_tokens=10,
        reserved_output_tokens=100,
        completeness="complete",
        missing=[],
        built_at=START.isoformat(),
    )
    manifest["digest"] = digest(manifest)
    return dict(
        draft=dict(
            common,
            id=ids["draft"],
            project_id=str(PROJECT),
            model_invocation_id=ids["call"],
            policy_id=ids["policy"],
            principal_id=ids["principal"],
            draft_kind=kind,
            capture_mode="trial",
            origin="ai",
            created_at=(START + timedelta(minutes=1)).isoformat(),
        ),
        call=dict(
            **common,
            id=ids["call"],
            project_id=str(PROJECT),
            agent_key="knowledge_lite",
            status="succeeded",
            usage_status="known",
            input_meter_version="normalized_input.v1",
            structured_attempts=1,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            provider="openai",
            model="fixture-model",
            model_version="fixture-revision-1",
            budget_call_id=ids["model_call"],
            prompt_version=f"meeting-{kind}-test.v1",
            protocol="openai-compatible",
        ),
        policy=dict(
            id=ids["policy"],
            tenant_id=str(TENANT),
            created_at=START.isoformat(),
            principal_id=ids["principal"],
            mode="tiered",
            contract_version="dc11-write-policy.v1",
            revision=1,
            operation_settings={f"meeting.{kind}.draft": {"mode": "confirm"}},
        ),
        observation=dict(
            **common,
            id=ids["observation"],
            model_call_id=ids["model_call"],
            authorization_id=ids["authorization"],
            metadata=metadata,
            output_body=output,
            bundle=bundle,
            context_body=dict(
                prompt_version=f"meeting-{kind}-test.v1",
                output_schema_sha256=digest(bundle["compiled"]["schema"]),
            ),
        ),
        checkpoint=dict(
            **common,
            id=ids["checkpoint"],
            invocation_id=ids["call"],
            model_call_id=ids["model_call"],
            observation_id=ids["observation"],
            manifest_id=ids["manifest"],
            body=dict(
                version="application-result.v1",
                status="succeeded",
                output={"minutes": "fixture"},
                structured_attempts=1,
            ),
        ),
        manifest=dict(
            **common,
            id=ids["manifest"],
            observation_id=ids["observation"],
            authorization_id=ids["authorization"],
            admission_id=ids["admission"],
            attempt_id=ids["attempt"],
            body=manifest,
        ),
        admission=admission,
        confirmed_at=END,
        edited_at=None,
        withdrawn_at=None,
    )


def expected(row: dict[str, Any] | None = None, **changes: Any) -> QualificationBinding:
    row = row or receipt()
    return QualificationBinding.model_validate(
        dict(
            operation_key=f"meeting.{row['draft']['draft_kind']}.draft",
            provider="openai",
            model="fixture-model",
            model_version="fixture-revision-1",
            release_bundle_version=row["manifest"]["body"]["release_bundle_version"],
            suite_version="gateway-fixture.v1",
            suite_digest="c" * 64,
            adapter_version=row["observation"]["bundle"]["compiled"]["reader"],
            policy_version="dc11-write-policy.v1",
            policy_revision=1,
        )
        | changes
    )


class ReadConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[Select[Any]] = []

    def execute(self, query: Select[Any]) -> ReadConnection:
        assert query.is_select
        self.queries.append(query)
        return self

    def mappings(self) -> ReadConnection:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


def collect(rows: list[dict[str, Any]], **changes: Any) -> TrialCollection:
    connection = ReadConnection(rows)
    args: dict[str, Any] = (
        dict(
            tenant_id=TENANT,
            project_ids=(PROJECT,),
            operation_key="meeting.minutes.draft",
            window_start=START,
            window_end=END,
            as_of=CUTOFF,
            expected_binding=expected(),
            evidence_kind="real_business",
            cohort_id=UUID(int=7000),
            evidence_ref="fixture://trial",
        )
        | changes
    )
    result = collect_trial(cast(Connection, connection), **args)
    assert len(connection.queries) == 1
    return result


@pytest.mark.parametrize("kind", ["minutes", "actions", "decisions"])
def test_complete_original_chain_produces_bound_evidence(kind: str) -> None:
    row = receipt(kind=kind)
    result = collect([row], operation_key=f"meeting.{kind}.draft", expected_binding=expected(row))
    assert result.raw_total == result.verified_total == 1
    assert result.unverified_total == 0
    assert result.blockers == ()
    assert result.cohort.selection_complete
    assert result.cohort.drafts[0].binding == expected(row)
    assert str(result.cohort.drafts[0].context_observation_id) == row["observation"]["id"]
    assert result.cohort.drafts[0].confirmed_at == END


def test_missing_sources_remain_in_raw_denominator_and_block_cohort() -> None:
    complete, missing, pending = receipt(), receipt(1), receipt(2)
    missing["manifest"] = None
    missing["withdrawn_at"] = CUTOFF
    pending["confirmed_at"] = None
    result = collect([complete, missing, pending])
    assert (result.raw_total, result.verified_total, result.unverified_total) == (3, 2, 1)
    assert result.raw_counts.generated == 3
    assert result.raw_counts.confirmed == 2
    assert result.raw_counts.withdrawn == result.raw_counts.pending == 1
    assert result.cohort.selection_complete is False
    assert result.blockers[0].reasons == ("manifest_missing",)
    assert UUID(missing["draft"]["id"]) in result.original_draft_ids


@pytest.mark.parametrize(
    "source", ["call", "policy", "observation", "checkpoint", "manifest", "admission"]
)
def test_every_missing_original_link_is_explicitly_unverified(source: str) -> None:
    row = receipt()
    row[source] = None
    result = collect([row])
    assert result.raw_total == result.unverified_total == 1
    assert result.cohort.drafts == ()
    assert f"{source}_missing" in result.blockers[0].reasons


@pytest.mark.parametrize(
    "source", ["call", "policy", "observation", "checkpoint", "manifest", "admission"]
)
def test_original_scope_mismatch_is_not_relabelled(source: str) -> None:
    row = receipt()
    row[source]["tenant_id"] = uid(999)
    result = collect([row])
    assert f"{source}_scope_mismatch" in result.blockers[0].reasons
    assert not result.cohort.selection_complete


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("usage_status", "legacy_unverified", "provider_call_unverified"),
        ("usage_status", "unknown", "provider_call_unverified"),
        ("input_meter_version", "legacy_unverified", "provider_call_unverified"),
        ("structured_attempts", 0, "provider_call_unverified"),
        ("status", "provider_error", "provider_call_unverified"),
        ("model_version", None, "model_version_unknown"),
        ("model_version", "unknown", "model_version_unknown"),
        ("model_version", "revision-other", "expected_binding_mismatch"),
        ("total_tokens", 31, "usage_totals_unverified"),
        ("input_tokens", None, "usage_totals_unverified"),
    ],
)
def test_call_failure_or_unknown_metadata_is_never_filtered_away(
    key: str, value: Any, reason: str
) -> None:
    row = receipt()
    row["call"][key] = value
    result = collect([row])
    assert result.raw_total == 1
    assert result.verified_total == 0
    assert reason in result.blockers[0].reasons


def test_expected_suite_must_reproduce_original_gateway_pin() -> None:
    result = collect([receipt()], expected_binding=expected(suite_version="dc11-new-suite.v1"))
    assert "suite_binding_unverified" in result.blockers[0].reasons
    assert not result.cohort.drafts
    result = collect([receipt()], expected_binding=expected(suite_digest="d" * 64))
    assert "suite_binding_unverified" in result.blockers[0].reasons


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("release_bundle_version", "sha256:" + "f" * 64),
        ("adapter_version", "other-adapter.v1"),
        ("policy_revision", 2),
        ("policy_version", "other-policy.v1"),
        ("provider", "minimax"),
        ("model", "other-model"),
    ],
)
def test_expected_binding_is_never_written_over_actual_binding(key: str, value: Any) -> None:
    result = collect([receipt()], expected_binding=expected(**{key: value}))
    assert "expected_binding_mismatch" in result.blockers[0].reasons
    assert result.cohort.drafts == ()


@pytest.mark.parametrize(
    ("source", "key", "value", "reason"),
    [
        ("manifest", "observation_id", uid(999), "context_chain_mismatch"),
        ("checkpoint", "manifest_id", uid(999), "context_chain_mismatch"),
        ("checkpoint", "invocation_id", uid(999), "context_chain_mismatch"),
        ("observation", "model_call_id", uid(999), "context_chain_mismatch"),
        ("policy", "mode", "legacy", "original_policy_unverified"),
        ("policy", "principal_id", uid(999), "original_policy_unverified"),
        ("call", "created_at", CUTOFF.isoformat(), "source_after_draft_or_time_unknown"),
    ],
)
def test_original_links_and_times_are_verified(
    source: str, key: str, value: Any, reason: str
) -> None:
    row = receipt()
    row[source][key] = value
    assert reason in collect([row]).blockers[0].reasons


@pytest.mark.parametrize(
    ("source", "field", "value", "reason"),
    [
        ("manifest", "body", {"digest": "0" * 64}, "context_contract_invalid"),
        ("observation", "metadata", {}, "context_contract_invalid"),
        ("observation", "output_body", {"different": True}, "observation_unverified"),
        ("checkpoint", "body", {"status": "succeeded"}, "original_result_unverified"),
        ("admission", "request_binding", {}, "admission_binding_unverified"),
    ],
)
def test_bad_original_bodies_are_preserved_as_blockers(
    source: str, field: str, value: Any, reason: str
) -> None:
    row = receipt()
    row[source][field] = value
    result = collect([row])
    assert reason in result.blockers[0].reasons
    assert result.raw_total == 1


def test_original_bundle_and_manifest_hashes_are_checked() -> None:
    row = receipt()
    row["observation"]["bundle"]["compiled"]["reader"] = "changed-reader.v2"
    assert "original_bundle_unverified" in collect([row]).blockers[0].reasons
    row = receipt()
    row["manifest"]["body"]["digest"] = "0" * 64
    assert "manifest_unverified" in collect([row]).blockers[0].reasons


def test_duplicate_join_rows_count_once_and_conflicting_receipts_block() -> None:
    row = receipt()
    result = collect([row, deepcopy(row)])
    assert result.raw_total == result.verified_total == 1
    assert result == collect([row])
    conflict = deepcopy(row)
    conflict["call"]["model_version"] = "changed"
    result = collect([row, conflict])
    assert result.raw_total == result.unverified_total == 1
    assert result.blockers[0].reasons == ("ambiguous_original_draft_join",)


def test_fixed_receipt_digest_is_stable_across_row_and_project_order() -> None:
    rows = [receipt(), receipt(1)]
    first = collect(rows, project_ids=(PROJECT, UUID(int=6000)))
    second = collect(list(reversed(rows)), project_ids=(UUID(int=6000), PROJECT, PROJECT))
    assert first == second
    changed = deepcopy(rows)
    changed[1]["edited_at"] = CUTOFF
    assert (
        collect(changed, project_ids=first.project_ids).cohort.receipt_digest
        != first.cohort.receipt_digest
    )


@pytest.mark.parametrize("kind", ["controlled_replay", "synthetic"])
def test_registered_protocol_evidence_kind_is_preserved_not_upgraded(kind: str) -> None:
    result = collect([receipt()], evidence_kind=kind)
    assert result.cohort.drafts[0].evidence_kind == kind


def test_empty_selection_is_complete_but_contains_no_qualification_sample() -> None:
    result = collect([])
    assert result.cohort.selection_complete
    assert result.raw_total == result.verified_total == result.unverified_total == 0
    assert result.cohort.drafts == ()


def test_invalid_scope_window_or_operation_rejected_before_read() -> None:
    for changes in (
        {"project_ids": ()},
        {"operation_key": "formal_action.execute"},
        {"operation_key": "meeting.actions.draft"},
        {"window_end": START},
        {"as_of": START},
        {"evidence_kind": "live_model_evaluation"},
    ):
        with pytest.raises(ValueError):
            collect([], **changes)


def test_query_is_one_full_outer_provenance_read_with_first_action_cutoff() -> None:
    query = trial_query(
        tenant_id=TENANT,
        project_ids=(PROJECT,),
        operation_key="meeting.minutes.draft",
        window_start=START,
        window_end=END,
        as_of=CUTOFF,
    )
    sql = str(
        query.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )
    assert sql.startswith("SELECT ")
    assert "LIMIT" not in sql and "OFFSET" not in sql
    assert sql.count("LEFT OUTER JOIN") == 7
    assert "model_invocations.status =" not in sql
    assert "ai_meeting_drafts.created_at >=" in sql and "ai_meeting_drafts.created_at <" in sql
    assert "ai_meeting_drafts.capture_mode = 'trial'" in sql
    assert "ai_meeting_drafts.draft_kind = 'minutes'" in sql
    assert "ai_meeting_draft_actions.created_at <=" in sql
    assert sql.count("min(cehub_ai.ai_meeting_draft_actions.created_at) FILTER") == 3
    assert "GROUP BY cehub_ai.ai_meeting_draft_actions.draft_id" in sql
    assert "application_result_checkpoints.manifest_id" in sql
    assert "budget_journal.id = cehub_ai.application_context_manifests.admission_id" in sql
