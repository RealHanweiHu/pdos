"""Located wire semantics and exact quoted-read bookkeeping; no model authority."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.extract_pages import (
    absolute_cursor,
    located_page,
    locator_text,
    project_page,
    resolve_locator,
)
from pdos_next.agent_kernel.extract_read_ledger import ExtractReadLedger
from pdos_next.agent_kernel.extract_schemas import ArtifactReadInput
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError
from tests.agent_kernel.test_extract_read_ledger import ARTIFACT, completed, entry, location, source


def arguments(**changes):
    return {"artifact_version_id": ARTIFACT, "page_size": 2, **changes}


def test_native_page_origin_and_relative_cursor_keep_the_actual_line_projection():
    seal = source(
        "one\ntwo\nthree\nfour\nfive",
        locator_map=[
            entry(1, 2, location("page", page=1)),
            entry(3, 5, location("page", page=2)),
        ],
    )
    data = arguments(locator="page:2")
    first = located_page(seal, data)
    assert first["blocks"] == [
        {"locator": "page:2", "text": "three\n", "derived_line_start": 3, "derived_line_end": 3},
        {"locator": "page:2", "text": "four\n", "derived_line_start": 4, "derived_line_end": 4},
    ]
    assert first["next_cursor"] == 2 and "artifact_id" not in first
    _, internal, locators = project_page(seal, data, first)
    assert internal["lines"] == [{"line": 3, "text": "three"}, {"line": 4, "text": "four"}]
    assert internal["next_cursor"] == 4 and locators == ("page:2",)
    assert absolute_cursor(seal, ArtifactReadInput.model_validate(data)) == 2
    second = located_page(seal, {**data, "cursor": 2})
    assert second["blocks"][0]["text"] == "five" and second["next_cursor"] is None


def test_cell_locator_preserves_sheet_punctuation_and_unicode_without_guessing():
    cell = location("cell", sheet='客户:说明 "中文"', row=3, column=2, cell="B3")
    locator = locator_text(cell)
    seal = source("75 dB(A)", locator_map=[entry(1, 1, cell)])
    wire = located_page(seal, arguments(locator=locator))
    assert resolve_locator(seal, locator) == cell
    assert wire["blocks"][0]["locator"] == locator
    with pytest.raises(DomainError):
        located_page(seal, arguments(locator="cell:B3"))


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_id": ARTIFACT},
        {"page_size": 201},
        {"cursor": True},
        {"page_size": "2"},
        {"locator": " "},
    ],
)
def test_older_wire_and_coerced_budget_fields_are_rejected(change):
    data = arguments(**change)
    with pytest.raises((ValidationError, DomainError)):
        located_page(source("one"), data)


@pytest.mark.parametrize(
    "change",
    [
        {"revision": True},
        {"artifact_id": ARTIFACT},
        {"next_cursor": 99},
        {"parse_status": "needs_ocr"},
        {"blocks": []},
    ],
)
def test_stored_page_cannot_be_repaired_or_downgraded_to_an_older_shape(change):
    seal = source("one\ntwo\nthree")
    good = located_page(seal, arguments())
    with pytest.raises(DomainError):
        project_page(seal, arguments(), {**deepcopy(good), **change})


def test_located_page_success_tracks_only_its_read_lines_and_eof_does_not_fill_gaps():
    seal = source("one\ntwo\nthree\nfour")
    ledger = ExtractReadLedger([seal])
    data = arguments(locator="line:3")
    wire = located_page(seal, data)
    _, internal, _ = project_page(seal, data, wire)
    from uuid import uuid4

    ledger.record_successful_page(internal, call_id=str(uuid4()), cursor=2, page_size=2)
    completed(ledger, seal, 99, 2)
    coverage = ledger.coverage(ARTIFACT)
    assert coverage["parsed_text"]["read_ranges"] == [[3, 4]]
    assert coverage["parsed_text"]["unread_ranges"] == [[1, 2]]
    assert not coverage["parsed_text"]["fully_read"]


def test_registry_has_new_schema_and_version_only_in_extract_isolation():
    registry = default_registry()
    actual = registry.get("evidence.artifact.read")
    assert actual.version == "2" and actual.input_schema == ArtifactReadInput.model_json_schema()
    assert not any(row["name"] == actual.name for row in registry.definitions("main"))
    assert [row["name"] for row in registry.definitions("extract")] == [actual.name, "result.read"]


def test_multiline_native_quote_keeps_literal_crlf_separators_across_wire_blocks():
    from uuid import uuid4

    native = location("page", page=1)
    seal = source("不得超过75 dB(A)\r\n启动前三秒除外。\r\n", locator_map=[entry(1, 2, native)])
    data = arguments(locator="page:1")
    wire = located_page(seal, data)
    literal = "".join(block["text"] for block in wire["blocks"])
    assert literal == seal.text
    _, internal, _ = project_page(seal, data, wire)
    ledger = ExtractReadLedger([seal])
    ledger.record_successful_page(internal, call_id=str(uuid4()), cursor=0, page_size=2)
    rows = ledger.verify_rows(
        [
            {
                "artifact_id": seal.artifact_id,
                "revision": 1,
                "locator": {name: getattr(native, name) for name in native.__dataclass_fields__},
                    "quote": literal[:-2],
                "fields": {"upper": "75"},
            }
        ]
    )
    assert len(rows.rows) == 1 and not rows.failures
