"""Synthetic rubric checks; fixtures are not human-verified golden publications."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.ai.meeting_capability_golden import (
    MAX_OUTPUT_BYTES,
    MAX_SUITE_BYTES,
    MeetingGoldenCase,
    MeetingGoldenSuite,
    load_meeting_golden_suite,
    score_meeting_output,
    verify_meeting_golden_suite,
)

SEGMENT = str(UUID(int=1))
OTHER = str(UUID(int=2))
SOURCE = (
    "李工说明：DVT良率为92%，尚未批准量产。李工下周提交失效分析报告。"
    "比较方案A和方案B，结论尚未形成。"
)
OPERATIONS = ("meeting.minutes.draft", "meeting.actions.draft", "meeting.decisions.draft")


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("golden scorer cannot use a database, network or model")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def expected(operation: str) -> dict[str, Any]:
    item: dict[str, Any]
    if operation == OPERATIONS[0]:
        field, disposition, item, quote = (
            "claims",
            "reading",
            {"text": "DVT良率为92%，尚未批准量产。"},
            "DVT良率为92%，尚未批准量产。",
        )
    elif operation == OPERATIONS[1]:
        field, disposition, item, quote = (
            "actions",
            "actions",
            {
                "title": "提交失效分析",
                "description": "李工下周提交失效分析报告。",
                "owner_text": "李工",
                "date_text": "下周",
                "expected_output": "失效分析报告",
            },
            "李工下周提交失效分析报告。",
        )
    else:
        field, disposition, item, quote = (
            "decisions",
            "decisions",
            {
                "title": "比较方案",
                "context": "方案A和方案B待比较",
                "options": ["方案A", "方案B"],
                "trade_offs": None,
                "outcome": None,
                "rationale": None,
                "consequence": None,
            },
            "比较方案A和方案B，结论尚未形成。",
        )
    item["citations"] = [{"segment_id": SEGMENT, "exact_quote": quote}]
    return {"disposition": disposition, field: [item], "open_questions": ["量产批准条件待补充"]}


def case_document(operation: str = OPERATIONS[0]) -> dict[str, Any]:
    return {
        "case_id": "synthetic-rubric-fixture.v1",
        "operation_key": operation,
        "context": {
            "question": "仅为评分器单元测试；不是人工核实golden",
            "references": [
                {
                    "reference_id": SEGMENT,
                    "entity_id": SEGMENT,
                    "entity": "meeting_transcript_segment",
                    "excerpt": SOURCE,
                }
            ],
        },
        "expected_outputs": [expected(operation)],
    }


def score(document: dict[str, Any], output: dict[str, Any] | str) -> Any:
    return score_meeting_output(
        MeetingGoldenCase.model_validate(document),
        output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
        execution_source="synthetic_output",
        real_provider_call=False,
    )


def codes(result: Any) -> set[str]:
    return {issue.code for issue in result.issues}


@pytest.mark.parametrize("operation", OPERATIONS)
def test_actual_typed_outputs_match_and_preserve_original(operation: str) -> None:
    document = case_document(operation)
    original = json.dumps(expected(operation), ensure_ascii=False)
    result = score(document, original)
    assert result.status == "passed"
    assert result.output_digest == sha256(original.encode()).hexdigest()
    assert result.execution_source == "synthetic_output"
    assert result.real_provider_call is False
    assert result.qualification_granted is False
    assert not result.issues


@pytest.mark.parametrize("operation", OPERATIONS)
def test_real_quote_does_not_validate_changed_meaning(operation: str) -> None:
    output = expected(operation)
    if operation == OPERATIONS[0]:
        output["claims"][0]["text"] = "DVT良率为92%，已批准量产。"
    elif operation == OPERATIONS[1]:
        output["actions"][0]["expected_output"] = "已完成失效分析报告"
    else:
        output["decisions"][0]["outcome"] = "批准方案A"
    result = score(case_document(operation), output)
    assert result.status == "failed"
    assert "unsupported_or_changed_content" in codes(result)
    assert "omitted_expected_item" in codes(result)


@pytest.mark.parametrize(
    "text", ["DVT良率为99%，尚未批准量产。", "DVT良率为92%，不再需要批准量产。"]
)
def test_number_and_negation_never_use_keyword_matching(text: str) -> None:
    output = expected(OPERATIONS[0])
    output["claims"][0]["text"] = text
    assert score(case_document(), output).status == "failed"


@pytest.mark.parametrize("field,value", [("owner_text", "王工"), ("date_text", "2026-10-04")])
def test_action_invented_person_or_relative_date_resolution_rejected(
    field: str, value: str
) -> None:
    output = expected(OPERATIONS[1])
    output["actions"][0][field] = value
    result = score(case_document(OPERATIONS[1]), output)
    assert "action_literal_not_in_cited_source" in codes(result)


def test_missing_action_owner_and_date_remain_null() -> None:
    document = case_document(OPERATIONS[1])
    original = document["expected_outputs"][0]
    original["actions"][0]["owner_text"] = None
    original["actions"][0]["date_text"] = None
    assert score(document, original).status == "passed"
    changed = deepcopy(original)
    changed["actions"][0]["owner_text"] = "李工"
    assert score(document, changed).status == "failed"


@pytest.mark.parametrize("field", ["trade_offs", "outcome", "rationale", "consequence"])
def test_decision_unknown_fields_cannot_be_filled(field: str) -> None:
    output = expected(OPERATIONS[2])
    output["decisions"][0][field] = "与原文无关的推定"
    assert score(case_document(OPERATIONS[2]), output).status == "failed"


def test_invented_decision_alternative_rejected() -> None:
    output = expected(OPERATIONS[2])
    output["decisions"][0]["options"].append("方案C")
    assert score(case_document(OPERATIONS[2]), output).status == "failed"


@pytest.mark.parametrize(
    "mode", ["wrong_segment", "paraphrase_quote", "duplicate", "unrelated", "empty"]
)
def test_citation_bound_to_exact_source_and_expected_evidence(mode: str) -> None:
    output = expected(OPERATIONS[0])
    quote = output["claims"][0]["citations"][0]
    if mode == "wrong_segment":
        quote["segment_id"] = OTHER
    elif mode == "paraphrase_quote":
        quote["exact_quote"] = "DVT良率达到92%"
    elif mode == "duplicate":
        output["claims"][0]["citations"].append(deepcopy(quote))
    elif mode == "unrelated":
        quote["exact_quote"] = "李工下周提交失效分析报告。"
    else:
        quote["exact_quote"] = " "
    result = score(case_document(), output)
    assert result.status == "failed"
    assert codes(result) & {
        "citation_not_in_frozen_source",
        "duplicate_citation",
        "missing_required_evidence",
    }


def test_larger_contiguous_quote_is_allowed_when_it_contains_required_evidence() -> None:
    output = expected(OPERATIONS[0])
    output["claims"][0]["citations"][0]["exact_quote"] = SOURCE
    assert score(case_document(), output).status == "passed"


@pytest.mark.parametrize("mode", ["omit", "extra", "duplicate", "unresolved"])
def test_omission_extra_duplicate_and_open_questions(mode: str) -> None:
    output = expected(OPERATIONS[0])
    if mode == "omit":
        output["claims"] = []
        output["disposition"] = "insufficient_evidence"
    elif mode == "extra":
        output["claims"].append(
            {"text": "客户已批准", "citations": deepcopy(output["claims"][0]["citations"])}
        )
    elif mode == "duplicate":
        output["claims"].append(deepcopy(output["claims"][0]))
    else:
        output["open_questions"] = []
    assert score(case_document(), output).status == "failed"


def test_insufficient_evidence_is_valid_only_when_fixed_expected() -> None:
    document = case_document()
    output = {
        "disposition": "insufficient_evidence",
        "claims": [],
        "open_questions": ["没有明确会议结论"],
    }
    document["expected_outputs"] = [output]
    assert score(document, output).status == "passed"
    assert score(document, expected(OPERATIONS[0])).status == "failed"


def test_explicit_paraphrase_variant_allowed_but_hybrid_not_invented() -> None:
    document = case_document(OPERATIONS[1])
    alternate = deepcopy(document["expected_outputs"][0])
    alternate["actions"][0]["title"] = "整理失效分析报告"
    alternate["actions"][0]["description"] = "下周由李工提交失效分析报告。"
    document["expected_outputs"].append(alternate)
    assert score(document, alternate).status == "passed"
    hybrid = deepcopy(alternate)
    hybrid["actions"][0]["description"] = expected(OPERATIONS[1])["actions"][0]["description"]
    assert score(document, hybrid).status == "failed"


@pytest.mark.parametrize(
    "invalid",
    [
        "not json",
        '{"disposition":"reading","disposition":"reading"}',
        '{"claims":[]}',
        "[1]",
        '"text"',
    ],
)
def test_structured_failures_return_score(invalid: str) -> None:
    result = score(case_document(), invalid)
    assert codes(result) == {"typed_output_invalid"}


def test_wrong_output_schema_and_size_rejected() -> None:
    assert "typed_output_invalid" in codes(score(case_document(), expected(OPERATIONS[1])))
    assert "output_too_large" in codes(score(case_document(), " " * (MAX_OUTPUT_BYTES + 1)))


@pytest.mark.parametrize(
    "source,real",
    [("offline_replay", False), ("live_model_evaluation", True), ("synthetic_output", False)],
)
def test_execution_origin_is_retained_without_qualification(source: Any, real: bool) -> None:
    result = score_meeting_output(
        MeetingGoldenCase.model_validate(case_document()),
        json.dumps(expected(OPERATIONS[0])),
        execution_source=source,
        real_provider_call=real,
    )
    assert result.execution_source == source
    assert result.real_provider_call is real
    assert not result.qualification_granted


@pytest.mark.parametrize(
    "source,real",
    [("offline_replay", True), ("live_model_evaluation", False), ("synthetic_output", True)],
)
def test_conflicting_execution_origin_rejected(source: Any, real: bool) -> None:
    with pytest.raises(ValueError, match="execution_source_conflict"):
        score_meeting_output(
            MeetingGoldenCase.model_validate(case_document()),
            "{}",
            execution_source=source,
            real_provider_call=real,
        )


@pytest.mark.parametrize(
    "mode",
    ["wrong_type", "invalid_quote", "duplicate_item", "duplicate_variant", "duplicate_source"],
)
def test_bad_golden_candidate_fails_before_scoring(mode: str) -> None:
    document = case_document()
    if mode == "wrong_type":
        document["expected_outputs"] = [expected(OPERATIONS[1])]
    elif mode == "invalid_quote":
        document["expected_outputs"][0]["claims"][0]["citations"][0]["exact_quote"] = (
            "not in source"
        )
    elif mode == "duplicate_item":
        document["expected_outputs"][0]["claims"].append(
            deepcopy(document["expected_outputs"][0]["claims"][0])
        )
    elif mode == "duplicate_variant":
        document["expected_outputs"].append(deepcopy(document["expected_outputs"][0]))
    else:
        document["context"]["references"].append(deepcopy(document["context"]["references"][0]))
    with pytest.raises(ValidationError):
        MeetingGoldenCase.model_validate(document)


def suite_document() -> dict[str, Any]:
    return {
        "version": "dc11-meeting-capability-golden.v1",
        "suite_version": "synthetic-unit-fixture.v1",
        "fixed_at": "2026-09-27T00:00:00Z",
        "review_status": "candidate",
        "cases": [case_document()],
    }


def test_suite_original_digest_and_no_fake_review(tmp_path: Path) -> None:
    document = suite_document()
    body = json.dumps(document).encode()
    path = tmp_path / "synthetic-unit-fixture.json"
    path.write_bytes(body)
    loaded = load_meeting_golden_suite(path, expected_sha256=sha256(body).hexdigest())
    assert loaded.digest == sha256(body).hexdigest()
    assert loaded.suite.review_status == "candidate"
    with pytest.raises(ValueError, match="digest_mismatch"):
        load_meeting_golden_suite(path, expected_sha256="0" * 64)
    document["review_status"] = "human_verified"
    with pytest.raises(ValidationError):
        MeetingGoldenSuite.model_validate(document)


def test_suite_size_duplicate_case_and_strict_version(tmp_path: Path) -> None:
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * (MAX_SUITE_BYTES + 1))
    with pytest.raises(ValueError, match="too_large"):
        load_meeting_golden_suite(path, expected_sha256="0" * 64)
    document = suite_document()
    document["cases"].append(deepcopy(document["cases"][0]))
    with pytest.raises(ValidationError, match="duplicate_case"):
        MeetingGoldenSuite.model_validate(document)
    document = suite_document()
    document["version"] = "future-version"
    with pytest.raises(ValidationError):
        MeetingGoldenSuite.model_validate(document)


def test_post_load_mutation_cannot_keep_original_digest(tmp_path: Path) -> None:
    body = json.dumps(suite_document()).encode()
    path = tmp_path / "mutable-fixture.json"
    path.write_bytes(body)
    loaded = load_meeting_golden_suite(path, expected_sha256=sha256(body).hexdigest())
    private = verify_meeting_golden_suite(loaded)
    assert private == loaded.suite
    assert private is not loaded.suite
    loaded.suite.cases[0].context["question"] = "changed after freezing"
    assert private.cases[0].context["question"] != "changed after freezing"
    with pytest.raises(ValueError, match="modified_after_loading"):
        verify_meeting_golden_suite(loaded)
