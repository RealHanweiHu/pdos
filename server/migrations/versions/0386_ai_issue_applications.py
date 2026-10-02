"""Confirmed AI Issue application and immutable source/run/call receipts."""
# ruff: noqa: E501
from alembic import op

revision = "0386_ai_issue_applications"
down_revision = "0385_issue_event_runs"
branch_labels = None
depends_on = None

DDL = "CREATE TABLE cehub_ai.ai_issue_applications (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tresult_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tmodel_invocation_id UUID NOT NULL, \n\tprincipal_id UUID NOT NULL, \n\tpolicy_id UUID NOT NULL, \n\tscope_revision_id UUID NOT NULL, \n\trequested_by_user_id UUID NOT NULL, \n\tconfirmed_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tsource_event_row_id BIGINT NOT NULL, \n\tsource_key VARCHAR(128) NOT NULL, \n\tissue_id UUID NOT NULL, \n\tdisposition VARCHAR(16) NOT NULL, \n\tcapture_mode VARCHAR(16) NOT NULL, \n\toutput_event_row_id BIGINT NOT NULL, \n\tissue_event_row_id BIGINT, \n\treceipt JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_ai_issue_applications PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_issue_application_0 FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_1 FOREIGN KEY(tenant_id, project_id, result_id) REFERENCES cehub_ai.ai_issue_event_results (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_2 FOREIGN KEY(tenant_id, run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_3 FOREIGN KEY(tenant_id, model_invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_4 FOREIGN KEY(tenant_id, principal_id) REFERENCES cehub_ai.ai_principals (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_5 FOREIGN KEY(tenant_id, policy_id) REFERENCES cehub_ai.ai_write_policies (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_6 FOREIGN KEY(tenant_id, project_id, scope_revision_id) REFERENCES cehub_ai.ai_write_scope_revisions (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_7 FOREIGN KEY(tenant_id, requested_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_8 FOREIGN KEY(tenant_id, confirmed_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_9 FOREIGN KEY(tenant_id, source_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_10 FOREIGN KEY(tenant_id, output_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_11 FOREIGN KEY(tenant_id, issue_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_application_12 FOREIGN KEY(tenant_id, project_id, issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_ai_issue_applications_shape CHECK (disposition IN ('created','reused') AND capture_mode='trial' AND btrim(source_key)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(receipt)='object' AND ((disposition='created')=(issue_event_row_id IS NOT NULL))), \n\tCONSTRAINT uq_ai_issue_application_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_ai_issue_application_result UNIQUE (tenant_id, result_id), \n\tCONSTRAINT uq_ai_issue_application_source UNIQUE (tenant_id, project_id, source_key), \n\tCONSTRAINT uq_ai_issue_application_event UNIQUE (tenant_id, source_event_row_id), \n\tCONSTRAINT uq_ai_issue_application_request UNIQUE (tenant_id, confirmed_by_user_id, request_id)\n);"
NEW_SCOPE = "operation_key IN ('meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft','event.issue.create') AND revision>0 AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$'"
OLD_SCOPE = "operation_key IN ('meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft') AND revision>0 AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$'"

GUARDS = """
CREATE FUNCTION cehub_ai.guard_issue_application() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM cehub_ai.ai_issue_event_results r
  JOIN cehub_ai.agent_runs run ON run.tenant_id=r.tenant_id AND run.id=r.run_id
  JOIN cehub_project.issues i ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id
  JOIN cehub_ai.ai_write_policies p ON p.tenant_id=r.tenant_id
  JOIN cehub_ai.ai_write_scope_revisions s ON s.tenant_id=r.tenant_id AND s.project_id=r.project_id
  JOIN cehub_event.events e ON e.tenant_id=r.tenant_id AND e.project_id=r.project_id
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.result_id
   AND r.run_id=NEW.run_id AND r.model_invocation_id=NEW.model_invocation_id
   AND r.event_row_id=NEW.source_event_row_id AND r.source_snapshot->>'source_key'=NEW.source_key
   AND r.source_snapshot=NEW.receipt->'source_snapshot' AND r.proposal=NEW.receipt->'proposal'
   AND run.status='succeeded' AND run.requested_by_user_id=NEW.requested_by_user_id
   AND i.id=NEW.issue_id AND i.id::text=NEW.receipt->'issue_snapshot'->>'id'
   AND p.id=NEW.policy_id AND p.principal_id=NEW.principal_id AND p.mode='tiered'
   AND p.operation_settings->'event.issue.create'->>'mode' IN ('confirm','automatic')
   AND s.id=NEW.scope_revision_id AND s.principal_id=NEW.principal_id AND s.enabled
   AND s.operation_key='event.issue.create'
   AND e.id=NEW.output_event_row_id AND e.entity_id=NEW.id
   AND e.event_type='AI_ISSUE_APPLICATION_RECORDED'
   AND e.payload->>'issue_id'=NEW.issue_id::text AND e.payload->>'disposition'=NEW.disposition
   AND (
    (NEW.disposition='reused' AND r.proposal->>'disposition'='reuse_issue'
     AND r.proposal->>'existing_issue_id'=i.id::text)
    OR
    (NEW.disposition='created' AND r.proposal->>'disposition'='create_issue'
     AND i.created_by_ai_principal_id=NEW.principal_id AND i.reported_by_user_id IS NULL
     AND i.title=r.proposal->>'title' AND i.description=r.proposal->>'description'
     AND i.severity=r.proposal->>'severity'
     AND EXISTS(SELECT 1 FROM cehub_event.events created
       WHERE created.tenant_id=NEW.tenant_id AND created.project_id=NEW.project_id
        AND created.id=NEW.issue_event_row_id AND created.entity_id=i.id AND created.event_type='ISSUE_CREATED')
     AND EXISTS(SELECT 1 FROM cehub_quality.test_cases tc
       WHERE tc.tenant_id=NEW.tenant_id AND tc.project_id=NEW.project_id AND tc.related_issue_id=i.id
        AND NEW.source_key='test_case:'||tc.id::text))
   )
 ) THEN RAISE EXCEPTION 'Issue application requires its exact result, source, writer and business receipt'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_issue_application BEFORE INSERT ON cehub_ai.ai_issue_applications
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_application();
CREATE TRIGGER immutable_issue_application BEFORE UPDATE OR DELETE ON cehub_ai.ai_issue_applications
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.ai_issue_applications FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
 REVOKE ALL ON cehub_ai.ai_issue_applications FROM pdos_agent; END IF; END $$;
"""


def _scope(expression: str) -> None:
    op.execute("ALTER TABLE cehub_ai.ai_write_scope_revisions DROP CONSTRAINT ck_ai_write_scope_revisions_shape")
    op.execute("ALTER TABLE cehub_ai.ai_write_scope_revisions ADD CONSTRAINT ck_ai_write_scope_revisions_shape CHECK (" + expression + ")")


def upgrade() -> None:
    _scope(NEW_SCOPE)
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_applications)
     OR EXISTS(SELECT 1 FROM cehub_ai.ai_write_scope_revisions WHERE operation_key='event.issue.create')
     THEN RAISE EXCEPTION 'Retain AI Issue applications and scope history'; END IF; END $$;""")
    op.execute("DROP TABLE cehub_ai.ai_issue_applications")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_application()")
    _scope(OLD_SCOPE)
