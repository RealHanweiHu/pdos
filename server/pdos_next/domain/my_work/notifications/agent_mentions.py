"""小Pai's proactive @ of a person (`ai.mention.notify`, P34-5, design §7.4; D37 ⑥).

Only three reasons exist: an assignment (the assignee, P53), missing information (the
person responsible for it) and a rule exception (e.g. a commitment about to be late).
The SQL function decides who is reached: the writer must be 小Pai acting for an
active human requester or rule owner, both that person and the recipient must see
the subject now, and the same object with the same reason reaches a person once per
cooldown, read or not. A successful automatic write mentions nobody else (DC-11 §5).
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from pdos_next.core.clock import now

# P41-9 tenant default: one working day. Before the tenant work calendar (D221) a
# working day is Monday to Friday without holidays (P41-10). Tenant settings: D391.
COOLDOWN_WORKING_DAYS = 1
COOLDOWN_TIMEZONE = "Asia/Shanghai"
REASONS = frozenset({"task.assigned", "agent.needs_info", "agent.rule_exception"})


def cooldown_seconds(at=None, *, days=COOLDOWN_WORKING_DAYS, timezone=COOLDOWN_TIMEZONE):
    """Seconds back to the same local time `days` working days earlier."""
    local = (at or now()).astimezone(ZoneInfo(timezone))
    start, remaining = local, days
    while remaining:
        start -= timedelta(days=1)
        if start.weekday() < 5:
            remaining -= 1
    return int((local - start).total_seconds())


def notify(s, ctx, recipient, reason, *, project_id, kind, subject_id, thread_id=None, latest=None):
    """One proactive mention, or None when the rules above leave nobody to reach."""
    import json

    if reason not in REASONS:
        raise ValueError("小Pai mentions only for assignment, missing information or a rule")
    s.flush()
    return s.scalar(
        text(
            "SELECT agent_mention_notify(:t, :recipient, :reason, :project, :kind, :subject, "
            ":thread, CAST(:latest AS jsonb), :cooldown)"
        ),
        {
            "t": ctx.tenant_id,
            "recipient": recipient,
            "reason": reason,
            "project": project_id,
            "kind": kind,
            "subject": subject_id,
            "thread": thread_id,
            "latest": json.dumps(latest or {}, ensure_ascii=False, default=str),
            "cooldown": cooldown_seconds(),
        },
    )


def signature(row, names):
    """“小Pai · 按某某的规则” for a rule-triggered mention (P34-5); else None."""
    owner = (row.latest or {}).get("rule_owner_id")
    if row.reason != "agent.rule_exception" or not owner:
        return None
    from uuid import UUID

    try:
        return f"小Pai · 按{names.get(UUID(str(owner)), '规则负责人')}的规则"
    except ValueError:
        return None
