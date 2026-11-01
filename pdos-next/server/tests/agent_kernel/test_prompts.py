import json
import shutil
from pathlib import Path

import pytest

from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.prompt_admin import create_draft, diff, register_draft
from pdos_next.agent_kernel.prompts import PromptCatalog
from pdos_next.agent_kernel.tools import default_registry

PACKAGE = Path(__file__).resolve().parents[2] / "pdos_next/prompt_packages"


def copy_package(tmp_path):
    target = tmp_path / "prompts"
    shutil.copytree(PACKAGE, target)
    return target


def test_active_prompt_is_independent_code_and_composes_the_same_skill_directory():
    catalog = PromptCatalog()
    active = catalog.active
    system, identity = active.compose([{"key": "synthetic", "purpose": "Synthetic only"}])
    assert active.key == "xiaopai.main" and active.version == "1.0.0"
    assert active.content.startswith("You are 小Pai, the single PDOS assistant.")
    expected_directory = '[{"key": "synthetic", "purpose": "Synthetic only"}]'
    assert system == active.content + "\nSkill directory:\n" + expected_directory
    assert identity == {
        "key": active.key,
        "version": active.version,
        "content_digest": active.digest,
        "system_digest": identity["system_digest"],
    }
    assert len(identity["system_digest"]) == 64


def test_unregistered_draft_does_not_break_or_change_the_active_prompt(tmp_path):
    package = copy_package(tmp_path)
    original = PromptCatalog(package).active
    draft = create_draft(package, "1.0.1-draft", source=original.version)
    path = package / "versions/1.0.1-draft.md"
    path.write_text(draft.content + "Synthetic draft instruction.\n")
    assert PromptCatalog(package).active.content == original.content
    with pytest.raises(ValueError, match="not registered"):
        PromptCatalog(package).version(draft.version)
    registered = register_draft(package, draft.version)
    assert registered.content.endswith("Synthetic draft instruction.\n")
    assert PromptCatalog(package).active.content == original.content
    patch = diff(package, original.version, registered.version)
    assert "--- xiaopai.main@1.0.0" in patch
    assert "+++ xiaopai.main@1.0.1-draft" in patch
    assert "+Synthetic draft instruction." in patch


def test_kernel_can_evaluate_a_registered_version_without_changing_the_default(tmp_path):
    package = copy_package(tmp_path)
    create_draft(package, "1.0.1-draft", source="1.0.0")
    candidate = PromptCatalog(package).version("1.0.1-draft")
    control = AgentKernel(None, default_registry())
    evaluation = AgentKernel(None, default_registry(), prompt=candidate)
    assert control.prompt.version == "1.0.0"
    assert evaluation.prompt.version == "1.0.1-draft"
    assert evaluation.system == control.system
    assert evaluation.prompt_identity["version"] == "1.0.1-draft"
    assert evaluation.prompt_identity["system_digest"] == control.prompt_identity["system_digest"]


def test_prompt_registry_rejects_path_escape_and_active_content_edits(tmp_path):
    package = copy_package(tmp_path)
    registry = package / "registry.json"
    data = json.loads(registry.read_text())
    data["versions"][0]["file"] = "../outside.md"
    registry.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inside the package"):
        PromptCatalog(package)

    package = copy_package(tmp_path / "second")
    active = PromptCatalog(package).active
    (package / "versions/1.0.0.md").write_text(active.content + "Unregistered active edit.\n")
    with pytest.raises(ValueError, match="not registered"):
        assert PromptCatalog(package).active.version == "1.0.0"
