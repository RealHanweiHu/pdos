"""Only committed answer references enter Temporal history."""

from alembic import op

revision = "s0_0703"
down_revision = "s0_0702"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE agent_run_inputs (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, created_at timestamptz NOT NULL,
      run_id uuid NOT NULL, requester_id uuid NOT NULL, idempotency_key varchar(160) NOT NULL,
      payload_digest varchar(64) NOT NULL, answers jsonb NOT NULL,
      UNIQUE(tenant_id,run_id,idempotency_key),
      FOREIGN KEY(tenant_id,run_id) REFERENCES agent_runs(tenant_id,id),
      FOREIGN KEY(tenant_id,requester_id) REFERENCES principals(tenant_id,id))""")
    op.execute("CREATE INDEX ix_agent_run_inputs_tenant_id ON agent_run_inputs(tenant_id)")
    op.execute("ALTER TABLE agent_run_inputs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_run_inputs FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY kernel_scope ON agent_run_inputs USING (
      tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND requester_id=scope_requester() AND EXISTS(SELECT 1 FROM agent_runs r
        WHERE r.tenant_id=agent_run_inputs.tenant_id AND r.id=run_id))
      WITH CHECK(requester_id=scope_requester() AND scope_actor()=scope_requester()
        AND EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=agent_run_inputs.tenant_id
          AND p.id=scope_actor() AND p.kind='human' AND p.active))""")
    op.execute("REVOKE ALL ON agent_run_inputs FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch")
    op.execute("GRANT SELECT,INSERT ON agent_run_inputs TO pdos_next_app")
    op.execute("""CREATE TRIGGER kernel_append BEFORE UPDATE OR DELETE ON agent_run_inputs
      FOR EACH ROW EXECUTE FUNCTION kernel_append_only()""")


def downgrade():
    op.execute("DROP TABLE agent_run_inputs")
