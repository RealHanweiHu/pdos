"""Repair exact JSON extraction precedence without replacing the applied head24."""

import hashlib

from alembic import op
from sqlalchemy import text

revision = "next_0025"
down_revision = "next_0024"
branch_labels = None
depends_on = None

BEFORE_SHA256 = "bad9809337d74467d6112e349d499bc9a765d3ecd462fbd59236f1180095a556"
AFTER_SHA256 = "1440edf39592be9cebe21a6a36b29dfb35c5599980fd4996fe53461fe00aacbc"
REPAIRS = (
    (
        "(NEW.issue_snapshot->'history' - (jsonb_array_length(NEW.issue_snapshot->'history')-1))",
        "((NEW.issue_snapshot->'history') - (jsonb_array_length(NEW.issue_snapshot->'history')-1))",
    ),
    ("(NEW.issue_snapshot->'capa'-'actions')", "((NEW.issue_snapshot->'capa')-'actions')"),
    ("(prior.issue_snapshot->'capa'-'actions')", "((prior.issue_snapshot->'capa')-'actions')"),
)


def _replace(*, reverse=False):
    bind = op.get_bind()
    body, definition = bind.execute(
        text(
            "SELECT prosrc,pg_get_functiondef(oid) FROM pg_proc "
            "WHERE oid='require_quality_followup_atom()'::regprocedure"
        )
    ).one()
    expected, desired = (AFTER_SHA256, BEFORE_SHA256) if reverse else (BEFORE_SHA256, AFTER_SHA256)
    if hashlib.sha256(body.encode()).hexdigest() != expected:
        raise RuntimeError("Actual followup guard differs from the exact reviewed predecessor")
    for old, new in REPAIRS:
        old, new = (new, old) if reverse else (old, new)
        if body.count(old) != 1 or definition.count(old) != 1:
            raise RuntimeError("Exact reviewed JSON repair anchor is not unique")
        body = body.replace(old, new, 1)
        definition = definition.replace(old, new, 1)
    if hashlib.sha256(body.encode()).hexdigest() != desired:
        raise RuntimeError("Guard repair would change unreviewed assertions")
    op.execute(definition)


def upgrade():
    _replace()


def downgrade():
    # Returning to the defective predecessor is only a pre-business roundtrip.
    # Never leave retained new facts under a guard that cannot validate them.
    op.execute(
        "LOCK TABLE confirmations,quality_issue_versions,capa_remediation_links,action_receipts "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM quality_issue_versions WHERE operation IN "
            "('quality.issue.root_cause.decide','quality.capa.actions.complete')) "
            "OR EXISTS(SELECT 1 FROM capa_remediation_links) "
            "OR EXISTS(SELECT 1 FROM action_receipts WHERE operation IN "
            "('quality.issue.root_cause.decide','quality.capa.actions.complete',"
            "'quality.capa.followup.link')) "
            "OR EXISTS(SELECT 1 FROM confirmations WHERE consumed IS TRUE AND operation IN "
            "('quality.issue.root_cause.decide','quality.capa.actions.complete',"
            "'quality.capa.followup.link'))"
        )
    ):
        raise RuntimeError("Retained followup business facts prevent guard downgrade")
    _replace(reverse=True)
