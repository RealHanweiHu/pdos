"""P56 handover lane (D37 ⑤): removal ends project visibility except own unhanded work.

Written as placeholder s0_0873 on s0_0861; renumbered to s0_0868 after W11's s0_0867
at the 11-09 integration (revision, down_revision and snapshot file together).
"""

from alembic import op

from migrations.schema_s0_0868 import DOWNGRADE_SQL, EXPECTED_MD5, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0868"
down_revision = "s0_0867"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def _require_reviewed_predecessor():
    bind = op.get_bind()
    for name, expected in EXPECTED_MD5.items():
        if name == "projects_using":
            actual = bind.exec_driver_sql(
                "SELECT md5(qual) FROM pg_policies WHERE schemaname='public' "
                "AND tablename='projects' AND policyname='category_scope'"
            ).scalar()
        else:
            actual = bind.exec_driver_sql(
                "SELECT md5(prosrc) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                f"WHERE n.nspname='public' AND p.proname='{name}'"
            ).scalar()
        if actual != expected:
            raise RuntimeError(f"{name} differs from the text s0_0868 was reviewed against")


def upgrade():
    ordinary_owner()
    _require_reviewed_predecessor()
    _execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    _execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
