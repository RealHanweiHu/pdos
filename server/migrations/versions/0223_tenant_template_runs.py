"""Allow explicitly scoped organization configuration runs on shared application budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0223_tenant_template_runs"
down_revision = "0222_process_template_briefs"
branch_labels = None
depends_on = None
DDL = """
ALTER TABLE cehub_ai.agent_runs ADD COLUMN scope_kind varchar(16) NOT NULL DEFAULT 'project';
ALTER TABLE cehub_ai.agent_runs ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.application_authorizations ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT uq_agent_run_scope_agent
UNIQUE(tenant_id,scope_kind,id,agent_key);
CREATE UNIQUE INDEX uq_tenant_agent_run_request ON
cehub_ai.agent_runs(tenant_id,agent_key,request_id) WHERE scope_kind='tenant';
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT ck_agent_runs_scope CHECK ((scope_kind='project'
AND project_id IS NOT NULL AND context_version<>'process-template-request-v1') OR
(scope_kind='tenant' AND project_id IS NULL AND agent_key='knowledge_lite' AND
context_version='process-template-request-v1'));
ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_event_bounds_consistent;
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT ck_agent_runs_event_bounds_consistent CHECK
((((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version IN
('report-mapping-request-v1', 'quality-work-package-request-v1')) OR (agent_key='knowledge_lite'
AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1','process-template-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS
NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE);

CREATE FUNCTION cehub_ai.guard_tenant_template_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b cehub_core.process_template_briefs;
BEGIN
 IF TG_OP='UPDATE' AND (NEW.scope_kind,NEW.project_id) IS DISTINCT FROM
(OLD.scope_kind,OLD.project_id) THEN
  RAISE EXCEPTION 'Run scope is immutable';
 END IF;
 IF NEW.scope_kind<>'tenant' THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.agent_key,NEW.request_id,NEW.requested_by_user_id,
  NEW.context_version,NEW.run_context->'process_template_brief_id',
  NEW.run_context->'process_template_root_brief_id',
  NEW.run_context->'process_template_source_digest',NEW.run_context->'process_template_source',
NEW.run_context->'process_template_prompt_version',NEW.run_context->'process_template_schema_digest')
  IS DISTINCT FROM (OLD.tenant_id,OLD.agent_key,OLD.request_id,OLD.requested_by_user_id,
  OLD.context_version,OLD.run_context->'process_template_brief_id',
  OLD.run_context->'process_template_root_brief_id',
  OLD.run_context->'process_template_source_digest',OLD.run_context->'process_template_source',
OLD.run_context->'process_template_prompt_version',OLD.run_context->'process_template_schema_digest')
THEN
  RAISE EXCEPTION 'Organization run input identity is immutable';
 END IF;
 SELECT * INTO b FROM cehub_core.process_template_briefs WHERE tenant_id=NEW.tenant_id
  AND id::text=NEW.run_context->>'process_template_brief_id';
 IF b.id IS NULL OR NEW.run_context->'process_template_source' IS DISTINCT FROM b.source_snapshot
  OR NEW.run_context->>'process_template_source_digest' IS DISTINCT FROM b.source_digest
  OR NEW.run_context->>'process_template_prompt_version' IS DISTINCT FROM
'process-template-configuration-v1'
  OR coalesce(NEW.run_context->>'process_template_schema_digest','') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Organization run requires an exact saved source and fixed prompt contract';
 END IF;
 IF NEW.run_context->>'process_template_root_brief_id' IS DISTINCT FROM (
  WITH RECURSIVE ancestry AS (
   SELECT id,previous_brief_id FROM cehub_core.process_template_briefs WHERE id=b.id
   UNION ALL
   SELECT p.id,p.previous_brief_id FROM cehub_core.process_template_briefs p
    JOIN ancestry a ON p.id=a.previous_brief_id WHERE p.tenant_id=NEW.tenant_id
  ) SELECT id::text FROM ancestry WHERE previous_brief_id IS NULL
 ) THEN RAISE EXCEPTION 'Organization run must retain original requirement lineage'; END IF;
 IF TG_OP='INSERT' AND NOT EXISTS(SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants t ON
t.id=u.tenant_id
  WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.requested_by_user_id AND u.is_active
  AND u.role IN ('owner','admin') AND t.status='active') THEN
  RAISE EXCEPTION 'Organization run requires a current named administrator';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_tenant_template_run() FROM PUBLIC;
CREATE TRIGGER guard_tenant_template_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_tenant_template_run();
ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_project_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE id=wanted_run AND
scope_kind='tenant')
 THEN EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
  JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=r.tenant_id
  JOIN cehub_core.process_template_briefs b ON b.tenant_id=r.tenant_id
    AND b.id::text=r.run_context->>'process_template_brief_id'
  WHERE r.id=wanted_run AND r.scope_kind='tenant' AND r.project_id IS NULL AND a.project_id IS NULL
   AND r.agent_key='knowledge_lite' AND r.context_version='process-template-request-v1'
   AND r.status='running' AND r.requested_by_user_id=a.principal_id
   AND u.is_active AND t.status='active' AND u.role IN ('owner','admin')
   AND a.expires_at>clock_timestamp() AND u.role=a.pins->>'role'
   AND u.auth_version=(a.pins->>'auth_version')::integer
   AND a.pins->>'action'='user.manage' AND a.pins->>'delegation_id' IS NULL
   AND a.pins->>'membership_id' IS NULL
   AND a.body->>'tenant_id'=r.tenant_id::text AND a.body->>'run_id'=r.id::text
   AND a.body->>'principal_id'=a.principal_id::text
   AND a.body->>'purpose'='process_template_configuration'
   AND a.body->'scope'=jsonb_build_object('kind','tenant','ref_id',r.tenant_id::text)
   AND r.run_context->'process_template_source'=b.source_snapshot
   AND r.run_context->>'process_template_source_digest'=b.source_digest
   AND jsonb_array_length(a.body->'sources')=1
   AND a.body->'sources' @> jsonb_build_array(jsonb_build_object(
'kind','process_template_brief','ref_id',b.id::text,'tenant_id',b.tenant_id::text,'digest',b.source_digest))
   AND b.base_release_id IS NOT DISTINCT FROM (SELECT id FROM cehub_core.process_template_releases
      WHERE tenant_id=b.tenant_id AND template_id=b.template_id ORDER BY sequence DESC LIMIT 1)
 ) ELSE cehub_ai.application_project_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""
