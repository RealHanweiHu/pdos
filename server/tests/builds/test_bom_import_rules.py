"""D98 BOM import conversion, version difference and rule card (no database).

The converter works on the parsed table the isolated parser already produced;
these tests build that table directly and check the deterministic rules.
"""

from uuid import uuid4

import pytest

from pdos_next.domain.builds.configurations import bom_import
from pdos_next.domain.builds.configurations.bom_diff import compare
from pdos_next.domain.builds.configurations.bom_import import (
    Cell,
    Table,
    _csv_table,
    _xlsx_table,
    convert,
    suggest_columns,
    suggest_header,
)
from pdos_next.domain.builds.configurations.bom_rules import rule_card

HEADER = ["料号", "名称", "用量", "单位", "位号", "ERP料号", "损耗率", "关键件", "供应商"]


def table(rows, header=HEADER, header_row=2):
    line = iter(range(1, 10_000))
    cells = {1: {1: Cell("BOM 清单 v3", next(line))}}
    cells[header_row] = {i: Cell(text, next(line)) for i, text in enumerate(header, start=1)}
    for offset, values in enumerate(rows, start=header_row + 1):
        cells[offset] = {
            i: Cell(str(v), next(line), "formula" if str(v).startswith("=") else "text")
            for i, v in enumerate(values, start=1)
            if v not in (None, "")
        }
    return Table("xlsx", ("BOM",), {"BOM": cells}, uuid4(), 1)


def basis(t, dispositions=(), columns=None):
    rows = t.cells["BOM"]
    header_row = suggest_header(rows)
    return {
        "artifact_id": str(t.artifact_id),
        "expected_revision": 1,
        "format": "xlsx",
        "sheet": "BOM",
        "header_row": header_row,
        "columns": columns or suggest_columns(rows[header_row]),
        "dispositions": list(dispositions),
    }


def part(number, erp=None, *, visible=True, visibility="private", name=None):
    return {
        "id": str(uuid4()),
        "revision": 1,
        "name": name or f"Part {number}",
        "internal_number": number,
        "erp_number": erp,
        "customer_number": None,
        "visibility": visibility,
        "visible": visible,
    }


def by_row(result):
    return {row["row"]: row for row in result["rows"]}


def test_header_and_columns_are_matched_by_fixed_synonyms_only():
    t = table([["RD-1", "Housing", "1", "pcs", "", "", "", "", "ACME"]])
    b = basis(t)
    assert b["header_row"] == 2
    fields = {c["field"]: c["column"] for c in b["columns"]}
    assert fields == {
        "internal_number": 1,
        "name": 2,
        "quantity": 3,
        "unit": 4,
        "reference_designators": 5,
        "erp_number": 6,
        "loss_rate": 7,
        "critical": 8,
    }
    result = convert(t, b)
    # The supplier column has no BOM field: it is listed, never guessed into notes.
    assert result["unmapped_columns"] == [{"column": 9, "header": "供应商"}]


def test_values_parse_deterministically_and_bad_rows_wait_for_a_disposition():
    t = table(
        [
            ["RD-1", "Resistor", "4", "pcs", "R1-R3, R7", "", "5%", "是"],
            ["RD-2", "Glue", "0.5", "g", "", "", "0.02", "否"],
            ["RD-3", "Screw", "-1", "pcs", "", "", "", ""],
            ["RD-4", "Label", "=B2*2", "pcs", "", "", "", ""],
            ["RD-5", "Cap", "2", "", "C1,C2", "", "", ""],
            [None, None, None, None, None, None, None, None, "ignored supplier"],
        ]
    )
    result = convert(t, basis(t))
    rows = by_row(result)
    first = next(line for line in result["lines"] if line["row"] == 3)
    assert first["reference_designators"] == ["R1", "R2", "R3", "R7"]
    assert first["loss_rate"] == "0.05" and first["critical"] is True
    assert first["part"]["internal_number"] == "RD-1" and first["key"] == "RD-1"
    assert next(line for line in result["lines"] if line["row"] == 4)["quantity"] == "0.5"
    assert [i["code"] for i in rows[5]["issues"]] == ["quantity_non_positive"]
    assert [i["code"] for i in rows[6]["issues"]] == ["formula"]
    assert [i["code"] for i in rows[7]["issues"]] == ["unit_missing"]
    assert all(rows[n]["status"] == "needs_disposition" for n in (5, 6, 7))
    assert all(rows[n]["allowed"] == ["skip"] for n in (5, 6, 7))
    # A row whose only content is in an unmapped column is not a BOM row.
    assert result["counts"] == {"ready": 2, "skipped": 0, "needs_disposition": 3, "ignored": 1}
    assert result["complete"] is False
    rules = {r["code"]: r for r in result["rules"]["rules"]}
    assert rules["quantity"]["status"] == "fail" and rules["missing_unit"]["status"] == "fail"

    skipped = convert(
        t,
        basis(t, [{"row": n, "action": "skip", "reason": "原件待改"} for n in (5, 6, 7)]),
    )
    assert skipped["complete"] is True and skipped["counts"]["skipped"] == 3
    assert [line["row"] for line in skipped["lines"]] == [3, 4]


