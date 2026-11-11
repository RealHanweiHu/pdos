"""@小Pai in shared threads and 小Pai's proactive mentions (D37 ⑥; P34-4/5, P52, P54, P62).

Assigned s0_0873 on s0_0872 at the 11-10 integration (placeholder s0_0880 in the D37 ⑥
range s0_0880–s0_0884; revision, down_revision, snapshot module and the downgrade guard
text moved together).
"""

from alembic import op

from migrations.schema_s0_0873 import DOWNGRADE_SQL, EXPECTED_MD5, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0873"
down_revision = "s0_0872"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def _require_reviewed_predecessor():
    bind = op.get_bind()
    for name, expected in EXPECTED_MD5.items():
        actual = bind.exec_driver_sql(
            "SELECT md5(prosrc) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            f"WHERE n.nspname='public' AND p.proname='{name}'"
        ).scalar()
        if actual != expected:
            raise RuntimeError(f"{name} differs from the text s0_0873 was reviewed against")


def upgrade():
    ordinary_owner()
    _require_reviewed_predecessor()
    _execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    _execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
