"""程序性汇总与修订候选审核 (memory design §6.4, §14.8; P88 第 3、4 项).

* **汇总**: a daily system pass (``memory_summarize_procedural``, deterministic
  SQL) counts the last 30 days of run feedback and explicit source exclusions
  per "tenant × target (loaded skill version, or the main prompt) × tool ×
  reason". A group reaching the threshold (5, initial value) becomes one
  candidate with up to five sample Runs. No text is copied and no model drafts
  anything here; a model-drafted diff stays a remainder (it would be a
  candidate too).
* **审核**: a current tenant administrator, named, adopts or rejects. The
  database lets nobody else read or decide (s0_0899).
* **采纳**: names the draft version to prepare (the next patch version, marked
  ``-draft``) and how to prepare it. Preparing the draft is an offline step
  (``tools/memory_revision_draft.py``): a prompt draft goes into the prompt
  registry as ``draft``; a skill-package draft goes under
  ``skill_packages/drafts/``, which the skill catalog never loads. Activation is
  not here: a prompt still needs ``tools/xiaopai_prompt.py activate`` with a
  passed A/B evaluation and a named reviewer; a skill still needs its
  golden-case run and ``ai.skill.enable`` / ``ai.skill.qualify``, after which
  existing T0 qualifications are re-reviewed (v1.1 §06.12).
* **永远不能改**: frozen-prefix safety rules, permission and write tiers,
  engineering thresholds, approval policy, evaluation gold standards. A
  candidate only ever points at a skill package or the main prompt; golden
  cases are never a target.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .m3_models import SkillRevisionCandidate, SkillRevisionDecision

THRESHOLD = 5  # P88 第 3 项 初始值
WINDOW_DAYS = 30
REASON_LABELS = {
    "wrong_object": "对象错", "wrong_value": "数值错", "missing_source": "缺来源",
    "not_useful": "没用", "too_many_actions": "动作太多", "should_not_automate": "不该自动做",
    "excluded_source": "用户排除了来源",
}
NEVER_CHANGED = ("冻结前缀里的安全规则", "权限与写入档位", "工程阈值", "批准政策", "评测金标准")
DRAFT_TOOL = "tools/memory_revision_draft.py"
PROMPTS = Path(__file__).resolve().parents[1] / "prompt_packages"
ACTIVATION = {
    "prompt": "tools/xiaopai_prompt.py evaluate → activate（须 A/B 通过与具名评审人）",
    "skill_package": "跑该技能的 golden-case 与回归题 → ai.skill.enable / "
                     "ai.skill.qualify（具名），"
                     "已有 T0 资格按 v1.1 §06.12 重审",
}


def summarize(session, tenant_id, *, as_of=None, threshold=THRESHOLD):
    """Run the deterministic daily summary; returns how many candidates it added."""
    as_of = as_of or datetime.now(UTC)
    return session.scalar(text("SELECT public.memory_summarize_procedural(:t, :at, :n)"),
                          {"t": tenant_id, "at": as_of, "n": threshold})


def _admin(session, ctx):
    from .corrections import _human

    _human(session, ctx)
    if not session.scalar(text("SELECT public.account_administrator()")):
        raise DomainError("ADMINISTRATOR_REQUIRED", "修订候选只由租户管理员本人审核。", 403)


def next_draft_version(version):
    """0.1.3-draft → 0.1.4-draft; 1.0.0 → 1.0.1-draft. Never reuses the base version."""
    found = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.]+)?", version or "")
    if not found:
        raise DomainError("VALIDATION_FAILED", "原版本号无法递增为草稿版本。", 422,
                          detail={"reason_key": "unparseable_version"})
    major, minor, patch = map(int, found.groups())
    return f"{major}.{minor}.{patch + 1}-draft"


def view(session, row, decision=None):
    decision = decision or session.scalar(select(SkillRevisionDecision).where(
        SkillRevisionDecision.candidate_id == row.id))
    return {
        "candidate_id": str(row.id),
        "target": {"kind": row.target_kind, "key": row.target_key, "version": row.target_version},
        "tool": row.tool or None,
        "reason": row.reason, "reason_label": REASON_LABELS.get(row.reason, row.reason),
        "window": {"start": row.window_start.isoformat(), "end": row.window_end.isoformat()},
        "signal_count": row.signal_count, "threshold": row.threshold,
        "signal_sources": row.signal_sources,
        "sample_run_ids": list(row.sample_run_ids),
        "status": "open" if decision is None else
        {"adopt": "adopted", "reject": "rejected"}[decision.decision],
        "decided_by": str(decision.decided_by) if decision else None,
        "decided_at": decision.created_at.isoformat() if decision else None,
        "draft": decision.draft if decision else None,
        "recorded_at": row.created_at.isoformat(),
    }


def listing(session, ctx, *, as_of=None):
    """审核页: candidates (open first) and the 30-day correction summary, counts only."""
    _admin(session, ctx)
    as_of = as_of or datetime.now(UTC)
    rows = session.scalars(select(SkillRevisionCandidate).order_by(
        SkillRevisionCandidate.created_at.desc()).limit(100)).all()
    decisions = {row.candidate_id: row for row in session.scalars(
        select(SkillRevisionDecision).where(SkillRevisionDecision.candidate_id.in_(
            [row.id for row in rows]))).all()} if rows else {}
    items = sorted((view(session, row, decisions.get(row.id)) for row in rows),
                   key=lambda item: (item["status"] != "open", item["recorded_at"]))
    summary = [
        {"target": {"kind": kind, "key": key, "version": version}, "reason": reason,
         "reason_label": REASON_LABELS.get(reason, reason), "signal_count": signals,
         "run_count": runs, "reaches_threshold": signals >= THRESHOLD}
        for kind, key, version, reason, signals, runs in session.execute(
            text("SELECT * FROM public.memory_procedural_overview(:t, :at)"),
            {"t": ctx.tenant_id, "at": as_of}).all()
    ]
    return {"version": "skill-revisions/v1", "items": items, "summary": summary,
            "threshold": THRESHOLD, "window_days": WINDOW_DAYS,
            "never_changed": list(NEVER_CHANGED),
            "tool_errors": "工具失败的原因类别待 D246 定；在那之前不按工具和错误类型汇总。",
            "note": "采纳只生成草稿版本，不激活；激活仍走具名评审与评测。"}


class RevisionDecision(StrictModel):
    request_key: UUID
    decision: Literal["adopt", "reject"]
    note: str | None = Field(default=None, min_length=1, max_length=500)


def decide(session, ctx, candidate_id, data):
    _admin(session, ctx)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"skill-revision:{ctx.tenant_id}:{candidate_id}"})
    row = session.scalar(select(SkillRevisionCandidate).where(
        SkillRevisionCandidate.id == candidate_id))
    if row is None:
        raise DomainError("NOT_FOUND", "修订候选不存在。", 404,
                          detail={"reason_key": "revision_candidate_not_found"})
    replay = session.scalar(select(SkillRevisionDecision).where(
        SkillRevisionDecision.decided_by == ctx.actor_id,
        SkillRevisionDecision.request_key == data.request_key))
    if replay is not None:
        if replay.candidate_id != row.id or replay.decision != data.decision:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的审核决定。",
                              detail={"reason_key": "revision_request_changed"})
        return view(session, row, replay)
    if session.scalar(select(SkillRevisionDecision.id).where(
            SkillRevisionDecision.candidate_id == row.id)):
        raise DomainError("VERSION_CONFLICT", "这条修订候选已经审核过了。",
                          detail={"reason_key": "already_decided"})
    draft = {}
    if data.decision == "adopt":
        base = row.target_version
        if row.target_kind == "prompt" and base == "unversioned":
            # The Runs never reached a model call, so no prompt identity was frozen on them;
            # the draft starts from the prompt that is active now.
            from pdos_next.agent.kernel.prompt_admin import _load

            base = _load(PROMPTS)["active"]
        draft = {"target_kind": row.target_kind, "key": row.target_key,
                 "base_version": base,
                 "draft_version": next_draft_version(base),
                 "status": "to_prepare", "prepare_with": DRAFT_TOOL,
                 "activation": ACTIVATION[row.target_kind]}
    decision = SkillRevisionDecision(
        id=uuid4(), tenant_id=ctx.tenant_id, candidate_id=row.id, decided_by=ctx.actor_id,
        decision=data.decision, note=data.note, draft=draft, request_key=data.request_key,
        request_sha256=digest({"candidate": row.id, "decision": data.decision,
                               "note": data.note}))
    session.add(decision)
    session.flush()
    return view(session, row, decision)