def test_internal_number_reuses_visible_part_and_erp_number_is_only_a_hint():
    known = part("RD-1")
    erp_only = part("OTHER", erp="ERP-9")
    hidden = part("RD-7", visible=False)
    t = table(
        [
            ["RD-1", "Housing", "1", "pcs"],
            ["RD-2", "Screw", "4", "pcs", "", "ERP-9"],
            ["RD-7", "Secret", "1", "pcs"],
        ]
    )
    parts = [known, erp_only, hidden]
    result = convert(t, basis(t), parts=parts)
    rows = by_row(result)
    assert rows[3]["resolution"] == "matched_internal" and rows[3]["status"] == "ready"
    assert rows[4]["status"] == "needs_disposition"
    assert rows[4]["hints"] == [
        {"part_id": erp_only["id"], "revision": 1, "label": "OTHER / Part OTHER"}
    ]
    assert rows[4]["allowed"] == ["skip", "new_part", "reuse"]
    assert [i["code"] for i in rows[5]["issues"]] == ["identity_forbidden"]

    decided = convert(
        t,
        basis(
            t,
            [
                {
                    "row": 4,
                    "action": "reuse",
                    "part_id": erp_only["id"],
                    "expected_part_revision": 1,
                },
                {"row": 5, "action": "skip", "reason": None},
            ],
        ),
        parts=parts,
    )
    assert decided["complete"] is True
    lines = {line["row"]: line for line in decided["lines"]}
    assert lines[3]["part_id"] == known["id"] and lines[3]["part"] is None
    assert lines[4]["part_id"] == erp_only["id"]
    new = convert(
        t, basis(t, [{"row": 4, "action": "new_part"}, {"row": 5, "action": "skip"}]), parts=parts
    )
    assert next(line for line in new["lines"] if line["row"] == 4)["part"]["erp_number"] == "ERP-9"
    # A private part cannot be pulled into a shared BOM by its number.
    shared = convert(t, basis(t), parts=parts, visibility="category")
    assert [i["code"] for i in by_row(shared)[3]["issues"]] == ["identity_private"]


def test_repeated_new_number_and_keys():
    previous_part = part("RD-1")
    t = table(
        [
            ["RD-1", "Housing", "1", "pcs"],
            ["RD 2/A", "Screw", "4", "pcs"],
            ["RD 2/A", "Screw again", "2", "pcs"],
            [None, "Unnumbered", "1", "pcs"],
        ]
    )
    previous = [{"key": "housing", "part_id": previous_part["id"]}]
    result = convert(t, basis(t), previous_lines=previous, parts=[previous_part])
    rows = by_row(result)
    assert [i["code"] for i in rows[5]["issues"]] == ["identity_repeated"]
    keys = {line["row"]: line["key"] for line in result["lines"]}
    # Same part as the predecessor keeps its key, so the difference stays line by line.
    assert keys == {3: "housing", 4: "RD-2-A", 6: "row-6"}


def test_explicit_key_column_must_be_valid_and_unique():
    header = ["序号", "料号", "名称", "用量", "单位"]
    t = table(
        [["10", "A", "a", "1", "pcs"], ["10", "B", "b", "1", "pcs"], ["x y", "C", "c", "1", "pcs"]],
        header=header,
    )
    rows = by_row(convert(t, basis(t)))
    assert rows[3]["key"] == "10"
    assert [i["code"] for i in rows[4]["issues"]] == ["key_repeated"]
    assert [i["code"] for i in rows[5]["issues"]] == ["key_invalid"]


def test_disposition_for_unknown_row_or_wrong_action_is_refused():
    t = table([["RD-1", "Housing", "-1", "pcs"]])
    result = convert(t, basis(t, [{"row": 3, "action": "new_part"}, {"row": 99, "action": "skip"}]))
    assert [i["code"] for i in result["issues"]] == ["disposition_unknown"]
    assert "disposition_invalid" in [i["code"] for i in by_row(result)[3]["issues"]]
    assert result["complete"] is False


