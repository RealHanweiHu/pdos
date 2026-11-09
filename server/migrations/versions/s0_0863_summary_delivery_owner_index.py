"""Finish s0_0852's summary delivery table: ordinary owner and tenant index (D284, D261).

s0_0852 transferred its functions but left dingtalk_summary_deliveries owned by the
migration identity (s0_0843 transferred its six DingTalk tables). It also omitted the
tenant index every other Row table has (`Row.tenant_id` is `index=True`). After the
transfer, no public business table may keep a migration-identity owner.

Placeholder number written on s0_0861 (11-08); renumber to the actual head at integration.
"""

from alembic import op
from sqlalchemy import bindparam, text

from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0863"
down_revision = "s0_0862"
branch_labels = depends_on = None

TABLE = "public.dingtalk_summary_deliveries"
INDEX = "ix_dingtalk_summary_deliveries_tenant_id"
# Harness tables stay with the migration identity, as in s0_0720.
HARNESS_TABLES = ("environment_guard", "alembic_version")


def upgrade():
    op.execute(f"ALTER TABLE {TABLE} OWNER TO pdos_next_owner")
    stray = (
        op.get_bind()
        .execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner "
                "WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p') "
                "AND c.relname NOT IN :harness AND r.rolname<>'pdos_next_owner' ORDER BY 1"
            ).bindparams(bindparam("harness", expanding=True)),
            {"harness": list(HARNESS_TABLES)},
        )
        .scalars()
        .all()
    )
    if stray:
        raise RuntimeError("Public tables must be owned by pdos_next_owner: " + ", ".join(stray))
    ordinary_owner()
    op.execute(f"CREATE INDEX {INDEX} ON {TABLE} (tenant_id)")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute(f"DROP INDEX public.{INDEX}")
    op.execute("SET LOCAL ROLE NONE")
    # Keep the ordinary owner; s0_0852's own downgrade drops the table.
