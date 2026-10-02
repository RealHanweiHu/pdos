"""Shared employee queue visibility for superseded findings and captured meeting drafts.

The immutable write receipt chooses sampling; the queue cannot grant direct
execution. Only an explicit unsampled direct receipt suppresses an unhandled
draft. Missing/unknown receipts remain visible as exceptions. Historical
Finding states and single-record reads retain their existing access rules.
"""

from sqlalchemy import ColumnElement, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.db.schema import tables


def finding_attention_visibility() -> ColumnElement[bool]:
    """Keep pending work only when the original draft still needs human attention."""
    finding = tables.findings
    draft = tables.ai_meeting_drafts
    action = tables.ai_meeting_draft_actions
    matching = (
        select(draft.c.id)
        .where(
            draft.c.tenant_id == finding.c.tenant_id,
            draft.c.project_id == finding.c.project_id,
            draft.c.finding_id == finding.c.id,
        )
        .correlate(finding)
    )
    handled = (
        select(action.c.id)
        .where(
            action.c.tenant_id == draft.c.tenant_id,
            action.c.project_id == draft.c.project_id,
            action.c.draft_id == draft.c.id,
            action.c.action.in_(("confirm", "edit", "withdraw", "publish")),
        )
        .correlate(draft)
        .exists()
    )
    # JSON containment distinguishes boolean false from null, strings and numbers.
    silent = (draft.c.capture_mode == "direct") & func.coalesce(
        cast(draft.c.write_receipt, JSONB).contains({"route": "direct", "sampled": False}), False
    )
    awaiting = matching.where(~handled, ~silent).exists()
    run = tables.agent_runs.alias("attention_run")
    superseded = (
        select(run.c.id)
        .where(
            run.c.tenant_id == finding.c.tenant_id,
            run.c.project_id == finding.c.project_id,
            run.c.id == finding.c.run_id,
            func.coalesce(run.c.run_context["superseded_by"].as_string(), "") != "",
        )
        .correlate(finding)
        .exists()
    )
    return or_(
        finding.c.status.not_in(("pending_review", "accepted")),
        ~superseded & or_(~matching.exists(), awaiting),
    )
