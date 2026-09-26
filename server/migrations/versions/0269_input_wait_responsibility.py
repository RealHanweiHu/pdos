"""Permit audited human follow-up reassignment without moving model authority."""

from alembic import op

revision = "0269_input_wait_responsibility"
down_revision = "0268_subscription_responsibility"
branch_labels = None
depends_on = None

IDENTITY = """
CREATE OR REPLACE FUNCTION cehub_ai.protect_application_input_wait() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'application wait history is retained'; END IF;
 IF OLD.resolved_at IS NOT NULL OR
  (to_jsonb(NEW)-ARRAY['resolved_at','resolution','continuation_run_id'{owner_column}])
  IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['resolved_at','resolution','continuation_run_id'{owner_column}]) THEN
  RAISE EXCEPTION 'application wait identity and resolved receipt are immutable';
 END IF;
 {owner_guard}
 RETURN NEW;
END $$;
"""
OWNER_GUARD = """
 IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id THEN
  IF NEW.resolved_at IS NOT NULL OR NEW.expires_at<=clock_timestamp() OR
   (to_jsonb(NEW)-'owner_user_id') IS DISTINCT FROM (to_jsonb(OLD)-'owner_user_id') OR
   NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r
    JOIN cehub_ai.findings f ON f.tenant_id=r.tenant_id AND f.run_id=r.id
    JOIN cehub_project.project_members m ON m.tenant_id=r.tenant_id AND m.project_id=r.project_id
    JOIN cehub_core.users u ON u.tenant_id=m.tenant_id AND u.id=m.user_id
    WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.status='waiting_input'
     AND f.id=NEW.finding_id AND f.finding_type='test_plan_change' AND f.status='pending_review'
     AND u.id=NEW.owner_user_id AND u.is_active
     AND u.role IN ('owner','admin','project_manager','engineer','quality')) THEN
   RAISE EXCEPTION 'Incoming human reviewer must retain the original active wait and authority'
    USING ERRCODE='23514';
  END IF;
 END IF;
"""
AUDIT_GUARD = """
CREATE FUNCTION cehub_ai.require_input_owner_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
  JOIN cehub_ai.agent_runs r ON r.tenant_id=a.tenant_id AND r.project_id=a.project_id
  WHERE a.tenant_id=NEW.tenant_id AND a.entity_id=NEW.id AND r.id=NEW.run_id
   AND a.action='application_input.responsibility.changed'
   AND length(btrim(a.context->>'reason'))>0 AND a.context->>'request_id' IS NOT NULL
   AND to_jsonb(jsonb_populate_record(NULL::cehub_ai.application_input_waits,
       a.before_snapshot::jsonb))=to_jsonb(OLD)
   AND to_jsonb(jsonb_populate_record(NULL::cehub_ai.application_input_waits,
       a.after_snapshot::jsonb))=to_jsonb(NEW)) THEN
  RAISE EXCEPTION 'Input owner change requires its exact audit receipt' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER require_input_owner_receipt AFTER UPDATE
ON cehub_ai.application_input_waits DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW WHEN (OLD.owner_user_id IS DISTINCT FROM NEW.owner_user_id)
EXECUTE FUNCTION cehub_ai.require_input_owner_receipt();
REVOKE ALL ON FUNCTION cehub_ai.require_input_owner_receipt() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(IDENTITY.format(owner_column=",'owner_user_id'", owner_guard=OWNER_GUARD))
    op.execute(AUDIT_GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER require_input_owner_receipt ON cehub_ai.application_input_waits")
    op.execute("DROP FUNCTION cehub_ai.require_input_owner_receipt()")
    op.execute(IDENTITY.format(owner_column="", owner_guard=""))
