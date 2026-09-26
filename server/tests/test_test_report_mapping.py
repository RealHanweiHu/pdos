"""Verdict policy is enforced independently of model-proposed column mappings."""

from __future__ import annotations

import pytest

from app.domain.test_report_import import ExcelImportMapping, _apply_mapping
from app.domain.test_report_workbook import parse_workbook
from tests.test_test_report_workbook import form_report


@pytest.mark.parametrize("verdict", ["参考", "不适用", "N/A", "未测试", ""])
def test_mapping_cannot_promote_non_decisive_verdict(verdict: str) -> None:
    mapping = ExcelImportMapping(
        case_title_column="case",
        result_column="result",
        pass_values=[verdict],
        confidence=1,
    )
    items, skipped = _apply_mapping(mapping, [{"case": "pressure", "result": verdict}])
    assert items == []
    assert skipped[0]["reason"] == "non_decisive_result"


def test_conflicting_mapping_cannot_choose_pass_over_fail() -> None:
    mapping = ExcelImportMapping(
        case_title_column="case",
        result_column="result",
        pass_values=["OK"],
        fail_values=["OK"],
        confidence=1,
    )
    items, skipped = _apply_mapping(mapping, [{"case": "pressure", "result": "OK"}])
    assert items == []
    assert skipped[0]["reason"] == "ambiguous_result_mapping"


@pytest.mark.parametrize(
    "missing,reason",
    [
        ("reported_date", "missing_test_date"),
        ("has_observations", "missing_observations"),
    ],
)
def test_form_cannot_pass_without_date_or_observations(missing: str, reason: str) -> None:
    report = parse_workbook(form_report())
    report.rows[0].source[missing] = None
    mapping = ExcelImportMapping(
        case_title_column="用例名称",
        result_column="测试结果",
        pass_values=["合格"],
        confidence=1,
    )
    items, skipped = _apply_mapping(mapping, [row.values for row in report.rows], report=report)
    if missing == "reported_date":
        # Missing time now remains a draft fact for explicit human amendment;
        # confirmation is blocked until a real execution date is supplied.
        assert len(items) == 1
        assert items[0]["source"]["reported_date"] is None
        assert items[0]["source"]["sheet"] == "气压精度 "
        assert not any(row["reason"] == reason for row in skipped)
        return
    assert items == []
    assert skipped[0]["reason"] == reason
    source = skipped[0]["source"]
    assert isinstance(source, dict) and source["sheet"] == "气压精度 "
