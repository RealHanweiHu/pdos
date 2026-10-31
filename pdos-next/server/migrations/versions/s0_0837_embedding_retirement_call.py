"""Restore the confirmed profile trigger's narrow retirement function call."""

from alembic import op

revision = "s0_0837"
down_revision = "s0_0836"
branch_labels = depends_on = None


def upgrade():
    # ALTER OWNER in 0836 replaced the old owner's ACL with the maintainer's.
    # Only the existing schema owner's confirmed deferred trigger needs to call
    # this function. Runtime roles keep neither EXECUTE nor role membership.
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.enterprise_embedding_retire(uuid,uuid[]) "
        "TO pdos_next_owner"
    )


def downgrade():
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.enterprise_embedding_retire(uuid,uuid[]) "
        "FROM pdos_next_owner"
    )
