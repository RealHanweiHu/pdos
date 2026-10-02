"""Pure proposal/source-binding checks; no database or provider calls."""

import json
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.ai import issue_event_proposal as p

TENANT, PROJECT, CASE, ISSUE, RUN = (str(UUID(int=i)) for i in range(1, 6))


def source(*, kind: str = "test_failure", existing: bool = False) -> dict[str, Any]:
    event = dict(
        id=17,
        event_id="test:original",
        event_type="TEST_FAILED",
        entity_id=CASE,
        tenant_id=TENANT,
        project_id=PROJECT,
        timestamp="2026-09-27T00:00:00+00:00",
    )
    raw: dict[str, Any] = dict(
        version="ai-issue-event-source-v1",
        event=event,
        source_key=f"test_case:{CASE}",
        audit={"actor_user_id": "MUST_NOT_SEND_AUDIT", "context": {"private": "AUDIT_SECRET"}},
        human={"auth_version": 9, "username": "PRIVATE_USERNAME", "id": "PRIVATE_ACTOR"},
        origin_kind="legacy_test_case",
        current_case=dict(
            id=CASE,
            status="failed",
            title="泵耐久测试",
            acceptance_criteria="运行 100 小时无泄漏",
            method="额定压力连续运行",
            result_notes="当前失败",
            related_issue_id=ISSUE if existing else None,
        ),
        original_result=dict(
            status="failed", result_notes="运行 80 小时后出现泄漏；尚未确认根因。"
        ),
    )
    if kind == "material_exception":
        event.update(event_id="npi:material_exception:original", event_type="NPI_RECORD_CHANGED")
        material = dict(
            material_reference="PUMP-01", unit="件", required="5", observed_on_hand_gap="2"
        )
        raw = dict(
            event=event,
            source_key=f"material_exception:{CASE}",
            original_review=dict(
                disposition="follow_up",
                basis_digest="b" * 64,
                reason="需补齐泵组件",
                snapshot={"basis": {"material": material}},
            ),
            current_assessment=dict(digest="b" * 64, basis={"material": deepcopy(material)}),
            human={"auth_version": 9},
            audit={"private": "AUDIT_SECRET"},
        )
    return dict(
        event_row_id=event["id"],
        event_id=event["event_id"],
        event_type=event["event_type"],
        event_at=event["timestamp"],
        source_kind=kind,
        source_status="current",
        source_digest="a" * 64,
        source=raw,
        existing_issue=dict(
            id=ISSUE,
            title="原问题",
            status="open",
            snapshot=dict(
                id=ISSUE,
                title="原泄漏问题",
                description="继续原质量处理",
                status="open",
                reported_by_user_id="PRIVATE_REPORTER",
                auth_version=10,
            ),
        )
        if existing
        else None,
    )


def create(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            disposition="create_issue",
            title="泵耐久测试泄漏",
            description="运行 80 小时出现泄漏，根因尚未确认。",
            severity="high",
            citations=[
                dict(
                    reference_id="test.original.result_notes", exact_quote="运行 80 小时后出现泄漏"
                )
            ],
        )
        | changes
    )


def reuse(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            disposition="reuse_issue",
            existing_issue_id=ISSUE,
            citations=[dict(reference_id="issue.current.title", exact_quote="原泄漏问题")],
        )
        | changes
    )


def insufficient(**changes: Any) -> dict[str, Any]:
    return (
        dict(disposition="insufficient_evidence", open_questions=["请补充泄漏位置与实测记录"])
        | changes
    )


def test_named_prompt_and_contract_are_loadable() -> None:
    assert (p.KEY, p.PURPOSE, p.OPERATION) == (
        "quality_intelligence.event_issue",
        "event_issue",
        "event.issue.create",
    )
    assert p.PROMPT.version == "issue-event-v1"
    assert p.PROMPT.agent_key.value == "quality_intelligence"
    schema = p.IssueEventProposal.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Citation"]["additionalProperties"] is False


