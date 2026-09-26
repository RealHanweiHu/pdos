"""Audited, paused subscription ownership changes with cancelled prior leases."""

from alembic import op

revision = "0268_subscription_responsibility"
down_revision = "0267_space_responsibility"
branch_labels = None
depends_on = None

IDENTITY = """
CREATE OR REPLACE FUNCTION cehub_evidence.protect_research_subscription() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Subscription history cannot be deleted' USING ERRCODE='42501';
 END IF;
 IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.source_id,
 {new_owner}NEW.url,NEW.hostname,NEW.request_id,NEW.request_digest,NEW.created_at)
 IS DISTINCT FROM
 (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.source_id,
 {old_owner}OLD.url,OLD.hostname,OLD.request_id,OLD.request_digest,OLD.created_at) THEN
  RAISE EXCEPTION 'Subscription identity is immutable' USING ERRCODE='42501';
 END IF;
 IF NEW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION 'Subscription version must advance once' USING ERRCODE='22023';
 END IF;
 {owner_guard}
 RETURN NEW;
END $$;
"""
OWNER_GUARD = """
 IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id THEN
  IF NEW.status<>'paused' OR NEW.next_due_at IS NOT NULL OR
   NEW.lease_token IS NOT NULL OR NEW.lease_expires_at IS NOT NULL OR
   (to_jsonb(NEW)-ARRAY['owner_user_id','status','next_due_at','lease_token',
      'lease_expires_at','version','updated_at']) IS DISTINCT FROM
   (to_jsonb(OLD)-ARRAY['owner_user_id','status','next_due_at','lease_token',
      'lease_expires_at','version','updated_at']) THEN
   RAISE EXCEPTION 'Ownership transfer must pause without changing collection history'
    USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM cehub_core.users u
    JOIN cehub_product.market_space_members m ON m.tenant_id=u.tenant_id AND m.user_id=u.id
    WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.owner_user_id AND u.is_active
    AND u.role IN ('owner','admin','project_manager','engineer','quality')
    AND m.market_space_id=NEW.market_space_id AND m.access IN ('contributor','manager')
    AND (NEW.product_line_id IS NULL OR EXISTS(SELECT 1 FROM cehub_product.product_line_members p
      WHERE p.tenant_id=NEW.tenant_id AND p.product_line_id=NEW.product_line_id
      AND p.user_id=u.id AND p.access IN ('contributor','manager')))) THEN
   RAISE EXCEPTION 'Incoming subscription owner needs existing scope access'
    USING ERRCODE='42501';
  END IF;
 END IF;
"""
AUDIT_GUARD = """
CREATE FUNCTION cehub_evidence.require_subscription_owner_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.lease_token IS NOT NULL AND EXISTS(SELECT 1 FROM cehub_evidence.research_collection_runs r
   WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.lease_token AND r.status='running') THEN
  RAISE EXCEPTION 'Previous collection lease must be cancelled in the same transaction'
   USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
  WHERE a.tenant_id=NEW.tenant_id AND a.entity_id=NEW.id
  AND a.action='preproject.responsibility.changed' AND a.context->>'kind'='subscription'
  AND a.context->>'market_space_id'=NEW.market_space_id::text
  AND length(btrim(a.context->>'reason'))>0 AND a.context->>'request_id' IS NOT NULL
  AND to_jsonb(jsonb_populate_record(NULL::cehub_evidence.research_subscriptions,
       a.before_snapshot::jsonb))=to_jsonb(OLD)
  AND to_jsonb(jsonb_populate_record(NULL::cehub_evidence.research_subscriptions,
       a.after_snapshot::jsonb))=to_jsonb(NEW)) THEN
  RAISE EXCEPTION 'Subscription owner change requires its exact audit receipt'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER require_subscription_owner_receipt AFTER UPDATE
ON cehub_evidence.research_subscriptions DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW WHEN (OLD.owner_user_id IS DISTINCT FROM NEW.owner_user_id)
EXECUTE FUNCTION cehub_evidence.require_subscription_owner_receipt();
REVOKE ALL ON FUNCTION cehub_evidence.require_subscription_owner_receipt() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(IDENTITY.format(new_owner="", old_owner="", owner_guard=OWNER_GUARD))
    op.execute(AUDIT_GUARD)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER require_subscription_owner_receipt ON cehub_evidence.research_subscriptions"
    )
    op.execute("DROP FUNCTION cehub_evidence.require_subscription_owner_receipt()")
    op.execute(
        IDENTITY.format(
            new_owner="NEW.owner_user_id,", old_owner="OLD.owner_user_id,", owner_guard=""
        )
    )
