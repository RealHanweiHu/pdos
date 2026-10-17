"""Executable skill examples and native wire contracts; no DB, model or network."""

import json
import re
from copy import deepcopy

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.category_candidate import CategoryCandidateInput
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import WireAgentOutput
from pdos_next.domain.preproject.evidence_schemas import ClaimWithdraw
from pdos_next.research.tools import FanoutInput

SKILLS = ("category_framing", "proposal_drafting", "public_research")


def skill(key):
    return SkillCatalog().load(key, None, lambda *_: True)


def example(key, contract):
    matches = re.findall(rf"```json {re.escape(contract)}\n(.*?)\n```", skill(key).content, re.S)
    assert len(matches) == 1, f"Expected one executable {contract} example"
    return json.loads(matches[0])


@pytest.mark.parametrize("key", SKILLS)
def test_skill_declares_actual_native_wire_schema(key):
    current = skill(key)
    assert current.metadata["output_schema"] == WireAgentOutput.model_json_schema()
    assert current.version == ("0.2.3-draft" if key == "proposal_drafting" else "0.2.2-draft")
    registry = default_registry()
    for operation in current.metadata["allowed_operations"]:
        assert registry.get(operation["tool"]).tier == operation["tier"]
    SkillCatalog().validate_registry(registry)


def test_documented_clarification_round_trip_and_three_question_limit():
    raw = example("category_framing", "wire")
    wire = WireAgentOutput.model_validate(raw)
    question = wire.questions[0]
    assert wire.status == "needs_input"
    assert question.recommended.value in {o.value for o in question.options}
    assert question.recommended.reason
    assert "assumptions" in json.loads(wire.result_json)
    assert "answer" not in raw["questions"][0]
    assert "preselected" not in raw["questions"][0]
    raw["questions"] *= 4
    with pytest.raises(ValidationError):
        WireAgentOutput.model_validate(raw)


def test_documented_category_maps_boundary_scenario_assumption_and_unknown_parameters():
    raw = example("category_framing", "category.create")
    candidate = CategoryCandidateInput.model_validate(raw)
    assert set(raw) == {"key", "name", "purpose", "groups"}
    knowledge = {entry.kind: entry for entry in candidate.groups.knowledge}
    assert knowledge["boundary"].content["definition"]
    assert knowledge["boundary"].content["edge_cases"]
    assert knowledge["segment"].content["jtbd"]
    assert set(knowledge["research_question"].content["assumption"]) == {
        "statement", "basis", "validation", "related",
    }
    parameter = candidate.groups.parameters[0]
    assert parameter.change_note
    assert parameter.standard_condition is None
    assert parameter.method is None
    assert parameter.acceptance_criterion is None
    assert candidate.groups.snapshot_refs == []


@pytest.mark.parametrize("invalid_field", ["parameter_skeleton", "assumptions", "research"])
def test_display_fields_cannot_be_passed_as_category_tool_arguments(invalid_field):
    raw = example("category_framing", "category.create")
    raw[invalid_field] = []
    with pytest.raises(ValidationError):
        CategoryCandidateInput.model_validate(raw)


def test_parameter_expert_pending_is_a_research_question_not_a_parameter_field():
    raw = example("category_framing", "category.create")
    invalid = deepcopy(raw)
    invalid["groups"]["parameters"][0]["expert_pending"] = True
    with pytest.raises(ValidationError):
        CategoryCandidateInput.model_validate(invalid)
    del raw["groups"]["parameters"][0]["change_note"]
    with pytest.raises(ValidationError):
        CategoryCandidateInput.model_validate(raw)


def test_research_example_has_only_actual_task_inputs():
    raw = example("public_research", "research.fanout")
    assert FanoutInput.model_validate(raw).tasks[0].focus
    raw["tasks"][0]["parameter_refs"] = []
    with pytest.raises(ValidationError):
        FanoutInput.model_validate(raw)


def test_claim_withdraw_example_is_actual_t1_without_confirmation_fabrication():
    raw = example("proposal_drafting", "evidence.claim.withdraw")
    assert ClaimWithdraw.model_validate(raw).confirmation_token is None
    assert "evidence.claim.withdraw" in skill("proposal_drafting").operations
    assert default_registry().get("evidence.claim.withdraw").tier == "T1"
