"""The declared context schema is executable and part of the skill identity."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pdos_next.agent_kernel.context_projection import combine_contracts, declared_contract, project
from pdos_next.agent_kernel.skills import SkillCatalog


def test_every_registered_skill_has_a_resolved_closed_context_contract_and_digest():
    catalog = SkillCatalog()
    assert catalog.index
    assert len({entry["key"] for entry in catalog.index}) == len(catalog.index)
    for entry in catalog.index:
        skill = catalog.configuration(entry["key"])
        schema = skill.metadata["context_schema"]
        assert schema["additionalProperties"] is False and schema["$defs"]
        metadata = deepcopy(skill.metadata)
        metadata["context_schema"]["$defs"]["category"]["description"] = "Changed contract"
        assert replace(skill, metadata=metadata).digest != skill.digest


def test_loaded_methods_union_their_declared_scope_and_drop_nested_unknowns_without_values():
    catalog = SkillCatalog()
    research = catalog.configuration("public_research")
    drafting = catalog.configuration("proposal_drafting")
    assert "proposal" not in combine_contracts(catalog, [research])["properties"]
    assert "proposal" in combine_contracts(catalog, [research, drafting])["properties"]
    schema = combine_contracts(catalog, [research])
    original = {"goal": "Synthetic", "sources": [], "category": {
        "id": "category", "name": "Pumps", "purpose": "Synthetic", "undeclared": "PRIVATE VALUE",
    }, "unrelated": {"raw": "PRIVATE VALUE"}}
    value, omitted, issues = project(original, schema)
    assert not issues and "undeclared" not in value["category"] and "unrelated" not in value
    assert omitted == [
        {"field": "/category/undeclared", "reason": "outside_skill_context_schema"},
        {"field": "/unrelated", "reason": "outside_skill_context_schema"},
    ]
    assert "PRIVATE VALUE" not in str(omitted) and original["unrelated"]["raw"] == "PRIVATE VALUE"
    _, _, missing = project({"goal": "Synthetic"}, schema)
    assert missing and missing[0]["reason"] == "context_required"


@pytest.mark.parametrize("reference", [
    "https://example.invalid/schema", "../secret.json", "context-schemas.json#/profiles/missing",
])
def test_skill_context_references_never_fetch_external_or_arbitrary_local_data(reference):
    with pytest.raises(ValueError):
        declared_contract({"$ref": reference}, SkillCatalog().contexts)
