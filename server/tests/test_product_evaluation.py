"""Synthetic evaluator controls, not product golden cases or model qualification."""

import json
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.ai import product_matrix_preparation as matrix
from app.ai.product_evaluation import (
    MAX_OUTPUT_BYTES,
    Capability,
    LoadedProductSuite,
    OfflineProductReplay,
    ProductEvaluationBinding,
    ProductEvaluationRequest,
    ProductEvaluationResponse,
    canonical,
    digest,
    load_product_suite,
    run_product_evaluation,
    runtime_contract,
)
from app.ai.product_work_preparation import PROJECTION_VERSION
from app.ai.provider_adapters import ProviderRequestError, ProviderUsage
from app.contracts.product_work_ai import REQUIRED_SECTIONS
from app.domain.product_workspace import digest as source_digest

TENANT = str(UUID(int=1))
SPACE = str(UUID(int=2))
LINE = str(UUID(int=3))
BINDING = ProductEvaluationBinding(
    provider="synthetic",
    model="fixed-fixture",
    protocol="offline_replay",
    configuration_sha256="a" * 64,
)


def fixture(capability: Capability) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt, _, runtime = runtime_contract(capability)
    if capability == "product_matrix":
        record_id = str(UUID(int=4))
        products = [str(UUID(int=5)), str(UUID(int=6))]
        refs = []

        def ref_statement(ref_id: str, label: str) -> dict[str, Any]:
            fields = {"label": label}
            refs.append(
                {
                    "reference_id": ref_id,
                    "label": label,
                    "digest": source_digest(fields),
                    "fields": fields,
                    "omitted_fields": [],
                }
            )
            return {
                "nature": "hypothesis",
                "text": label,
                "citations": [
                    {
                        "reference_id": ref_id,
                        "digest": source_digest(fields),
                        "field_path": ["label"],
                        "quoted_value": label,
                    }
                ],
            }

        positions = [
            {
                "product_id": identity,
                "positioning": ref_statement(
                    f"matrix:{record_id}:product:{identity}", f"合成产品{index}"
                ),
                "missing": ["真实证据缺失"],
            }
            for index, identity in enumerate(products)
        ]
        for position in positions:
            position["coverage"] = deepcopy(position["positioning"])
        criterion = ref_statement(
            f"matrix:{record_id}:criterion:{source_digest('pressure')[:24]}", "合成判据"
        )
        source = {
            "projection_version": matrix.PROJECTION,
            "selection": {"record_id": record_id, "roadmap_ids": []},
            "product_ids": products,
            "criterion_keys": ["pressure"],
            "model_context": {
                "question": "核对合成矩阵",
                "coverage_limits": [],
                "omitted_references": [],
                "references": refs,
            },
        }
        output = {
            "disposition": "insufficient_evidence",
            "summary": [],
            "products": positions,
            "criteria": [
                {"criterion_key": "pressure", "explanation": criterion, "human_next_steps": []}
            ],
            "positioning_hypotheses": [],
            "platform_reuse_hypotheses": [],
            "missing": ["真实资料缺失"],
            "coverage_limits": "合成样例，不代表资格",
        }
    else:
        refs = [
            {
                "reference_id": f"space:{SPACE}",
                "label": "合成空间",
                "digest": source_digest({"title": "合成空间"}),
                "fields": {"title": "合成空间"},
            }
        ]
        source = {
            "projection_version": PROJECTION_VERSION,
            "market_space_id": SPACE,
            "actor_id": TENANT,
            "selection": {
                "capability": capability,
                "question": "核对合成资料",
                "product_line_id": LINE,
                "sources": [{"kind": "file", "id": SPACE, "ordinals": [1]}]
                if capability == "rfq_requirements"
                else [],
            },
            "references": refs,
            "warnings": [],
            "coverage_limits": ["仅合成测试"],
        }
        output = {
            "capability": capability,
            "disposition": "insufficient_evidence",
            "summary": [],
            "sections": [
                {"key": key, "statements": [], "missing": ["真实资料缺失"]}
                for key in REQUIRED_SECTIONS[capability]
            ],
            "next_steps": [],
            "missing": ["真实资料缺失"],
            "coverage_limits": "合成样例，不代表资格",
        }
    source["digest"] = source_digest(source)
    suite = {
        "version": "product-capability-evaluation.v1",
        "suite_version": "synthetic-tests",
        "review_status": "candidate",
        "capability": capability,
        "prompt_version": prompt.version,
        "runtime_sha256": digest(runtime),
        "cases": [
            {
                "case_id": "case-1",
                "slices": ["missing_evidence", "synthetic"],
                "tenant_id": TENANT,
                "source": source,
                "source_sha256": digest(source),
                "expected_outputs": [output],
            }
        ],
    }
    return suite, output


