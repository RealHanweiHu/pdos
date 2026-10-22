"""Extraction-consumption proof projections; pure shape checks, no database."""

import pytest

from pdos_next.agent_kernel.extracted_claim import expected_availability, expected_content
from pdos_next.errors import DomainError


def test_non_spec_row_projects_to_text_only():
    fields = {"kind": "compliance", "statement": "噪声不超过 75 dB", "spec": None, "missing": []}
    assert expected_content(fields) == {"text": "噪声不超过 75 dB"}
    assert expected_availability(fields) == "known"


def test_spec_row_projects_only_claim_content_keys():
    fields = {
        "kind": "spec",
        "statement": "额定压力 20 psi",
        "spec": {
            "key": "rated_pressure",
            "parameter": "额定压力",
            "value_type": "number",
            "value": "20",
            "lower": None,
            "upper": None,
            "text": None,
            "unit": "psi",
            "condition_note": None,
            "modality": "must",
            "exceptions": [],
            "verification_method": "客户验收",
            "acceptance_criterion": None,
            "availability": "known",
            "reason": None,
        },
        "missing": [],
    }
    content = expected_content(fields)
    assert content == {
        "text": "额定压力 20 psi",
        "value": "20",
        "unit": "psi",
        "modality": "must",
        "verification_method": "客户验收",
    }
    # Spec-only authority and bookkeeping keys never leak into the claim.
    assert "key" not in content and "availability" not in content and "value_type" not in content
    assert expected_availability(fields) == "known"


def test_spec_row_with_unknown_availability_projects_no_values():
    fields = {
        "kind": "spec",
        "statement": "目标成本待定",
        "spec": {"availability": "unknown", "value": None},
        "missing": ["value"],
    }
    assert expected_content(fields) == {"text": "目标成本待定"}
    assert expected_availability(fields) == "unknown"


def test_invalid_rows_are_refused():
    with pytest.raises(DomainError) as error:
        expected_content(None)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    with pytest.raises(DomainError):
        expected_content({"kind": "spec", "statement": "x", "spec": None})
    with pytest.raises(DomainError):
        expected_availability({"kind": "spec", "statement": "x", "spec": {"availability": "wild"}})
