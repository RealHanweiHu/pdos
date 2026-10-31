"""Work skill reaches real commands without changing identity or decision gates."""

import json
import re
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.command_usage import registry as usage
from pdos_next.agent_kernel.disclosure import disclosed_names
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import RunScope, WireAgentOutput
from pdos_next.contracts import PAYLOADS
from pdos_next.domain.quality_execution.evidence import POSITION
from pdos_next.errors import DomainError

WORK = {name for name in PAYLOADS if name.startswith("work.")}


@pytest.fixture
def loaded():
    return SkillCatalog().load("work_management", None, lambda *_: True)


@pytest.fixture
def scope():
    return RunScope(*(uuid4() for _ in range(7)), project_id=uuid4())


def test_work_skill_uses_native_wire_and_covers_all_actual_commands(loaded):
    assert loaded.metadata["output_schema"] == WireAgentOutput.model_json_schema()
    assert {name for name in loaded.operations if name.startswith("work.")} == WORK
    assert WORK and all(usage()[name].written for name in WORK)


@pytest.mark.parametrize("name", sorted(WORK))
def test_work_commands_need_loaded_enabled_skill_and_never_enter_child(name, loaded, scope):
    registry = default_registry()
    arguments = {"project_id": str(scope.project_id)}
    for skills, enabled in (({}, True), ({loaded.key: loaded}, False)):
        with pytest.raises(DomainError):
            registry.authorize(scope, name, arguments, skills, lambda *_, value=enabled: value)
    spec = registry.authorize(
        scope, name, arguments, {loaded.key: loaded}, lambda *_: True
    )
    assert spec.operation_key == name and spec.tier in {"T0", "T1"}
    assert name not in disclosed_names(registry)
    assert name in disclosed_names(registry, operations=loaded.operations)
    with pytest.raises(DomainError):
        registry.authorize(
            replace(scope, isolation="extract"), name, arguments,
            {loaded.key: loaded}, lambda *_: True,
        )
    with pytest.raises(DomainError):
        registry.authorize(
            scope, name, {**arguments, "requester_id": str(scope.requester_id)},
            {loaded.key: loaded}, lambda *_: True,
        )


def test_work_documented_task_is_valid_domain_input_without_model_authority(loaded):
    raw = re.findall(r"```json work.task.create\n(.*?)\n```", loaded.content, re.S)
    assert len(raw) == 1
    value = json.loads(raw[0])
    payload = PAYLOADS["work.task.create"].model_validate(value)
    assert payload.outcomes[0].required and payload.sources[0].kind == "artifact"
    position = POSITION.fullmatch(payload.sources[0].position)
    assert position and position.group(1) == "1"
    assert position.group(2) == sha256("请整理噪声复验原件并交付可核对报告。".encode()).hexdigest()
    with pytest.raises(ValidationError):
        PAYLOADS["work.task.create"].model_validate({**value, "qualified": True})
    with pytest.raises(ValidationError):
        PAYLOADS["work.task.create"].model_validate({**value, "sources": []})


def test_change_completion_skill_retains_named_prepare_only_boundary():
    skill = SkillCatalog().configuration("change_control")
    registry = default_registry()
    assert skill.version == "0.1.1-draft"
    assert registry.get("change.effectivity.record").tier == "T1"
    assert usage()["change.effectivity.record"].written
    for name in ("change.verification.record", "change.close"):
        assert name in skill.operations
        assert usage()[name].written
        spec = registry.get(name)
        assert spec.tier == "T2-prepare-only" and spec.operation_key is None