def loaded(suite: dict[str, Any]) -> LoadedProductSuite:
    document = canonical(suite).encode()
    return LoadedProductSuite(document, sha256(document).hexdigest())


@pytest.mark.parametrize("capability", [*REQUIRED_SECTIONS, "product_matrix"])
def test_each_product_contract_has_an_independent_non_qualifying_report(
    capability: Capability,
) -> None:
    suite, output = fixture(capability)
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": [canonical(output)]}),
    )
    assert report["status"] == "passed" and report["capability"] == capability
    assert report["slices"]["missing_evidence"] == {"cases": 1, "passed": 1}
    for key in (
        "qualification_granted",
        "reference_answers_approved",
        "source_authorization_verified",
        "provider_calls_verified",
    ):
        assert report[key] is False
    assert report["report_sha256"] == digest(
        {k: v for k, v in report.items() if k != "report_sha256"}
    )


def test_executor_never_receives_reference_answers_and_only_format_failures_retry() -> None:
    suite, output = fixture("research_planning")
    calls = []

    def executor(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        calls.append(request)
        assert "expected_outputs" not in request.model_dump_json()
        assert "合成样例，不代表资格" not in request.model_dump_json()
        return ProductEvaluationResponse(
            content="not json" if request.attempt == 1 else canonical(output),
            input_tokens=7,
            output_tokens=3,
        )

    report = run_product_evaluation(loaded(suite), binding=BINDING, executor=executor)
    assert report["status"] == "passed" and len(calls) == 2
    assert calls[0].messages[0] == calls[1].messages[0]
    assert calls[0].output_schema_json == calls[1].output_schema_json
    assert report["usage"] == {"input_tokens": 14, "output_tokens": 6}
    wrong = {**output, "coverage_limits": "同样可解析，但不是固定参考答案"}
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": [canonical(wrong), canonical(output)]}),
    )
    assert report["status"] == "failed" and len(report["cases"][0]["attempts"]) == 1
    assert report["cases"][0]["attempts"][0]["error_code"] == "reference_answer_mismatch"


