"""T0 value metrics and the automatic step back to one confirmation (D117; P41-8, P42).

All numbers come from the database functions of migration s0_0890: completed T0
writes recorded by the domain execution ledger, their receipts, whole-run and
single-item withdrawals, and later formal changes by people. Nothing here asks a
model. A breach only ever removes T0; the one-confirmation path stays available, and
T0 returns only through a new named ``ai.skill.qualify`` decision, which starts a new
window from its approval time.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text

from pdos_next.errors import DomainError

from .models import TenantAdministrator, TenantSkillEnablement


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    window: int
    limit: float  # breached when the rate is strictly greater (P41 item 8)
    unit: str  # "run" or "write"
    definition: str


WITHDRAWAL = Rule(
    "withdrawal",
    "撤回率",
    20,
    0.05,
    "run",
    "最近 20 次 T0 运行中，被整次撤回或其中任一写入被单独撤回的比例。",
)
MODIFICATION = Rule(
    "modification",
    "人工修改率",
    50,
    0.30,
    "write",
    "最近 50 次 T0 写入中，所写对象之后被人以正式命令修改或删除的比例；撤回另计。",
)
FRAMEWORK = Rule(
    "framework_check",
    "框架检查失败率",
    20,
    0.10,
    "run",
    "最近 20 次生成或修改中，两次检查仍不通过而交负责人的比例。",
)
RULES = (WITHDRAWAL, MODIFICATION, FRAMEWORK)

# P41 item 8 states these thresholds for P33 project plans (work_management).
# Whether draft packages also use the withdrawal threshold waits for the user's
# decision (D37 ⑧ question 2); until then only the literal P41 scope gates T0.
GATING = {"work_management": (WITHDRAWAL, MODIFICATION, FRAMEWORK)}

# No source records framework check outcomes yet (deterministic checker: W6 ②, D34).
UNAVAILABLE = {FRAMEWORK.key: "框架检查器尚未接入（W6 ② D34），没有可计算的记录。"}


@dataclass(frozen=True)
class Counts:
    runs_window: int
    runs_withdrawn: int
    writes_window: int
    writes_changed: int
    writes_withdrawn: int


def counts(session, tenant, skill_key, skill_version, model_version, since):
    row = session.execute(
        text(
            "SELECT * FROM kernel_skill_quality_counts(:tenant,:skill,:skill_version,"
            ":model_version,:since,:runs,:writes)"
        ),
        {
            "tenant": tenant,
            "skill": skill_key,
            "skill_version": skill_version,
            "model_version": model_version,
            "since": since,
            "runs": WITHDRAWAL.window,
            "writes": MODIFICATION.window,
        },
    ).one_or_none()
    return Counts(*row) if row else None


def judge(rule, value: Counts | None):
    """One P41 judgement: N/A while the window is not full, never a guess."""
    if rule.key in UNAVAILABLE:
        return {"state": "unavailable", "sample": 0, "count": 0, "rate": None,
                "reason": UNAVAILABLE[rule.key]}
    if value is None:
        return {"state": "unavailable", "sample": 0, "count": 0, "rate": None,
                "reason": "指标读取失败，按未通过处理。"}
    sample, count = (
        (value.runs_window, value.runs_withdrawn)
        if rule is WITHDRAWAL
        else (value.writes_window, value.writes_changed)
    )
    rate = count / sample if sample else None
    if sample < rule.window:
        return {"state": "insufficient", "sample": sample, "count": count, "rate": rate,
                "reason": f"样本 {sample}/{rule.window}，只记录、不判定（N/A）。"}
    breached = rate > rule.limit
    return {"state": "breached" if breached else "within", "sample": sample, "count": count,
            "rate": rate, "reason": None}


def breach(session, tenant, skill_key, skill_version, model_version, since):
    """The first P41 threshold this qualification crosses, or None.

    An unreadable count fails closed: T0 steps back to one confirmation.
    """
    rules = GATING.get(skill_key, ())
    if not rules:
        return None
    value = counts(session, tenant, skill_key, skill_version, model_version, since)
    if value is None:
        return "unavailable"
    for rule in rules:
        if judge(rule, value)["state"] == "breached":
            return rule.key
    return None


def qualification_breach(session, tenant, row: TenantSkillEnablement):
    if not row or not row.reviewed_at:
        return None
    return breach(
        session,
        tenant,
        row.skill_key,
        row.qualified_skill_version,
        row.qualified_model_version,
        row.reviewed_at,
    )


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def _value(value: Counts | None):
    if value is None:
        return None
    kept = value.writes_window - value.writes_withdrawn
    return {
        "runs_window": value.runs_window,
        "runs_withdrawn": value.runs_withdrawn,
        "writes_window": value.writes_window,
        "writes_changed": value.writes_changed,
        "writes_withdrawn": value.writes_withdrawn,
        "withdrawal_rate": _rate(value.runs_withdrawn, value.runs_window),
        "modification_rate": _rate(value.writes_changed, value.writes_window),
        "retention_rate": _rate(kept, value.writes_window),
        "untouched_rate": _rate(kept - value.writes_changed, value.writes_window),
    }


def _basis(session, tenant, skill_key, skill_version, model_version, since):
    rows = session.execute(
        text(
            "SELECT * FROM kernel_skill_quality_basis(:tenant,:skill,:skill_version,"
            ":model_version,:since,:runs,:writes)"
        ),
        {
            "tenant": tenant,
            "skill": skill_key,
            "skill_version": skill_version,
            "model_version": model_version,
            "since": since,
            "runs": WITHDRAWAL.window,
            "writes": MODIFICATION.window,
        },
    ).mappings()
    withdrawn, changed = [], []
    for row in rows:
        if row["fact"] == "run" and row["withdrawn"]:
            withdrawn.append(str(row["run_id"]))
        if row["fact"] == "write" and row["changed"] and str(row["run_id"]) not in changed:
            changed.append(str(row["run_id"]))
    return {"withdrawal": withdrawn, "modification": changed}


def _sample(session, tenant, skill_key, skill_version, model_version, since):
    rows = session.execute(
        text(
            "SELECT * FROM kernel_skill_spot_check_sample(:tenant,:skill,:skill_version,"
            ":model_version,:since,200)"
        ),
        {
            "tenant": tenant,
            "skill": skill_key,
            "skill_version": skill_version,
            "model_version": model_version,
            "since": since,
        },
    ).mappings().all()
    weeks = {}
    for row in rows:
        week = weeks.setdefault(row["week_start"].isoformat(), {"runs": 0, "sampled": 0})
        week["runs"] += 1
        week["sampled"] += int(row["sampled"])
    return {
        "rule": "按运行编号哈希抽 20%；每周（周一至周日，北京时间）不足 min(2, 当周 T0 运行数) "
        "时按时间补足（P42）。",
        "weeks": [
            {"week_start": key, **value, "required": min(2, value["runs"])}
            for key, value in sorted(weeks.items(), reverse=True)
        ],
        "runs": [
            {
                "run_id": str(row["run_id"]),
                "first_at": row["first_at"].isoformat(),
                "week_start": row["week_start"].isoformat(),
                "reason": row["reason"],
            }
            for row in rows
            if row["sampled"]
        ][:50],
    }


def _iso(value: datetime | None):
    return value.isoformat() if value else None


def view(session, ctx, skill_key):
    """Read-only AI value metrics and the current qualification's P41 judgement."""
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    )
    if ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id or not admin:
        raise DomainError("NAMED_DECISION_REQUIRED", "请由当前租户管理员本人查看资格指标。", 403)
    groups = session.execute(
        text("SELECT * FROM kernel_skill_quality_groups(:tenant,:skill)"),
        {"tenant": ctx.tenant_id, "skill": skill_key},
    ).mappings().all()
    values = [
        {
            "skill_version": group["skill_version"],
            "model_version": group["model_version"],
            "runs_total": group["runs_total"],
            "writes_total": group["writes_total"],
            "first_at": _iso(group["first_at"]),
            "last_at": _iso(group["last_at"]),
            "metrics": _value(
                counts(
                    session,
                    ctx.tenant_id,
                    skill_key,
                    group["skill_version"],
                    group["model_version"],
                    None,
                )
            ),
        }
        for group in groups[:10]
    ]
    row = session.scalar(
        select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == ctx.tenant_id,
            TenantSkillEnablement.skill_key == skill_key,
        )
    )
    current = None
    if row and row.reviewed_at and not row.qualification_revoked:
        binding = (
            ctx.tenant_id,
            skill_key,
            row.qualified_skill_version,
            row.qualified_model_version,
            row.reviewed_at,
        )
        value = counts(session, *binding)
        gating = GATING.get(skill_key, ())
        current = {
            "skill_version": row.qualified_skill_version,
            "model_version": row.qualified_model_version,
            "since": _iso(row.reviewed_at),
            "metrics": _value(value),
            "rules": [
                {
                    "key": rule.key,
                    "label": rule.label,
                    "window": rule.window,
                    "limit": rule.limit,
                    "definition": rule.definition,
                    "gating": rule in gating,
                    **judge(rule, value),
                }
                for rule in RULES
            ],
            "breach": qualification_breach(session, ctx.tenant_id, row),
            "basis": _basis(session, *binding),
            "spot_check": _sample(session, *binding),
        }
    return {
        "skill_key": skill_key,
        "definitions": {
            "withdrawal_rate": WITHDRAWAL.definition,
            "modification_rate": MODIFICATION.definition,
            "retention_rate": "最近 50 次 T0 写入中未被撤回的比例（人改过的仍算保留）。",
            "untouched_rate": "最近 50 次 T0 写入中既未撤回、也未被人改动的比例。",
            "granularity": "人工修改按回执所指对象判断；提案与型号定义的条目级口径待细化（D411）。",
        },
        "groups": values,
        "current": current,
        "model_judgement": False,
    }
