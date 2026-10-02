"""Allow the dispatcher to recognize exact AI success without business-table reads."""

from alembic import op

revision = "0388_ai_issue_silent_events"
down_revision = "0387_ai_issue_withdrawals"
branch_labels = None
depends_on = None

DDL = """
CREATE OR REPLACE FUNCTION cehub_ai.is_silent_ai_issue_event(
 p_tenant uuid, p_project uuid, p_event bigint, p_issue uuid
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT EXISTS(
  SELECT 1 FROM cehub_event.events e
  JOIN cehub_ai.ai_issue_applications app
   ON app.tenant_id=e.tenant_id AND app.project_id=e.project_id
   AND app.issue_event_row_id=e.id AND app.issue_id=e.entity_id
  JOIN cehub_project.issues i
   ON i.tenant_id=app.tenant_id AND i.project_id=app.project_id AND i.id=app.issue_id
  JOIN cehub_audit.audit_log a
   ON a.tenant_id=e.tenant_id AND a.project_id=e.project_id AND a.event_id=e.event_id
   AND a.entity=e.entity AND a.entity_id=e.entity_id AND a.timestamp=e.timestamp
  WHERE e.id=p_event AND e.tenant_id=p_tenant AND e.project_id=p_project
   AND e.entity_id=p_issue AND e.event_type='ISSUE_CREATED'
   AND e.entity='issue' AND e.source='issue_service'
   AND app.disposition='created' AND i.created_by_ai_principal_id=app.principal_id
   AND i.reported_by_user_id IS NULL AND a.action='issue.create'
   AND a.actor_user_id IS NULL AND a.context->>'origin'='ai'
   AND a.context->>'application_id'=app.id::text
   AND a.context->>'writer_principal_id'=app.principal_id::text
   AND a.context->>'result_id'=app.result_id::text
   AND a.context->>'run_id'=app.run_id::text
   AND a.context->>'model_invocation_id'=app.model_invocation_id::text
   AND a.context->>'source_event_row_id'=app.source_event_row_id::text
 );
$body$;
REVOKE ALL ON FUNCTION cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid) FROM PUBLIC;
DO $acl$
BEGIN
 IF EXISTS (
  SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
  WHERE p.oid='cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid)'::regprocedure
   AND r.rolname IN ('pdos_worker','pdos_agent')
 ) THEN
  RAISE EXCEPTION 'Silent Issue event predicate must be owned by the application migration role';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pdos_agent') THEN
  REVOKE ALL ON FUNCTION cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid)
   FROM pdos_agent;
 END IF;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pdos_worker') THEN
  GRANT EXECUTE ON FUNCTION cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid)
   TO pdos_worker;
 END IF;
END $acl$;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP FUNCTION cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid)")