@pytest.mark.parametrize("capability", list(REQUIRED_SECTIONS))
def test_wire_context_preserves_source_fields_scope_and_instructions(
    capability: Capability,
) -> None:
    suite, output = fixture(capability)
    case = suite["cases"][0]
    source = case["source"]
    fields = {
        "content": "仅合成材料：压力110kPa；停止研究不代表结论成立。",
        "captured_at": "2026-09-29T00:00:00Z",
        "content_digest": "b" * 64,
    }
    evidence = {
        "reference_id": f"evidence:{UUID(int=8)}",
        "label": "合成证据",
        "digest": source_digest(fields),
        "fields": fields,
        "private_extra": "must-not-leave",
    }
    source["references"].append(evidence)
    if capability == "rfq_requirements":
        file_fields = {"ordinal": 1, "text": "合成RFQ要求：110kPa，25℃±5℃"}
        source["references"].append(
            {
                "reference_id": f"file:{SPACE}:1",
                "label": "合成RFQ原文",
                "fields": file_fields,
                "digest": source_digest(file_fields),
            }
        )
    source["warnings"] = ["同口径资料不足"]
    source["private_extra"] = "must-not-leave"
    source["digest"] = source_digest({k: v for k, v in source.items() if k != "digest"})
    case["source_sha256"] = digest(source)
    case["user_instruction"] = "保留失败实验"

    def executor(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        wire = json.loads(request.messages[-1].content.split("PDOS_CONTEXT_JSON\n", 1)[1])
        assert wire == json.loads(request.context_json)
        assert "must-not-leave" not in canonical(wire)
        details = json.loads(wire["question"].split("\n本次分析范围与要求：", 1)[1])
        assert details["capability"] == capability
        assert details["required_sections"] == list(REQUIRED_SECTIONS[capability])
        assert details["warnings"] == source["warnings"]
        assert details["coverage_limits"] == source["coverage_limits"]
        assert details["user_instruction"] == "保留失败实验"
        ref = next(r for r in wire["references"] if r["reference_id"] == evidence["reference_id"])
        assert json.loads(ref["excerpt"]) == {"fields": fields, "digest": evidence["digest"]}
        if capability == "rfq_requirements":
            file_ref = next(r for r in wire["references"] if r["reference_id"] == f"file:{SPACE}:1")
            assert json.loads(file_ref["excerpt"])["fields"] == file_fields
        if capability not in ("research_planning", "rfq_requirements"):
            bound = details["evidence_references"][0]["reference"]
            assert bound["tenant_id"] == TENANT
            assert bound["ref_id"] == str(UUID(int=8))
            assert bound["digest"] == fields["content_digest"]
        return ProductEvaluationResponse(content=canonical(output))

    report = run_product_evaluation(loaded(suite), binding=BINDING, executor=executor)
    assert report["status"] == "passed", report["cases"]
    assert report["cases"][0]["removed_context_paths"] == []
    assert report["runtime_snapshot"]["compiled"]["reader"] == "product-work-source-adapter.v2"


def test_valid_citation_does_not_make_an_invented_claim_pass() -> None:
    suite, output = fixture("competitor_analysis")
    ref = suite["cases"][0]["source"]["references"][0]
    output["summary"] = [
        {
            "nature": "hypothesis",
            "text": "合成产品性能有待确认",
            "citations": [
                {
                    "reference_id": ref["reference_id"],
                    "digest": ref["digest"],
                    "field_path": ["title"],
                    "quoted_value": "合成空间",
                }
            ],
        }
    ]
    suite["cases"][0]["expected_outputs"] = [deepcopy(output)]
    output["summary"][0]["text"] = "合成产品确定优于所有竞争型号"
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": [canonical(output)]}),
    )
    assert report["cases"][0]["attempts"][0]["status"] == "answer_mismatch"


def test_forged_citation_is_a_terminal_binding_failure_not_a_format_retry() -> None:
    suite, output = fixture("research_planning")
    forged = deepcopy(output)
    forged["summary"] = [
        {
            "nature": "hypothesis",
            "text": "伪造引用",
            "citations": [
                {
                    "reference_id": "absent",
                    "digest": "a" * 64,
                    "field_path": ["title"],
                    "quoted_value": "不存在",
                }
            ],
        }
    ]
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": [canonical(forged), canonical(output)]}),
    )
    attempts = report["cases"][0]["attempts"]
    assert len(attempts) == 1 and attempts[0]["status"] == "source_binding_failed"
    assert report["status"] == "failed"


