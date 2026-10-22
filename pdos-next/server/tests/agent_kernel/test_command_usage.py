"""Calling notes are a registered, required part of a command; no DB, model or network."""

import pytest

from pdos_next.agent_kernel.command_usage import PENDING_LIMIT, pending, registry, require
from pdos_next.agent_kernel.tools import COMPUTE, M3_TIERS, READS, default_registry
from pdos_next.contracts import PAYLOADS
from pdos_next.errors import DomainError


def test_every_registered_tool_has_a_calling_note():
    known = set(registry())
    for item in default_registry().definitions("main"):
        assert item["name"] in known, f"{item['name']} reaches 小Pai with no registered note"


def test_a_new_domain_command_cannot_reach_the_model_unregistered():
    with pytest.raises(DomainError) as error:
        require([*PAYLOADS, "change.invented.command"])
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert "change.invented.command" in error.value.detail["operations"]


def test_unwritten_notes_may_only_decrease():
    assert len(pending()) <= PENDING_LIMIT, (
        f"{len(pending())} commands lack 何时调用, above the {PENDING_LIMIT} ratchet; "
        "write the note instead of raising the cap"
    )


def test_no_description_is_generated_from_the_name_alone():
    generated = set(PAYLOADS) | READS | COMPUTE | set(M3_TIERS) | {"skill.load"}
    for item in default_registry().definitions("main"):
        description = item["description"]
        # Either a written note, or an explicit statement that it is unwritten.
        assert description.rstrip("。") != item["name"]
        assert len(description) > len(item["name"]) + 4
        # MCP and research have explicit calling notes in their own ToolSpecs.
        if item["name"] in generated and not registry()[item["name"]].written:
            assert "何时调用尚未登记" in description


def test_written_notes_never_claim_an_unregistered_effect():
    for _name, usage in registry().items():
        if usage.produces is not None:
            assert usage.produces and "." in usage.produces
        assert usage.source in {"v1.1 附录 A", "DC-11 档位政策"}
        assert usage.tier in {"T0", "T1", "T2", "T2-prepare-only", "READ"}


def test_prepare_only_reads_as_preparation_not_execution():
    registered = default_registry()
    for item in registered.definitions("main"):
        spec = registered.get(item["name"])
        if spec.tier == "T2-prepare-only":
            assert not item["description"].startswith("办理")
        if spec.kind == "read" and spec.tier == "READ":
            assert not item["description"].startswith("办理")
