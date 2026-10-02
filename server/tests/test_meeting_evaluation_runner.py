"""Real typed meeting execution receipts, using offline inputs and no database/network."""

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

from app.ai.application_domain_context import bundle as domain_bundle
from app.ai.meeting_capability_golden import LoadedMeetingGoldenSuite, load_meeting_golden_suite
from app.ai.meeting_evaluation_runner import (
    MeetingEvaluationRequest,
    MeetingEvaluationResponse,
    OfflineMeetingReplay,
    run_meeting_evaluation,
)
from app.ai.observations import digest
from app.ai.provider_adapters import ProviderRequestError, ProviderUsage
from app.contracts.ai_write_qualification import DraftOperation, QualificationBinding
from tests.test_ai_write_qualification_contract import binding as fixture_binding

SEGMENT = str(UUID(int=100))
STAMP = datetime(2026, 9, 27, tzinfo=UTC)
OPERATIONS: tuple[DraftOperation, ...] = (
    "meeting.minutes.draft",
    "meeting.actions.draft",
    "meeting.decisions.draft",
)


def binding(**changes: Any) -> QualificationBinding:
    operation = changes.get("operation_key", "meeting.minutes.draft")
    purpose = str(operation).removeprefix("meeting.").removesuffix(".draft")
    current = domain_bundle("meeting_" + purpose)
    return fixture_binding(
        **{
            "release_bundle_version": "sha256:" + digest(current),
            "adapter_version": current["compiled"]["reader"],
            **changes,
        }
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("meeting execution tests must not access provider or database")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def output(operation: DraftOperation) -> dict[str, Any]:
    citations = [{"segment_id": SEGMENT, "exact_quote": "今天不发布，等待验证。"}]
    if operation == "meeting.minutes.draft":
        return {
            "disposition": "reading",
            "claims": [{"text": "今天不发布，等待验证。", "citations": citations}],
            "open_questions": [],
        }
    if operation == "meeting.actions.draft":
        return {
            "disposition": "actions",
            "actions": [
                {
                    "title": "等待验证",
                    "description": "今天不发布，等待验证。",
                    "citations": citations,
                }
            ],
            "open_questions": [],
        }
    return {
        "disposition": "decisions",
        "decisions": [{"title": "今天不发布", "outcome": "等待验证", "citations": citations}],
        "open_questions": [],
    }


def suite(tmp_path: Path, operation: DraftOperation, count: int = 1) -> LoadedMeetingGoldenSuite:
    raw = json.dumps(
        {
            "version": "dc11-meeting-capability-golden.v1",
            "suite_version": "fixture-meeting.v1",
            "fixed_at": "2026-09-01T00:00:00Z",
            "review_status": "candidate",
            "cases": [
                {
                    "case_id": f"case-{index}",
                    "operation_key": operation,
                    "context": {
                        "question": "归纳会议原话",
                        "raw_secret": "do-not-send",
                        "references": [
                            {
                                "reference_id": SEGMENT,
                                "entity": "meeting_transcript_segment",
                                "entity_id": SEGMENT,
                                "label": "片段1",
                                "excerpt": "今天不发布，等待验证。",
                            }
                        ],
                    },
                    "expected_outputs": [output(operation)],
                }
                for index in range(count)
            ],
        },
        ensure_ascii=False,
    ).encode()
    path = tmp_path / "suite.json"
    path.write_bytes(raw)
    return load_meeting_golden_suite(path, expected_sha256=sha256(raw).hexdigest())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_offline_runner_uses_actual_typed_schema_and_preserves_originals(
    tmp_path: Path,
    operation: DraftOperation,
) -> None:
    loaded = suite(tmp_path, operation)
    raw = json.dumps(output(operation), ensure_ascii=False)
    seen: list[MeetingEvaluationRequest] = []
    replay = OfflineMeetingReplay({"case-0": [raw]})

    def execute(request: MeetingEvaluationRequest) -> MeetingEvaluationResponse:
        seen.append(request)
        assert "expected_outputs" not in request.model_dump_json()
        assert "do-not-send" not in request.model_dump_json()
        return replay(request)

    report = run_meeting_evaluation(
        loaded,
        binding=binding(operation_key=operation),
        executor=execute,
        evaluation_id=UUID(int=7),
        clock=lambda: STAMP,
    )
    assert report.status == "passed"
    assert report.qualification_granted is report.golden_approval_verified is False
    assert report.provider_calls_verified is False
    assert report.input_tokens == report.output_tokens == 0
    assert sha256(report.original_suite_json.encode()).hexdigest() == report.suite_digest
    assert (
        "sha256:" + digest(json.loads(report.runtime_bundle_json))
        == report.binding.release_bundle_version
    )
    case = report.cases[0]
    assert case.passed and case.score is not None
    assert case.score.case_digest == case.case_digest
    assert "raw_secret" in case.removed_context_paths
    attempt = case.attempts[0]
    assert attempt.raw_output == raw
    assert attempt.output_digest == sha256(raw.encode()).hexdigest()
    assert attempt.execution_source == "offline_replay" and not attempt.real_provider_call
    assert attempt.invocation_ref == f"offline-replay:{attempt.request.call_id}"
    assert attempt.typed_output_json is not None
    assert json.loads(attempt.typed_output_json)["disposition"] == output(operation)["disposition"]
    assert "label" not in json.loads(report.output_schema_json)["properties"]
    snapshot = report.model_dump(mode="json", exclude={"report_digest"})
    assert (
        report.report_digest
        == sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert seen[0].input_digest == attempt.request.input_digest


def test_format_retry_retains_first_failure_and_semantic_failure_does_not_retry(
    tmp_path: Path,
) -> None:
    operation: DraftOperation = "meeting.minutes.draft"
    loaded = suite(tmp_path, operation, 2)
    raw = json.dumps(output(operation), ensure_ascii=False)
    changed = raw.replace("今天不发布", "今天发布")
    report = run_meeting_evaluation(
        loaded,
        binding=binding(),
        executor=OfflineMeetingReplay(
            {
                "case-0": ["not JSON", raw],
                "case-1": [changed, raw],
            }
        ),
        clock=lambda: STAMP,
    )
    assert report.status == "failed"
    first, second = report.cases
    assert first.passed and len(first.attempts) == 2
    assert first.attempts[0].raw_output == "not JSON"
    assert first.attempts[0].status == "structured_invalid"
    assert "previous response failed" in first.attempts[1].request.messages[1].content
    assert not second.passed and len(second.attempts) == 1
    assert second.error_code == "EXPECTED_OUTPUT_MISMATCH"
    assert second.score and second.score.issues


def test_provider_error_keeps_usage_reference_and_runs_the_remaining_cases(tmp_path: Path) -> None:
    loaded = suite(tmp_path, "meeting.minutes.draft", 2)
    replay = OfflineMeetingReplay({"case-1": [json.dumps(output("meeting.minutes.draft"))]})

    def execute(request: MeetingEvaluationRequest) -> MeetingEvaluationResponse:
        if request.case_id == "case-0":
            raise ProviderRequestError(
                "rate_limited",
                "internal upstream text",
                usage=ProviderUsage(7, 2),
                request_id="provider-error-original",
            )
        return replay(request)

    report = run_meeting_evaluation(
        loaded, binding=binding(), executor=execute, clock=lambda: STAMP
    )
    assert report.status == "failed" and len(report.cases) == 2
    assert report.cases[0].attempts[0].provider_request_id == "provider-error-original"
    assert report.cases[0].error_code == "RATE_LIMITED"
    assert report.input_tokens == 7 and report.output_tokens == 2
    assert report.cases[1].passed
    assert "internal upstream text" not in report.model_dump_json()


def test_mismatched_execution_labels_and_binding_fail_before_becoming_evidence(
    tmp_path: Path,
) -> None:
    loaded = suite(tmp_path, "meeting.minutes.draft")
    replay = OfflineMeetingReplay({"case-0": [json.dumps(output("meeting.minutes.draft"))]})

    def mislabeled(request: MeetingEvaluationRequest) -> MeetingEvaluationResponse:
        return replace(replay(request), real_provider_call=True)

    report = run_meeting_evaluation(
        loaded, binding=binding(), executor=mislabeled, clock=lambda: STAMP
    )
    assert not report.cases[0].passed
    assert report.cases[0].error_code == "EXECUTION_SOURCE_MISMATCH"
    assert report.qualification_granted is False
    with pytest.raises(ValueError, match="single_capability_binding"):
        run_meeting_evaluation(
            loaded, binding=binding(operation_key="meeting.actions.draft"), executor=replay
        )
    loaded.suite.cases[0].context["question"] = "mutated after pinning"
    with pytest.raises(ValueError):
        run_meeting_evaluation(loaded, binding=binding(), executor=replay)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "change,error",
    [
        ({"release_bundle_version": "sha256:" + "0" * 64}, "runtime_release_bundle_mismatch"),
        ({"adapter_version": "unrelated-reader.v1"}, "runtime_source_adapter_mismatch"),
    ],
)
def test_rejects_foreign_runtime_binding_before_any_execution(
    tmp_path: Path,
    operation: DraftOperation,
    change: dict[str, str],
    error: str,
) -> None:
    loaded = suite(tmp_path, operation)

    def forbidden(request: MeetingEvaluationRequest) -> MeetingEvaluationResponse:
        raise AssertionError("mismatched runtime must not execute")

    with pytest.raises(ValueError, match=error):
        run_meeting_evaluation(
            loaded,
            binding=binding(operation_key=operation, **change),
            executor=forbidden,
        )
