"""Per-call tool disclosure derivation; no DB, model or network.

Checks the server-side derivation only. Wiring it into the graph, gateway and
the write/read proofs is a separate change; these cases pin the contract those
call sites will depend on.
"""

import pytest

from pdos_next.agent_kernel.disclosure import (
    CORE,
    check_growth,
    disclosed_names,
    disclosure,
    disclosure_digest,
    skill_operations,
)
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError


def catalog_skill(key):
    return SkillCatalog().load(key, None, lambda *_: True)


def test_disclosure_hides_exactly_what_authorize_would_refuse():
    """Nothing callable without a loaded skill may be hidden.

    This is the whole safety argument for the narrowing: both sides read
    ``ToolSpec.requires_loaded_skill``, so a run only stops seeing commands it
    would have been refused for asking.
    """
    registry = default_registry()
    names = frozenset(disclosed_names(registry, "main"))
    for item in registry.definitions("main"):
        spec = registry.get(item["name"])
        if not spec.requires_loaded_skill:
            assert item["name"] in names, f"{item['name']} is callable with no skill"
        else:
            assert item["name"] not in names


def test_no_loaded_skill_keeps_reads_and_t2_preparation():
    registry = default_registry()
    names = disclosed_names(registry, "main")
    assert "skill.load" in names
    # Reads never required a loaded skill to be authorized, so they stay visible.
    assert "conversation.history" in names
    assert "category.list" in names
    # T2 preparation is exempt from the skill requirement in authorize; hiding it
    # would remove a capability instead of removing payload.
    assert "proposal.g0.submit" in names
    assert "project.create" in names
    assert not [
        n for n in names if registry.get(n).tier in {"T0", "T1"} and registry.get(n).kind == "write"
    ]


def test_loaded_skill_discloses_exactly_its_own_write_tools():
    registry = default_registry()
    skill = catalog_skill("category_framing")
    operations = skill_operations([skill])
    names = frozenset(disclosed_names(registry, "main", operations))
    main = {item["name"] for item in registry.definitions("main")}
    disclosed_gated = {n for n in names if registry.get(n).requires_loaded_skill}
    expected = {n for n in operations if n in main and registry.get(n).requires_loaded_skill}
    assert disclosed_gated == expected
    assert expected, "category_framing is expected to own at least one write command"


def test_disclosure_is_a_strict_subset_of_the_full_list():
    registry = default_registry()
    full = [item["name"] for item in registry.definitions("main")]
    narrowed = disclosed_names(registry, "main", skill_operations([catalog_skill("jtbd")]))
    assert set(narrowed) < set(full)
    # Order must follow the registry so the digest is reproducible.
    assert list(narrowed) == [n for n in full if n in set(narrowed)]


def test_every_catalog_skill_narrows_the_surface():
    registry, catalog = default_registry(), SkillCatalog()
    full = len(registry.definitions("main"))
    for entry in catalog.index:
        skill = catalog.load(entry["key"], None, lambda *_: True)
        names = disclosed_names(registry, "main", skill_operations([skill]))
        assert len(names) < full, f"{entry['key']} disclosed the whole registry"


def test_loading_every_skill_still_hides_unowned_skill_gated_commands():
    registry, catalog = default_registry(), SkillCatalog()
    skills = [catalog.load(e["key"], None, lambda *_: True) for e in catalog.index]
    operations = skill_operations(skills)
    names = frozenset(disclosed_names(registry, "main", operations))
    hidden = {
        item["name"]
        for item in registry.definitions("main")
        if item["name"] not in names
    }
    assert hidden, "every registered command is skill-authorized; narrowing buys nothing"
    # Whatever stays hidden is skill-gated and listed by no skill in the catalog.
    for name in hidden:
        assert registry.get(name).requires_loaded_skill
        assert name not in operations


def test_isolated_subtask_disclosure_cannot_be_widened_by_a_skill():
    registry = default_registry()
    # public_research lists an original-text read that only the extract child may hold.
    operations = skill_operations([catalog_skill("public_research")])
    for isolation in ("research", "extract", "mcp"):
        allowed = {item["name"] for item in registry.definitions(isolation)}
        assert frozenset(disclosed_names(registry, isolation, operations)) <= allowed


def test_digest_matches_the_full_list_when_nothing_is_hidden():
    registry = default_registry()
    from pdos_next.service import digest

    every_write = {
        item["name"] for item in registry.definitions("main")
        if registry.get(item["name"]).kind == "write"
    }
    assert disclosure_digest(registry, "main", every_write) == digest(
        registry.definitions("main")
    )


def test_digest_is_stable_and_distinguishes_disclosures():
    registry = default_registry()
    one = skill_operations([catalog_skill("jtbd")])
    two = skill_operations([catalog_skill("jtbd"), catalog_skill("proposal_drafting")])
    assert disclosure_digest(registry, "main", one) == disclosure_digest(registry, "main", one)
    assert disclosure_digest(registry, "main", one) != disclosure_digest(registry, "main", two)


