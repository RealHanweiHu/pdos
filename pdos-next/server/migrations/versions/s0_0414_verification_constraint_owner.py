"""Validate immutable execution atoms as their constraint owner.

The deferred triggers return no business data and perform no writes. Business
RLS still controls every statement; invariant checks see the complete saved atom
without repeating reader audience projections for every dependent row.
"""

from alembic import op

revision = "s0_0414"
down_revision = "s0_0413"
branch_labels = None
depends_on = None

TRIGGERS = ("require_test_launch_atom", "require_test_resource_dependency_atom")


def upgrade():
    for name in TRIGGERS:
        op.execute(f"ALTER FUNCTION {name}() SECURITY DEFINER")
        op.execute(f"ALTER FUNCTION {name}() SET search_path=pg_catalog,public")
        op.execute(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC,pdos_next_app,pdos_agent")


def downgrade():
    for name in TRIGGERS:
        op.execute(f"ALTER FUNCTION {name}() SECURITY INVOKER")
    op.execute("ALTER FUNCTION require_test_launch_atom() RESET search_path")
