"""Defer meeting and template source row resolution until their scope applies."""

from alembic import op

revision = "0372_scoped_run_sources"
down_revision = "0371_scoped_run_record_type"
branch_labels = None
depends_on = None

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_meeting_planning_run()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE b cehub_project.meeting_planning_briefs;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='meeting-planning-request-v1' AND
 (NEW.tenant_id,NEW.project_id,NEW.context_version,NEW.request_id,NEW.requested_by_user_id,
 NEW.run_context-'meeting_planning_finding_id'-'meeting_planning_reading') IS DISTINCT FROM
 (OLD.tenant_id,OLD.project_id,OLD.context_version,OLD.request_id,OLD.requested_by_user_id,
 OLD.run_context-'meeting_planning_finding_id'-'meeting_planning_reading') THEN
 RAISE EXCEPTION 'Meeting planning run input identity is immutable'; END IF;
 IF NEW.context_version<>'meeting-planning-request-v1' THEN RETURN NEW; END IF;
 SELECT * INTO b FROM cehub_project.meeting_planning_briefs WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id::text=NEW.run_context->>'meeting_planning_brief_id'
  AND created_by_user_id=NEW.requested_by_user_id;
 IF b.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.scope_kind<>'project'
  OR NEW.run_context->>'meeting_planning_root_brief_id' IS DISTINCT FROM b.root_id::text
  OR NEW.run_context->>'meeting_planning_source_digest' IS DISTINCT FROM b.source_digest
  OR NEW.run_context->'meeting_planning_source' IS DISTINCT FROM
   b.source_snapshot||jsonb_build_object('brief_id',b.id::text,'source_digest',b.source_digest)
  OR NEW.run_context->>'meeting_planning_prompt_version' IS DISTINCT FROM 'meeting-planning-v1'
  OR coalesce(NEW.run_context->>'meeting_planning_schema_digest','') !~ '^[0-9a-f]{64}$'
  OR coalesce(NEW.run_context->>'meeting_planning_prompt_digest','') !~ '^[0-9a-f]{64}$' THEN
 RAISE EXCEPTION 'Meeting planning run requires exact private sources and contract'; END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION cehub_ai.guard_tenant_template_run()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
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
  OR coalesce(NEW.run_context->>'process_template_prompt_version','') NOT IN
('process-template-configuration-v1','process-template-configuration-v2','process-template-configuration-v3','process-template-configuration-v4','process-template-configuration-v5','process-template-configuration-v6','process-template-configuration-v7','process-template-configuration-v8','process-template-configuration-v9')
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
END $function$;
"""

GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_meeting_planning_run()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE b record;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='meeting-planning-request-v1' AND
 (NEW.tenant_id,NEW.project_id,NEW.context_version,NEW.request_id,NEW.requested_by_user_id,
 NEW.run_context-'meeting_planning_finding_id'-'meeting_planning_reading') IS DISTINCT FROM
 (OLD.tenant_id,OLD.project_id,OLD.context_version,OLD.request_id,OLD.requested_by_user_id,
 OLD.run_context-'meeting_planning_finding_id'-'meeting_planning_reading') THEN
 RAISE EXCEPTION 'Meeting planning run input identity is immutable'; END IF;
 IF NEW.context_version<>'meeting-planning-request-v1' THEN RETURN NEW; END IF;
 SELECT * INTO b FROM cehub_project.meeting_planning_briefs WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id::text=NEW.run_context->>'meeting_planning_brief_id'
  AND created_by_user_id=NEW.requested_by_user_id;
 IF b.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.scope_kind<>'project'
  OR NEW.run_context->>'meeting_planning_root_brief_id' IS DISTINCT FROM b.root_id::text
  OR NEW.run_context->>'meeting_planning_source_digest' IS DISTINCT FROM b.source_digest
  OR NEW.run_context->'meeting_planning_source' IS DISTINCT FROM
   b.source_snapshot||jsonb_build_object('brief_id',b.id::text,'source_digest',b.source_digest)
  OR NEW.run_context->>'meeting_planning_prompt_version' IS DISTINCT FROM 'meeting-planning-v1'
  OR coalesce(NEW.run_context->>'meeting_planning_schema_digest','') !~ '^[0-9a-f]{64}$'
  OR coalesce(NEW.run_context->>'meeting_planning_prompt_digest','') !~ '^[0-9a-f]{64}$' THEN
 RAISE EXCEPTION 'Meeting planning run requires exact private sources and contract'; END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION cehub_ai.guard_tenant_template_run()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE b record;
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
  OR coalesce(NEW.run_context->>'process_template_prompt_version','') NOT IN
('process-template-configuration-v1','process-template-configuration-v2','process-template-configuration-v3','process-template-configuration-v4','process-template-configuration-v5','process-template-configuration-v6','process-template-configuration-v7','process-template-configuration-v8','process-template-configuration-v9')
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
END $function$;
"""


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(OLD_GUARD)
