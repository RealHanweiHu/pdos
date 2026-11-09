"""Hand s0_0776's receipt-key definer to the ordinary owner; refuse any other definer owner (D258).

s0_0720 transferred only the functions that existed then. s0_0776 created
change_receipt_key_bound later without transferring it, so it kept the migration
identity (a superuser in the test database, possibly an RDS administrator) and ran
outside RLS. After the transfer, every SECURITY DEFINER function in public must be
owned by the ordinary owner or one of the two reviewed narrow maintenance roles.

Placeholder number written on s0_0861 (11-08); renumber to the actual head at integration.
"""

from alembic import op
from sqlalchemy import bindparam, text

revision = "s0_0862"
down_revision = "s0_0861"
branch_labels = depends_on = None

SIGNATURE = "public.change_receipt_key_bound(uuid,uuid,uuid)"
# Same registered set as tests/categories/preproject/test_review_fixes.py.
REGISTERED_OWNERS = (
    "pdos_next_owner",
    "pdos_next_dingtalk_maintenance",
    "pdos_enterprise_index_maintainer",
)


def upgrade():
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO pdos_next_owner")
    # Extension members are owned by the extension, as in s0_0720's transfer.
    stray = (
        op.get_bind()
        .execute(
            text(
                "SELECT p.oid::regprocedure::text FROM pg_proc p "
                "JOIN pg_roles r ON r.oid=p.proowner "
                "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef "
                "AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass "
                "AND d.objid=p.oid AND d.deptype='e') "
                "AND (r.rolsuper OR r.rolbypassrls OR r.rolname NOT IN :owners) ORDER BY 1"
            ).bindparams(bindparam("owners", expanding=True)),
            {"owners": list(REGISTERED_OWNERS)},
        )
        .scalars()
        .all()
    )
    if stray:
        raise RuntimeError(
            "SECURITY DEFINER functions must be owned by a registered ordinary role: "
            + ", ".join(stray)
        )


def downgrade():
    # Keep the ordinary owner; s0_0776's own downgrade drops the function. Reversing
    # this revision must not reintroduce a superuser definer (same rule as s0_0720).
    pass
