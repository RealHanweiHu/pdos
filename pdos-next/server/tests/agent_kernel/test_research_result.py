from copy import deepcopy

import pytest

from pdos_next.agent_kernel.research_result import attach
from pdos_next.errors import DomainError
from pdos_next.research.egress import compact, overlaps


def tool():
    return {
        "tool": "research.fanout",
        "tier": "READ",
        "value": {
            "job_id": "actual-job",
            "status": "partial",
            "ledger": [{"row_id": "actual-row"}],
            "snapshots": [{"id": "actual-source"}],
            "coverage": [{"accepted_rows": 1}],
            "failures": [{"reason": "read_timeout", "message": "Source timed out"}],
            "snapshot_digests": {"internal": "proof-not-for-display"},
        },
    }


def test_report_replaces_model_claims_with_deduplicated_actual_job_coverage_and_failures():
    output = {"result": {"research": {"source_count": 999}, "answer": "kept"}}
    original = deepcopy(output)
    result = attach(output, [tool(), tool()])
    assert result["result"]["answer"] == "kept" and output == original
    report = result["result"]["research"]
    assert report["source_count"] == report["row_count"] == len(report["jobs"]) == 1
    assert report["jobs"][0]["failures"][0]["reason"] == "read_timeout"
    assert "snapshot_digests" not in report["jobs"][0]


def test_no_research_cannot_keep_invented_evidence_and_actual_error_remains_visible():
    assert attach({"result": {"research": {"source_count": 7}}}, []) == {"result": {}}
    result = attach(
        {"result": {}},
        [
            {
                "tool": "research.fanout",
                "tier": "READ",
                "value": {
                    "error": {"code": "SOURCE_UNAVAILABLE", "message": "实际读取服务不可用"},
                },
            }
        ],
    )
    assert result["result"]["research"]["source_count"] == 0
    assert result["result"]["research"]["jobs"][0]["failures"][0]["message"] == "实际读取服务不可用"


def test_one_job_cannot_publish_two_different_ledgers():
    other = deepcopy(tool())
    other["value"]["status"] = "completed"
    with pytest.raises(DomainError):
        attach({"result": {}}, [tool(), other])


def test_partial_research_does_not_leave_a_fully_completed_run_label():
    result = attach({"status": "completed", "result": {}, "unfinished": []}, [tool()])
    assert result["status"] == "partial" and len(result["unfinished"]) == 1
    complete = tool()
    complete["value"]["status"] = "completed"
    assert attach({"status": "partial", "result": {}}, [complete])["status"] == "partial"


@pytest.mark.parametrize(
    "query,source,expected",
    [
        ("public pump catalogue", "confidential prototype architecture", False),
        (
            "请查询专用密封腔压缩率指标，不附客户名",
            "原文：专用密封腔压缩率指标，仅限当前客户。",
            True,
        ),
        (
            "prefix confidentialprototype suffix",
            "private confidential prototype specification",
            True,
        ),
        ("https://public.example/%EF%BC%A1%EF%BC%A3%EF%BC%AD%EF%BC%A5", "ACME", True),
        ("external pump performance", "密封验收", False),
    ],
)
def test_actual_text_normalization_and_private_fragment_matching(query, source, expected):
    assert overlaps(compact(query), source) is expected
