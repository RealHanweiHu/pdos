"""Dispatch-only technical failure after actual run scope loss; no business mutations."""

from alembic import op

revision = "s0_0711"
down_revision = "s0_0710"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION kernel_scope_failed(rid uuid) RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE r agent_runs; cid uuid; prior_actor text; lost boolean;
      BEGIN
        SELECT * INTO r FROM agent_runs WHERE id=rid
          AND tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
          AND requester_id=scope_requester() AND requester_id=scope_actor()
          AND category_id IS NOT DISTINCT FROM
            NULLIF(current_setting('pdos.category_id',true),'')::uuid FOR UPDATE;
        IF NOT FOUND OR r.state IN ('completed','partial','failed','cancelled') THEN RETURN false; END IF;
        prior_actor=current_setting('pdos.actor_id',true);
        PERFORM set_config('pdos.actor_id',r.writer_id::text,true);
        lost=NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=r.tenant_id
            AND p.id=r.writer_id AND p.kind='agent' AND p.active)
          OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=r.tenant_id
            AND p.id=r.requester_id AND p.kind='human' AND p.active)
          OR (r.category_id IS NOT NULL AND NOT category_access(r.tenant_id,r.category_id))
          OR NOT kernel_read_set_visible(r.tenant_id,r.category_id,r.read_sources)
          OR (r.validation_budget_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM agent_validation_budgets b WHERE b.id=r.validation_budget_id
              AND b.tenant_id=r.tenant_id AND b.active))
          OR (r.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products p
            WHERE p.id=r.product_id AND p.tenant_id=r.tenant_id AND p.category_id=r.category_id
              AND (p.visibility='category' OR p.owner_id=r.requester_id OR EXISTS(
                SELECT 1 FROM object_audiences a WHERE a.tenant_id=p.tenant_id
                  AND a.category_id=p.category_id AND a.object_type='products'
                  AND a.subject_id=p.id AND a.owner_id=p.owner_id AND a.principal_id=r.requester_id))));
        IF NOT COALESCE(lost,true) THEN
          PERFORM set_config('pdos.actor_id',prior_actor,true); RETURN false;
        END IF;
        FOR cid IN SELECT id FROM agent_tool_calls WHERE tenant_id=r.tenant_id
            AND run_id=r.id AND state='started' ORDER BY id LOOP
          PERFORM kernel_release_call(r.id,cid,'FORBIDDEN_SCOPE',true,0,NULL);
        END LOOP;
        PERFORM set_config('pdos.actor_id',prior_actor,true);
        UPDATE agent_runs SET state='failed',error_code='FORBIDDEN_SCOPE',result=NULL WHERE id=r.id;
        RETURN true;
      END $$""")
    op.execute("""REVOKE ALL ON FUNCTION kernel_scope_failed(uuid)
      FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth""")
    op.execute("GRANT EXECUTE ON FUNCTION kernel_scope_failed(uuid) TO pdos_next_dispatch")


def downgrade():
    op.execute("DROP FUNCTION kernel_scope_failed(uuid)")
