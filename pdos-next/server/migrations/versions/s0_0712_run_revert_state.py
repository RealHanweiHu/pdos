"""Atomic technical stamp for the public whole-run business reversal owner."""

from alembic import op

from migrations.schema_s0_0712 import OLD_RUN_GUARD, RUN_GUARD

revision = "s0_0712"
down_revision = "s0_0711"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agent_runs ADD COLUMN reverted_at timestamptz")
    op.execute("ALTER TABLE agent_runs ADD COLUMN reverted_by uuid")
    op.execute("ALTER TABLE agent_runs ADD COLUMN revert_receipt_id uuid")
    op.execute("""ALTER TABLE agent_runs ADD CONSTRAINT kernel_revert_actor_fk
      FOREIGN KEY(tenant_id,reverted_by) REFERENCES principals(tenant_id,id)""")
    op.execute("""ALTER TABLE agent_runs ADD CONSTRAINT kernel_revert_receipt_fk
      FOREIGN KEY(tenant_id,revert_receipt_id) REFERENCES action_receipts(tenant_id,id)""")
    op.execute(RUN_GUARD)
    op.execute("""CREATE FUNCTION kernel_revert_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ DECLARE a action_receipts;
      BEGIN
        IF TG_OP='INSERT' THEN
          IF NEW.reverted_at IS NOT NULL OR NEW.reverted_by IS NOT NULL OR NEW.revert_receipt_id IS NOT NULL
          THEN RAISE EXCEPTION 'Revert must follow actual public command'; END IF; RETURN NEW;
        END IF;
        IF ROW(NEW.reverted_at,NEW.reverted_by,NEW.revert_receipt_id)
          IS NOT DISTINCT FROM ROW(OLD.reverted_at,OLD.reverted_by,OLD.revert_receipt_id)
        THEN RETURN NEW; END IF;
        IF OLD.reverted_at IS NOT NULL OR NEW.reverted_at IS NULL OR NEW.reverted_by IS NULL
          OR NEW.revert_receipt_id IS NULL OR NEW.requester_id<>scope_actor()
          OR scope_actor()<>scope_requester() OR NEW.reverted_by<>scope_actor()
          OR NEW.cancel_epoch<>OLD.cancel_epoch+1 OR NEW.held_tokens<>0
          OR (NEW.category_id IS NOT NULL AND NOT category_access(NEW.tenant_id,NEW.category_id,true))
          OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id
            AND p.id=scope_actor() AND p.active AND p.kind='human')
          OR EXISTS(SELECT 1 FROM agent_tool_calls c WHERE c.tenant_id=NEW.tenant_id
            AND c.run_id=NEW.id AND c.state='started')
        THEN RAISE EXCEPTION 'Revert stamp requires current owner and released existing calls'; END IF;
        SELECT * INTO a FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.revert_receipt_id;
        IF a.id IS NULL OR a.operation<>'ai.run.revert' OR a.subject_type<>'agent_run'
          OR a.subject_id<>NEW.id OR a.actor_id<>scope_actor() OR a.requester_id<>scope_requester()
          OR a.category_id IS DISTINCT FROM NEW.category_id OR a.product_id IS DISTINCT FROM NEW.product_id
          OR a.run_id IS NOT NULL OR to_jsonb(a)->>'agent_run_id' IS NOT NULL
          OR NEW.reverted_at<a.created_at OR NEW.reverted_at>clock_timestamp()
        THEN RAISE EXCEPTION 'Revert stamp requires exact actual Human receipt'; END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER kernel_revert BEFORE INSERT OR UPDATE ON agent_runs
      FOR EACH ROW EXECUTE FUNCTION kernel_revert_guard()""")
    op.execute("""CREATE FUNCTION kernel_run_receipt_ids(rid uuid) RETURNS SETOF uuid
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ DECLARE r agent_runs;
      BEGIN
        SELECT * INTO r FROM agent_runs WHERE id=rid
          AND tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
          AND requester_id=scope_actor() AND requester_id=scope_requester()
          AND category_id IS NOT DISTINCT FROM NULLIF(current_setting('pdos.category_id',true),'')::uuid;
        IF r.id IS NULL OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=r.tenant_id
            AND p.id=r.requester_id AND p.active AND p.kind='human')
          OR (r.category_id IS NOT NULL AND NOT category_access(r.tenant_id,r.category_id,true))
          OR NOT kernel_read_set_visible(r.tenant_id,r.category_id,r.read_sources)
          OR (r.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products p
            WHERE p.id=r.product_id AND p.tenant_id=r.tenant_id AND p.category_id=r.category_id
              AND (p.visibility='category' OR p.owner_id=r.requester_id OR EXISTS(
                SELECT 1 FROM object_audiences a WHERE a.tenant_id=p.tenant_id AND a.category_id=p.category_id
                  AND a.object_type='products' AND a.subject_id=p.id AND a.owner_id=p.owner_id
                  AND a.principal_id=r.requester_id))))
        THEN RAISE EXCEPTION 'Run receipt index requires current actual owner write scope'; END IF;
        -- Only opaque IDs are exposed here; Python requires every corresponding
        -- receipt to remain readable through ordinary RLS, without truncation.
        RETURN QUERY SELECT a.id FROM action_receipts a WHERE a.tenant_id=r.tenant_id
          AND a.agent_run_id=r.id ORDER BY a.created_at,a.id;
      END $$""")
    for function in ("kernel_revert_guard()", "kernel_run_receipt_ids(uuid)"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch")
    op.execute("GRANT EXECUTE ON FUNCTION kernel_run_receipt_ids(uuid) TO pdos_next_app")


def downgrade():
    op.execute("DROP FUNCTION kernel_run_receipt_ids(uuid)")
    op.execute("DROP TRIGGER kernel_revert ON agent_runs")
    op.execute("DROP FUNCTION kernel_revert_guard()")
    op.execute(OLD_RUN_GUARD)
    op.execute("ALTER TABLE agent_runs DROP COLUMN revert_receipt_id")
    op.execute("ALTER TABLE agent_runs DROP COLUMN reverted_by")
    op.execute("ALTER TABLE agent_runs DROP COLUMN reverted_at")
