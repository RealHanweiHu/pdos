"""Synthetic candidate examples only; no human golden approval or real model evidence."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.issue_capability_golden import (
    IssueGoldenCase,
    IssueGoldenSuite,
    LoadedIssueGoldenSuite,
    content_digest,
    load_issue_golden_suite,
    score_issue_output,
    verify_issue_golden_suite,
)
from app.ai.issue_event_proposal import IssueEventProposal, model_context, source_snapshot
from app.domain.product_workspace import digest
from tests.test_issue_event_proposal import create, insufficient, reuse, source


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("golden candidate tests cannot access databases or providers")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def pin_source(value: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(value)
    value.setdefault("reason_code", "current")
    value["source_digest"] = digest(
        {
            key: value.get(key)
            for key in ("source", "existing_issue", "source_status", "reason_code")
        }
    )
    return value


def candidate_case(
    case_id: str = "test-create",
    *,
    kind: str = "test_failure",
    disposition: str = "create_issue",
    blocked: bool = False,
) -> IssueGoldenCase:
    original = source(kind=kind, existing=disposition == "reuse_issue")
    answer = (
        create()
        if disposition == "create_issue"
        else reuse()
        if disposition == "reuse_issue"
        else insufficient()
    )
    if kind == "material_exception" and disposition == "create_issue":
        quote = model_context(original)["references"][0]["excerpt"]
        answer = create(
            title="补齐泵组件",
            description="已登记范围现货缺口 2 件，固定需求 5 件。",
            severity="medium",
            citations=[{"reference_id": "material.original.shortage", "exact_quote": quote}],
        )
    if blocked:
        original.update(
            source_status="changed",
            reason_code="test_changed" if kind == "test_failure" else "material_changed",
        )
    original = pin_source(original)
    return IssueGoldenCase(
        case_id=case_id,
        source=original,
        source_document_digest=content_digest(original),
        expected_source_snapshot=None if blocked else source_snapshot(original),
        expected_outputs=() if blocked else (IssueEventProposal.model_validate(answer),),
        expected_source_error="source_not_current" if blocked else None,
    )


def candidate_document(cases: tuple[IssueGoldenCase, ...] | None = None) -> dict[str, Any]:
    items = cases or (
        candidate_case(),
        candidate_case("test-reuse", disposition="reuse_issue"),
        candidate_case("test-insufficient", disposition="insufficient_evidence"),
        candidate_case("material-create", kind="material_exception"),
        candidate_case("material-reuse", kind="material_exception", disposition="reuse_issue"),
        candidate_case("source-stale", blocked=True),
    )
    return {
        "version": "dc11-issue-capability-golden.v1",
        "suite_version": "synthetic-issue-candidate.v1",
        "fixed_at": "2026-09-27T01:00:00Z",
        "review_status": "candidate",
        "cases": [item.model_dump(mode="json") for item in items],
    }


def loaded_suite(
    path: Path, cases: tuple[IssueGoldenCase, ...] | None = None
) -> LoadedIssueGoldenSuite:
    raw = json.dumps(candidate_document(cases), ensure_ascii=False, indent=2).encode()
    path.write_bytes(raw)
    return load_issue_golden_suite(path, expected_sha256=sha256(raw).hexdigest())


def score(case: IssueGoldenCase, value: Any) -> Any:
    return score_issue_output(
        case,
        json.dumps(value, ensure_ascii=False),
        execution_source="offline_replay",
        real_provider_call=False,
    )


@pytest.mark.parametrize(
    "kind,disposition",
    [
        ("test_failure", "create_issue"),
        ("test_failure", "reuse_issue"),
        ("test_failure", "insufficient_evidence"),
        ("material_exception", "create_issue"),
        ("material_exception", "reuse_issue"),
        ("material_exception", "insufficient_evidence"),
    ],
)
def test_all_actual_dispositions_and_source_kinds_score_typed_expected_answers(
    kind: str, disposition: str
) -> None:
    case = candidate_case(kind=kind, disposition=disposition)
    result = score(case, case.expected_outputs[0].model_dump(mode="json"))
    assert result.status == "passed" and not result.qualification_granted
    assert result.execution_source == "offline_replay" and not result.real_provider_call


@pytest.mark.parametrize(
    "changes",
    [
        {"severity": "low"},
        {"description": "运行 100 小时没有泄漏，根因已确认。"},
        {"description": "运行 80 小时出现泄漏。"},
        {"title": "测试已通过"},
    ],
)
def test_valid_reference_does_not_excuse_changed_fact_negation_omission_or_severity(
    changes: dict[str, Any],
) -> None:
    case = candidate_case()
    result = score(case, {**case.expected_outputs[0].model_dump(mode="json"), **changes})
    assert result.status == "failed"
    assert "unsupported_or_changed_content" in {item.code for item in result.issues}


def test_required_evidence_and_existing_issue_identity_cannot_be_substituted() -> None:
    case = candidate_case()
    body = case.expected_outputs[0].model_dump(mode="json")
    body["citations"] = [
        {"reference_id": "test.original.failure", "exact_quote": "原登记测试结果：失败"}
    ]
    assert "missing_required_evidence" in {item.code for item in score(case, body).issues}
    body["citations"] = [
        {"reference_id": "test.original.result_notes", "exact_quote": "从未记录的失效"}
    ]
    assert "citation_invalid" in {item.code for item in score(case, body).issues}
    linked = candidate_case(disposition="reuse_issue")
    assert "existing_issue_requires_reuse" in {item.code for item in score(linked, create()).issues}


def test_answer_variant_must_be_fixed_and_complete() -> None:
    case = candidate_case()
    variant = case.expected_outputs[0].model_copy(update={"title": "耐久泄漏待核对"})
    revised = IssueGoldenCase.model_validate(
        {**case.model_dump(), "expected_outputs": (*case.expected_outputs, variant)}
    )
    assert score(revised, variant.model_dump(mode="json")).status == "passed"
    assert score(case, variant.model_dump(mode="json")).status == "failed"


def test_source_rejection_is_not_a_model_pass_and_supply_is_not_shortage() -> None:
    case = candidate_case(blocked=True)
    with pytest.raises(ValueError, match="not_model_evaluation"):
        score(case, create())
    original = source(kind="material_exception")
    original["source"]["current_assessment"]["basis"]["material"]["observed_on_hand_gap"] = "0"
    original = pin_source(original)
    rejected = IssueGoldenCase(
        case_id="not-shortage",
        source=original,
        source_document_digest=content_digest(original),
        expected_source_snapshot=None,
        expected_source_error="source_not_current",
    )
    assert rejected.expected_outputs == ()
    with pytest.raises(ValidationError):
        IssueGoldenCase.model_validate({**rejected.model_dump(), "expected_outputs": [create()]})


def test_original_source_event_snapshot_and_reader_digest_are_pinned() -> None:
    original = candidate_case().model_dump(mode="json")
    for field in ("source_document_digest",):
        with pytest.raises(ValidationError):
            IssueGoldenCase.model_validate({**original, field: "0" * 64})
    bad = deepcopy(original)
    bad["source"]["source"]["event"]["id"] += 1
    bad["source_document_digest"] = content_digest(bad["source"])
    with pytest.raises(ValidationError, match="event_mismatch"):
        IssueGoldenCase.model_validate(bad)
    bad = deepcopy(original)
    bad["source"]["source_digest"] = "0" * 64
    bad["source_document_digest"] = content_digest(bad["source"])
    with pytest.raises(ValidationError, match="reader_digest_mismatch"):
        IssueGoldenCase.model_validate(bad)
    bad = deepcopy(original)
    bad["expected_source_snapshot"]["event_row_id"] += 1
    with pytest.raises(ValidationError, match="snapshot_mismatch"):
        IssueGoldenCase.model_validate(bad)


def test_suite_loader_bounds_duplicates_and_mutation(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    loaded = loaded_suite(path)
    assert verify_issue_golden_suite(loaded) == loaded.suite
    with pytest.raises(ValueError, match="digest_mismatch"):
        load_issue_golden_suite(path, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="original_digest_mismatch"):
        verify_issue_golden_suite(replace(loaded, document=loaded.document + b" "))
    loaded.suite.cases[0].source["source_status"] = "changed"
    with pytest.raises(ValueError, match="modified_after_loading"):
        verify_issue_golden_suite(loaded)
    path.write_text('{"version":"first","version":"second"}')
    with pytest.raises(ValueError, match="duplicate_json_key"):
        load_issue_golden_suite(path, expected_sha256=sha256(path.read_bytes()).hexdigest())
    duplicate = candidate_document()
    duplicate["cases"].append(duplicate["cases"][0])
    with pytest.raises(ValidationError, match="duplicate_case_id"):
        IssueGoldenSuite.model_validate(duplicate)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="too_large"):
        load_issue_golden_suite(path, expected_sha256=sha256(path.read_bytes()).hexdigest())


def test_invalid_typed_response_and_conflicting_execution_claim_fail() -> None:
    case = candidate_case()
    result = score_issue_output(
        case,
        '{"disposition":"create_issue","disposition":"reuse_issue"}',
        execution_source="offline_replay",
        real_provider_call=False,
    )
    assert result.status == "failed" and result.issues[0].code == "typed_output_invalid"
    with pytest.raises(ValueError, match="execution_source_conflict"):
        score_issue_output(case, "{}", execution_source="offline_replay", real_provider_call=True)
