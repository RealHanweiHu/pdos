"""Memory M3 rules without a database: B6 switches (T27, T28), drafted-candidate admission
(T22, T25, T26), the draft-only skill package, draft preparation, fan-out start."""

import asyncio
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from pdos_next.agent.kernel.skills import SkillCatalog
from pdos_next.agent.memory import curation, distillation, fanout
from pdos_next.agent.memory.procedural import next_draft_version

NOW = datetime(2026, 11, 15, tzinfo=UTC)
SKILLS = Path(__file__).resolve().parents[3] / "pdos_next/agent/skill_packages"


# ---------------------------------------------------------------------------
# B6 is closed unless an evaluation switches it on.


def note(identity, statement, passage, **extra):
    return curation.Note(identity, 1, statement, "confirmer",
                         sources=(curation.Source(f"e-{identity}", passage),), **extra)


def test_b6_is_closed_by_default():
    assert curation.DEFAULT_SWITCHES == frozenset()
    for call in (lambda: curation.entry_check([], switches=None),
                 lambda: curation.due([], switches=frozenset()),
                 lambda: curation.residency([], [], switches={"entry_check"})):
        with pytest.raises(curation.Closed):
            call()
    with pytest.raises(ValueError):
        curation.require("rewrite_notes", {"rewrite_notes"})


def test_t27_entry_check_only_hints_and_never_changes_the_notes():
    passage = "样机在 1 米处测得整机噪音 ≤62 dB。气嘴材质为 POM。"
    notes = [
        note("same", "整机噪音 ≤62 dB", passage),
        note("drifted", "整机噪音 ≤65 dB", passage),
        note("absent", "客户要求外箱印英文标签", passage),
    ]
    frozen = [replace(item) for item in notes]

    def judge(statement, text):
        # A fake judge: supported only when the statement's words are in the passage.
        sentence = text.split("。")[0] + "。"
        return statement.replace(" ", "") in text.replace(" ", ""), sentence

    rules_only = curation.entry_check(notes, switches={"entry_check"}, judge=judge)
    assert [(hint.note_id, hint.kind) for hint in rules_only] == [("drifted", "value_mismatch")]
    assert rules_only[0].quote == "样机在 1 米处测得整机噪音 ≤62 dB。"
    with_model = curation.entry_check(notes, switches={"entry_check", "entry_check_model"},
                                      judge=judge)
    assert sorted((hint.note_id, hint.kind) for hint in with_model) == [
        ("absent", "claim_not_found"), ("drifted", "value_mismatch")]
    assert all(hint.confirmer_id == "confirmer" for hint in with_model)
    assert notes == frozen  # text, revision and everything else unchanged


def test_entry_check_drops_a_judge_quote_not_in_the_passage_and_flags_unreadable():
    passage = "额定电压 12 V。"
    hints = curation.entry_check(
        [note("n", "整机重量 2 kg", passage),
         curation.Note("gone", 1, "额定电压 12 V", "c", sources=(curation.Source("x", None),))],
        switches={"entry_check", "entry_check_model"},
        judge=lambda statement, text: (False, "并不存在的原句"))
    assert [(hint.note_id, hint.kind) for hint in hints] == [("gone", "source_unreadable")]


def test_entry_check_reports_conflict_with_the_current_object_value():
    hints = curation.entry_check(
        [note("n", "目标价 99 元", "报价单：目标价 99 元。",
              current_values=(("目标价", 109, "元"),))],
        switches={"entry_check"})
    assert [(hint.kind, hint.detail["current"]) for hint in hints] == [
        ("object_conflict", "109元")]


def test_cadence_priority_and_budget_pause_order():
    switches = {"entry_check"}
    fresh = note("fresh", "a", "a", carried=50, last_checked=NOW - timedelta(days=3),
                 watermark=(1, (2,)), checked_watermark=(1, (2,)))
    changed = note("changed", "a", "a", carried=1, last_checked=NOW - timedelta(days=3),
                   watermark=(1, (3,)), checked_watermark=(1, (2,)))
    old = note("old", "a", "a", carried=10, last_checked=NOW - timedelta(days=40),
               watermark=(1, (2,)), checked_watermark=(1, (2,)))
    never = note("never", "a", "a", carried=1)
    assert [item.note_id for item in curation.due([fresh, changed, old, never], now=NOW,
                                                  switches=switches)] == [
        "old", "never", "changed"]  # 40 天 × 10 次 > 从未核对（按 365 天）× 1 次 > 3 天
    costs = {"scope_brief": 30, "entry_check_model": 20, "distillation": 10}
    assert curation.paused(100, costs) == []
    assert curation.paused(35, costs) == ["scope_brief"]
    assert curation.paused(5, costs) == ["scope_brief", "entry_check_model", "distillation"]
    assert curation.concurrency_key("scope_brief", "project:1", "w") == \
        curation.concurrency_key("scope_brief", "project:1", "w")


