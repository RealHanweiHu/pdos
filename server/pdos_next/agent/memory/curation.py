"""B6 后台整理：条目核对、常驻升降建议、节奏与预算 (target architecture §6.9; T27, T28).

Evaluation only. Every function here is closed unless the evaluation harness
passes the feature in ``switches``; there is no user route, no schedule and no
environment default that opens it (用户 11-12: 消融增益为正才上线, §8.4). The
output is hints and suggestions, never a change: no function here writes a note,
its state, its pin or its scope, and none raises a note's 可信状态.

* **条目核对** (``entry_check``): step 1 has no model: is each evidence source
  still there and readable; do the statement's numbers and units appear in the
  cited passage; does the statement conflict with the subject's current value.
  Step 2 (``entry_check_model``) asks a judge one question, "does the passage
  support the statement?", and keeps the answer only when the quoted sentence is
  really in the passage. The judge is an injected port; nothing here calls a
  provider. Hints go to the note's confirmer.
* **常驻升降建议** (``residency``): deterministic signals from the owner's own
  usage lists (``memory_usage.notes`` on their Runs) and correction marks:
  pin or widen, archive, narrow, unpin or revise, clean up. For the owner only.
* **节奏与预算**: who is due (``due``), in which order (carried count × days
  since the last check), and which model tasks stop first when the budget runs
  short (``paused``).

How to switch it in an ablation run: see
``docs/reports/evidence/pdos-next-memory-m3-20261115/README.md`` §B6.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

FEATURES = frozenset({"entry_check", "entry_check_model", "residency"})
# Nothing is open by default, for anyone (§8.4 消融为正才上线).
DEFAULT_SWITCHES = frozenset()

CHECK_INTERVAL = timedelta(days=30)
ARCHIVE_AFTER = timedelta(days=90)
SEARCH_HITS_FOR_PIN = 3
OVERFLOW_RUNS_FOR_CLEANUP = 3
# 预算不够时只停调用模型的任务：先停范围简报，再停条目核对，经验沉淀最后停 (§6.9).
PAUSE_ORDER = ("scope_brief", "entry_check_model", "distillation")
MODEL_TASKS = frozenset(PAUSE_ORDER)


class Closed(RuntimeError):
    """A B6 feature was asked for without being switched on for this evaluation."""


def require(feature, switches):
    if feature not in FEATURES:
        raise ValueError(f"Unknown B6 feature {feature!r}")
    if feature not in frozenset(switches or DEFAULT_SWITCHES):
        raise Closed(f"B6 {feature} is closed; it opens only inside an evaluation run")


# ---------------------------------------------------------------------------
# 条目核对

UNITS = ("dB", "dBA", "mm", "cm", "m", "kg", "g", "N", "kPa", "MPa", "Pa", "bar", "psi", "V",
         "mV", "A", "mA", "W", "kW", "Hz", "kHz", "rpm", "s", "ms", "min", "h", "℃", "°C", "%",
         "L", "mL", "天", "小时", "分钟", "秒", "毫米", "厘米", "米", "公斤", "克", "元", "次",
         "台", "件", "个")
_UNIT = "|".join(sorted((re.escape(unit) for unit in UNITS), key=len, reverse=True))
QUANTITY = re.compile(
    rf"(?P<op>[≤≥<>=±]|不超过|不低于|小于|大于|至少|最多)?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})")
SENTENCE = re.compile(r"[^。；;！!？?\n]+[。；;！!？?]?")


def quantities(value):
    return [(match["op"] or "", float(match["num"]), match["unit"], match.group(0).strip())
            for match in QUANTITY.finditer(value or "")]


def _sentence(passage, needle):
    for sentence in SENTENCE.findall(passage):
        if needle in sentence:
            return sentence.strip()
    return None


@dataclass(frozen=True)
class Source:
    """One evidence link as the confirmer can read it now (``text`` None: unreadable)."""

    evidence_id: str
    text: str | None


@dataclass(frozen=True)
class Note:
    note_id: str
    revision: int
    statement: str
    confirmer_id: str
    sources: tuple[Source, ...] = ()
    # The subject's current structured values as (label, value, unit), if any.
    current_values: tuple[tuple[str, float, str], ...] = ()
    carried: int = 0
    last_checked: datetime | None = None
    # (note revision, source versions) now, and as they were at the last check.
    watermark: tuple = ()
    checked_watermark: tuple | None = None


@dataclass
class Hint:
    note_id: str
    revision: int
    confirmer_id: str
    kind: str  # claim_not_found | value_mismatch | object_conflict | source_unreadable
    quote: str | None
    detail: dict = field(default_factory=dict)


def rule_check(note):
    """Step 1, no model."""
    hints = []
    readable = [source for source in note.sources if source.text is not None]
    for source in note.sources:
        if source.text is None:
            hints.append(Hint(note.note_id, note.revision, note.confirmer_id,
                              "source_unreadable", None, {"evidence_id": source.evidence_id}))
    for op, number, unit, written in quantities(note.statement):
        found = [(source, item) for source in readable for item in quantities(source.text)
                 if item[2] == unit]
        if found and not any(item[1] == number and item[0] == op for _source, item in found):
            source, item = found[0]
            hints.append(Hint(note.note_id, note.revision, note.confirmer_id, "value_mismatch",
                              _sentence(source.text, item[3]),
                              {"statement": written, "source": item[3],
                               "evidence_id": source.evidence_id}))
        for label, value, current_unit in note.current_values:
            if current_unit == unit and value != number:
                hints.append(Hint(note.note_id, note.revision, note.confirmer_id,
                                  "object_conflict", None,
                                  {"statement": written, "field": label,
                                   "current": f"{value:g}{current_unit}"}))
    return hints


def model_check(note, judge):
    """Step 2: the judge answers (supported, quote); the quote must be in the passage."""
    hints = []
    for source in note.sources:
        if source.text is None:
            continue
        supported, quote = judge(note.statement, source.text)
        if not quote or quote not in source.text:
            continue  # an answer that cannot be traced to the passage is dropped
        if not supported:
            hints.append(Hint(note.note_id, note.revision, note.confirmer_id,
                              "claim_not_found", quote, {"evidence_id": source.evidence_id}))
    return hints


def entry_check(notes, *, switches, judge=None):
    """Hints for the confirmers. The notes themselves are returned untouched."""
    require("entry_check", switches)
    hints = []
    for note in notes:
        found = rule_check(note)
        if not found and judge is not None and "entry_check_model" in switches:
            found = model_check(note, judge)
        hints.extend(found)
    return hints


def due(notes, *, now=None, switches):
    """Which notes to check now, highest priority first (被带入次数 × 距上次核对的天数)."""
    require("entry_check", switches)
    now = now or datetime.now(UTC)
    ready = []
    for note in notes:
        last = note.last_checked
        # 条目和来源的版本都没变，30 天内不再核对；来源或条目出新版本时不受此限。
        changed = last is not None and note.checked_watermark != note.watermark
        if last is not None and not changed and now - last < CHECK_INTERVAL:
            continue
        days = max((now - last).days, 1) if last else 365
        ready.append((max(note.carried, 1) * days, note))
    return [note for _score, note in sorted(ready, key=lambda pair: (-pair[0], pair[1].note_id))]


def paused(remaining_budget, costs):
    """Model tasks to stop, in order, until the rest fits; deterministic tasks never stop."""
    stopped, needed = [], sum(costs.get(task, 0) for task in MODEL_TASKS)
    for task in PAUSE_ORDER:
        if needed <= remaining_budget:
            break
        if costs.get(task):
            stopped.append(task)
            needed -= costs[task]
    return stopped


def concurrency_key(task, scope, watermark):
    """同一范围同一类任务同时只有一个：编号由范围和来源水位算出。"""
    from pdos_next.core.service import digest

    return f"pdos-memory-curation:{task}:{digest([task, scope, watermark])[:32]}"


# ---------------------------------------------------------------------------
# 常驻升降建议


@dataclass(frozen=True)
class Usage:
    """One of the owner's Runs: which notes it carried or found, and how it went."""

    run_id: str
    at: datetime
    project_id: str | None
    notes: tuple[tuple[str, str], ...]  # (note_id, zone: constraint | background | search)
    corrected: bool = False
    omitted: int = 0


