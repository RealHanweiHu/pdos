"""D311 refusal rules without a database: frozen specs and variant definitions."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.categories.products import definition_inherit, definition_update
from pdos_next.errors import DomainError
from pdos_next.schemas.products.definition_update import DefinitionUpdatePayload


def payload(**changes):
    return DefinitionUpdatePayload.model_validate(
        {
            "definition_id": str(uuid4()),
            "expected_definition_revision": 1,
            "title": "New title",
            "purpose": "New purpose text",
            "use_cases": ["Use"],
            "change_reason": "Reason given",
            **changes,
        }
    )


def parent(**changes):
    values = {
        "id": uuid4(),
        "revision": 1,
        "variant_id": None,
        "status": "draft",
        "publication_receipt_id": None,
        "sealed": True,
        "title": "Old title",
        "purpose": "Old purpose",
        "visibility": "private",
        "use_cases": ["Use"],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def inherited(monkeypatch):
    holder = {}

    def fake(s, ctx, command, product, value):
        return definition_inherit.InheritedDefinition(holder["parent"], (), ())

    monkeypatch.setattr(definition_inherit, "validate", fake)
    return holder


def test_frozen_specification_goes_through_a_change_order(inherited):
    inherited["parent"] = parent(status="published", publication_receipt_id=uuid4())
    with pytest.raises(DomainError) as failed:
        definition_update.validate(None, None, None, None, payload())
    assert failed.value.detail["reason"] == "definition_frozen" and "变更单" in failed.value.message


def test_variant_definition_keeps_its_derive_path(inherited):
    inherited["parent"] = parent(variant_id=uuid4())
    with pytest.raises(DomainError) as failed:
        definition_update.validate(None, None, None, None, payload())
    assert failed.value.detail["reason"] == "definition_variant_update"


def test_sealed_g0_v1_continues_as_a_new_draft_with_only_the_changed_fields(inherited):
    inherited["parent"] = parent()
    value = definition_update.validate(None, None, None, None, payload())
    assert {change["path"] for change in value.changes} == {"title", "purpose"}
    assert value.fields["visibility"] == "private" and value.fields["title"] == "New title"


def test_payload_refuses_blank_duplicate_or_excluded_requirements():
    for bad in (
        {"title": "  "},
        {"use_cases": ["a", "a"]},
        {"requirements": ["x"], "exclusions": ["x"]},
        {"use_cases": []},
    ):
        with pytest.raises(ValueError):
            payload(**bad)
    assert "confirmation_token" not in definition_update.semantic(
        payload(confirmation_token="t" * 24)
    )
