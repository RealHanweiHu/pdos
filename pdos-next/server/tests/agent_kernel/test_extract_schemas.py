"""Private pure DTO tests. No production imports are patched; no DB/LLM is used."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.extract_schemas import (
    SCHEMAS,
    ArtifactReadInput,
    CitationDraft,
    ExtractInput,
    ParameterFocus,
    RFQDraftRow,
    RFQSpecDraft,
    RowSchemaDeclaration,
    RowSchemaRegistry,
    draft_registry,
)
from pdos_next.domain.preproject.schemas import SpecItem

RFQ = {"kind": "rfq_requirement", "version": "1"}


def row(**changes):
    return {
        "artifact_version_id": str(uuid4()),
        "locator": "page:2/table:3/row:4/cell:B4",
        "quote": "  Noise shall be <=75 dB(A), except during start-up.\n",
        "kind": "spec",
        "statement": "Noise requirement with a start-up exception",
        "spec": {
            "key": "noise",
            "parameter": "Noise level",
            "value_type": "number",
            "value": "75.123456789012",
            "availability": "known",
            "unit": "dB(A)",
            "condition_note": "at 1 m",
            "modality": "must",
            "exceptions": [{"text": "except during start-up", "applies_to": "start-up"}],
            "verification_method": None,
            "acceptance_criterion": None,
        },
        **changes,
    }


def test_proposal_default_is_selector_not_a_source_grant():
    parsed = ExtractInput(proposal_id=uuid4(), row_schema=RFQ)
    assert parsed.artifact_version_ids is None
    assert set(parsed.model_dump()) == {
        "proposal_id",
        "artifact_version_ids",
        "row_schema",
        "focus",
    }


def test_category_requires_explicit_ids_without_assuming_privacy_from_row_kind():
    with pytest.raises(ValidationError):
        ExtractInput(row_schema=RFQ)
    parsed = ExtractInput(artifact_version_ids=[uuid4()], row_schema=RFQ)
    assert parsed.proposal_id is None
    # This merely parses an explicit selector. Actual category-visible imported
    # sources remain a host/manifest check, never a private-RFQ permission here.
    assert len(parsed.artifact_version_ids) == 1


@pytest.mark.parametrize("ids", [[], [str(uuid4())] * 2])
def test_empty_or_duplicate_source_selection_is_not_silently_reinterpreted(ids):
    with pytest.raises(ValidationError):
        ExtractInput(proposal_id=uuid4(), artifact_version_ids=ids, row_schema=RFQ)


@pytest.mark.parametrize(
    "authority", ["tenant_id", "actor_id", "product_id", "permissions", "tools"]
)
def test_input_cannot_grant_scope_or_tools(authority):
    with pytest.raises(ValidationError):
        ExtractInput(proposal_id=uuid4(), row_schema=RFQ, **{authority: "forged"})


@pytest.mark.parametrize("extra", ["tools", "allowed_operations", "input_schema", "tier"])
def test_row_declaration_is_not_an_arbitrary_tool_definition(extra):
    with pytest.raises(ValidationError):
        RowSchemaDeclaration(**RFQ, **{extra: "forged"})


def test_unknown_row_contract_requires_host_registration():
    registry = draft_registry()
    declaration = RowSchemaDeclaration(kind="public_import_measurement", version="1")
    with pytest.raises(ValueError, match="not registered"):
        registry.rows_model(declaration)

    class ImportedMeasurement(CitationDraft):
        measurement: str

    registry.register(declaration, ImportedMeasurement)
    parsed = registry.rows_model(declaration).model_validate(
        {
            "rows": [
                {
                    "artifact_version_id": str(uuid4()),
                    "locator": "line:1",
                    "quote": "42 kg",
                    "measurement": "42 kg",
                }
            ]
        }
    )
    assert parsed.rows[0].measurement == "42 kg"
    with pytest.raises(ValueError, match="replaced"):
        registry.register(declaration, ImportedMeasurement)


def test_registered_data_model_cannot_install_host_status():
    class ForgedStatus(CitationDraft):
        status: str

    with pytest.raises(ValueError, match="authority"):
        RowSchemaRegistry().register(RowSchemaDeclaration(kind="bad", version="1"), ForgedStatus)


def test_full_actual_spec_content_fields_are_reused_and_no_assignment_exported():
    assert set(RFQSpecDraft.model_fields) == set(SpecItem.model_fields) - {
        "nature",
        "item_status",
        "owner_id",
    }
    parsed = RFQDraftRow.model_validate(row())
    assert parsed.spec.value == Decimal("75.123456789012")
    assert parsed.spec.verification_method is None and parsed.spec.acceptance_criterion is None
    assert parsed.quote.startswith("  ") and parsed.quote.endswith("\n")
    assert not {"nature", "item_status", "owner_id"} & parsed.spec.model_dump().keys()


def test_exception_and_variant_structures_survive_without_narrowing():
    data = row()
    data["spec"]["exceptions"] = [
        {
            "text": "  exact original exception  ",
            "applies_to": {"region": "EU", "period": "start"},
            "source_note": {"table": "B4"},
        }
    ]
    data["spec"]["applicable_variants"] = [{"key": "winter", "details": {"condition": "cold"}}]
    before = deepcopy(data["spec"])
    result = RFQDraftRow.model_validate(data).model_dump(mode="json")["spec"]
    assert result["exceptions"] == before["exceptions"]
    assert result["applicable_variants"] == before["applicable_variants"]


@pytest.mark.parametrize(
    "field", ["nature", "item_status", "owner_id", "source_refs", "status", "error"]
)
def test_content_cannot_submit_authority_fields(field):
    data = row()
    data["spec"][field] = "forged"
    with pytest.raises(ValidationError):
        RFQDraftRow.model_validate(data)


@pytest.mark.parametrize(
    "field", ["status", "error", "coverage", "row_id", "counts", "sample_size"]
)
def test_draft_rows_cannot_submit_verification_or_coverage(field):
    with pytest.raises(ValidationError):
        RFQDraftRow.model_validate({**row(), field: "forged"})


@pytest.mark.parametrize(
    "changes",
    [
        {"parameter_id": str(uuid4())},
        {"lower": "2", "upper": "1", "value": None, "value_type": "range"},
        {"availability": "unknown"},
        {"tolerance": "-1"},
    ],
)
def test_actual_spec_consistency_rules_still_apply(changes):
    data = row()
    data["spec"].update(changes)
    with pytest.raises(ValidationError):
        RFQDraftRow.model_validate(data)


@pytest.mark.parametrize("bound", ["lower", "upper"])
@pytest.mark.parametrize("value_type", ["number", "range"])
def test_one_sided_literal_boundary_is_retained_without_inventing_other_endpoint(bound, value_type):
    data = row()
    data["spec"].update(value_type=value_type, value=None, **{bound: "75"})
    parsed = RFQDraftRow.model_validate(data)
    assert getattr(parsed.spec, bound) == Decimal("75")
    assert getattr(parsed.spec, "lower" if bound == "upper" else "upper") is None
    assert parsed.spec.availability == "known"
    # The draft uses the actual shared shape while still exporting no authority.
    business_shape = SpecItem.model_validate(
        {
            **parsed.spec.model_dump(),
            "nature": "extracted",
            "item_status": "ai_draft",
            "owner_id": None,
        }
    )
    assert getattr(business_shape, bound) == Decimal("75")
    assert getattr(business_shape, "lower" if bound == "upper" else "upper") is None


def test_non_spec_requirement_preserves_citation_without_fabricating_spec():
    parsed = RFQDraftRow.model_validate(row(kind="commercial", spec=None))
    assert parsed.spec is None and parsed.quote
    with pytest.raises(ValidationError):
        RFQDraftRow.model_validate(row(kind="spec", spec=None))


def test_parameter_focus_uses_actual_reference_shape_without_source_authority():
    focus = ParameterFocus(parameter={"type": "parameter", "id": str(uuid4()), "version": 3})
    assert focus.parameter.version == 3
    with pytest.raises(ValidationError):
        ParameterFocus(parameter={"type": "claim", "id": str(uuid4()), "version": 1})


@pytest.mark.parametrize(
    "changes", [{"cursor": True}, {"cursor": -1}, {"page_size": False}, {"page_size": 201}]
)
def test_single_page_read_rejects_invalid_cursors_and_bounds(changes):
    with pytest.raises(ValidationError):
        ArtifactReadInput(artifact_version_id=uuid4(), **changes)


def test_read_wire_has_explicit_version_selector_no_old_alias_or_scope_switch():
    parsed = ArtifactReadInput(artifact_version_id=uuid4(), locator="line:1")
    assert parsed.cursor == 0 and parsed.page_size == 100
    with pytest.raises(ValidationError):
        ArtifactReadInput(artifact_id=uuid4())
    assert set(ArtifactReadInput.model_json_schema()["properties"]) == {
        "artifact_version_id",
        "locator",
        "cursor",
        "page_size",
    }
    assert set(SCHEMAS) == {"evidence.extract", "evidence.artifact.read"}


def test_model_rows_have_no_business_count_limit_or_authoritative_summary():
    model = draft_registry().rows_model(RowSchemaDeclaration(**RFQ))
    schema = model.model_json_schema()
    assert set(schema["properties"]) == {"rows"}
    assert "maxItems" not in schema["properties"]["rows"]
    assert len(model.model_validate({"rows": [row(kind="other", spec=None)] * 600}).rows) == 600
    with pytest.raises(ValidationError):
        model.model_validate({"rows": [], "coverage": {"complete": True}})


def test_registration_cannot_loosen_citation_or_open_arbitrary_output_fields():
    class OpenFields(CitationDraft):
        model_config = {"extra": "allow"}

    class UntypedCitation(CitationDraft):
        artifact_version_id: str

    for row_type in (OpenFields, UntypedCitation):
        with pytest.raises(ValueError, match="closed fields and typed citations"):
            RowSchemaRegistry().register(RowSchemaDeclaration(kind="bad", version="1"), row_type)
