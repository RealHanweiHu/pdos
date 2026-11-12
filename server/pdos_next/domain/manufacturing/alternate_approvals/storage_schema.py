"""Alternate approval SQL declarations (D308); the migration owns installation.

Rows are readable exactly when their fixed Build is. Versions are append-only
and bound at commit to the common receipt of a named person with no AI run.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from pdos_next.domain.named_records import storage

from .models import AlternateApprovalCurrent, AlternateApprovalVersion
from .schemas import SUBJECT

BUILD_READ = (
    "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.builds b "
    "WHERE b.tenant_id={t}.tenant_id AND b.category_id={t}.category_id AND b.product_id={t}.product_id "
    "AND b.project_id={t}.project_id AND b.id={t}.build_id AND b.owner_id={t}.owner_id AND b.visibility={t}.visibility)"
)
CHAIN = storage.Chain(
    versions=AlternateApprovalVersion,
    currents=AlternateApprovalCurrent,
    subject=SUBJECT,
    prefix="alternate_approval",
    read=BUILD_READ,
    history="Alternate approval history requires s0_0883",
    visibility=True,
)


def upgrade_sql():
    return storage.upgrade_sql(CHAIN)


def downgrade_sql():
    return storage.downgrade_sql(CHAIN)
