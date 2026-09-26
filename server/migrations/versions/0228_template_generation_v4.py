"""Add pinned reminder generation v4 without changing older run contracts."""

import sqlalchemy as sa
from alembic import op

revision = "0228_template_generation_v4"
down_revision = "0227_template_generation_v3"
branch_labels = None
depends_on = None

V3 = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_tenant_template_run() RETURNS trigger
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
  OR coalesce(NEW.run_context->>'process_template_prompt_version','') NOT IN
('process-template-configuration-v1','process-template-configuration-v2','process-template-configuration-v3')
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
"""

V4 = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_tenant_template_run() RETURNS trigger
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
  OR coalesce(NEW.run_context->>'process_template_prompt_version','') NOT IN
('process-template-configuration-v1','process-template-configuration-v2','process-template-configuration-v3','process-template-configuration-v4')
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
"""


def upgrade() -> None:
    op.execute(V4)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE scope_kind='tenant'
          AND run_context->>'process_template_prompt_version'='process-template-configuration-v4')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard reminder generation v4 history")
    op.execute(V3)
