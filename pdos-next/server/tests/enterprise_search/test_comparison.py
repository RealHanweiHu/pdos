"""Alignment truth comes from code and exact source spans, not model summaries."""

from types import SimpleNamespace

import pytest

from pdos_next.agent_kernel.extract_read_ledger import LocatorEntry, SourceLocation
from pdos_next.enterprise_search.comparison import MAX_CHARS, align


def text(body):
    return {"body": body, "seal": None}


def sheet(rows, *, partial=False):
    body, entries, line = [], [], 1
    for number, row in enumerate(rows, 1):
        for column, value in enumerate(row, 1):
            if value is None:
                continue
            body.append(value)
            entries.append(
                LocatorEntry(
                    line,
                    line + value.count("\n"),
                    SourceLocation(
                        "cell",
                        sheet="规格",
                        row=number,
                        column=column,
                        cell=f"{chr(64 + column)}{number}",
                    ),
                    "formula" if value.startswith("=") else "text",
                )
            )
            line += value.count("\n") + 1
    return {
        "body": "\n".join(body),
        "seal": SimpleNamespace(
            locator_map=entries,
            parse_status="parsed",
            parse_code="PARTIAL_TEXT" if partial else None,
        ),
    }


def test_paragraph_changes_keep_both_exact_locations_and_unchanged_text_is_not_returned():
    old = text("共同标题\n\n压力 10 bar\n\n共同未变化正文标记")
    new = text("共同标题\n\n压力 12 bar\n\n共同未变化正文标记")
    result = align("left", old, "right", new)
    assert result["stats"]["changes"] == 1 and not result["partial"]
    assert "共同未变化正文标记" not in str(result)
    for key, source in (("old", old), ("new", new)):
        row = result["changes"][0][key]
        assert (
            source["body"][row["locator"]["char_start"] : row["locator"]["char_end"]]
            == row["quote"]
        )


def test_unrelated_replacements_are_unaligned_and_limits_are_never_no_change():
    result = align("left", text("AAAA\n"), "right", text("ZZZZ\n"))
    assert result["partial"] and result["stats"]["unaligned_changes"] == 2
    limited = align("left", text("x" * (MAX_CHARS + 1)), "right", text("x"))
    assert limited["partial"] and limited["unmatched"][0]["reason"] == "comparison_size_limit"


def test_markdown_rows_and_empty_line_changes_keep_literal_spans():
    old = text("| 项目 | 值 |\n| --- | --- |\n| 压力 | 10 |\n")
    new = text("| 项目 | 值 |\n| --- | --- |\n| 压力 | 12 |\n")
    result = align("left", old, "right", new)
    assert result["stats"]["changes"] == 1
    assert result["changes"][0]["old"]["locator"]["line_start"] == 3
    assert align("left", old, "right", old)["stats"]["changes"] == 0
    assert align("left", text("a\n"), "right", text("a\n\n"))["stats"]["changes"] > 0


def test_xlsx_aligns_reordered_columns_and_rows_by_the_original_key_header():
    old = sheet([["参数", "值"], ["压力", "10"], ["温度", "20"]])
    new = sheet([["值", "参数"], ["20", "温度"], ["12", "压力"]])
    result = align("left", old, "right", new)
    assert result["stats"]["changes"] == 1 and not result["partial"], result
    row = result["changes"][0]
    assert row["old"]["quote"] == "10" and row["new"]["quote"] == "12"
    assert row["old"]["locator"]["native"] == ['cell:["规格","B2"]']
    assert row["new"]["locator"]["native"] == ['cell:["规格","A3"]']
    assert {basis["key_header"] for basis in result["alignment_basis"]} == {"参数"}


def test_ambiguous_headers_or_keys_are_not_invented_as_additions_or_removals():
    old = sheet([["参数", "值"], ["压力", "10"]])
    for new in [
        sheet([["参数", "参数"], ["压力", "12"]]),
        sheet([["参数", "值"], ["压力", "12"], ["压力", "15"]]),
        sheet([["别的主键", "值"], ["压力", "12"]]),
    ]:
        result = align("left", old, "right", new)
        assert result["partial"] and result["unmatched"] and not result["changes"]


def test_formulas_are_literal_not_calculated_and_parse_gaps_stay_explicit():
    old = sheet([["参数", "值"], ["合计", "=A1+A2"]])
    new = sheet([["参数", "值"], ["合计", "=SUM(A1:A2)"]], partial=True)
    result = align("left", old, "right", new)
    assert result["changes"][0]["new"]["value_kind"] == "formula"
    assert result["changes"][0]["new"]["quote"] == "=SUM(A1:A2)"
    assert result["partial"] and result["unmatched"][0]["reason"] == "incomplete_parse"


def test_comparison_child_has_one_read_surface_and_no_search_or_write_authority():
    from uuid import uuid4

    from pdos_next.agent_kernel.tools import default_registry
    from pdos_next.agent_kernel.types import RunScope
    from pdos_next.errors import DomainError

    registry = default_registry()
    assert {row["name"] for row in registry.definitions("assistant_compare")} == {
        "assistant.comparison.read", "result.read",
    }
    assert "assistant.comparison.read" not in {row["name"] for row in registry.definitions()}
    scope = RunScope(*(uuid4() for _ in range(6))).child("assistant_compare")
    for name in (
        "assistant.search",
        "assistant.materials.read",
        "skill.load",
        "verification.request.create",
    ):
        with pytest.raises(DomainError):
            registry.authorize(scope, name, {}, {}, lambda *_args: True)