@dataclass(frozen=True)
class OwnedNote:
    note_id: str
    scope_kind: str
    resident: bool = True  # global or in-scope notes ride along every matching Run
    confirmed_at: datetime | None = None


def residency(notes, runs, *, now=None, switches):
    """Suggestions for the owner only; applying one is the owner's own click."""
    require("residency", switches)
    now = now or datetime.now(UTC)
    recent = [run for run in runs if now - run.at <= ARCHIVE_AFTER]
    carried, searched, projects, corrected = {}, {}, {}, {}
    for run in recent:
        for note_id, zone in run.notes:
            bucket = searched if zone == "search" else carried
            bucket[note_id] = bucket.get(note_id, 0) + 1
            projects.setdefault(note_id, set()).add(run.project_id)
            if run.corrected and zone != "search":
                corrected[note_id] = corrected.get(note_id, 0) + 1
    suggestions = []
    for note in notes:
        identity = note.note_id
        old_enough = note.confirmed_at is None or now - note.confirmed_at >= ARCHIVE_AFTER
        if not note.resident and searched.get(identity, 0) >= SEARCH_HITS_FOR_PIN:
            suggestions.append({"note_id": identity, "suggest": "pin_or_widen",
                                "basis": {"searched": searched[identity]}})
        if note.resident and old_enough and not carried.get(identity) \
                and not searched.get(identity):
            suggestions.append({"note_id": identity, "suggest": "archive",
                                "basis": {"days_unused": ARCHIVE_AFTER.days}})
        used_in = projects.get(identity, set())
        if note.scope_kind == "global" and len(used_in) == 1 and None not in used_in \
                and carried.get(identity, 0) + searched.get(identity, 0) >= 2:
            suggestions.append({"note_id": identity, "suggest": "narrow_scope",
                                "basis": {"project_id": next(iter(used_in))}})
        if corrected.get(identity):
            suggestions.append({"note_id": identity, "suggest": "unpin_or_revise",
                                "basis": {"corrected_runs": corrected[identity]}})
    overflowing = [run for run in recent if run.omitted > 0]
    if len(overflowing) >= OVERFLOW_RUNS_FOR_CLEANUP:
        last_used = {}
        for run in recent:
            for note_id, _zone in run.notes:
                last_used[note_id] = max(last_used.get(note_id, run.at), run.at)
        stale = sorted(notes, key=lambda note: (last_used.get(note.note_id,
                       datetime.min.replace(tzinfo=UTC)), note.note_id))[:3]
        suggestions.append({"note_id": None, "suggest": "cleanup",
                            "basis": {"overflow_runs": len(overflowing),
                                      "least_used": [note.note_id for note in stale]}})
    return suggestions


def suggestion_count(suggestions):
    """What an administrator may see (T28): a number, never the notes or suggestions."""
    return {"suggestions": len(suggestions)}


def usage_from_runs(rows):
    """Usage rows from AgentRun rows read as their owner (versions.memory_usage.notes)."""
    result = []
    for row in rows:
        usage = (row.versions or {}).get("memory_usage") or {}
        context = (row.versions or {}).get("memory_notes_context") or {}
        result.append(Usage(
            run_id=str(row.id), at=row.created_at, project_id=str(row.project_id)
            if row.project_id else None,
            notes=tuple((item["note_id"], item.get("zone", "search"))
                        for item in usage.get("notes") or []),
            omitted=int(context.get("omitted") or 0) if isinstance(context, dict) else 0))
    return result