@pytest.mark.parametrize("change", ["source", "runtime", "capability", "bad_expected_citation"])
def test_all_cases_are_validated_before_any_executor_call(change: str) -> None:
    suite, _ = fixture("research_planning")
    second = deepcopy(suite["cases"][0])
    second["case_id"] = "case-2"
    suite["cases"].append(second)
    if change == "source":
        second["source"]["warnings"].append("被改写")
    elif change == "runtime":
        suite["runtime_sha256"] = "0" * 64
    elif change == "capability":
        suite["capability"] = "market_analysis"
    else:
        second["expected_outputs"][0]["summary"] = [
            {
                "nature": "hypothesis",
                "text": "伪造引用",
                "citations": [
                    {
                        "reference_id": "missing",
                        "digest": "a" * 64,
                        "field_path": ["title"],
                        "quoted_value": "不存在",
                    }
                ],
            }
        ]
    calls = []

    def executor(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        calls.append(request)
        return ProductEvaluationResponse(content="{}")

    with pytest.raises(ValueError):
        run_product_evaluation(loaded(suite), binding=BINDING, executor=executor)
    assert calls == []


def test_later_case_message_limit_is_checked_before_any_executor_call() -> None:
    suite, _ = fixture("research_planning")
    second = deepcopy(suite["cases"][0])
    second["case_id"] = "case-2"
    source = second["source"]
    source["coverage_limits"] = ["x" * 210_000]
    source["digest"] = source_digest({k: v for k, v in source.items() if k != "digest"})
    second["source_sha256"] = digest(source)
    suite["cases"].append(second)
    calls = []

    def executor(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        calls.append(request)
        return ProductEvaluationResponse(content="{}")

    with pytest.raises(ValueError, match="200000"):
        run_product_evaluation(loaded(suite), binding=BINDING, executor=executor)
    assert calls == []


def test_call_failure_retains_cost_without_exception_text_or_false_provider_verification() -> None:
    suite, output = fixture("research_planning")
    second = deepcopy(suite["cases"][0])
    second["case_id"] = "case-2"
    suite["cases"].append(second)

    def executor(request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        if request.case_id == "case-1":
            raise ProviderRequestError(
                "timeout",
                "private-provider-secret",
                usage=ProviderUsage(input_tokens=4, output_tokens=1),
            )
        return ProductEvaluationResponse(
            content=canonical(output),
            execution_source="provider_claim",
            original_receipt_ref="claimed-call",
            reported_model="model-a",
        )

    report = run_product_evaluation(loaded(suite), binding=BINDING, executor=executor)
    assert report["status"] == "failed" and report["cases"][1]["passed"]
    assert report["usage"] == {"input_tokens": 4, "output_tokens": 1}
    assert "private-provider-secret" not in canonical(report)
    assert not report["provider_calls_verified"] and not report["qualification_granted"]


def test_output_budget_and_duplicate_json_fail_closed() -> None:
    suite, output = fixture("research_planning")
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": ["x" * (MAX_OUTPUT_BYTES + 1)]}),
    )
    attempt = report["cases"][0]["attempts"][0]
    assert attempt["error_code"] == "output_too_large" and attempt["response"]["content"] is None
    repeated = canonical(output)[:-1] + ',"capability":"research_planning"}'
    report = run_product_evaluation(
        loaded(suite),
        binding=BINDING,
        executor=OfflineProductReplay({"case-1": [repeated]}),
        max_structured_attempts=1,
    )
    assert report["status"] == "failed"


def test_pinned_file_and_cli_do_not_write_suite_or_publish(tmp_path: Path) -> None:
    suite, output = fixture("research_planning")
    path = tmp_path / "candidate.json"
    path.write_text(canonical(suite))
    original = path.read_bytes()
    pin = sha256(original).hexdigest()
    with pytest.raises(ValueError):
        load_product_suite(path, expected_sha256="0" * 64)
    responses = tmp_path / "replay.json"
    responses.write_text(canonical({"case-1": [canonical(output)]}))
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluate_product",
            "--suite",
            str(path),
            "--suite-sha256",
            pin,
            "--responses",
            str(responses),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["binding"]["protocol"] == "offline_replay" and not report["qualification_granted"]
    assert path.read_bytes() == original