def test_xlsx_and_csv_tables_come_from_the_parsed_locator():
    lines = ["料号", "用量", "RD-1", "2"]
    locator = [
        {
            "derived_line_start": n,
            "derived_line_end": n,
            "value_kind": "text",
            "location": {
                "kind": "cell",
                "sheet": "S",
                "row": 1 + (n > 2),
                "column": 1 + (n % 2 == 0),
            },
        }
        for n in range(1, 5)
    ]
    t = _xlsx_table(lines, locator)
    assert t.sheets == ("S",) and t.cells["S"][2][2].text == "2" and t.cells["S"][2][2].line == 4
    csv = _csv_table(["﻿料号,名称,用量,单位", 'RD-1,"Housing, top",1,pcs', 'RD-2,"broken', ""])
    assert csv.cells[None][2][2].text == "Housing, top"
    assert [i["code"] for i in csv.issues] == ["csv_multiline_cell"]
    tab = _csv_table(["料号\t用量", "RD-1\t2"])
    assert tab.cells[None][2][2].text == "2"


def test_rule_card_over_saved_lines():
    lines = [
        {"key": "a", "quantity": "3", "unit": "pcs", "reference_designators": ["R1", "R2"]},
        {"key": "b", "quantity": "1", "unit": "pcs", "reference_designators": ["r2"]},
        {"key": "c", "quantity": None, "unit": None, "reference_designators": []},
        {"key": "d", "quantity": "2", "unit": "g", "reference_designators": ["X1"]},
    ]
    card = rule_card(lines)
    rules = {r["code"]: r for r in card["rules"]}
    assert rules["duplicate_designator"]["status"] == "fail"
    assert rules["duplicate_designator"]["items"][0]["designator"] == "R2"
    # Only count units compare designators with quantity; grams are not counted.
    assert [i["key"] for i in rules["designator_quantity_mismatch"]["items"]] == ["a"]
    assert rules["missing_unit"]["status"] == "warn" and rules["quantity"]["status"] == "warn"
    assert card["status"] == "fail" and card["ruleset"] == "bom-rules.v1"
    clean = rule_card([{"key": "a", "quantity": "1", "unit": "pcs", "reference_designators": []}])
    assert clean["status"] == "pass"
    assert {r["code"]: r["status"] for r in clean["rules"]}[
        "duplicate_designator"
    ] == "not_applicable"


def test_difference_reports_quantity_part_and_designator_changes():
    p1, p2 = str(uuid4()), str(uuid4())

    def line(key, pid, qty, refs, name="Part"):
        return {
            "key": key,
            "part_id": pid,
            "expected_part_revision": 1,
            "part": {"internal_number": key.upper(), "name": name},
            "quantity": qty,
            "unit": "pcs",
            "loss_rate": None,
            "critical": False,
            "notes": None,
            "reference_designators": refs,
        }

    before = [line("a", p1, "2", ["R1", "R2"]), line("b", p2, "1", []), line("c", p2, "1", [])]
    after = [line("a", p1, "2.0", ["R2", "R3"]), line("b", p1, "1", []), line("d", p2, "5", [])]
    diff = compare(before, after)
    assert diff["summary"] == {"added": 1, "removed": 1, "changed": 2, "unchanged": 0}
    rows = {row["key"]: row for row in diff["lines"]}
    # 2 and 2.0 are the same quantity; only the designators changed on line a.
    assert rows["a"]["fields"] == ["reference_designators"]
    assert rows["a"]["designators"] == {"added": ["R3"], "removed": ["R1"]}
    assert rows["b"]["fields"] == ["part"]
    assert rows["c"]["change"] == "removed" and rows["d"]["change"] == "added"
    assert compare([], after)["summary"]["added"] == 3


@pytest.mark.parametrize(
    "text,expected",
    [("R1-R3", ["R1", "R2", "R3"]), ("C10-12", ["C10", "C11", "C12"]), ("U1A U1B", ["U1A", "U1B"])],
)
def test_designator_ranges(text, expected):
    values, problems = bom_import._designators(text)
    assert values == expected and problems == []


def test_designator_problems_are_reported():
    assert bom_import._designators("R5-R1")[1] == ["R5-R1"]
    assert bom_import._designators("R1，R2；中文")[1] == ["中文"]