def test_t28_residency_only_suggests_and_admin_sees_a_count():
    notes = [curation.OwnedNote(f"n{index}", "global", confirmed_at=NOW - timedelta(days=200))
             for index in range(10)]
    notes.append(curation.OwnedNote("unused", "global", confirmed_at=NOW - timedelta(days=200)))
    notes.append(curation.OwnedNote("searched", "project", resident=False,
                                    confirmed_at=NOW - timedelta(days=10)))
    runs = [curation.Usage(f"r{index}", NOW - timedelta(days=index + 1), "p1",
                           tuple((f"n{other}", "constraint") for other in range(10))
                           + (("searched", "search"),))
            for index in range(4)]
    before = list(notes)
    suggestions = curation.residency(notes, runs, now=NOW, switches={"residency"})
    found = {(item["note_id"], item["suggest"]) for item in suggestions}
    assert ("unused", "archive") in found and ("searched", "pin_or_widen") in found
    assert not any(item["suggest"] == "archive" and item["note_id"] != "unused"
                   for item in suggestions)
    assert notes == before
    assert curation.suggestion_count(suggestions) == {"suggestions": len(suggestions)}
    assert "note_id" not in json.dumps(curation.suggestion_count(suggestions))


def test_usage_rows_are_read_from_run_versions():
    row = SimpleNamespace(id=uuid4(), created_at=NOW, project_id=None, versions={
        "memory_usage": {"notes": [{"note_id": "a", "revision": 1, "zone": "constraint"}]},
        "memory_notes_context": {"omitted": 2}})
    (usage,) = curation.usage_from_runs([row])
    assert usage.notes == (("a", "constraint"),) and usage.omitted == 2


# ---------------------------------------------------------------------------
# 经验沉淀: drafted output is admitted only as candidates.


def evidence(source_type="business_record", receipt=True, root=None):
    return {"root_source_id": str(root or uuid4()), "source_type": source_type,
            "has_result_receipt": receipt}


def test_t22_a_single_case_is_only_a_case_record_with_locked_conditions():
    applicability = {"model": "P-200", "build": "EVT2", "condition": "-20℃ 冷启动"}
    accepted, rejected = distillation.admit([
        {"kind": "candidate_method", "statement": "O 圈换 FKM 可解决漏气",
         "applicability": applicability, "evidence": [evidence()]},
        {"kind": "candidate_method", "statement": "缺适用条件", "evidence": [evidence()]},
    ])
    assert [item["kind"] for item in accepted] == ["case_record"]
    assert accepted[0]["applicability"] == applicability and accepted[0]["status"] == "candidate"
    assert [item["reason"] for item in rejected] == ["applicability_required"]
    two, _ = distillation.admit([{
        "kind": "candidate_method", "statement": "O 圈换 FKM", "applicability": applicability,
        "evidence": [evidence(), evidence()], "counter_examples": ["P-100 常温无差异"]}])
    assert two[0]["kind"] == "candidate_method"


def test_t25_t26_root_sources_counted_once_and_xiaopai_output_is_not_a_source():
    root = uuid4()
    accepted, rejected = distillation.admit([
        {"kind": "scope_note", "statement": "报价含税",
         "evidence": [evidence(root=root), evidence(root=root), evidence(root=root)]},
        {"kind": "scope_note", "statement": "根因可能是模具温度",
         "evidence": [evidence("xiaopai_answer")]},
        {"kind": "scope_note", "statement": "已核实", "evidence": [evidence()],
         "epistemic": "verified"},
    ])
    assert accepted[0]["evidence_count"] == 1 and accepted[0]["epistemic"] == "stated"
    assert [item["reason"] for item in rejected] == ["no_root_source", "cannot_verify"]


