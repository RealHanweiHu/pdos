"""Tooling and tool-trial SQL declarations (D305); the migration owns installation.

Tooling rows are readable exactly when their project is, trials when their
Build is. Both are append-only and bound at commit to the one common receipt of
the trial: the trial is the receipt's subject, and a tooling version written in
the same confirmation must be the exact tooling that trial references. A trial
also requires its first-revision verification request on the same Build.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from pdos_next.domain.manufacturing.alternate_approvals.storage_schema import BUILD_READ
from pdos_next.domain.manufacturing.fixture_acceptance.storage_schema import PROJECT_READ
from pdos_next.domain.named_records import storage

from .models import ToolingCurrent, ToolingVersion, ToolTrialCurrent, ToolTrialVersion
from .schemas import SUBJECT

TOOLING_SUBJECT = (
    f"r.subject_type<>'{SUBJECT}' OR NOT EXISTS(SELECT 1 FROM public.tool_trial_versions t "
    "WHERE t.tenant_id=NEW.tenant_id AND t.id=r.subject_id AND t.revision=r.subject_revision "
    "AND t.receipt_id=NEW.receipt_id AND t.tooling_id=NEW.record_id AND t.tooling_revision=NEW.revision)"
)
TRIAL_LINKS = """ IF NOT EXISTS(SELECT 1 FROM public.tooling_versions m WHERE m.tenant_id=NEW.tenant_id AND m.product_id=NEW.product_id
   AND m.project_id=NEW.project_id AND m.record_id=NEW.tooling_id AND m.revision=NEW.tooling_revision) THEN
  RAISE EXCEPTION 'tool_trial requires its exact tooling version' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.verification_formal_requests q WHERE q.tenant_id=NEW.tenant_id AND q.product_id=NEW.product_id
   AND q.request_id=NEW.request_id AND q.revision=1 AND q.build_id=NEW.build_id AND q.operation='verification.request.create') THEN
  RAISE EXCEPTION 'tool_trial requires its verification request on the same Build' USING ERRCODE='23514'; END IF;
"""
TOOLING = storage.Chain(
    versions=ToolingVersion,
    currents=ToolingCurrent,
    subject="tooling",
    prefix="tooling",
    read=PROJECT_READ,
    history="Tooling history requires s0_0886",
    subject_sql=TOOLING_SUBJECT,
)
TRIAL = storage.Chain(
    versions=ToolTrialVersion,
    currents=ToolTrialCurrent,
    subject=SUBJECT,
    prefix="tool_trial",
    read=BUILD_READ,
    history="Tool trial history requires s0_0886",
    extra_atom=TRIAL_LINKS,
    visibility=True,
)


def upgrade_sql():
    return storage.upgrade_sql(TOOLING, TRIAL)


def downgrade_sql():
    return storage.downgrade_sql(TOOLING, TRIAL)
