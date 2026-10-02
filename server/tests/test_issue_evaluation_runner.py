"""Reproducible offline Issue evaluation artifacts; all sources are synthetic candidates."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.ai.application_domain_context import bundle
from app.ai.issue_capability_golden import canonical, load_issue_golden_suite
from app.ai.issue_evaluation_runner import (
    IssueEvaluationBinding,
    IssueEvaluationRequest,
    IssueEvaluationResponse,
    OfflineIssueReplay,
    main,
    run_issue_evaluation,
)
from app.ai.issue_event_runs import model_context as runtime_model_context
from app.ai.observations import digest
from app.ai.provider_adapters import ProviderRequestError, ProviderResponse
from tests.test_issue_capability_golden import candidate_case, loaded_suite

STAMP = datetime(2026, 9, 27, 2, tzinfo=UTC)


def candidate_binding(**changes: Any) -> IssueEvaluationBinding:
    runtime = bundle("event_issue")
    return IssueEvaluationBinding.model_validate(
        {
            "operation_key": "event.issue.create",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "model_version": "fixture-revision",
            "release_bundle_version": "sha256:" + digest(runtime),
            "suite_version": "gateway-admission-fixture.v1",
            "suite_digest": "b" * 64,
            "adapter_version": runtime["compiled"]["reader"],
            "policy_version": "fixture-policy.v1",
            "policy_revision": 1,
            **changes,
        }
    )


def write_offline_example(directory: Path) -> dict[str, str]:
    """Write SIX synthetic candidates for external replay; never a trusted publication.

    Usage: write_offline_example(Path('/external/evidence/issue-candidate'));
    python -m app.ai.issue_evaluation_runner --suite <suite> --suite-sha256 <sha>
      --binding <binding> --responses <responses> --output <report>
    All paths and the exact suite SHA are returned. The binding pins current code.
    """
    directory.mkdir(parents=True, exist_ok=True)
    loaded = loaded_suite(directory / "synthetic-issue-suite.json")
    responses = {
        case.case_id: [case.expected_outputs[0].model_dump_json()]
        for case in loaded.suite.cases
        if case.expected_outputs
    }
    binding_path, responses_path = (
        directory / "candidate-binding.json",
        directory / "offline-responses.json",
    )
    binding_path.write_text(candidate_binding().model_dump_json(indent=2) + "\n")
    responses_path.write_text(json.dumps(responses, ensure_ascii=False, indent=2) + "\n")
    return {
        "suite": str(directory / "synthetic-issue-suite.json"),
        "suite_sha256": loaded.digest,
        "binding": str(binding_path),
        "responses": str(responses_path),
        "report": str(directory / "offline-report.json"),
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Issue runner tests cannot access a database/provider")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_offline_actual_schema_context_and_original_digests(tmp_path: Path) -> None:
    loaded = loaded_suite(tmp_path / "suite.json")
    original_outputs = {
        case.case_id: [case.expected_outputs[0].model_dump_json()]
        for case in loaded.suite.cases
        if case.expected_outputs
    }
    replay = OfflineIssueReplay(original_outputs)
    seen = []

    def execute(request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        seen.append(request)
        for private in (
            "expected_outputs",
            "AUDIT_SECRET",
            "PRIVATE_ACTOR",
            "PRIVATE_REPORTER",
            "fixture-answer",
        ):
            assert private not in request.model_dump_json()
        return replay(request)

    report = run_issue_evaluation(
        loaded,
        binding=candidate_binding(),
        executor=execute,
        evaluation_id=UUID(int=1),
        clock=lambda: STAMP,
    )
    assert report.version == "dc11-issue-capability-execution.v1"
    assert report.status == "passed" and report.model_case_count == report.model_passed_count == 5
    assert report.source_guard_count == 1 and len(seen) == 5
    assert (
        not report.provider_calls_verified
        and not report.golden_approval_verified
        and not report.qualification_granted
    )
    assert sha256(report.original_suite_json.encode()).hexdigest() == report.suite_digest
    assert (
        "sha256:" + digest(json.loads(report.runtime_bundle_json))
        == report.binding.release_bundle_version
    )
    assert (
        sha256(
            canonical(report.model_dump(mode="json", exclude={"report_digest"})).encode()
        ).hexdigest()
        == report.report_digest
    )
    for case, receipt in zip(loaded.suite.cases, report.cases, strict=True):
        assert sha256(receipt.case_snapshot_json.encode()).hexdigest() == receipt.case_digest
        if case.expected_source_error:
            assert not receipt.passed and receipt.score is None and receipt.attempts == ()
            assert receipt.source_guard_matched and receipt.error_code == "source_not_current"
            continue
        assert case.expected_source_snapshot is not None
        expected = runtime_model_context(case.expected_source_snapshot)
        context = json.loads(receipt.projected_context_json)
        assert context["question"] == expected["question"]
        assert '"existing_issue_id"' in context["question"]
        attempt = receipt.attempts[0]
        assert attempt.raw_output == original_outputs[case.case_id][0]
        assert sha256(attempt.raw_output.encode()).hexdigest() == attempt.output_digest
        assert attempt.original_receipt_digest == attempt.output_digest
        assert attempt.invocation_ref == f"offline-replay:{attempt.request.call_id}"
        assert not attempt.real_provider_call and not attempt.provenance_verified
        assert (
            sha256(
                canonical(
                    attempt.request.model_dump(mode="json", exclude={"input_digest"})
                ).encode()
            ).hexdigest()
            == attempt.request.input_digest
        )
    assert "disposition" in json.loads(report.output_schema_json)["properties"]
    assert "label" not in json.loads(report.output_schema_json)["properties"]


def test_format_retry_preserves_failure_semantic_error_does_not_retry(tmp_path: Path) -> None:
    one, two = candidate_case("one"), candidate_case("two")
    loaded = loaded_suite(tmp_path / "suite.json", (one, two))
    valid = one.expected_outputs[0].model_dump_json()
    changed = one.expected_outputs[0].model_copy(update={"severity": "low"}).model_dump_json()
    report = run_issue_evaluation(
        loaded,
        binding=candidate_binding(),
        executor=OfflineIssueReplay({"one": ["not-json", valid], "two": [changed, valid]}),
        clock=lambda: STAMP,
    )
    assert report.status == "failed" and report.model_passed_count == 1
    assert (
        len(report.cases[0].attempts) == 2 and report.cases[0].attempts[0].raw_output == "not-json"
    )
    assert report.cases[0].attempts[0].status == "structured_invalid"
    assert (
        len(report.cases[1].attempts) == 1
        and report.cases[1].error_code == "EXPECTED_OUTPUT_MISMATCH"
    )


def test_guard_only_suite_never_claims_model_pass(tmp_path: Path) -> None:
    loaded = loaded_suite(tmp_path / "suite.json", (candidate_case(blocked=True),))

    def forbidden(request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        raise AssertionError("source rejection cannot call the model")

    report = run_issue_evaluation(
        loaded, binding=candidate_binding(), executor=forbidden, clock=lambda: STAMP
    )
    assert (
        report.status == "guards_only" and report.model_case_count == report.model_passed_count == 0
    )
    assert report.source_guard_count == 1 and report.cases[0].score is None


def test_live_executor_claims_are_retained_but_never_verified(tmp_path: Path) -> None:
    case = candidate_case()
    loaded = loaded_suite(tmp_path / "suite.json", (case,))

    def claimed_live(request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        return IssueEvaluationResponse(
            ProviderResponse(
                case.expected_outputs[0].model_dump_json(),
                11,
                7,
                "claimed-request",
                "fixture-revision",
            ),
            "live_model_evaluation",
            True,
            "claimed-call:1",
            "c" * 64,
        )

    report = run_issue_evaluation(
        loaded,
        binding=candidate_binding(),
        executor=claimed_live,
        execution_source="live_model_evaluation",
        clock=lambda: STAMP,
    )
    attempt = report.cases[0].attempts[0]
    assert report.status == "passed" and attempt.real_provider_call
    assert (
        attempt.invocation_ref == "claimed-call:1" and attempt.original_receipt_digest == "c" * 64
    )
    assert not attempt.provenance_verified and not report.provider_calls_verified
    assert not report.golden_approval_verified and not report.qualification_granted
    assert report.input_tokens == 11 and report.output_tokens == 7


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"execution_source": "offline_replay", "real_provider_call": False},
            "EXECUTION_SOURCE_MISMATCH",
        ),
        ({"invocation_ref": None}, "ORIGINAL_CALL_REFERENCE_MISSING"),
        ({"model_version": "other"}, "MODEL_REVISION_MISMATCH"),
    ],
)
def test_live_claim_mismatch_keeps_raw_attempt_without_scoring(
    tmp_path: Path, change: dict[str, Any], code: str
) -> None:
    case = candidate_case()
    loaded = loaded_suite(tmp_path / "suite.json", (case,))
    original = IssueEvaluationResponse(
        ProviderResponse(
            case.expected_outputs[0].model_dump_json(), 1, 1, "claimed-request", "fixture-revision"
        ),
        "live_model_evaluation",
        True,
        "claimed-call:1",
        "c" * 64,
    )
    if "model_version" in change:
        response = replace(
            original, response=replace(original.response, model_version=change["model_version"])
        )
    else:
        response = replace(original, **change)
    report = run_issue_evaluation(
        loaded,
        binding=candidate_binding(),
        executor=lambda request: response,
        execution_source="live_model_evaluation",
        clock=lambda: STAMP,
    )
    assert report.status == "failed" and report.cases[0].error_code == code
    assert report.cases[0].attempts[0].raw_output == original.response.content
    assert report.cases[0].score is None


def test_original_failure_is_preserved_and_later_cases_continue(tmp_path: Path) -> None:
    loaded = loaded_suite(
        tmp_path / "suite.json", (candidate_case("first"), candidate_case("second"))
    )

    def failure(request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        raise ProviderRequestError(
            "fixture_unavailable", "synthetic no call", request_id="unverified"
        )

    report = run_issue_evaluation(
        loaded, binding=candidate_binding(), executor=failure, clock=lambda: STAMP
    )
    assert report.status == "failed" and len(report.cases) == 2
    assert all(
        item.attempts[0].status == "call_failed"
        and item.attempts[0].provider_request_id == "unverified"
        for item in report.cases
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"release_bundle_version": "sha256:" + "a" * 64}, "runtime_release_bundle_mismatch"),
        ({"adapter_version": "other.v1"}, "runtime_source_adapter_mismatch"),
    ],
)
def test_runtime_binding_mismatch_prevents_execution(
    tmp_path: Path, change: dict[str, Any], code: str
) -> None:
    loaded = loaded_suite(tmp_path / "suite.json")
    with pytest.raises(ValueError, match=code):
        run_issue_evaluation(
            loaded,
            binding=candidate_binding(**change),
            executor=OfflineIssueReplay({}),
            clock=lambda: STAMP,
        )


def test_cli_is_offline_only_and_replayable_from_shared_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = write_offline_example(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "issue-evaluation",
            "--suite",
            files["suite"],
            "--suite-sha256",
            files["suite_sha256"],
            "--binding",
            files["binding"],
            "--responses",
            files["responses"],
            "--output",
            files["report"],
        ],
    )
    main()
    report = json.loads(Path(files["report"]).read_text())
    assert (
        report["status"] == "passed"
        and report["model_case_count"] == 5
        and report["source_guard_count"] == 1
    )
    assert all(
        attempt["execution_source"] == "offline_replay" and not attempt["real_provider_call"]
        for case in report["cases"]
        for attempt in case["attempts"]
    )
    assert not report["provider_calls_verified"] and not report["golden_approval_verified"]
    assert (
        load_issue_golden_suite(
            Path(files["suite"]), expected_sha256=files["suite_sha256"]
        ).suite.review_status
        == "candidate"
    )


def test_live_unknown_model_and_unfixed_golden_cannot_call_executor(tmp_path: Path) -> None:
    loaded = loaded_suite(tmp_path / "suite.json")

    def forbidden(request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        raise AssertionError("invalid candidate must not call executor")

    with pytest.raises(ValueError, match="known_model_revision"):
        run_issue_evaluation(
            loaded,
            binding=candidate_binding(model_version=None),
            executor=forbidden,
            execution_source="live_model_evaluation",
            clock=lambda: STAMP,
        )
    with pytest.raises(ValueError, match="precedes_golden_fixation"):
        run_issue_evaluation(
            loaded,
            binding=candidate_binding(),
            executor=forbidden,
            clock=lambda: datetime(2026, 9, 26, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="cannot_be_gateway"):
        run_issue_evaluation(
            loaded,
            binding=candidate_binding(suite_digest=loaded.digest),
            executor=forbidden,
            clock=lambda: STAMP,
        )
