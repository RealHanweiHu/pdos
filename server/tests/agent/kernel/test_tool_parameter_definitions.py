"""D255: every tool 小Pai can see carries the parameter model its handler validates."""

from uuid import uuid4

import pytest

from pdos_next.agent.kernel import tools
from pdos_next.agent.kernel.disclosure import disclosure, skill_operations
from pdos_next.agent.kernel.extract_schemas import ExtractInput
from pdos_next.agent.kernel.skills import SkillCatalog, SkillLoadInput

ISOLATIONS = ("main", "research", "extract", "mcp", "assistant_extract", "assistant_compare")


def every_operation():
    catalog = SkillCatalog()
    return skill_operations(
        catalog.load(item["key"], None, lambda *_: True) for item in catalog.index
    )


@pytest.mark.parametrize("isolation", ISOLATIONS)
def test_no_disclosed_tool_lacks_a_parameter_definition(isolation):
    """The 11-06 run sent evidence.extract and skill.load as a bare object."""
    for item in disclosure(tools.default_registry(), isolation, every_operation()):
        assert "properties" in item["parameters"], f"{item['name']} has no parameters"


def test_both_tools_are_defined_by_their_handler_models():
    definitions = {d["name"]: d["parameters"] for d in tools.default_registry().definitions()}
    assert definitions["evidence.extract"] == ExtractInput.model_json_schema()
    assert definitions["evidence.extract"]["required"] == ["row_schema"]
    assert definitions["skill.load"] == SkillLoadInput.model_json_schema()
    assert definitions["skill.load"]["required"] == ["name"]


def test_every_declared_row_schema_fills_the_extract_definition():
    catalog = SkillCatalog()
    declared = [
        declaration
        for item in catalog.index
        for declaration in catalog.configuration(item["key"]).row_schemas
    ]
    assert declared
    for declaration in declared:
        ExtractInput.model_validate({
            "artifact_version_ids": [str(uuid4())],
            "row_schema": declaration.model_dump(mode="json"),
        })


def test_a_read_without_a_parameter_model_is_refused_at_registry_build(monkeypatch):
    monkeypatch.setattr(tools, "READS", tools.READS | {"synthetic.unmodelled.read"})
    with pytest.raises(ValueError, match="synthetic.unmodelled.read"):
        tools.default_registry()
