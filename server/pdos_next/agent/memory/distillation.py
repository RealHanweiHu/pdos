"""“经验沉淀”技能包与系统自动化规则 (memory design §7.5, §14.6; P88 第 1 项).

The mechanism, without any qualification:

* **规则** are preset per tenant and live in code (``RULES``). An administrator
  can stop or restart one (``memory_system_rule_settings``); nobody can rewrite
  what it does. Per P57 the rule's owner is the trigger object's owner and the
  run would read and write no wider than that owner's current scope.
* **触发**: the business-event fan-out (``fanout.py``) asks ``dispatch`` once per
  event. Deterministic rules (改版标待复核) never call a model and run in the
  fan-out's staleness handler. Drafting rules would start an automation run that
  loads the skill package ``experience_distillation``; that run goes through the
  registered graph like any other, so egress decisions and the run receipt are
  the normal ones.
* **起草出的是候选**: whatever the run drafts passes ``admit`` before it can be
  stored for its confirmer: only candidates, each with locked applicability
  conditions; a single case is only a case record (T22); evidence is counted by
  root source and nothing 小Pai generated counts (T25, T26); nothing is
  ``verified``.

The skill package itself is registered as a draft only
(``skill_packages/drafts/experience_distillation.md``): the catalog does not load
it, no tenant has it enabled, no T0 qualification exists, so every drafting
trigger is held with the reason. Golden cases are never written here.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .m3_models import MemorySystemRuleSetting

SKILL_KEY = "experience_distillation"


@dataclass(frozen=True)
class Rule:
    key: str
    events: tuple[str, ...]
    drafts: str | None  # None: deterministic, no model
    confirmer: str
    label: str


REVISION_EVENTS = ("proposal.item_patched", "proposal.g0_submitted", "proposal.g0_decided",
                   "change.effectivity_recorded")
RULES = {
    rule.key: rule for rule in (
        Rule("distill_g0", ("proposal.g0_decided",), "scope_note_candidates", "proposal_owner",
             "G0 评审结束：起草品类或同客户标签的备忘候选，由提案负责人确认"),
        Rule("distill_issue_closed", ("issue.closed",), "knowledge_candidate", "issue_owner",
             "品质问题关闭：起草知识候选（knowledge.candidate.create 现有档位），由问题负责人确认"),
        # 项目关闭 has no domain event yet; phase ends wait for the P33 NPI framework.
        Rule("distill_project_closed", (), "review_checklist", "project_owner",
             "项目关闭：起草复盘清单，由项目负责人确认（待项目关闭事件）"),
        Rule("stale_on_revision", REVISION_EVENTS, None, "note_reviewer",
             "变更生效、提案改版：不调用模型，把引用旧版本的条目标待复核并通知复核人"),
    )
}


def enabled(session, tenant_id, rule_key):
    return bool(session.scalar(text("SELECT public.memory_system_rule_enabled(:t, :r)"),
                               {"t": tenant_id, "r": rule_key}))


def skill_state(session, tenant_id, *, catalog=None):
    """Why the distillation skill cannot run now, or None when it could."""
    from pdos_next.agent.kernel.models import TenantSkillEnablement
    from pdos_next.agent.kernel.skills import SkillCatalog

    catalog = catalog or SkillCatalog()
    try:
        configuration = catalog.configuration(SKILL_KEY)
    except Exception:  # noqa: BLE001 -- an unknown key is exactly "not registered"
        configuration = None
    if configuration is None:
        return "skill_draft_only"
    row = session.scalar(select(TenantSkillEnablement).where(
        TenantSkillEnablement.tenant_id == tenant_id,
        TenantSkillEnablement.skill_key == SKILL_KEY))
    if row is None or not row.enabled:
        return "skill_not_enabled"
    return None


def dispatch(session, tenant_id, event, *, start=None, catalog=None):
    """The distillation handler of the fan-out: (outcome, detail). Never calls a model."""
    rules = [rule for rule in RULES.values() if rule.drafts and event["event_type"] in rule.events]
    if not rules:
        return "skipped", {"reason": "no_drafting_rule"}
    held = []
    for rule in rules:
        if not enabled(session, tenant_id, rule.key):
            held.append({"rule": rule.key, "reason": "rule_stopped"})
            continue
        reason = skill_state(session, tenant_id, catalog=catalog)
        if reason is None and start is None:
            reason = "no_dispatch_port"
        if reason is not None:
            held.append({"rule": rule.key, "reason": reason})
            continue
        # The automation run binds the trigger object's owner (P57); the port starts it.
        start({"tenant_id": str(tenant_id), "rule": rule.key, "event_id": event["event_id"],
               "skill": SKILL_KEY})
        return "done", {"rule": rule.key, "started": True}
    return "held", {"rules": held}


# ---------------------------------------------------------------------------
# What a drafting run may hand back: candidates only (T22, T25, T26).

GENERATED_SOURCES = frozenset({"xiaopai_answer", "scope_brief", "derived", "memory"})


class Evidence(StrictModel):
    root_source_id: UUID
    source_type: str = Field(min_length=1, max_length=40)
    has_result_receipt: bool = False


class Applicability(StrictModel):
    model: str = Field(min_length=1, max_length=80)
    build: str = Field(min_length=1, max_length=80)
    condition: str = Field(min_length=1, max_length=200)


class Drafted(StrictModel):
    kind: str = Field(pattern="^(scope_note|case_record|candidate_method)$")
    statement: str = Field(min_length=1, max_length=300)
    applicability: Applicability | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    counter_examples: list[str] = Field(default_factory=list, max_length=10)
    epistemic: str = "stated"


def admit(items):
    """Deterministic admission: (accepted, rejected). Nothing accepted is in effect."""
    accepted, rejected = [], []
    for raw in items:
        try:
            item = Drafted.model_validate(raw)
        except Exception:  # noqa: BLE001
            rejected.append({"item": raw, "reason": "shape"})
            continue
        roots = {value.root_source_id for value in item.evidence
                 if value.source_type not in GENERATED_SOURCES}
        if not roots:
            rejected.append({"item": raw, "reason": "no_root_source"})
            continue
        if item.epistemic == "verified":
            rejected.append({"item": raw, "reason": "cannot_verify"})
            continue
        if item.kind != "scope_note" and item.applicability is None:
            rejected.append({"item": raw, "reason": "applicability_required"})
            continue
        kind = item.kind
        receipted = {value.root_source_id for value in item.evidence
                     if value.source_type not in GENERATED_SOURCES and value.has_result_receipt}
        if kind == "candidate_method" and (len(receipted) < 2 or not item.counter_examples):
            kind = "case_record"  # 一次成功不推广 (§6.9)
        accepted.append({**item.model_dump(mode="json"), "kind": kind,
                         "evidence_count": len(roots), "status": "candidate",
                         "epistemic": item.epistemic})
    return accepted, rejected


# ---------------------------------------------------------------------------
# Administrator: stop or restart a preset rule. The rule text is not editable.


class RuleSetting(StrictModel):
    request_key: UUID
    enabled: bool


def rules_view(session, tenant_id):
    from .procedural import _admin  # noqa: F401  (callers check first)

    return {
        "version": "memory-system-rules/v1",
        "skill": {"key": SKILL_KEY, "state": skill_state(session, tenant_id) or "available",
                  "note": "经验沉淀只登记为草稿：未启用、无 T0 资格；"
                          "上线前须 golden-case 与资格。"},
        "rules": [{"key": rule.key, "label": rule.label, "events": list(rule.events),
                   "calls_model": rule.drafts is not None, "confirmer": rule.confirmer,
                   "enabled": enabled(session, tenant_id, rule.key)}
                  for rule in RULES.values()],
    }


def set_rule(session, ctx, rule_key, data):
    from .procedural import _admin

    _admin(session, ctx)
    if rule_key not in RULES:
        raise DomainError("NOT_FOUND", "没有这条系统规则。", 404,
                          detail={"reason_key": "rule_not_found"})
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                    {"k": f"memory-rule:{ctx.tenant_id}:{rule_key}"})
    fingerprint = digest({"rule": rule_key, "enabled": data.enabled})
    replay = session.scalar(select(MemorySystemRuleSetting).where(
        MemorySystemRuleSetting.set_by == ctx.actor_id,
        MemorySystemRuleSetting.request_key == data.request_key))
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的规则设置。",
                              detail={"reason_key": "rule_request_changed"})
        return rules_view(session, ctx.tenant_id)
    revision = (session.scalar(select(MemorySystemRuleSetting.revision).where(
        MemorySystemRuleSetting.rule_key == rule_key).order_by(
        MemorySystemRuleSetting.revision.desc()).limit(1)) or 0) + 1
    session.add(MemorySystemRuleSetting(
        id=uuid4(), tenant_id=ctx.tenant_id, rule_key=rule_key, revision=revision,
        enabled=data.enabled, set_by=ctx.actor_id, request_key=data.request_key,
        request_sha256=fingerprint))
    session.flush()
    return rules_view(session, ctx.tenant_id)
