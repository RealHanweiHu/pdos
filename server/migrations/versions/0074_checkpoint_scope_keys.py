"""Enforce checkpoint and recovery receipt tenant/run identity with composite keys."""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_checkpoint_scope_keys"
down_revision: str | Sequence[str] | None = "0073_agent_result_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
      ALTER TABLE cehub_ai.model_invocations ADD CONSTRAINT uq_model_checkpoint_scope
        UNIQUE(tenant_id,run_id,id);
      ALTER TABLE cehub_ai.findings ADD CONSTRAINT uq_finding_recovery_scope
        UNIQUE(tenant_id,run_id,id);
      ALTER TABLE cehub_ai.agent_result_checkpoints ADD CONSTRAINT uq_checkpoint_recovery_scope
        UNIQUE(tenant_id,run_id,id);
      ALTER TABLE cehub_ai.agent_result_checkpoints
        DROP CONSTRAINT agent_result_checkpoints_model_invocation_id_fkey,
        ADD CONSTRAINT fk_checkpoint_trace_scope FOREIGN KEY(tenant_id,run_id,model_invocation_id)
          REFERENCES cehub_ai.model_invocations(tenant_id,run_id,id) ON DELETE RESTRICT;
      ALTER TABLE cehub_ai.agent_run_recoveries
        DROP CONSTRAINT agent_run_recoveries_checkpoint_id_fkey,
        DROP CONSTRAINT agent_run_recoveries_finding_id_fkey,
        ADD CONSTRAINT fk_recovery_checkpoint_scope FOREIGN KEY(tenant_id,run_id,checkpoint_id)
          REFERENCES cehub_ai.agent_result_checkpoints(tenant_id,run_id,id) ON DELETE RESTRICT,
        ADD CONSTRAINT fk_recovery_finding_scope FOREIGN KEY(tenant_id,run_id,finding_id)
          REFERENCES cehub_ai.findings(tenant_id,run_id,id) ON DELETE RESTRICT;
    """)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_result_checkpoints)
         OR EXISTS(SELECT 1 FROM cehub_ai.agent_run_recoveries) THEN
        RAISE EXCEPTION 'cannot remove scope keys with persistent checkpoint recovery history';
      END IF;
    END $body$;""")
    op.execute("""
      ALTER TABLE cehub_ai.agent_run_recoveries
        DROP CONSTRAINT fk_recovery_checkpoint_scope,
        DROP CONSTRAINT fk_recovery_finding_scope,
        ADD CONSTRAINT agent_run_recoveries_checkpoint_id_fkey FOREIGN KEY(checkpoint_id)
          REFERENCES cehub_ai.agent_result_checkpoints(id) ON DELETE RESTRICT,
        ADD CONSTRAINT agent_run_recoveries_finding_id_fkey FOREIGN KEY(finding_id)
          REFERENCES cehub_ai.findings(id) ON DELETE RESTRICT;
      ALTER TABLE cehub_ai.agent_result_checkpoints DROP CONSTRAINT fk_checkpoint_trace_scope,
        ADD CONSTRAINT agent_result_checkpoints_model_invocation_id_fkey
          FOREIGN KEY(model_invocation_id)
          REFERENCES cehub_ai.model_invocations(id) ON DELETE RESTRICT;
      ALTER TABLE cehub_ai.agent_result_checkpoints DROP CONSTRAINT uq_checkpoint_recovery_scope;
      ALTER TABLE cehub_ai.findings DROP CONSTRAINT uq_finding_recovery_scope;
      ALTER TABLE cehub_ai.model_invocations DROP CONSTRAINT uq_model_checkpoint_scope;
    """)