def test_disclosure_follows_the_write_surface_not_the_skill_identity():
    """jtbd and price_band list the same write commands, so they disclose the same.

    Disclosure is derived from allowed operations; it is not keyed on which
    skill happened to be loaded.
    """
    registry = default_registry()
    left = skill_operations([catalog_skill("jtbd")])
    right = skill_operations([catalog_skill("price_band")])
    writes = {
        n for n in left | right
        if registry.get(n).kind == "write"
    }
    assert {n for n in left if registry.get(n).kind == "write"} == writes
    assert disclosure_digest(registry, "main", left) == disclosure_digest(registry, "main", right)


def test_core_stays_disclosed_under_every_combination():
    registry, catalog = default_registry(), SkillCatalog()
    for entry in [None, *catalog.index]:
        operations = (
            () if entry is None
            else skill_operations([catalog.load(entry["key"], None, lambda *_: True)])
        )
        assert CORE <= frozenset(disclosed_names(registry, "main", operations))


def test_disclosure_may_only_grow_within_a_run():
    assert check_growth(("a", "b"), ("a", "b", "c")) == ("c",)
    assert check_growth((), ()) == ()
    with pytest.raises(DomainError) as error:
        check_growth(("a", "b"), ("a",))
    assert error.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError):
        check_growth(("a",), ("b",))


def test_model_supplied_shapes_are_refused():
    registry = default_registry()
    with pytest.raises(DomainError):
        disclosure(registry, "main", "proposal.item.patch")
    with pytest.raises(DomainError):
        disclosure(registry, "main", {"proposal.item.patch": True})
    with pytest.raises(DomainError):
        disclosure(registry, "main", ["", "proposal.item.patch"])
    with pytest.raises(DomainError):
        skill_operations([object()])


def test_run_records_an_append_only_disclosure_chain():
    from pdos_next.agent_kernel.disclosure import CHAIN_KEY, disclosed_in_run, record_disclosure

    versions = {"tool_definitions": {}}
    first = record_disclosure(versions, "main", ["a", "b"], "d1")
    versions = {**versions, CHAIN_KEY: first, "tool_definitions": {"main": "d1"}}
    second = record_disclosure(versions, "main", ["a", "b", "c"], "d2")
    versions = {**versions, CHAIN_KEY: second, "tool_definitions": {"main": "d2"}}
    # The widened list is current, and the earlier narrower one stays verifiable.
    assert disclosed_in_run(versions, "main", "d2")
    assert disclosed_in_run(versions, "main", "d1")
    assert not disclosed_in_run(versions, "main", "d3")
    assert second["main"]["chain"] == ["d1", "d2"]


def test_a_narrowed_or_swapped_disclosure_is_refused_within_a_run():
    from pdos_next.agent_kernel.disclosure import CHAIN_KEY, record_disclosure

    versions = {"tool_definitions": {"main": "d1"}, CHAIN_KEY: {
        "main": {"names": ["a", "b"], "chain": ["d1"]},
    }}
    with pytest.raises(DomainError) as error:
        record_disclosure(versions, "main", ["a"], "d2")
    assert error.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError):
        record_disclosure(versions, "main", ["a", "x"], "d2")


def test_isolations_keep_separate_chains():
    from pdos_next.agent_kernel.disclosure import CHAIN_KEY, disclosed_in_run, record_disclosure

    versions = {"tool_definitions": {}}
    versions = {**versions, CHAIN_KEY: record_disclosure(versions, "main", ["a"], "m1"),
                "tool_definitions": {"main": "m1"}}
    versions = {**versions, CHAIN_KEY: record_disclosure(versions, "research", ["r"], "r1"),
                "tool_definitions": {"main": "m1", "research": "r1"}}
    assert disclosed_in_run(versions, "main", "m1")
    assert disclosed_in_run(versions, "research", "r1")
    # A child's disclosure never counts as the main loop's, or the reverse.
    assert not disclosed_in_run(versions, "main", "r1")
    assert not disclosed_in_run(versions, "research", "m1")


def test_binding_operations_refuses_a_skill_that_changed_after_the_call():
    from types import SimpleNamespace

    from pdos_next.agent_kernel.disclosure import binding_operations

    catalog = SkillCatalog()
    skill = catalog.configuration("jtbd")
    good = SimpleNamespace(key=skill.key, version=skill.version, digest=skill.digest)
    assert binding_operations(catalog, [good]) == skill.operations
    for bad in (
        SimpleNamespace(key=skill.key, version="9.9.9", digest=skill.digest),
        SimpleNamespace(key=skill.key, version=skill.version, digest="0" * 64),
        SimpleNamespace(key="not_a_skill", version=skill.version, digest=skill.digest),
    ):
        with pytest.raises(DomainError) as error:
            binding_operations(catalog, [bad])
        assert error.value.code == "VERSION_CONFLICT"


def test_module_imports_cleanly_from_every_entry_point():
    """pdos_next.service reaches this module through contracts -> snapshot_command.

    A module-level ``from pdos_next.service import digest`` here is a circular
    import that pytest's own import order hides, so check it in a fresh
    interpreter the way a worker or an offline script would import it.
    """
    import subprocess
    import sys

    for module in (
        "pdos_next.service",
        "pdos_next.contracts",
        "pdos_next.agent_kernel.disclosure",
        "pdos_next.agent_kernel.snapshot_command",
        "pdos_next.agent_kernel.skills",
    ):
        done = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True, text=True, timeout=120,
        )
        assert done.returncode == 0, f"{module} does not import alone:\n{done.stderr[-800:]}"
