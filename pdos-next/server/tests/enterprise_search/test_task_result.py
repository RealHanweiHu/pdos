"""Task cells are finite selectors, with exact extraction and responsibility proofs."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.assistant_result import attach as ordinary_answer
from pdos_next.enterprise_search.task_result import FORMATS, assemble, markdown


def source(*, structured=False):
    cid = str(uuid4())
    values = {
        "facts": {
            "root_cause": {"text": "密封圈破损", "actor_id": "SYN-RECORDER"},
            "actions": [{"text": "更换密封圈", "executor_id": "SYN-EXECUTOR"}],
            "wait": {"responsible_id": "SYN-OWNER", "next_check_at": "2026-11-02T09:00:00Z"},
            "promised_at": None,
            "empty": "",
            "quantity": 0,
        },
        "source_refs": [{"id": "NOT_A_BUSINESS_FACT"}],
    }
    body = json.dumps(values, ensure_ascii=False) if structured else "问题记录\n措施：更换密封圈。"
    actual = {
        cid: {
            "structured": values,
            "body": body,
            "source_revision": 3,
            "is_current": True,
            "read_basis_status": "current",
        }
    }
    quote = "更换密封圈"
    start = body.index(quote)
    evidence = [
        {
            "citation_id": cid,
            "quote": quote,
            "locator": {"char_start": start, "char_end": start + len(quote)},
        }
    ]
    if structured:
        evidence[0]["values"] = deepcopy(values)
    return cid, evidence, actual


def draft(format_, field, cid, **selector):
    return {
        "format": format_,
        "rows": [
            {
                "cells": {
                    field: {"status": "recorded", "citation_id": cid, **selector},
                }
            }
        ],
    }


@pytest.mark.parametrize(
    "format_,field",
    [
        ("blockers", "next_step"),
        ("cases", "measures"),
        ("review", "key_changes"),
        ("commitments", "follow_up"),
    ],
)
def test_all_registered_results_use_exact_spans_and_explicit_missing_cells(format_, field):
    cid, evidence, actual = source()
    table, proofs, gaps = assemble(draft(format_, field, cid, quote="更换密封圈"), evidence, actual)
    assert not gaps and table["verified"]
    cells = table["rows"][0]["cells"]
    assert cells[field]["text"] == "更换密封圈"
    assert cells[field]["citation_id"] == cid and cells[field]["source_revision"] == 3
    assert cells[field]["locator"]["line_start"] == 2
    assert table["unknown_count"] == len(FORMATS[format_][1]) - 1
    if format_ == "blockers":
        assert cells["owner"] == {"status": "unspecified", "text": "未指定"}
    assert proofs[0]["quote"] == "更换密封圈"


@pytest.mark.parametrize(
    "selector",
    [
        {"quote": "未曾读取的措施"},
        {"quote": "问题记录"},  # It is in the source, but not in the extraction.
        {"field_path": ["facts", "root_cause", "text"]},
    ],
)
def test_unread_text_and_unextracted_fields_are_downgraded_per_cell(selector):
    cid, evidence, actual = source()
    table, proofs, gaps = assemble(draft("cases", "measures", cid, **selector), evidence, actual)
    assert not table["verified"] and gaps and proofs == []
    assert table["rows"][0]["cells"]["measures"] == {"status": "to_confirm", "text": "待确认"}
    assert "未曾读取" not in str(table)


def test_structured_values_are_selected_by_exact_path_and_keep_dates_unchanged():
    cid, evidence, actual = source(structured=True)
    table, proofs, gaps = assemble(
        {
            "format": "blockers",
            "rows": [
                {
                    "cells": {
                        "owner": {
                            "status": "recorded",
                            "citation_id": cid,
                            "field_path": ["facts", "wait", "responsible_id"],
                        },
                        "next_step": {
                            "status": "recorded",
                            "citation_id": cid,
                            "field_path": ["facts", "wait", "next_check_at"],
                        },
                    }
                }
            ],
        },
        evidence,
        actual,
    )
    assert not gaps and len(proofs) == 2
    cells = table["rows"][0]["cells"]
    assert cells["owner"]["text"] == "SYN-OWNER"
    assert cells["owner"]["locator"] == {"json_pointer": "/facts/wait/responsible_id"}
    assert cells["next_step"]["text"] == "2026-11-02T09:00:00Z"


@pytest.mark.parametrize(
    "selector",
    [
        {"field_path": ["facts", "root_cause", "actor_id"]},
        {"quote": "更换密封圈"},
        {"field_path": ["facts", "wait", "missing_owner_id"]},
    ],
)
def test_author_or_a_name_in_text_cannot_become_responsibility(selector):
    cid, evidence, actual = source(structured=True)
    table, proofs, gaps = assemble(draft("blockers", "owner", cid, **selector), evidence, actual)
    assert gaps and not proofs
    assert table["rows"][0]["cells"]["owner"] == {"status": "unspecified", "text": "未指定"}


@pytest.mark.parametrize(
    "path",
    [
        ["source_refs", 0, "id"],
        ["facts", "promised_at"],
        ["facts", "empty"],
        ["facts", "actions", 99, "text"],
    ],
)
def test_missing_empty_composite_and_metadata_are_not_recorded_cells(path):
    cid, evidence, actual = source(structured=True)
    table, proofs, gaps = assemble(
        draft("cases", "measures", cid, field_path=path), evidence, actual
    )
    assert gaps and not proofs and table["rows"][0]["cells"]["measures"]["text"] == "待确认"


def test_zero_is_a_recorded_value_and_escaped_pointer_is_exact():
    cid, evidence, actual = source(structured=True)
    table, _proofs, gaps = assemble(
        draft("commitments", "current_commitment", cid, field_path=["facts", "quantity"]),
        evidence,
        actual,
    )
    assert not gaps and table["rows"][0]["cells"]["current_commitment"]["text"] == "0"


def test_grounded_analysis_is_separate_from_the_literal_evidence_and_private_save():
    cid, evidence, actual = source()
    analysis = "密封圈措施可供本次复验参考，工况差异仍需核对。"
    table, _proofs, gaps = assemble(
        draft("cases", "conditions_and_differences", cid, quote="更换密封圈", text=analysis),
        evidence,
        actual,
    )
    assert not gaps
    cell = table["rows"][0]["cells"]["conditions_and_differences"]
    assert cell["text"] == analysis and cell["basis_text"] == "更换密封圈"
    assert cell["content_kind"] == "analysis"
    assert f"分析：{analysis}<br>依据：更换密封圈" in markdown(table)


def test_bounded_structured_subrecord_can_support_analysis_without_replacing_dates():
    cid, evidence, actual = source(structured=True)
    table, _proofs, gaps = assemble(
        draft(
            "cases",
            "root_cause",
            cid,
            field_path=["facts", "root_cause"],
            text="登记根因指向密封圈，需要结合当前失效工况确认。",
        ),
        evidence,
        actual,
    )
    assert not gaps
    assert "密封圈破损" in table["rows"][0]["cells"]["root_cause"]["basis_text"]
    for field, path in (
        ("next_step", ["facts", "wait", "next_check_at"]),
        ("owner", ["facts", "wait", "responsible_id"]),
    ):
        rejected, proofs, gaps = assemble(
            draft("blockers", field, cid, field_path=path, text="MODEL_OVERRIDE"), evidence, actual
        )
        assert gaps and not proofs and "MODEL_OVERRIDE" not in str(rejected)


@pytest.mark.parametrize("change", ["unissued", "withdrawn", "altered_values", "altered_span"])
def test_source_and_extraction_proofs_cannot_be_forged_or_reused_after_invalidity(change):
    cid, evidence, actual = source(structured=change == "altered_values")
    selector = (
        {"field_path": ["facts", "quantity"]}
        if change == "altered_values"
        else {"quote": "更换密封圈"}
    )
    if change == "unissued":
        cid = str(uuid4())
    elif change == "withdrawn":
        actual.clear()
    elif change == "altered_values":
        evidence[0]["values"]["facts"]["quantity"] = 99
    else:
        evidence[0]["locator"]["char_start"] = 0
    table, proofs, gaps = assemble(draft("cases", "measures", cid, **selector), evidence, actual)
    assert gaps and not proofs and "更换密封圈" not in str(table)


@pytest.mark.parametrize(
    "value",
    [
        {"format": "unregistered", "rows": []},
        {"format": "cases", "rows": [{"cells": {"fabricated": {"status": "to_confirm"}}}]},
        {
            "format": "cases",
            "rows": [
                {
                    "cells": {
                        "measures": {
                            "status": "not_recorded",
                            "quote": "HIDDEN_FAKE_FACT",
                        }
                    }
                }
            ],
        },
        {"format": "cases", "rows": [{}] * 41},
    ],
)
def test_malformed_structures_fail_closed_without_leaking_the_proposed_content(value):
    table, proofs, gaps = assemble(value, [], {})
    assert table is None and proofs == [] and gaps and "HIDDEN_FAKE_FACT" not in str(gaps)


def test_empty_table_stays_honest_and_ordinary_dialogue_cannot_forge_a_task_table():
    table, _proofs, gaps = assemble({"format": "blockers", "rows": []}, [], {})
    assert not gaps and table["unknown_count"] == 5
    assert "未指定" in markdown(table) and "待确认" in markdown(table)
    ordinary = ordinary_answer({"result": {"assistant": {"task_result": table}}}, [])
    assert ordinary["result"]["assistant"] == {"version": 1, "kind": "general", "lookup": "not_run"}


def test_private_markdown_preserves_literal_cells_escaping_unknowns_and_source_identity():
    cid, evidence, actual = source()
    table, _proofs, _gaps = assemble(
        draft("cases", "measures", cid, quote="更换密封圈"), evidence, actual
    )
    text = markdown(table)
    assert "| 相似案例 | 根因 | 措施 | 验证结果 | 适用条件与差异 |" in text
    assert f"〔1〕 {cid}" in text and "更换密封圈 〔1〕" in text
    assert "4 项未记录或待确认" in text
    table["rows"][0]["cells"]["measures"]["text"] = "a|b\nnext"
    assert "a\\|b<br>next" in markdown(table)
