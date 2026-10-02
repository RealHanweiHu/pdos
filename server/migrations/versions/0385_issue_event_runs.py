"""Budgeted event-Issue proposals with immutable, actual model result lineage."""

# ruff: noqa: E501

from importlib import import_module

from alembic import op

revision = "0385_issue_event_runs"
down_revision = "0384_issue_ai_identity"
branch_labels = None
depends_on = None

previous = import_module("migrations.versions.0383_ai_meeting_event_receipts")
OLD = previous.NEW_EVENT_BOUNDS
NEW = OLD.replace(
    "'report-mapping-request-v1', 'quality-work-package-request-v1'",
    "'report-mapping-request-v1', 'quality-work-package-request-v1','event-issue-request-v1'",
)

DDL = "CREATE TABLE cehub_ai.ai_issue_event_results (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tmodel_invocation_id UUID NOT NULL, \n\tevent_row_id BIGINT NOT NULL, \n\tsource_digest VARCHAR(64) NOT NULL, \n\tsource_snapshot JSONB NOT NULL, \n\tproposal JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_ai_issue_event_results PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_issue_event_results_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_event_results_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_event_results_tenant_id_model_invocations FOREIGN KEY(tenant_id, model_invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_event_results_tenant_id_events FOREIGN KEY(tenant_id, event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_ai_issue_event_results_shape CHECK ((source_digest ~ '^[a-f0-9]{64}$' AND event_row_id>0 AND jsonb_typeof(source_snapshot)='object' AND jsonb_typeof(proposal)='object' AND source_snapshot->>'version'='event-issue-source-v1' AND source_snapshot->>'source_digest'=source_digest AND source_snapshot->>'event_row_id'=event_row_id::text AND source_snapshot->>'tenant_id'=tenant_id::text AND source_snapshot->>'project_id'=project_id::text AND proposal->>'disposition' IN ('create_issue','reuse_issue','insufficient_evidence')) IS TRUE), \n\tCONSTRAINT uq_ai_issue_result_run UNIQUE (tenant_id, run_id), \n\tCONSTRAINT uq_ai_issue_result_scope UNIQUE (tenant_id, project_id, id)\n);"

GUARDS = """
CREATE FUNCTION cehub_ai.guard_issue_event_result() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.model_invocations i ON i.tenant_id=r.tenant_id AND i.run_id=r.id
  JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=r.tenant_id
   AND cp.run_id=r.id AND cp.invocation_id=i.id
  JOIN cehub_event.events e ON e.tenant_id=r.tenant_id AND e.project_id=r.project_id
  WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
   AND r.agent_key='quality_intelligence' AND r.context_version='event-issue-request-v1'
   AND r.status='running' AND r.requested_by_user_id IS NOT NULL
   AND r.run_context->'issue_event_source'=NEW.source_snapshot
   AND i.id=NEW.model_invocation_id AND i.project_id=NEW.project_id
   AND i.agent_key='quality_intelligence' AND i.status='succeeded'
   AND i.prompt_version=r.run_context->>'issue_event_prompt_version'
   AND cp.body->>'status'='succeeded' AND cp.body->'output'=NEW.proposal
   AND e.id=NEW.event_row_id AND e.event_id=NEW.source_snapshot->>'event_id'
   AND e.entity_id::text=NEW.source_snapshot->>'entity_id'
   AND (e.event_type='TEST_FAILED' OR (e.event_type='NPI_RECORD_CHANGED'
    AND e.payload->>'record_type'='material_exception'
    AND e.payload->>'action' IN ('confirmed','reviewed')))
 ) THEN RAISE EXCEPTION 'Issue proposal requires its actual source, run and model result'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_issue_event_result BEFORE INSERT ON cehub_ai.ai_issue_event_results
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_event_result();
CREATE TRIGGER immutable_issue_event_result BEFORE UPDATE OR DELETE ON cehub_ai.ai_issue_event_results
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.ai_issue_event_results FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
 REVOKE ALL ON cehub_ai.ai_issue_event_results FROM pdos_agent; END IF; END $$;
"""


def upgrade() -> None:
    op.execute(previous._replace_run_check("ck_agent_runs_event_bounds_consistent", NEW))
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_event_results)
     OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE context_version='event-issue-request-v1')
     THEN RAISE EXCEPTION 'Retain event-Issue runs and model results'; END IF; END $$;""")
    op.execute("DROP TABLE cehub_ai.ai_issue_event_results")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_event_result()")
    op.execute(previous._replace_run_check("ck_agent_runs_event_bounds_consistent", OLD))