def test_distillation_skill_is_registered_as_a_draft_only():
    assert SkillCatalog().configuration(distillation.SKILL_KEY) is None
    text = (SKILLS / "drafts/experience_distillation.md").read_text()
    header = yaml.safe_load(text[4:].split("\n---", 1)[0])
    assert header["key"] == distillation.SKILL_KEY and header["version"].endswith("-draft")
    for key in ("purpose", "input_schema", "output_schema", "context_requirements",
                "context_schema", "allowed_operations", "evidence_policy", "failure_policy",
                "budget", "model_capability_requirements", "evaluation_suite", "owner",
                "preload_when"):
        assert key in header
    tiers = {item["tool"]: item["tier"] for item in header["allowed_operations"]}
    assert tiers["knowledge.candidate.create"] == "T0" and tiers["scope_note.save"] == "T1"


def test_drafting_rules_and_deterministic_rule_are_separate():
    assert distillation.RULES["stale_on_revision"].drafts is None
    assert distillation.RULES["distill_project_closed"].events == ()
    assert "proposal.g0_decided" in fanout.FANOUT_EVENTS
    assert "issue.closed" in fanout.FANOUT_EVENTS


# ---------------------------------------------------------------------------
# Adopting a revision names a draft; preparing it never activates anything.


def test_next_draft_version():
    assert next_draft_version("0.1.3-draft") == "0.1.4-draft"
    assert next_draft_version("1.0.0") == "1.0.1-draft"


def test_prepare_skill_and_prompt_drafts_without_activation(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[4] / "tools/memory_revision_draft.py"
    spec = importlib.util.spec_from_file_location("memory_revision_draft", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    skills = tmp_path / "skills"
    skills.mkdir()
    shutil.copy(SKILLS / "quality_issue.md", skills / "quality_issue.md")
    shutil.copy(SKILLS / "context-schemas.json", skills / "context-schemas.json")
    base = yaml.safe_load((skills / "quality_issue.md").read_text()[4:].split("\n---", 1)[0])
    version = next_draft_version(base["version"])
    result = tool.prepare({"target_kind": "skill_package", "key": "quality_issue",
                           "base_version": base["version"], "draft_version": version},
                          skills=skills)
    assert result["activated"] is False
    assert (skills / "quality_issue.md").read_text() == (SKILLS / "quality_issue.md").read_text()
    assert f"version: {version}" in (skills / f"drafts/quality_issue-{version}.md").read_text()
    assert SkillCatalog(skills).configuration("quality_issue").version == base["version"]
    prompts = tmp_path / "prompts"
    shutil.copytree(SKILLS.parent / "prompt_packages", prompts)
    registry = json.loads((prompts / "registry.json").read_text())
    tool.prepare({"target_kind": "prompt", "key": "xiaopai.main",
                  "base_version": registry["active"], "draft_version": "1.0.9-draft"},
                 prompts=prompts)
    after = json.loads((prompts / "registry.json").read_text())
    assert after["active"] == registry["active"]
    assert {item["version"]: item["status"] for item in after["versions"]}["1.0.9-draft"] == \
        "draft"


# ---------------------------------------------------------------------------
# Fan-out start: one workflow per relevant event, nothing for other events.


class FakeClient:
    def __init__(self):
        self.started = []

    async def start_workflow(self, run, reference, **options):
        self.started.append((reference, options["id"]))


def envelope(kind):
    return SimpleNamespace(tenant_id=str(uuid4()), event_id=str(uuid4()), event_type=kind,
                           subject_id=str(uuid4()), subject_revision=2)


def test_fanout_starts_only_for_memory_events():
    client = FakeClient()
    assert asyncio.run(fanout.start(client, "q", envelope("product.created"))) is None
    event = envelope("proposal.item_patched")
    identity = asyncio.run(fanout.start(client, "q", event))
    assert identity == fanout.workflow_id(event) and client.started[0][1] == identity
    assert client.started[0][0]["event_type"] == "proposal.item_patched"
    tenant = uuid4()
    first = asyncio.run(fanout.start_daily(client, "q", tenant, today=NOW.date()))
    assert first.endswith("2026-11-15")
    assert asyncio.run(fanout.start_daily(client, "q", tenant, today=NOW.date())) is None
