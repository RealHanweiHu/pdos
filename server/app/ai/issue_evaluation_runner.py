"""Execute pinned Issue-capability cases with real typed outputs and replayable receipts.

An injected executor is the only call boundary. The offline executor makes no
provider calls. Execution-source labels and original-call references are claims
for later verification, never a human golden approval or an execution grant.
Nothing here reads credentials, opens a database, publishes or enables a model.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field, TypeAdapter

from app.ai.application_domain_context import bundle as domain_bundle
from app.ai.context_projection import project_gateway_context
from app.ai.executor import PromptFile
from app.ai.gateway import json_document, structured_messages
from app.ai.issue_capability_golden import (
    IssueCaseScore,
    LoadedIssueGoldenSuite,
    score_issue_output,
    verify_issue_golden_suite,
)
from app.ai.issue_event_proposal import IssueEventProposal, IssueEventProposalError, source_snapshot
from app.ai.issue_event_runs import model_context as runtime_model_context
from app.ai.observations import digest as bundle_digest
from app.ai.provider_adapters import ChatMessage, ProviderRequestError, ProviderResponse
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding as IssueEvaluationBinding
from app.contracts.ai_write_qualification import EvaluationExecutionSource
from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Positive, Text


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class IssueEvaluationRequest(Contract):
    """Exactly what an executor may see; expected golden answers are absent."""

    evaluation_id: UUID
    call_id: UUID
    case_id: Key
    attempt: Positive
    binding: IssueEvaluationBinding
    prompt_version: Key
    prompt_digest: Digest
    context_json: str
    output_schema_json: str
    messages: tuple[ChatMessage, ...]
    input_digest: Digest


@dataclass(frozen=True)
class IssueEvaluationResponse:
    """Executor-supplied provenance CLAIMS; this runner cannot verify provider calls."""

    response: ProviderResponse
    execution_source: EvaluationExecutionSource
    real_provider_call: bool
    invocation_ref: str | None = None
    original_receipt_digest: str | None = None


class IssueEvaluationExecutor(Protocol):
    def __call__(self, request: IssueEvaluationRequest) -> IssueEvaluationResponse: ...


class OfflineIssueReplay:
    """Snapshot supplied response strings; never label a replay as a real model call."""

    def __init__(self, outputs: Mapping[str, Sequence[str]]) -> None:
        self._outputs = {key: tuple(values) for key, values in outputs.items()}

    def __call__(self, request: IssueEvaluationRequest) -> IssueEvaluationResponse:
        responses = self._outputs.get(request.case_id, ())
        if request.attempt > len(responses):
            raise ProviderRequestError("offline_response_missing", "No fixed replay response")
        content = responses[request.attempt - 1]
        return IssueEvaluationResponse(
            response=ProviderResponse(
                content=content,
                input_tokens=0,
                output_tokens=0,
                request_id=None,
                model_version=None,
            ),
            execution_source="offline_replay",
            real_provider_call=False,
            invocation_ref=f"offline-replay:{request.call_id}",
            original_receipt_digest=_digest(content),
        )


class IssueEvaluationAttempt(Contract):
    request: IssueEvaluationRequest
    provenance_verified: Literal[False] = False
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: Literal["structured_valid", "structured_invalid", "call_failed"]
    error_code: Key | None
    raw_output: str | None
    output_digest: Digest | None
    typed_output_json: str | None
    execution_source: EvaluationExecutionSource
    real_provider_call: bool = Field(strict=True)
    invocation_ref: Text | None
    original_receipt_digest: Digest | None
    provider_request_id: Text | None
    reported_model_version: Text | None
    input_tokens: Nonnegative
    output_tokens: Nonnegative


class IssueEvaluationCaseReceipt(Contract):
    case_id: Key
    case_snapshot_json: str
    case_digest: Digest
    projected_context_json: str
    removed_context_paths: tuple[str, ...]
    attempts: tuple[IssueEvaluationAttempt, ...]
    score: IssueCaseScore | None
    passed: bool = Field(strict=True)
    error_code: Key | None
    source_guard_matched: bool | None = None


class IssueEvaluationReport(Contract):
    version: Literal["dc11-issue-capability-execution.v1"] = "dc11-issue-capability-execution.v1"
    evaluation_id: UUID
    binding: IssueEvaluationBinding
    suite_version: Key
    suite_digest: Digest
    suite_snapshot_json: str
    original_suite_json: str
    runtime_bundle_json: str
    started_at: AwareDatetime
    completed_at: AwareDatetime
    prompt_json: str
    prompt_digest: Digest
    output_schema_json: str
    cases: tuple[IssueEvaluationCaseReceipt, ...]
    status: Literal["passed", "failed", "guards_only"]
    model_case_count: Nonnegative
    model_passed_count: Nonnegative
    source_guard_count: Nonnegative
    input_tokens: Nonnegative
    output_tokens: Nonnegative
    provider_calls_verified: Literal[False] = False
    golden_approval_verified: Literal[False] = False
    qualification_granted: Literal[False] = False
    report_digest: Digest


def run_issue_evaluation(
    loaded_suite: LoadedIssueGoldenSuite,
    *,
    binding: IssueEvaluationBinding,
    executor: IssueEvaluationExecutor,
    execution_source: EvaluationExecutionSource = "offline_replay",
    max_structured_attempts: int = 2,
    evaluation_id: UUID | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> IssueEvaluationReport:
    """Execute every case in order, retaining failures and each bounded format retry.

    A live executor must independently enforce authorization/budget and persist
    original provider calls. The report preserves supplied references for review;
    it cannot attest that any injected response really came from a provider.
    """
    if type(max_structured_attempts) is not int or not 1 <= max_structured_attempts <= 3:
        raise ValueError("structured_attempt_budget_must_be_one_to_three")
    execution_source = TypeAdapter(EvaluationExecutionSource).validate_python(execution_source)
    if execution_source == "live_model_evaluation" and (
        binding.model_version is None
        or binding.model_version.casefold()
        in {"unknown", "latest", "unspecified", "unavailable", "未知", "未登记"}
    ):
        raise ValueError("live_candidate_requires_known_model_revision")
    suite = verify_issue_golden_suite(loaded_suite)
    if binding.suite_digest == loaded_suite.digest:
        raise ValueError("capability_suite_cannot_be_gateway_admission_suite")
    original_suite_json = loaded_suite.document.decode("utf-8")
    if not suite.cases or any(case.operation_key != binding.operation_key for case in suite.cases):
        raise ValueError("suite_must_match_single_capability_binding")
    runtime_bundle = domain_bundle("event_issue")
    if binding.release_bundle_version != "sha256:" + bundle_digest(runtime_bundle):
        raise ValueError("runtime_release_bundle_mismatch")
    compiled = runtime_bundle["compiled"]
    if binding.adapter_version != compiled["reader"]:
        raise ValueError("runtime_source_adapter_mismatch")
    evaluation_id = evaluation_id or uuid4()
    started_at = TypeAdapter(AwareDatetime).validate_python(clock())
    if suite.fixed_at > started_at:
        raise ValueError("evaluation_precedes_golden_fixation")
    prompt = PromptFile.model_validate(compiled["prompt"])
    prompt_json = _json(prompt.model_dump(mode="json"))
    prompt_digest = _digest(prompt_json)
    output_model = IssueEventProposal
    if output_model.model_json_schema() != compiled["schema"]:
        raise ValueError("runtime_output_schema_mismatch")
    schema_json = _json(compiled["schema"])
    results: list[IssueEvaluationCaseReceipt] = []
    for case in suite.cases:
        case_json = _json(case.model_dump(mode="json"))
        if case.expected_source_error is not None:
            try:
                source_snapshot(case.source)
            except IssueEventProposalError as error:
                code = error.code
            else:
                code = "SOURCE_GUARD_NOT_REJECTED"
            results.append(
                IssueEvaluationCaseReceipt(
                    case_id=case.case_id,
                    case_snapshot_json=case_json,
                    case_digest=_digest(case_json),
                    projected_context_json="null",
                    removed_context_paths=(),
                    attempts=(),
                    score=None,
                    passed=False,
                    error_code=code,
                    source_guard_matched=code == case.expected_source_error,
                )
            )
            continue
        projection = project_gateway_context(runtime_model_context(source_snapshot(case.source)))
        context_json = _json(projection.payload)
        attempts: list[IssueEvaluationAttempt] = []
        score: IssueCaseScore | None = None
        for attempt in range(1, max_structured_attempts + 1):
            messages = tuple(
                structured_messages(
                    system_prompt=prompt.system_prompt,
                    instruction=prompt.instruction,
                    context_json=context_json,
                    schema_json=schema_json,
                    retry=attempt > 1,
                )
            )
            call_id = uuid5(evaluation_id, f"{case.case_id}:{attempt}")
            request_body = dict(
                evaluation_id=evaluation_id,
                call_id=call_id,
                case_id=case.case_id,
                attempt=attempt,
                binding=binding,
                prompt_version=prompt.version,
                prompt_digest=prompt_digest,
                context_json=context_json,
                output_schema_json=schema_json,
                messages=messages,
            )
            request = IssueEvaluationRequest.model_validate(
                {**request_body, "input_digest": "0" * 64}
            )
            request = request.model_copy(
                update={
                    "input_digest": _digest(
                        _json(request.model_dump(mode="json", exclude={"input_digest"}))
                    )
                }
            )
            call_started = clock()
            try:
                response = executor(request)
            except ProviderRequestError as error:
                attempts.append(
                    IssueEvaluationAttempt(
                        request=request,
                        started_at=call_started,
                        completed_at=clock(),
                        status="call_failed",
                        error_code=error.code.upper(),
                        raw_output=None,
                        output_digest=None,
                        typed_output_json=None,
                        execution_source=execution_source,
                        real_provider_call=False,
                        invocation_ref=None,
                        original_receipt_digest=None,
                        provider_request_id=error.request_id,
                        reported_model_version=None,
                        input_tokens=error.usage.input_tokens if error.usage else 0,
                        output_tokens=error.usage.output_tokens if error.usage else 0,
                    )
                )
                break
            completed_at = clock()
            provider = response.response
            typed_json = None
            error_code = None
            status: Literal["structured_valid", "structured_invalid", "call_failed"] = (
                "structured_valid"
            )
            if response.execution_source != execution_source or (
                response.real_provider_call != (execution_source == "live_model_evaluation")
            ):
                status, error_code = "call_failed", "EXECUTION_SOURCE_MISMATCH"
            elif execution_source == "live_model_evaluation" and (
                not response.invocation_ref or not response.original_receipt_digest
            ):
                status, error_code = "call_failed", "ORIGINAL_CALL_REFERENCE_MISSING"
            elif (
                execution_source == "live_model_evaluation"
                and provider.model_version != binding.model_version
            ):
                status, error_code = "call_failed", "MODEL_REVISION_MISMATCH"
            else:
                try:
                    output = output_model.model_validate_json(json_document(provider.content))
                    typed_json = _json(output.model_dump(mode="json"))
                except ValueError:
                    status, error_code = "structured_invalid", "STRUCTURED_OUTPUT_INVALID"
            attempts.append(
                IssueEvaluationAttempt(
                    request=request,
                    started_at=call_started,
                    completed_at=completed_at,
                    status=status,
                    error_code=error_code,
                    raw_output=provider.content,
                    output_digest=_digest(provider.content),
                    typed_output_json=typed_json,
                    execution_source=response.execution_source,
                    real_provider_call=response.real_provider_call,
                    invocation_ref=response.invocation_ref,
                    original_receipt_digest=response.original_receipt_digest,
                    provider_request_id=provider.request_id,
                    reported_model_version=provider.model_version,
                    input_tokens=provider.input_tokens,
                    output_tokens=provider.output_tokens,
                )
            )
            if status == "call_failed":
                break
            if status == "structured_valid" or attempt == max_structured_attempts:
                score = score_issue_output(
                    case,
                    json_document(provider.content),
                    execution_source=execution_source,
                    real_provider_call=response.real_provider_call,
                )
                break
        last = attempts[-1]
        results.append(
            IssueEvaluationCaseReceipt(
                case_id=case.case_id,
                case_snapshot_json=case_json,
                case_digest=_digest(case_json),
                projected_context_json=context_json,
                removed_context_paths=projection.removed_paths,
                attempts=tuple(attempts),
                score=score,
                passed=score is not None
                and score.status == "passed"
                and last.status == "structured_valid",
                error_code=last.error_code
                or ("EXPECTED_OUTPUT_MISMATCH" if score and score.status != "passed" else None),
            )
        )
    report = IssueEvaluationReport(
        evaluation_id=evaluation_id,
        binding=binding,
        suite_version=suite.suite_version,
        suite_digest=loaded_suite.digest,
        suite_snapshot_json=_json(suite.model_dump(mode="json")),
        original_suite_json=original_suite_json,
        runtime_bundle_json=_json(runtime_bundle),
        started_at=started_at,
        completed_at=clock(),
        prompt_json=prompt_json,
        prompt_digest=prompt_digest,
        output_schema_json=schema_json,
        cases=tuple(results),
        status=(
            "failed"
            if any(
                item.source_guard_matched is False
                or (item.source_guard_matched is None and not item.passed)
                for item in results
            )
            else "guards_only"
            if all(item.source_guard_matched is not None for item in results)
            else "passed"
        ),
        model_case_count=sum(item.source_guard_matched is None for item in results),
        model_passed_count=sum(item.passed for item in results),
        source_guard_count=sum(item.source_guard_matched is not None for item in results),
        input_tokens=sum(attempt.input_tokens for result in results for attempt in result.attempts),
        output_tokens=sum(
            attempt.output_tokens for result in results for attempt in result.attempts
        ),
        report_digest="0" * 64,
    )
    return report.model_copy(
        update={
            "report_digest": _digest(
                _json(report.model_dump(mode="json", exclude={"report_digest"}))
            )
        }
    )


def main() -> None:
    """Offline-only artifact replay. No credential loading or live CLI switch."""
    import argparse
    from pathlib import Path

    from app.ai.issue_capability_golden import load_issue_golden_suite

    parser = argparse.ArgumentParser(description="Replay pinned Issue candidate golden offline")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--suite-sha256", required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    loaded = load_issue_golden_suite(args.suite, expected_sha256=args.suite_sha256)
    binding = IssueEvaluationBinding.model_validate_json(args.binding.read_bytes())
    outputs = json.loads(args.responses.read_text())
    if not isinstance(outputs, dict) or any(
        not isinstance(key, str)
        or not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        for key, values in outputs.items()
    ):
        parser.error("responses must map case IDs to lists of original output strings")
    report = run_issue_evaluation(loaded, binding=binding, executor=OfflineIssueReplay(outputs))
    args.output.write_text(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
