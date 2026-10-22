"""Read-authorized replay aliases are metadata, without business write authority."""

from alembic import op

revision = "s0_0004"
down_revision = "s0_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER POLICY category_scope ON request_keys WITH CHECK "
        "(category_access(tenant_id,category_id) AND actor_id=scope_actor() "
        "AND EXISTS(SELECT 1 FROM action_receipts r WHERE "
        "r.id=request_keys.receipt_id AND r.tenant_id=request_keys.tenant_id))"
    )
    op.execute(
        "CREATE POLICY own_request_key ON request_keys AS RESTRICTIVE "
        "USING (actor_id=scope_actor()) WITH CHECK (actor_id=scope_actor())"
    )


def downgrade():
    op.execute("DROP POLICY own_request_key ON request_keys")
    op.execute(
        "ALTER POLICY category_scope ON request_keys WITH CHECK "
        "(category_access(tenant_id,category_id,true) "
        "AND EXISTS(SELECT 1 FROM action_receipts r WHERE "
        "r.id=request_keys.receipt_id AND r.tenant_id=request_keys.tenant_id))"
    )
