"""P87 第 8 项: a skill's context contract may declare a memory recipe (``x-memory``).

No database. The shipped packages do not declare one yet (registered remainder),
so the contract registry here is a temporary copy with a recipe added.
"""

import json
import shutil
from pathlib import Path

import pytest

from pdos_next.agent.kernel.context_projection import load_contracts
from pdos_next.agent.kernel.skills import SkillCatalog
from pdos_next.agent.memory import scope_assemble

PACKAGES = Path(scope_assemble.__file__).resolve().parents[1] / "skill_packages"


def packages(tmp_path, recipe, profile="project"):
    target = tmp_path / "skill_packages"
    shutil.copytree(PACKAGES, target)
    path = target / "context-schemas.json"
    data = json.loads(path.read_text())
    data["profiles"][profile]["x-memory"] = recipe
    path.write_text(json.dumps(data, ensure_ascii=False))
    return target


def test_a_declared_recipe_travels_with_the_skill_and_changes_its_version_identity(tmp_path):
    declared = {"personal": ["notes", "recent_episodes"],
                "scope_notes": {"anchors": ["project", "category"], "customer_tag": "same_only",
                                "budget_tokens": 600},
                "scope_recent": {"budget_tokens": 300}, "knowledge": ["design_rules"]}
    shipped = SkillCatalog()
    catalog = SkillCatalog(packages(tmp_path, declared))
    skill = catalog.configuration("work_management")
    assert skill.metadata["context_schema"]["x-memory"] == declared
    assert scope_assemble.recipe((skill,)) == {
        "scope_notes": {"anchors": ["project", "category"], "customer_tag": "same_only",
                        "pinned_only": False, "budget_tokens": 600},
        "scope_recent": {"budget_tokens": 300}}
    # 改配方就是改技能包版本: the digest a qualification is bound to moves with the recipe.
    assert skill.digest != shipped.configuration("work_management").digest
    # A skill on another profile is untouched, and without any declaration the default applies.
    other = catalog.configuration("proposal_drafting")
    assert other.digest == shipped.configuration("proposal_drafting").digest
    assert scope_assemble.recipe((other,)) == scope_assemble.DEFAULT_RECIPE


@pytest.mark.parametrize("recipe", [
    {"scope_notes": {"anchors": ["session"]}},
    {"scope_notes": {"anchors": []}},
    {"scope_notes": {"customer_tag": "all"}},
    {"scope_notes": {"budget_tokens": 801}},
    {"scope_recent": {"budget_tokens": 0}},
    {"scope_notes": {"owner_id": "someone"}},
    {"everything": True},
    ["scope_notes"],
])
def test_a_recipe_the_server_cannot_honour_stops_the_catalog(tmp_path, recipe):
    with pytest.raises(ValueError):
        load_contracts(packages(tmp_path, recipe))


def test_shipped_contracts_still_load_and_declare_no_recipe_yet():
    data = load_contracts(PACKAGES)
    assert all("x-memory" not in schema for schema in data["profiles"].values())
