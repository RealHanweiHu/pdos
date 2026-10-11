"""Pure schema checks: no ORM imports or database fixtures are needed."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject.evidence_schemas import (
    ClaimContent,
    ClaimRecord,
    ClaimRecordBatch,
    ClaimSource,
    ClaimWithdraw,
    EvidenceLinkCreate,
    ProposalShare,
)


def canonical(**changes):
    return {
        "source": {
            "kind": "snapshot",
            "id": str(uuid4()),
            "version": 2,
            "locator": "line:7",
            "quote": "  标称噪声 42 dB  ",
        },
        "nature": "extracted",
        "availability": "known",
        "content": {"value": "42", "unit": "dB", "text": "厂商标称"},
        **changes,
    }


def legacy(**changes):
    return {
        "artifact_id": str(uuid4()),
        "line": 1,
        "quote": "噪声 42 dB",
        "statement": "噪声标称值为 42 dB",
        **changes,
    }


def sharing(**changes):
    return {
        "proposal_id": str(uuid4()),
        "expected_revision": 3,
        "visibility": "category",
        "audience_ids": [],
        "deidentified_confirmed": False,
        **changes,
    }


def test_legacy_serialization_preserves_existing_candidate_semantic_content():
    body = legacy()
    result = ClaimRecord.model_validate(body)
    assert result.source is None
    assert result.model_dump(mode="json", exclude={"prepared_event_id", "confirmation_token"}) == {
        **body,
        "nature": "extracted",
        "availability": "known",
        "visibility": "private",
    }
    explicit = {
        **body,
        "visibility": "category",
        "prepared_event_id": str(uuid4()),
        "confirmation_token": "x" * 24,
    }
    record = ClaimRecord.model_validate(explicit)
    assert str(record.prepared_event_id) == explicit["prepared_event_id"]
    assert record.visibility == "category"
    assert record.model_dump(mode="json") == {
        **explicit,
        "nature": "extracted",
        "availability": "known",
    }


@pytest.mark.parametrize("field", ["artifact_id", "line", "quote", "statement"])
def test_legacy_source_requires_complete_existing_input(field):
    body = legacy()
    del body[field]
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(body)


@pytest.mark.parametrize("nature", ["observed", "extracted", "computed", "inferred", "decided"])
def test_canonical_source_supports_all_claim_natures_and_preserves_quote(nature):
    body = canonical(nature=nature)
    result = ClaimRecord.model_validate(body)
    assert result.nature == nature
    assert result.source.quote == body["source"]["quote"]
    assert result.source.line == 7
    assert result.source.version == 2
    assert result.artifact_id is None and result.visibility is None
    serialized = result.model_dump(mode="json")
    assert "visibility" not in serialized and "artifact_id" not in serialized
    assert ClaimRecord.model_validate(serialized) == result


@pytest.mark.parametrize("availability", ["known", "unknown", "conflicted", "not_applicable"])
def test_all_availability_states_preserve_explanatory_text(availability):
    record = ClaimRecord.model_validate(
        canonical(availability=availability, content={"text": "等待确认或解释适用性"})
    )
    assert record.availability == availability


@pytest.mark.parametrize("nature", ["observed", "computed", "inferred", "decided"])
def test_vendor_claimed_requires_extraction(nature):
    with pytest.raises(ValidationError, match="Only extracted"):
        ClaimRecord.model_validate(canonical(nature=nature, vendor_claimed=True))


def test_vendor_claim_and_customer_quote_are_distinct():
    assert ClaimRecord.model_validate(canonical(vendor_claimed=True)).vendor_claimed is True
    assert ClaimRecord.model_validate(canonical()).vendor_claimed is False
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(canonical(vendor_claimed="false"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("visibility", "category"),
        ("visibility", None),
        ("privacy", "category"),
        ("origin", "human"),
        ("writer_id", str(uuid4())),
        ("run_id", str(uuid4())),
        ("confirmed_by", str(uuid4())),
        ("artifact_id", str(uuid4())),
        ("line", 1),
        ("quote", "另一段原文"),
        ("statement", "另一项事实"),
    ],
)
def test_canonical_claim_rejects_policy_facts_and_ambiguous_legacy_input(field, value):
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(canonical(**{field: value}))


@pytest.mark.parametrize("field", ["privacy", "origin", "writer_id"])
def test_legacy_claim_also_rejects_server_owned_facts(field):
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(legacy(**{field: "human"}))


def test_locator_normalizes_lines_without_changing_source_text():
    source = canonical()["source"]
    del source["locator"]
    source["line"] = 4
    record = ClaimSource.model_validate(source)
    assert record.locator == "line:4"
    assert record.quote == source["quote"]
    structured_locator = {**source, "locator": "sheet:参数!B4", "line": None}
    assert ClaimSource.model_validate(structured_locator).locator == "sheet:参数!B4"


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 0},
        {"line": 6},
        {"locator": "line:0"},
        {"locator": "line:wrong"},
        {"locator": "   "},
        {"locator": None, "line": None},
        {"quote": "\n  "},
        {"kind": "claim"},
    ],
)
def test_source_rejects_invalid_or_conflicting_locations(changes):
    with pytest.raises(ValidationError):
        ClaimSource.model_validate({**canonical()["source"], **changes})


@pytest.mark.parametrize(
    "content",
    [
        {"parameter_id": str(uuid4())},
        {"parameter_version": 1},
        {"parameter_id": str(uuid4()), "parameter_version": 0},
        {"lower": "2", "upper": "1"},
        {"lower": "1", "upper": "2", "value": "1.5"},
        {"value": Decimal("Infinity")},
        {"lower": "NaN", "upper": "2"},
        {"origin": "human"},
    ],
)
def test_content_checks_parameter_pair_range_and_finite_numeric_values(content):
    with pytest.raises(ValidationError):
        ClaimContent.model_validate(content)


def test_content_keeps_decimal_precision_and_supports_boolean_and_text_values():
    value = Decimal("12345678901234567890.123456789")
    typed = ClaimContent(value=value)
    assert typed.value == value
    assert typed.model_dump(mode="json")["value"] == str(value)
    assert ClaimContent(value=False).value is False
    assert ClaimContent(value="数字显示").value == "数字显示"
    assert ClaimContent(lower="0.01", upper="0.02").upper == Decimal("0.02")


@pytest.mark.parametrize("availability", ["unknown", "not_applicable"])
def test_unavailable_claim_does_not_assert_a_value(availability):
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(canonical(availability=availability))
    assert (
        ClaimRecord.model_validate(canonical(availability=availability, content={})).content == {}
    )


def test_batch_has_no_business_row_limit_and_rejects_empty_batches():
    body = canonical()
    result = ClaimRecordBatch.model_validate({"claims": [deepcopy(body) for _ in range(257)]})
    assert len(result.claims) == 257
    with pytest.raises(ValidationError):
        ClaimRecordBatch(claims=[])


@pytest.mark.parametrize("evidence_type", ["claim", "snapshot", "artifact"])
@pytest.mark.parametrize("target_type", ["proposal_item", "knowledge_entry", "definition_spec"])
def test_evidence_links_pin_both_typed_ends(evidence_type, target_type):
    record = EvidenceLinkCreate.model_validate(
        {
            "evidence": {"type": evidence_type, "id": str(uuid4()), "version": 2},
            "target": {"type": target_type, "id": str(uuid4()), "version": 3},
            "relation": "supports",
        }
    )
    assert record.evidence.version == 2 and record.target.version == 3


@pytest.mark.parametrize("field", ["evidence", "target"])
def test_evidence_links_require_a_real_version(field):
    data = {
        "evidence": {"type": "claim", "id": str(uuid4()), "version": 1},
        "target": {"type": "proposal_item", "id": str(uuid4()), "version": 1},
        "relation": "supports",
    }
    data[field]["version"] = 0
    with pytest.raises(ValidationError):
        EvidenceLinkCreate.model_validate(data)


def test_claim_withdrawal_requires_expected_version_and_reason():
    body = {"claim_id": str(uuid4()), "expected_version": 2, "reason": "引用包含客户身份"}
    assert ClaimWithdraw.model_validate(body).expected_version == 2
    for changes in ({"expected_version": 0}, {"reason": "  "}, {"actor_id": str(uuid4())}):
        with pytest.raises(ValidationError):
            ClaimWithdraw.model_validate({**body, **changes})


def test_sharing_requires_explicit_choice_and_uncoerced_deidentification_confirmation():
    for field in ("visibility", "audience_ids", "deidentified_confirmed"):
        body = sharing()
        del body[field]
        with pytest.raises(ValidationError):
            ProposalShare.model_validate(body)
    for confirmation in ("false", "true", 1, 0, None):
        with pytest.raises(ValidationError):
            ProposalShare.model_validate(sharing(deidentified_confirmed=confirmation))
    assert ProposalShare.model_validate(sharing()).deidentified_confirmed is False
    assert ProposalShare.model_validate(sharing(deidentified_confirmed=True)).deidentified_confirmed


def test_named_audiences_are_explicit_and_distinct():
    person = str(uuid4())
    valid = sharing(visibility="audience", audience_ids=[person])
    assert len(ProposalShare.model_validate(valid).audience_ids) == 1
    for changes in (
        {"visibility": "private"},
        {"visibility": "audience", "audience_ids": []},
        {"visibility": "category", "audience_ids": [person]},
        {"visibility": "audience", "audience_ids": [person, person]},
        {"run_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            ProposalShare.model_validate(sharing(**changes))
