"""Pure fixtures only: no actual ModelCall, authorization, database, or provider."""

import hashlib
import unittest
from copy import deepcopy
from uuid import uuid4

from pdos_next.agent_kernel.extract_read_ledger import (
    ArtifactSeal,
    ExtractReadLedger,
    ParseManifest,
    SourceLocation,
)

ARTIFACT = "11111111-1111-4111-8111-111111111111"
OTHER_ARTIFACT = "22222222-2222-4222-8222-222222222222"


def location(kind, **coordinates):
    return SourceLocation.from_mapping({"kind": kind, **coordinates})


def entry(start, end, native, *, value_kind="text"):
    return {
        "derived_line_start": start,
        "derived_line_end": end,
        "location": {name: getattr(native, name) for name in native.__dataclass_fields__},
        "value_kind": value_kind,
    }


def source(text, *, artifact_id=ARTIFACT, locator_map=None, **changes):
    return ArtifactSeal.from_server(
        artifact_id=artifact_id,
        revision=1,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        total_lines=len(text.splitlines()),
        locator_map=locator_map or [],
        parse_status=changes.pop("parse_status", "parsed"),
        **changes,
    )


def page(seal, cursor, size):
    # Exactly the current domain_reads result; these are pure synthetic values.
    end = min(seal.total_lines, cursor + size)
    lines = seal.text.splitlines()
    return {
        "artifact_id": seal.artifact_id,
        "revision": seal.revision,
        "content_hash": seal.content_hash,
        "lines": [{"line": index + 1, "text": lines[index]} for index in range(cursor, end)],
        "next_cursor": end if end < seal.total_lines else None,
    }


def completed(ledger, seal, cursor, size, *, call_id=None):
    return ledger.record_successful_page(
        page(seal, cursor, size),
        call_id=call_id or str(uuid4()),
        cursor=cursor,
        page_size=size,
    )


def row(quote, locator="line:1", *, artifact_id=ARTIFACT, revision=1, **extra):
    return {
        "artifact_id": artifact_id,
        "revision": revision,
        "locator": locator,
        "quote": quote,
        "fields": {"text": "合成需求，尚未登记事实", "unit": None},
        **extra,
    }


