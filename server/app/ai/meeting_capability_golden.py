"""Fixed candidate golden contracts and deterministic meeting-output scoring.

Uses the actual three gateway output schemas, not gateway admission labels.
Semantics are deliberately conservative: only complete, explicitly fixed typed
answer variants are recognized. Different wording needs another reviewed variant;
substring/keyword matches cannot prove negation, quantities, ownership or intent.
These candidate cases do not claim human verification, live execution or T0
qualification. A runner must retain actual request/response/call originals and an
operator must independently review the golden before any trusted publication.
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

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from app.ai.meeting_reading import MeetingReading
from app.contracts.ai_write_qualification import DraftOperation, EvaluationExecutionSource
from app.contracts.common_objects import Contract, Digest, Key
from app.domain.meeting_action_proposals import MeetingActionAssessment
from app.domain.meeting_decision_proposals import MeetingDecisionAssessment

MeetingOutput = MeetingReading | MeetingActionAssessment | MeetingDecisionAssessment
OUTPUT_MODELS: dict[
    DraftOperation,
    type[MeetingReading] | type[MeetingActionAssessment] | type[MeetingDecisionAssessment],
] = {
    "meeting.minutes.draft": MeetingReading,
    "meeting.actions.draft": MeetingActionAssessment,
    "meeting.decisions.draft": MeetingDecisionAssessment,
}
ITEM_FIELDS: dict[DraftOperation, str] = {
    "meeting.minutes.draft": "claims",
    "meeting.actions.draft": "actions",
    "meeting.decisions.draft": "decisions",
}
MAX_SUITE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate_json_key")
        document[key] = value
    return document


def _references(context: dict[str, Any]) -> dict[str, str]:
    references = context.get("references")
    if not isinstance(references, list) or len(references) > 1000:
        raise ValueError("golden_requires_bounded_runtime_references")
    sources: dict[str, str] = {}
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("golden_reference_invalid")
        if not isinstance(reference.get("reference_id"), str):
            raise ValueError("golden_reference_id_invalid")
        key = str(UUID(reference["reference_id"]))
        if (
            reference.get("entity") != "meeting_transcript_segment"
            or reference.get("entity_id") != key
            or not isinstance(reference.get("excerpt"), str)
            or not reference["excerpt"].strip()
            or key in sources
        ):
            raise ValueError("golden_reference_invalid_or_duplicate")
        sources[key] = reference["excerpt"]
    return sources


def _items(output: MeetingOutput, operation: DraftOperation) -> list[dict[str, Any]]:
    return list(output.model_dump(mode="json")[ITEM_FIELDS[operation]])


def _semantic_key(item: dict[str, Any]) -> str:
    return _canonical({key: value for key, value in item.items() if key != "citations"})


def _citation_issues(items: list[dict[str, Any]], sources: dict[str, str]) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        seen: set[tuple[str, str]] = set()
        for quote_index, quote in enumerate(item["citations"]):
            key, text = quote["segment_id"], quote["exact_quote"]
            path = f"items/{index}/citations/{quote_index}"
            if (key, text) in seen:
                issues.append(("duplicate_citation", path))
            seen.add((key, text))
            if not text.strip() or text not in sources.get(key, ""):
                issues.append(("citation_not_in_frozen_source", path))
        # The production action prompt requires responsibility/date verbatim,
        # never inferred calendar dates or names even if other content matches.
        for literal_field in ("owner_text", "date_text"):
            value = item.get(literal_field)
            if value is not None and (
                not value.strip()
                or not any(value in quote["exact_quote"] for quote in item["citations"])
            ):
                issues.append(
                    ("action_literal_not_in_cited_source", f"items/{index}/{literal_field}")
                )
    return issues


class MeetingGoldenCase(Contract):
    case_id: Key
    operation_key: DraftOperation
    context: dict[str, Any]
    expected_outputs: Annotated[tuple[MeetingOutput, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def frozen_typed_expectations(self) -> Self:
        try:
            sources = _references(self.context)
            _canonical(self.context)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("golden_context_invalid") from error
        seen: set[str] = set()
        for expected in self.expected_outputs:
            if not isinstance(expected, OUTPUT_MODELS[self.operation_key]):
                raise ValueError("golden_output_operation_mismatch")
            items = _items(expected, self.operation_key)
            keys = [_semantic_key(item) for item in items]
            if len(set(keys)) != len(keys) or _citation_issues(items, sources):
                raise ValueError("golden_expected_items_or_citations_invalid")
            if len(set(expected.open_questions)) != len(expected.open_questions):
                raise ValueError("golden_duplicate_open_question")
            identity = _canonical(expected.model_dump(mode="json"))
            if identity in seen:
                raise ValueError("golden_duplicate_answer_variant")
            seen.add(identity)
        return self


class MeetingGoldenSuite(Contract):
    version: Literal["dc11-meeting-capability-golden.v1"]
    suite_version: Key
    fixed_at: AwareDatetime
    review_status: Literal["candidate"]
    cases: Annotated[tuple[MeetingGoldenCase, ...], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def distinct_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("golden_duplicate_case_id")
        return self


@dataclass(frozen=True)
class LoadedMeetingGoldenSuite:
    suite: MeetingGoldenSuite
    digest: str
    document: bytes = field(repr=False)


def verify_meeting_golden_suite(loaded: LoadedMeetingGoldenSuite) -> MeetingGoldenSuite:
    """Rebuild a private snapshot from original bytes; reject post-load mutation."""
    if (
        len(loaded.document) > MAX_SUITE_BYTES
        or sha256(loaded.document).hexdigest() != loaded.digest
    ):
        raise ValueError("golden_suite_original_digest_mismatch")
    original = MeetingGoldenSuite.model_validate(
        json.loads(loaded.document, object_pairs_hook=_json_object)
    )
    if original.model_dump(mode="json") != loaded.suite.model_dump(mode="json"):
        raise ValueError("golden_suite_modified_after_loading")
    return original


def load_meeting_golden_suite(path: Path, *, expected_sha256: str) -> LoadedMeetingGoldenSuite:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("golden_invalid_sha256_pin")
    with path.open("rb") as source:
        body = source.read(MAX_SUITE_BYTES + 1)
    if len(body) > MAX_SUITE_BYTES:
        raise ValueError("golden_suite_too_large")
    if sha256(body).hexdigest() != expected_sha256:
        raise ValueError("golden_suite_digest_mismatch")
    document = json.loads(body, object_pairs_hook=_json_object)
    return LoadedMeetingGoldenSuite(
        suite=MeetingGoldenSuite.model_validate(document), digest=expected_sha256, document=body
    )


class MeetingScoreIssue(Contract):
    code: Key
    path: str


class MeetingCaseScore(Contract):
    case_id: Key
    operation_key: DraftOperation
    case_digest: Digest
    output_digest: Digest
    execution_source: EvaluationExecutionSource
    real_provider_call: bool = Field(strict=True)
    status: Literal["passed", "failed"]
    issues: tuple[MeetingScoreIssue, ...]
    qualification_granted: Literal[False] = False


def _variant_issues(
    actual: MeetingOutput, expected: MeetingOutput, operation: DraftOperation
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    actual_items, expected_items = _items(actual, operation), _items(expected, operation)
    expected_by_key = {_semantic_key(item): item for item in expected_items}
    actual_counts = Counter(_semantic_key(item) for item in actual_items)
    if actual.disposition != expected.disposition:
        issues.append(("disposition_mismatch", "disposition"))
    for key in expected_by_key:
        if not actual_counts[key]:
            issues.append(("omitted_expected_item", f"expected/{list(expected_by_key).index(key)}"))
    for index, item in enumerate(actual_items):
        key = _semantic_key(item)
        if actual_counts[key] > 1:
            issues.append(("duplicate_output_item", f"items/{index}"))
        if key not in expected_by_key:
            issues.append(("unsupported_or_changed_content", f"items/{index}"))
            continue
        required = expected_by_key[key]["citations"]
        # Cover each fixed evidentiary quote, including qualifications/negation;
        # a true but unrelated quote cannot support the expected assertion.
        for quote in required:
            if not any(
                actual_quote["segment_id"] == quote["segment_id"]
                and quote["exact_quote"] in actual_quote["exact_quote"]
                for actual_quote in item["citations"]
            ):
                issues.append(("missing_required_evidence", f"items/{index}/citations"))
        for quote in item["citations"]:
            if not any(
                quote["segment_id"] == required_quote["segment_id"]
                and required_quote["exact_quote"] in quote["exact_quote"]
                for required_quote in required
            ):
                issues.append(("unrelated_evidence", f"items/{index}/citations"))
    if Counter(actual.open_questions) != Counter(expected.open_questions):
        issues.append(("unresolved_questions_mismatch", "open_questions"))
    return issues


def score_meeting_output(
    case: MeetingGoldenCase,
    output_json: str,
    *,
    execution_source: EvaluationExecutionSource,
    real_provider_call: bool,
) -> MeetingCaseScore:
    """Score the original typed response; provenance labels never attest a call.

    All variants must already be fixed before execution. A pass recognizes only
    this bounded rubric, not general semantic accuracy or independent approval.
    Offline/synthetic scores remain distinguishable and never count as live runs.
    """
    if type(real_provider_call) is not bool or execution_source not in {
        "live_model_evaluation",
        "offline_replay",
        "synthetic_output",
    }:
        raise ValueError("evaluation_execution_source_invalid")
    if real_provider_call != (execution_source == "live_model_evaluation"):
        raise ValueError("evaluation_execution_source_conflict")
    # Revalidate nested mutable context supplied by a caller before using it.
    fixed = MeetingGoldenCase.model_validate(case.model_dump(mode="json"))
    body = output_json.encode()
    problems: list[tuple[str, str]]
    if len(body) > MAX_OUTPUT_BYTES:
        problems = [("output_too_large", "$")]
    else:
        try:
            document = json.loads(output_json, object_pairs_hook=_json_object)
            actual = OUTPUT_MODELS[fixed.operation_key].model_validate(document)
        except (ValueError, ValidationError, RecursionError):
            problems = [("typed_output_invalid", "$")]
        else:
            problems = _citation_issues(
                _items(actual, fixed.operation_key), _references(fixed.context)
            )
            candidates: list[list[tuple[str, str]]] = [
                _variant_issues(actual, expected, fixed.operation_key)
                for expected in fixed.expected_outputs
            ]
            best = min(candidates, key=lambda candidate: len(candidate))
            problems.extend(best)
    return MeetingCaseScore(
        case_id=fixed.case_id,
        operation_key=fixed.operation_key,
        case_digest=_digest(fixed.model_dump(mode="json")),
        output_digest=sha256(body).hexdigest(),
        execution_source=execution_source,
        real_provider_call=real_provider_call,
        status="failed" if problems else "passed",
        issues=tuple(MeetingScoreIssue(code=code, path=path) for code, path in problems),
    )