OLD_EVENT_BOUNDS = """
(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version IN
('report-mapping-request-v1', 'quality-work-package-request-v1')) OR (agent_key='knowledge_lite'
AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS
NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE scope_kind='tenant')")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard tenant-scoped run history")
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute(
        "ALTER FUNCTION cehub_ai.application_project_authorization_is_current(uuid) "
        "RENAME TO application_authorization_is_current"
    )
    op.execute("DROP TRIGGER guard_tenant_template_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_tenant_template_run()")
    op.execute(
        "ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_event_bounds_consistent"
    )
    op.execute(
        "ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT "
        "ck_agent_runs_event_bounds_consistent CHECK (" + OLD_EVENT_BOUNDS + ")"
    )
    op.execute("DROP INDEX cehub_ai.uq_tenant_agent_run_request")
    op.drop_constraint("uq_agent_run_scope_agent", "agent_runs", schema="cehub_ai", type_="unique")
    op.drop_constraint(op.f("ck_agent_runs_scope"), "agent_runs", schema="cehub_ai", type_="check")
    op.drop_column("agent_runs", "scope_kind", schema="cehub_ai")
    op.alter_column("agent_runs", "project_id", nullable=False, schema="cehub_ai")
    op.alter_column("application_authorizations", "project_id", nullable=False, schema="cehub_ai")
