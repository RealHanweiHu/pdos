"""Allow audited owner succession while retaining market space identity."""

from alembic import op

revision = "0267_space_responsibility"
down_revision = "0266_task_takeover_packets"
branch_labels = None
depends_on = None

IDENTITY = """
CREATE OR REPLACE FUNCTION cehub_product.protect_market_space_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Market space history cannot be deleted' USING ERRCODE='42501';
 END IF;
 IF (NEW.id,NEW.tenant_id,NEW.code,{new_owner}NEW.request_id,NEW.request_digest,NEW.created_at)
 IS DISTINCT FROM
 (OLD.id,OLD.tenant_id,OLD.code,{old_owner}OLD.request_id,OLD.request_digest,OLD.created_at) THEN
  RAISE EXCEPTION 'Market space identity is immutable' USING ERRCODE='42501';
 END IF;
 IF NEW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION 'Market space version must advance once' USING ERRCODE='22023';
 END IF;
 {owner_guard}
 RETURN NEW;
END $$;
"""
OWNER_GUARD = """
 IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id THEN
  IF OLD.lifecycle='archived' OR
   (to_jsonb(NEW)-ARRAY['owner_user_id','version','updated_at']) IS DISTINCT FROM
   (to_jsonb(OLD)-ARRAY['owner_user_id','version','updated_at']) THEN
   RAISE EXCEPTION 'Owner succession only changes active space responsibility'
    USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM cehub_product.market_space_members m
   JOIN cehub_core.users u ON u.tenant_id=m.tenant_id AND u.id=m.user_id
   WHERE m.tenant_id=NEW.tenant_id AND m.market_space_id=NEW.id
   AND m.user_id=NEW.owner_user_id AND m.access='manager' AND u.is_active
   AND u.role IN ('owner','admin','project_manager')) THEN
   RAISE EXCEPTION 'Incoming owner requires existing space management access'
    USING ERRCODE='42501';
  END IF;
 END IF;
"""
AUDIT_GUARD = """
CREATE FUNCTION cehub_product.require_space_owner_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
  WHERE a.tenant_id=NEW.tenant_id AND a.entity_id=NEW.id
  AND a.action='preproject.responsibility.changed'
  AND a.context->>'kind'='space'
  AND a.context->>'market_space_id'=NEW.id::text
  AND length(btrim(a.context->>'reason'))>0
  AND a.context->>'request_id' IS NOT NULL
  AND (a.before_snapshot::jsonb-ARRAY['created_at','updated_at'])=
   (to_jsonb(OLD)-ARRAY['created_at','updated_at'])
  AND (a.after_snapshot::jsonb-ARRAY['created_at','updated_at'])=
   (to_jsonb(NEW)-ARRAY['created_at','updated_at'])
  AND (a.before_snapshot->>'created_at')::timestamptz=OLD.created_at
  AND (a.before_snapshot->>'updated_at')::timestamptz=OLD.updated_at
  AND (a.after_snapshot->>'created_at')::timestamptz=NEW.created_at
  AND (a.after_snapshot->>'updated_at')::timestamptz=NEW.updated_at) THEN
  RAISE EXCEPTION 'Space owner succession requires its exact audit receipt'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER require_space_owner_receipt AFTER UPDATE
ON cehub_product.market_spaces DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW WHEN (OLD.owner_user_id IS DISTINCT FROM NEW.owner_user_id)
EXECUTE FUNCTION cehub_product.require_space_owner_receipt();
REVOKE ALL ON FUNCTION cehub_product.require_space_owner_receipt() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(IDENTITY.format(new_owner="", old_owner="", owner_guard=OWNER_GUARD))
    op.execute(AUDIT_GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER require_space_owner_receipt ON cehub_product.market_spaces")
    op.execute("DROP FUNCTION cehub_product.require_space_owner_receipt()")
    op.execute(
        IDENTITY.format(
            new_owner="NEW.owner_user_id,", old_owner="OLD.owner_user_id,", owner_guard=""
        )
    )