class ExtractReadLedgerTests(unittest.TestCase):
    def test_out_of_order_overlap_union_and_eof_do_not_hide_missing_text(self):
        seal = source("one\ntwo\nthree\nfour\nfive\nsix")
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 4, 2)
        completed(ledger, seal, 0, 2)
        completed(ledger, seal, 1, 2)
        completed(ledger, seal, 99, 2)
        coverage = ledger.coverage(ARTIFACT)
        self.assertEqual(coverage["parsed_text"]["read_ranges"], [[1, 3], [5, 6]])
        self.assertEqual(coverage["parsed_text"]["unread_ranges"], [[4, 4]])
        self.assertFalse(coverage["parsed_text"]["fully_read"])
        completed(ledger, seal, 3, 1)
        self.assertTrue(ledger.coverage(ARTIFACT)["parsed_text"]["fully_read"])

    def test_completed_page_fingerprint_and_identity_are_exact_and_fail_atomically(self):
        seal = source(" one \ntwo\nthree")
        ledger = ExtractReadLedger([seal])
        good = page(seal, 0, 2)
        mutations = [
            {"revision": 2},
            {"content_hash": "b" * 64},
            {"artifact_id": OTHER_ARTIFACT},
            {"next_cursor": None},
            {"lines": [{"line": 1, "text": "one"}, {"line": 2, "text": "two"}]},
            {"lines": [{"line": True, "text": " one "}, {"line": 2, "text": "two"}]},
            {"lines": [{"line": 1, "text": " one "}, {"line": 3, "text": "three"}]},
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                ledger.record_successful_page(
                    {**good, **change}, call_id=str(uuid4()), cursor=0, page_size=2
                )
        self.assertEqual(ledger.coverage(ARTIFACT)["parsed_text"]["read_ranges"], [])
        identity = str(uuid4())
        first = completed(ledger, seal, 0, 2, call_id=identity)
        self.assertEqual(first, completed(ledger, seal, 0, 2, call_id=identity))
        with self.assertRaises(ValueError):
            completed(ledger, seal, 2, 1, call_id=identity)
        self.assertEqual(ledger.coverage(ARTIFACT)["parsed_text"]["read_ranges"], [[1, 2]])

    def test_invalid_quotes_are_removed_without_model_declared_success(self):
        seal = source("must keep  two spaces\nunread requirement")
        ledger = ExtractReadLedger([seal])
        read = completed(ledger, seal, 0, 1)
        result = ledger.verify_rows(
            [
                row("keep  two spaces"),
                row("keep two spaces"),
                row("unread requirement", "line:2"),
                row("keep  two spaces", status="ok", coverage={"complete": True}),
                row("keep  two spaces", artifact_id=OTHER_ARTIFACT),
                row("keep  two spaces", revision=2),
            ]
        )
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].read_call_ids, (read.call_id,))
        self.assertEqual(
            [failure.code for failure in result.failures],
            [
                "quote_not_in_source",
                "source_location_not_read",
                "invalid_extraction_row",
                "source_not_assigned",
                "source_version_mismatch",
            ],
        )
        self.assertEqual([failure.input_index for failure in result.failures], [1, 2, 3, 4, 5])

    def test_multiline_cell_quote_requires_all_actual_lines_and_preserves_crlf(self):
        cell = location("cell", sheet="需求", row=2, column=2, cell="B2")
        seal = source("head\r\nsecond\r\nthird", locator_map=[entry(2, 3, cell)])
        ledger = ExtractReadLedger([seal])
        read_second = completed(ledger, seal, 1, 1)
        raw_locator = entry(2, 3, cell)["location"]
        first = ledger.verify_rows(
            [row("second\r\nthird", raw_locator), row("second", raw_locator)]
        )
        self.assertEqual([failure.code for failure in first.failures], ["source_location_not_read"])
        self.assertEqual(first.rows[0].quote, "second")
        read_third = completed(ledger, seal, 2, 1)
        exact = ledger.verify_rows(
            [row("second\r\nthird", raw_locator), row("second\nthird", raw_locator)]
        )
        self.assertEqual(len(exact.rows), 1)
        self.assertEqual(
            set(exact.rows[0].read_call_ids), {read_second.call_id, read_third.call_id}
        )
        self.assertEqual(exact.failures[0].code, "quote_not_in_source")
        self.assertEqual(exact.rows[0].as_dict()["locator"], raw_locator)

    def test_pdf_separator_is_not_an_original_page(self):
        first, second = location("page", page=1), location("page", page=2)
        seal = source(
            "page one\n\npage two",
            locator_map=[entry(1, 1, first), entry(3, 3, second)],
            parse_manifest=ParseManifest("synthetic-native-parser-v1", "page", (first, second)),
        )
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 0, 1)
        completed(ledger, seal, 2, 1)
        coverage = ledger.coverage(ARTIFACT)
        self.assertEqual(coverage["parsed_text"]["unread_ranges"], [[2, 2]])
        self.assertFalse(coverage["parsed_text"]["fully_read"])
        self.assertEqual(len(coverage["original_locations"]["represented"]), 2)
        self.assertTrue(coverage["original_locations"]["fully_read"])
        self.assertIn("visual/OCR", coverage["original_locations"]["limitation"])

    def test_legacy_partial_text_cannot_establish_original_extent(self):
        first = location("page", page=1)
        seal = source(
            "only native text", locator_map=[entry(1, 1, first)], parse_code="PARTIAL_TEXT"
        )
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 0, 1)
        coverage = ledger.coverage(ARTIFACT)
        self.assertTrue(coverage["parsed_text"]["fully_read"])
        self.assertFalse(coverage["original_locations"]["extent_known"])
        self.assertIsNone(coverage["original_locations"]["fully_represented"])
        self.assertIsNone(coverage["original_locations"]["fully_read"])
        self.assertEqual(coverage["original_locations"]["reason"], "partial_text_extent_unknown")

    def test_parser_inventory_reports_missing_page_even_when_parsed_text_is_all_read(self):
        first, missing, third = (location("page", page=number) for number in (1, 2, 3))
        seal = source(
            "first\n\nthird",
            locator_map=[entry(1, 1, first), entry(3, 3, third)],
            parse_code="PARTIAL_TEXT",
            parse_manifest=ParseManifest(
                "synthetic-native-parser-v1", "page", (first, missing, third)
            ),
        )
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 0, 3)
        coverage = ledger.coverage(ARTIFACT)
        self.assertTrue(coverage["parsed_text"]["fully_read"])
        self.assertEqual(coverage["original_locations"]["unrepresented"][0]["page"], 2)
        self.assertFalse(coverage["original_locations"]["fully_represented"])
        self.assertFalse(coverage["original_locations"]["fully_read"])

    def test_cell_identity_includes_sheet_and_rejects_ambiguous_mapping(self):
        a = location("cell", sheet="A", row=1, column=1, cell="A1")
        b = location("cell", sheet="B", row=1, column=1, cell="A1")
        seal = source("first\nsecond", locator_map=[entry(1, 1, a), entry(2, 2, b)])
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 0, 2)
        result = ledger.verify_rows([row("second", entry(1, 1, a)["location"])])
        self.assertEqual(result.failures[0].code, "quote_not_in_source")
        ambiguous = source("first\nsecond", locator_map=[entry(1, 1, a), entry(2, 2, a)])
        ledger = ExtractReadLedger([ambiguous])
        completed(ledger, ambiguous, 0, 2)
        result = ledger.verify_rows([row("first", entry(1, 1, a)["location"])])
        self.assertEqual(result.failures[0].code, "ambiguous_locator")

    def test_sealed_metadata_and_verified_fields_do_not_alias_mutable_inputs(self):
        native = location("line", line=1)
        mapping = [entry(1, 1, native)]
        seal = source("exact source", locator_map=mapping)
        mapping[0]["location"]["line"] = 99
        ledger = ExtractReadLedger([seal])
        completed(ledger, seal, 0, 1)
        raw = row("exact", deepcopy(entry(1, 1, native)["location"]))
        raw["fields"]["exceptions"] = [{"text": "原文例外"}]
        result = ledger.verify_rows([raw])
        raw["fields"]["exceptions"][0]["text"] = "changed after verification"
        self.assertEqual(result.rows[0].as_dict()["fields"]["exceptions"][0]["text"], "原文例外")
        self.assertEqual(result.rows[0].as_dict()["locator"]["line"], 1)
        with self.assertRaises(TypeError):
            result.rows[0].fields["unit"] = "invented"

    def test_unparsed_source_cannot_become_read_or_quoted_via_empty_text(self):
        seal = source("", parse_status="needs_ocr", parse_code="OCR_REQUIRED")
        ledger = ExtractReadLedger([seal])
        with self.assertRaises(ValueError):
            completed(ledger, seal, 0, 1)
        result = ledger.verify_rows([row("invented")])
        self.assertEqual(result.failures[0].code, "source_not_parsed")
        coverage = ledger.coverage(ARTIFACT)
        self.assertFalse(coverage["parsed_text"]["fully_read"])
        self.assertEqual(coverage["parse_code"], "OCR_REQUIRED")

    def test_total_line_count_is_a_sealed_fact_and_never_a_model_estimate(self):
        with self.assertRaises(ValueError):
            ArtifactSeal.from_server(
                artifact_id=ARTIFACT,
                revision=1,
                content_hash=hashlib.sha256(b"one\ntwo").hexdigest(),
                text="one\ntwo",
                total_lines=1,
                locator_map=[],
                parse_status="parsed",
            )

    def test_source_digest_also_binds_unread_text(self):
        with self.assertRaises(ValueError):
            ArtifactSeal.from_server(
                artifact_id=ARTIFACT,
                revision=1,
                content_hash=hashlib.sha256(b"one\ntwo").hexdigest(),
                text="one\nmodified unread tail",
                total_lines=2,
                locator_map=[],
                parse_status="parsed",
            )


if __name__ == "__main__":
    unittest.main()
