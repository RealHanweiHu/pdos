"""Pinned candidate Issue golden and strict, deterministic typed-output scoring.

Reviewed whole-answer variants fix meaning, including severity and uncertainty;
valid citations alone never prove that a generated claim is supported. Candidate
fixtures do not assert human approval, a real call, or automatic-write authority.
Source adapter rejection is a separate outcome and cannot pass a model case.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from app.ai.issue_event_proposal import (
    IssueEventProposal,
    IssueEventProposalError,
    model_context,
    source_snapshot,
    validate_proposal,
)
from app.contracts.ai_write_qualification import EvaluationExecutionSource
from app.contracts.common_objects import Contract, Digest, Key
from app.domain.product_workspace import digest as reader_digest

MAX_SUITE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_digest(value: Any) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _event(source: dict[str, Any]) -> dict[str, Any]:
    raw = source.get("source")
    event = raw.get("event") if isinstance(raw, dict) else None
    if not isinstance(event, dict) or type(event.get("id")) is not int or event["id"] <= 0:
        raise ValueError("golden_original_event_missing")
    for top, key in (
        ("event_row_id", "id"),
        ("event_id", "event_id"),
        ("event_type", "event_type"),
    ):
        if source.get(top) != event.get(key) or not event.get(key):
            raise ValueError("golden_original_event_mismatch")
    for key in ("tenant_id", "project_id", "entity_id"):
        UUID(str(event.get(key)))
    TypeAdapter(AwareDatetime).validate_python(event.get("timestamp"))
    if source.get("source_kind") not in {"test_failure", "material_exception"}:
        raise ValueError("golden_source_kind_unsupported")
    if not isinstance(source.get("source_digest"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", source["source_digest"]
    ):
        raise ValueError("golden_reader_digest_missing")
    if not isinstance(source.get("reason_code"), str) or source["source_digest"] != reader_digest(
        {
            "source": source["source"],
            "existing_issue": source.get("existing_issue"),
            "source_status": source.get("source_status"),
            "reason_code": source["reason_code"],
        }
    ):
        raise ValueError("golden_reader_digest_mismatch")
    return event


class IssueGoldenCase(Contract):
    case_id: Key
    operation_key: Literal["event.issue.create"] = "event.issue.create"
    # The source is the complete frozen reader receipt, including the original
    # event/review and distinct current basis. The reader's digest is retained;
    # this independent digest pins all supplied bytes semantically, not DB truth.
    source: dict[str, Any]
    source_document_digest: Digest
    expected_source_snapshot: dict[str, Any] | None
    expected_outputs: Annotated[tuple[IssueEventProposal, ...], Field(max_length=8)] = ()
    expected_source_error: Key | None = None

    @model_validator(mode="after")
    def fixed_source_and_answers(self) -> Self:
        _event(self.source)
        if content_digest(self.source) != self.source_document_digest:
            raise ValueError("golden_source_document_digest_mismatch")
        try:
            snapshot = source_snapshot(self.source)
        except IssueEventProposalError as error:
            if (
                self.expected_source_error != error.code
                or self.expected_outputs
                or self.expected_source_snapshot is not None
            ):
                raise ValueError("golden_source_rejection_mismatch") from error
            return self
        if self.expected_source_error is not None or not self.expected_outputs:
            raise ValueError("golden_current_source_requires_model_answers")
        if snapshot != self.expected_source_snapshot or snapshot["context"] != model_context(
            self.source
        ):
            raise ValueError("golden_source_snapshot_mismatch")
        seen: set[str] = set()
        for expected in self.expected_outputs:
            validate_proposal(self.source, expected)
            identity = canonical(expected.model_dump(mode="json"))
            if identity in seen or len(set(expected.open_questions)) != len(
                expected.open_questions
            ):
                raise ValueError("golden_duplicate_answer_or_question")
            seen.add(identity)
        return self


class IssueGoldenSuite(Contract):
    version: Literal["dc11-issue-capability-golden.v1"]
    suite_version: Key
    fixed_at: AwareDatetime
    review_status: Literal["candidate"]
    cases: Annotated[tuple[IssueGoldenCase, ...], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def fixed_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("golden_duplicate_case_id")
        if any(
            TypeAdapter(AwareDatetime).validate_python(_event(case.source)["timestamp"])
            > self.fixed_at
            for case in self.cases
        ):
            raise ValueError("golden_event_after_fixation")
        return self


@dataclass(frozen=True)
class LoadedIssueGoldenSuite:
    suite: IssueGoldenSuite
    digest: str
    document: bytes = field(repr=False)


def verify_issue_golden_suite(loaded: LoadedIssueGoldenSuite) -> IssueGoldenSuite:
    if (
        len(loaded.document) > MAX_SUITE_BYTES
        or sha256(loaded.document).hexdigest() != loaded.digest
    ):
        raise ValueError("golden_suite_original_digest_mismatch")
    original = IssueGoldenSuite.model_validate(
        json.loads(loaded.document, object_pairs_hook=json_object)
    )
    if original.model_dump(mode="json") != loaded.suite.model_dump(mode="json"):
        raise ValueError("golden_suite_modified_after_loading")
    return original


def load_issue_golden_suite(path: Path, *, expected_sha256: str) -> LoadedIssueGoldenSuite:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("golden_invalid_sha256_pin")
    with path.open("rb") as source:
        document = source.read(MAX_SUITE_BYTES + 1)
    if len(document) > MAX_SUITE_BYTES:
        raise ValueError("golden_suite_too_large")
    if sha256(document).hexdigest() != expected_sha256:
        raise ValueError("golden_suite_digest_mismatch")
    suite = IssueGoldenSuite.model_validate(json.loads(document, object_pairs_hook=json_object))
    return LoadedIssueGoldenSuite(suite, expected_sha256, document)


class IssueScoreIssue(Contract):
    code: Key
    path: str


class IssueCaseScore(Contract):
    case_id: Key
    operation_key: Literal["event.issue.create"] = "event.issue.create"
    case_digest: Digest
    output_digest: Digest
    execution_source: EvaluationExecutionSource
    real_provider_call: bool = Field(strict=True)
    status: Literal["passed", "failed"]
    issues: tuple[IssueScoreIssue, ...]
    qualification_granted: Literal[False] = False


def _variant_issues(
    actual: IssueEventProposal, expected: IssueEventProposal
) -> list[tuple[str, str]]:
    problems = []
    for key in ("disposition", "title", "description", "severity", "existing_issue_id"):
        if getattr(actual, key) != getattr(expected, key):
            problems.append(
                (
                    "disposition_mismatch"
                    if key == "disposition"
                    else "unsupported_or_changed_content",
                    key,
                )
            )
    if Counter(actual.open_questions) != Counter(expected.open_questions):
        problems.append(("unresolved_questions_mismatch", "open_questions"))
    for quote in expected.citations:
        if not any(
            item.reference_id == quote.reference_id and quote.exact_quote in item.exact_quote
            for item in actual.citations
        ):
            problems.append(("missing_required_evidence", "citations"))
    for quote in actual.citations:
        if not any(
            item.reference_id == quote.reference_id and item.exact_quote in quote.exact_quote
            for item in expected.citations
        ):
            problems.append(("unrelated_evidence", "citations"))
    return problems


def score_issue_output(
    case: IssueGoldenCase,
    output_json: str,
    *,
    execution_source: EvaluationExecutionSource,
    real_provider_call: bool,
) -> IssueCaseScore:
    if (
        type(real_provider_call) is not bool
        or execution_source not in {"live_model_evaluation", "offline_replay", "synthetic_output"}
        or real_provider_call != (execution_source == "live_model_evaluation")
    ):
        raise ValueError("evaluation_execution_source_conflict")
    fixed = IssueGoldenCase.model_validate(case.model_dump(mode="json"))
    if fixed.expected_source_error is not None:
        raise ValueError("source_guard_case_is_not_model_evaluation")
    body = output_json.encode()
    problems: list[tuple[str, str]] = []
    if len(body) > MAX_OUTPUT_BYTES:
        problems.append(("output_too_large", "$"))
    else:
        try:
            actual = IssueEventProposal.model_validate(
                json.loads(output_json, object_pairs_hook=json_object)
            )
        except (ValueError, RecursionError):
            problems.append(("typed_output_invalid", "$"))
        else:
            try:
                validate_proposal(fixed.source, actual)
            except IssueEventProposalError as error:
                problems.append((error.code, "$"))
            variants = [_variant_issues(actual, answer) for answer in fixed.expected_outputs]
            best: list[tuple[str, str]] = min(variants, key=lambda variant: len(variant))
            problems.extend(best)
    return IssueCaseScore(
        case_id=fixed.case_id,
        operation_key=fixed.operation_key,
        case_digest=content_digest(fixed.model_dump(mode="json")),
        output_digest=sha256(body).hexdigest(),
        execution_source=execution_source,
        real_provider_call=real_provider_call,
        status="failed" if problems else "passed",
        issues=tuple(IssueScoreIssue(code=code, path=path) for code, path in problems),
    )