@pytest.mark.parametrize("field", ["title", "description", "severity"])
def test_create_requires_all_fields(field: str) -> None:
    body = create()
    del body[field]
    with pytest.raises(ValidationError):
        p.IssueEventProposal.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", " "),
        ("description", "\n"),
        ("severity", "major"),
        ("owner_user_id", ISSUE),
        ("status", "closed"),
        ("origin", "ai"),
        ("write_permission", True),
        ("existing_issue_id", ISSUE),
        ("citations", []),
        ("open_questions", ["不能混入另一处置"]),
    ],
)
def test_create_rejects_wrong_or_unapproved_fields(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        p.IssueEventProposal.model_validate(create(**{field: value}))


@pytest.mark.parametrize("disposition", ["reuse_issue", "insufficient_evidence"])
@pytest.mark.parametrize(
    "field,value", [("title", "新题目"), ("description", "新正文"), ("severity", "low")]
)
def test_other_dispositions_cannot_write_content(disposition: str, field: str, value: Any) -> None:
    body = reuse() if disposition == "reuse_issue" else insufficient()
    with pytest.raises(ValidationError):
        p.IssueEventProposal.model_validate(body | {field: value})


@pytest.mark.parametrize(
    "body",
    [
        insufficient(open_questions=[]),
        insufficient(open_questions=["  "]),
        insufficient(existing_issue_id=ISSUE),
        reuse(existing_issue_id=None),
        reuse(citations=[]),
        reuse(open_questions=["不确定"]),
    ],
)
def test_reuse_and_insufficient_shapes(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        p.IssueEventProposal.model_validate(body)


def test_valid_current_failure_proposal_round_trips_without_mutating_source() -> None:
    original = source()
    before = deepcopy(original)
    result = p.validate_proposal(original, create())
    assert result.disposition == "create_issue"
    assert original == before
    assert p.validate_proposal(original, result) == result
    assert p.IssueEventProposal.model_validate_json(result.model_dump_json()) == result


def test_exact_quote_preserves_whitespace_and_negation() -> None:
    original = source()
    original["source"]["original_result"]["result_notes"] = (
        "  尚未确认根因。\n不能判定为供应商责任。"
    )
    body = create(
        citations=[
            dict(reference_id="test.original.result_notes", exact_quote="  尚未确认根因。\n")
        ]
    )
    assert p.validate_proposal(original, body).citations[0].exact_quote == "  尚未确认根因。\n"
    with pytest.raises(p.IssueEventProposalError, match="逐字"):
        p.validate_proposal(
            original,
            create(
                citations=[
                    dict(
                        reference_id="test.original.result_notes", exact_quote="已确认根因为供应商"
                    )
                ]
            ),
        )


@pytest.mark.parametrize("status", ["changed", "unavailable", None])
@pytest.mark.parametrize("body", [create(), insufficient()])
def test_all_proposals_require_current_source(status: str | None, body: dict[str, Any]) -> None:
    value = source() | {"source_status": status}
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(value, body)
    assert caught.value.code == "source_not_current"


@pytest.mark.parametrize("status", ["passed", "planned", "blocked", "waived"])
def test_current_flag_does_not_override_actual_test_result(status: str) -> None:
    value = source()
    value["source"]["current_case"]["status"] = status
    with pytest.raises(p.IssueEventProposalError):
        p.model_context(value)


@pytest.mark.parametrize("body", [create(), insufficient(), reuse(existing_issue_id=RUN)])
def test_existing_issue_only_reuses_exact_actual_issue(body: dict[str, Any]) -> None:
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(source(existing=True), body)
    assert caught.value.code == "existing_issue_requires_reuse"


def test_no_issue_cannot_claim_reuse() -> None:
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(source(), reuse())
    assert caught.value.code == "existing_issue_missing"


def test_existing_closed_issue_reuses_without_claiming_reopen() -> None:
    value = source(existing=True)
    value["existing_issue"]["snapshot"]["status"] = "closed"
    assert p.validate_proposal(value, reuse()).disposition == "reuse_issue"
    assert p.model_context(value)["current_state"]["issue_status"] == "closed"


def test_withdrawn_issue_cannot_be_reused() -> None:
    value = source(existing=True)
    value["existing_issue"]["snapshot"]["withdrawn_at"] = "2026-09-27T01:00:00Z"
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(value, reuse())
    assert caught.value.code == "existing_issue_withdrawn"


@pytest.mark.parametrize(
    "reference,quote",
    [
        ("source.event.event_id", "test:original"),
        ("source_digest", "a"),
        ("audit", "AUDIT_SECRET"),
        ("human.auth_version", "9"),
        ("test.original.result_notes", "发生爆炸"),
        ("test.original.result_notes", "；"),
    ],
)
def test_metadata_fabrications_and_punctuation_are_not_citations(
    reference: str, quote: str
) -> None:
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(
            source(), create(citations=[dict(reference_id=reference, exact_quote=quote)])
        )
    assert caught.value.code == "citation_invalid"


@pytest.mark.parametrize(
    "reference,quote",
    [
        ("test.case.title", "泵耐久测试"),
        ("test.case.acceptance_criteria", "100 小时"),
        ("test.original.failure", "失败"),
    ],
)
def test_create_needs_original_failure_evidence_not_only_labels(reference: str, quote: str) -> None:
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(
            source(), create(citations=[dict(reference_id=reference, exact_quote=quote)])
        )
    assert caught.value.code == "failure_evidence_required"


def test_full_original_failed_fact_supports_failure_without_fabricated_notes() -> None:
    value = source()
    value["source"]["original_result"]["result_notes"] = None
    body = create(
        citations=[dict(reference_id="test.original.failure", exact_quote="原登记测试结果：失败")]
    )
    assert p.validate_proposal(value, body).disposition == "create_issue"


def test_model_context_excludes_audit_authority_and_arbitrary_nested_fields() -> None:
    value = source(existing=True)
    value["source"]["original_result"]["metrics"] = [
        dict(
            name="温度",
            value="90",
            unit="℃",
            target="80",
            verdict="fail",
            auth_version="METRIC_SECRET",
            extra={"log": "NESTED_SECRET"},
        )
    ]
    context = p.model_context(value)
    encoded = json.dumps(context, ensure_ascii=False)
    for forbidden in ("AUDIT_SECRET", "PRIVATE_", "auth_version", "METRIC_SECRET", "NESTED_SECRET"):
        assert forbidden not in encoded
    assert context["existing_issue_id"] == ISSUE
    assert "指标：温度；实测：90；单位：℃；目标：80；原判定：fail" in encoded


def test_snapshots_bind_scope_event_and_reader_digest_without_raw_audit() -> None:
    value = source()
    result = p.source_snapshot(value)
    assert result["tenant_id"] == TENANT
    assert result["project_id"] == PROJECT
    assert result["event_row_id"] == 17
    assert result["source_digest"] == "a" * 64
    assert result["context"] == p.model_context(value)
    assert p.source_snapshot(deepcopy(value)) == result
    assert "AUDIT_SECRET" not in json.dumps(result)
    changed = deepcopy(value)
    changed["source_digest"] = "b" * 64
    assert p.source_snapshot(changed)["source_digest"] != result["source_digest"]


@pytest.mark.parametrize(
    "field,value", [("event_row_id", 99), ("event_id", "other"), ("source_digest", "bad")]
)
def test_snapshot_rejects_broken_event_pin(field: str, value: Any) -> None:
    with pytest.raises(p.IssueEventProposalError):
        p.source_snapshot(source() | {field: value})


def test_reference_size_overflow_is_rejected_not_truncated() -> None:
    value = source()
    value["source"]["original_result"]["result_notes"] = "证" * (p.MAX_REFERENCE_CHARS + 1)
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.model_context(value)
    assert caught.value.code == "context_too_large"


def test_total_utf8_size_overflow_is_rejected() -> None:
    value = source()
    value["source"]["current_case"]["acceptance_criteria"] = "据" * 15_000
    value["source"]["original_result"]["result_notes"] = "证" * 15_000
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.model_context(value)
    assert caught.value.code == "context_too_large"


def test_metric_capacity_does_not_silently_drop_rows() -> None:
    value = source()
    value["source"]["original_result"]["metrics"] = [dict(name="实测", value="2")] * 101
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.model_context(value)
    assert caught.value.code == "context_too_large"


def test_material_requires_complete_original_positive_gap_citation() -> None:
    value = source(kind="material_exception")
    references = p.model_context(value)["references"]
    shortage = references[0]
    assert shortage["reference_id"] == "material.original.shortage"
    assert (
        p.validate_proposal(
            value,
            create(
                citations=[
                    dict(reference_id=shortage["reference_id"], exact_quote=shortage["excerpt"])
                ]
            ),
        ).disposition
        == "create_issue"
    )
    with pytest.raises(p.IssueEventProposalError) as caught:
        p.validate_proposal(
            value,
            create(citations=[dict(reference_id=shortage["reference_id"], exact_quote="PUMP-01")]),
        )
    assert caught.value.code == "failure_evidence_required"


@pytest.mark.parametrize("gap", [None, "0", "-1", "NaN", "Infinity"])
def test_unknown_or_nonpositive_material_gap_is_not_evidence(gap: str | None) -> None:
    value = source(kind="material_exception")
    value["source"]["original_review"]["snapshot"]["basis"]["material"]["observed_on_hand_gap"] = (
        gap
    )
    with pytest.raises(p.IssueEventProposalError):
        p.model_context(value)


def test_current_material_must_match_original_confirmed_gap() -> None:
    value = source(kind="material_exception")
    value["source"]["current_assessment"]["basis"]["material"]["observed_on_hand_gap"] = "1"
    with pytest.raises(p.IssueEventProposalError):
        p.model_context(value)


def test_insufficient_is_a_question_not_an_execution_or_issue() -> None:
    result = p.validate_proposal(source(), insufficient())
    assert result.title is None
    assert result.existing_issue_id is None
    assert result.open_questions == ("请补充泄漏位置与实测记录",)
