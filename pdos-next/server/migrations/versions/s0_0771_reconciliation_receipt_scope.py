"""Read-only receipt identity index for technical Run reconciliation.

The original revert index stays write-scoped.
"""

from alembic import op

revision = "s0_0771"
down_revision = "s0_0770"
branch_labels = None
depends_on = None

SQL = """CREATE OR REPLACE FUNCTION public.kernel_reconciliation_receipt_ids(rid uuid)
 RETURNS SETOF uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$ DECLARE r agent_runs;
      BEGIN
        SELECT * INTO r FROM agent_runs WHERE id=rid
          AND tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
          AND requester_id=scope_actor() AND requester_id=scope_requester()
          AND category_id IS NOT DISTINCT FROM
            NULLIF(current_setting('pdos.category_id',true),'')::uuid;
        IF r.id IS NULL OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=r.tenant_id
            AND p.id=r.requester_id AND p.active AND p.kind='human')
          OR (r.category_id IS NOT NULL AND NOT category_access(r.tenant_id,r.category_id,false))
          OR NOT kernel_read_set_visible(r.tenant_id,r.category_id,r.read_sources)
          OR (r.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products p
            WHERE p.id=r.product_id AND p.tenant_id=r.tenant_id AND p.category_id=r.category_id
              AND (p.visibility='category' OR p.owner_id=r.requester_id OR EXISTS(
                SELECT 1 FROM object_audiences a
                WHERE a.tenant_id=p.tenant_id AND a.category_id=p.category_id
                  AND a.object_type='products' AND a.subject_id=p.id AND a.owner_id=p.owner_id
                  AND a.principal_id=r.requester_id))))
        THEN RAISE EXCEPTION 'Run receipt index requires current actual owner read scope'; END IF;
        -- Only opaque IDs are exposed here; Python requires every corresponding
        -- receipt to remain readable through ordinary RLS, without truncation.
        RETURN QUERY SELECT a.id FROM action_receipts a WHERE a.tenant_id=r.tenant_id
          AND a.agent_run_id=r.id ORDER BY a.created_at,a.id;
      END $function$
"""


def upgrade():
    op.execute(SQL)
    op.execute("ALTER FUNCTION kernel_reconciliation_receipt_ids(uuid) OWNER TO pdos_next_owner")
    op.execute(
        "REVOKE ALL ON FUNCTION kernel_reconciliation_receipt_ids(uuid) "
        "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute("GRANT EXECUTE ON FUNCTION kernel_reconciliation_receipt_ids(uuid) TO pdos_next_app")


def downgrade():
    op.execute("DROP FUNCTION kernel_reconciliation_receipt_ids(uuid)")
