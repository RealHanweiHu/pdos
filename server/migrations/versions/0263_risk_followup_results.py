"""Immutable risk follow-up submissions and named independent receipt."""

from alembic import op

revision = "0263_risk_followup_results"
down_revision = "0262_risk_candidate_batches"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_project.risk_followup_results (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
risk_id UUID NOT NULL,
task_id UUID NOT NULL,
origin_audit_id BIGINT NOT NULL,
revision INTEGER NOT NULL,
action VARCHAR(16) NOT NULL,
submission_id UUID,
actor_user_id UUID NOT NULL,
receiver_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
basis JSONB NOT NULL,
payload JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_risk_followup_results PRIMARY KEY (id),
CONSTRAINT uq_risk_followup_result_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_risk_followup_result_revision UNIQUE (tenant_id, task_id, revision),
CONSTRAINT uq_risk_followup_result_request UNIQUE (tenant_id, actor_user_id, request_id),
CONSTRAINT fk_risk_followup_results_tenant_id_risks FOREIGN KEY(tenant_id, risk_id) REFERENCES
cehub_project.risks (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_followup_results_tenant_id_tasks FOREIGN KEY(tenant_id, project_id, task_id)
REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_followup_results_tenant_id_audit_log FOREIGN KEY(tenant_id, origin_audit_id)
REFERENCES cehub_audit.audit_log (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_followup_result_actor FOREIGN KEY(tenant_id, actor_user_id) REFERENCES
cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_followup_result_receiver FOREIGN KEY(tenant_id, receiver_user_id) REFERENCES
cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_followup_results_tenant_id_risk_followup_results FOREIGN KEY(tenant_id,
project_id, submission_id) REFERENCES cehub_project.risk_followup_results (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT ck_risk_followup_results_revision_digest CHECK (revision>0 AND request_digest ~
'^[0-9a-f]{64}$'),
CONSTRAINT ck_risk_followup_results_action CHECK ((action='submitted' AND submission_id IS NULL
AND actor_user_id<>receiver_user_id) OR (action IN ('accepted','returned') AND submission_id IS
NOT NULL AND actor_user_id=receiver_user_id)),
CONSTRAINT ck_risk_followup_results_snapshots CHECK (jsonb_typeof(basis)='object' AND
jsonb_typeof(payload)='object')
)

;
CREATE INDEX ix_risk_followup_receiver ON cehub_project.risk_followup_results (tenant_id,
receiver_user_id, created_at, id);
"""
GUARD = """
CREATE FUNCTION cehub_project.guard_risk_followup_result() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous cehub_project.risk_followup_results%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Risk result history is immutable'; END IF;
 IF NOT EXISTS (SELECT 1 FROM cehub_project.risks r
  JOIN cehub_project.tasks t ON t.tenant_id=r.tenant_id AND t.project_id=r.project_id
  JOIN cehub_audit.audit_log a ON a.tenant_id=t.tenant_id AND a.entity_id=t.id
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.risk_id
   AND t.id=NEW.task_id AND t.kind='risk_action' AND t.source_entity_id=r.id
   AND a.id=NEW.origin_audit_id AND a.action='task.create'
   AND a.context->'risk_followup'->'basis'->'risk'->>'id'=r.id::text) THEN
  RAISE EXCEPTION 'Risk result must retain original task assignment';
 END IF;
 SELECT * INTO previous FROM cehub_project.risk_followup_results
 WHERE tenant_id=NEW.tenant_id AND task_id=NEW.task_id ORDER BY revision DESC LIMIT 1;
 IF NEW.revision<>coalesce(previous.revision,0)+1 THEN
  RAISE EXCEPTION 'Risk result revision changed';
 END IF;
 IF NEW.action='submitted' THEN
  IF NOT EXISTS (SELECT 1 FROM cehub_project.tasks WHERE tenant_id=NEW.tenant_id
    AND id=NEW.task_id AND assignee_user_id=NEW.actor_user_id AND status='done'
    AND btrim(completion_evidence_ref)<>'') THEN
   RAISE EXCEPTION 'Completed task and named evidence required';
  END IF;
 ELSE
  IF previous.id IS NULL OR previous.action<>'submitted' OR previous.id<>NEW.submission_id
     OR previous.receiver_user_id<>NEW.actor_user_id
     OR previous.actor_user_id=NEW.actor_user_id THEN
   RAISE EXCEPTION 'Latest submission and independent named receiver required';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_risk_followup_result() FROM PUBLIC;
CREATE TRIGGER guard_risk_followup_result BEFORE INSERT OR UPDATE OR DELETE
ON cehub_project.risk_followup_results FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_risk_followup_result();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.risk_followup_results) THEN
      RAISE EXCEPTION 'Risk result history must be retained';
    END IF;
    END $$;
    DROP TABLE cehub_project.risk_followup_results;
    DROP FUNCTION cehub_project.guard_risk_followup_result();
    """)
