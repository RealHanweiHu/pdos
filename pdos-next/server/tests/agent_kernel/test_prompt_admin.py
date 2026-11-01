import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pdos_next.agent_kernel.prompt_admin import (
    activate,
    assert_evaluation_current,
    create_draft,
    register_draft,
    rollback,
)
from pdos_next.agent_kernel.prompts import PromptCatalog
from pdos_next.agent_kernel.skills import SkillCatalog

PACKAGE = Path(__file__).resolve().parents[2] / "pdos_next/prompt_packages"


def package(tmp_path):
    target = tmp_path / "prompts"
    shutil.copytree(PACKAGE, target)
    return target


def report(directory, candidate, status="passed"):
    current = PromptCatalog(directory).active
    index = SkillCatalog().index
    _, baseline_identity = current.compose(index)
    _, candidate_identity = candidate.compose(index)
    return {
        "schema": "xiaopai-prompt-ab/v1",
        "control_status": status,
        "quality_status": "not_scored",
        "baseline": {
            "key": current.key,
            "version": current.version,
            "content_digest": current.digest,
            **baseline_identity,
        },
        "candidate": {
            "version": candidate.version,
            "content_digest": candidate.digest,
            **candidate_identity,
        },
        "inputs": {"source_sha256": {"synthetic.py": "0" * 64}},
    }


def activate_report(directory, candidate, value):
    return activate(
        directory, candidate.version, expected_active=PromptCatalog(directory).active_version,
        evaluation=value, reviewer="Synthetic Reviewer",
        current_sources=value["inputs"]["source_sha256"],
    )


def test_draft_activation_and_rollback_preserve_content_and_history(tmp_path):
    directory = package(tmp_path)
    original = PromptCatalog(directory).active
    draft = create_draft(directory, "1.0.1-draft", source=original.version)
    path = directory / "versions/1.0.1-draft.md"
    path.write_text(draft.content + "Synthetic reviewed improvement.\n")
    candidate = register_draft(directory, draft.version)
    with pytest.raises(ValueError, match="Active prompt changed"):
        activate(directory, candidate.version, expected_active="9.9.9",
                 evaluation=report(directory, candidate), reviewer="Synthetic Reviewer",
                 current_sources={})
    with pytest.raises(ValueError, match="passing evaluation"):
        activate_report(directory, candidate, report(directory, candidate, "failed"))
    activated = activate_report(directory, candidate, report(directory, candidate))
    assert activated.content == candidate.content
    with pytest.raises(ValueError, match="Only an editable draft"):
        register_draft(directory, candidate.version)
    restored = rollback(
        directory, original.version, expected_active=candidate.version,
        reviewer="Synthetic Reviewer", reason="Synthetic rollback verification",
    )
    assert restored.content == original.content
    data = json.loads((directory / "registry.json").read_text())
    assert [item["kind"] for item in data["history"]] == ["activate", "rollback"]
    assert data["history"][0]["quality_status"] == "not_scored"
    assert {item["status"] for item in data["versions"]} == {"active", "published"}


@pytest.mark.parametrize("version", ["../../escaped", "not semver", "/tmp/escaped"])
def test_invalid_draft_version_has_no_filesystem_or_registry_side_effect(tmp_path, version):
    directory = package(tmp_path)
    before = (directory / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="Invalid prompt version"):
        create_draft(directory, version, source="1.0.0")
    assert (directory / "registry.json").read_bytes() == before
    assert not (tmp_path / "escaped.md").exists()


def test_existing_orphan_draft_is_never_deleted_by_failed_creation(tmp_path):
    directory = package(tmp_path)
    orphan = directory / "versions/1.0.1-draft.md"
    orphan.write_text("Unregistered edits that must survive.\n")
    before = (directory / "registry.json").read_bytes()
    with pytest.raises(FileExistsError):
        create_draft(directory, "1.0.1-draft", source="1.0.0")
    assert orphan.read_text() == "Unregistered edits that must survive.\n"
    assert (directory / "registry.json").read_bytes() == before


def test_activation_binds_exact_candidate_baseline_system_and_sources(tmp_path):
    directory = package(tmp_path)
    candidate = create_draft(directory, "1.0.1-draft", source="1.0.0")
    value = report(directory, candidate)
    value["candidate"]["content_digest"] = "0" * 64
    with pytest.raises(ValueError, match="exact prompt"):
        activate_report(directory, candidate, value)
    value = report(directory, candidate)
    value["baseline"]["version"] = "0.0.1"
    with pytest.raises(ValueError, match="exact prompt"):
        activate_report(directory, candidate, value)
    value = report(directory, candidate)
    with pytest.raises(ValueError, match="stale"):
        activate(
            directory, candidate.version, expected_active="1.0.0", evaluation=value,
            reviewer="Synthetic Reviewer",
            current_sources={**value["inputs"]["source_sha256"], "new.py": "1" * 64},
        )
    assert PromptCatalog(directory).active.version == "1.0.0"


def test_tampered_candidate_cannot_be_activated_or_change_registry(tmp_path):
    directory = package(tmp_path)
    candidate = create_draft(directory, "1.0.1-draft", source="1.0.0")
    value = report(directory, candidate)
    (directory / "versions/1.0.1-draft.md").write_text(candidate.content + "Tampered.\n")
    before = (directory / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="not registered"):
        activate_report(directory, candidate, value)
    assert (directory / "registry.json").read_bytes() == before


def test_tampered_rollback_target_leaves_active_and_history_unchanged(tmp_path):
    directory = package(tmp_path)
    candidate = create_draft(directory, "1.0.1-draft", source="1.0.0")
    activate_report(directory, candidate, report(directory, candidate))
    original = (directory / "versions/1.0.0.md").read_text()
    (directory / "versions/1.0.0.md").write_text(original + "Tampered rollback target.\n")
    before = (directory / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="not registered"):
        rollback(directory, "1.0.0", expected_active=candidate.version,
                 reviewer="Synthetic Reviewer", reason="Synthetic tamper check")
    assert (directory / "registry.json").read_bytes() == before
    assert PromptCatalog(directory).active.version == candidate.version


def test_concurrent_activation_cannot_lose_history_or_replace_expected_active(tmp_path):
    directory = package(tmp_path)
    candidate = create_draft(directory, "1.0.1-draft", source="1.0.0")
    value = report(directory, candidate)

    def attempt():
        try:
            activate(
                directory, candidate.version, expected_active="1.0.0", evaluation=value,
                reviewer="Synthetic Reviewer",
                current_sources=value["inputs"]["source_sha256"],
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [False, True]
    data = json.loads((directory / "registry.json").read_text())
    assert data["active"] == candidate.version and len(data["history"]) == 1


def test_evaluation_source_fingerprint_rejects_stale_code(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("value = 1\n")
    current = hashlib.sha256(source.read_bytes()).hexdigest()
    value = {"inputs": {"source_sha256": {"source.py": current}}}
    assert_evaluation_current(value, tmp_path)
    assert_evaluation_current(value, current_hashes=value["inputs"]["source_sha256"])
    source.write_text("value = 2\n")
    with pytest.raises(ValueError, match="stale"):
        assert_evaluation_current(value, tmp_path)
    with pytest.raises(ValueError, match="stale"):
        assert_evaluation_current(value, current_hashes={})
    with pytest.raises(ValueError, match="stale"):
        assert_evaluation_current(
            {"inputs": {"source_sha256": {"../outside.py": current}}}, tmp_path,
        )
