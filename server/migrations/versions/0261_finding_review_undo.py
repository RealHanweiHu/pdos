"""Five-second undo of the actor's own unapplied Finding review, including batches."""

from alembic import op

revision = "0261_finding_review_undo"
down_revision = "0260_finding_batches"
branch_labels = None
depends_on = None

NEW_ACTION = """
action IN ('created', 'accepted', 'rejected', 'applied', 'archived', 'restored',
'review_undone')
"""
OLD_ACTION = """
action IN ('created', 'accepted', 'rejected', 'applied', 'archived', 'restored')
"""
NEW_TRANSITION = """
(action = 'created' AND actor_user_id IS NULL AND from_status IS NULL AND to_status =
'pending_review') OR (action IN ('accepted', 'rejected') AND actor_user_id IS NOT NULL AND
from_status = 'pending_review' AND to_status = action) OR (action = 'applied' AND actor_user_id
IS NOT NULL AND from_status = 'accepted' AND to_status = 'applied') OR (action = 'archived' AND
(actor_user_id IS NOT NULL OR (detail->>'automatic'='true' AND
detail->>'policy'='finding-inactivity-v1') IS TRUE) AND from_status = 'pending_review' AND
to_status = 'archived') OR (action = 'restored' AND actor_user_id IS NOT NULL AND from_status =
'archived' AND to_status = 'pending_review') OR (action='review_undone' AND actor_user_id IS NOT
NULL AND from_status IN ('accepted','rejected') AND to_status='pending_review')
"""
OLD_TRANSITION = """
(action = 'created' AND actor_user_id IS NULL AND from_status IS NULL AND to_status =
'pending_review') OR (action IN ('accepted', 'rejected') AND actor_user_id IS NOT NULL AND
from_status = 'pending_review' AND to_status = action) OR (action = 'applied' AND actor_user_id
IS NOT NULL AND from_status = 'accepted' AND to_status = 'applied') OR (action = 'archived' AND
(actor_user_id IS NOT NULL OR (detail->>'automatic'='true' AND
detail->>'policy'='finding-inactivity-v1') IS TRUE) AND from_status = 'pending_review' AND
to_status = 'archived') OR (action = 'restored' AND actor_user_id IS NOT NULL AND from_status =
'archived' AND to_status = 'pending_review')
"""
NEW_BATCH = """
action IN ('accepted','rejected','applied','review_undone') AND request_digest ~
'^[0-9a-f]{64}$'
"""
OLD_BATCH = """
action IN ('accepted','rejected','applied') AND request_digest ~ '^[0-9a-f]{64}$'
"""
NEW_GUARD = """


CREATE OR REPLACE FUNCTION cehub_ai.guard_finding_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Finding batch receipts are immutable'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
  IF NOT EXISTS (SELECT 1 FROM cehub_ai.findings f
   WHERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id
   AND f.id=(item->>'finding_id')::uuid AND f.finding_type=NEW.finding_type
   AND f.updated_at=(item->>'updated_at')::timestamptz
   AND ((NEW.action='review_undone' AND f.status='pending_review' AND EXISTS
     (SELECT 1 FROM cehub_ai.finding_actions a WHERE a.tenant_id=f.tenant_id
      AND a.finding_id=f.id AND a.action='review_undone' AND a.created_at=f.updated_at
      AND a.actor_user_id=NEW.actor_user_id)) OR
    (NEW.action<>'review_undone' AND f.status=NEW.action AND
     (CASE WHEN NEW.action='applied' THEN f.applied_by_user_id
       ELSE f.reviewed_by_user_id END)=NEW.actor_user_id))) THEN
   RAISE EXCEPTION 'Batch must reference actual named Finding decisions';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""
OLD_GUARD = """


CREATE OR REPLACE FUNCTION cehub_ai.guard_finding_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Finding batch receipts are immutable'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
  IF NOT EXISTS (SELECT 1 FROM cehub_ai.findings f
   WHERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id
   AND f.id=(item->>'finding_id')::uuid AND f.finding_type=NEW.finding_type
   AND f.status=NEW.action AND f.updated_at=(item->>'updated_at')::timestamptz
   AND (CASE WHEN NEW.action='applied' THEN f.applied_by_user_id
         ELSE f.reviewed_by_user_id END)=NEW.actor_user_id) THEN
   RAISE EXCEPTION 'Batch must reference actual named Finding decisions';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""


def swap(table: str, suffix: str, expression: str) -> None:
    op.execute(f"ALTER TABLE cehub_ai.{table} DROP CONSTRAINT ck_{table}_{suffix}")
    op.create_check_constraint(op.f(f"ck_{table}_{suffix}"), table, expression, schema="cehub_ai")


def upgrade() -> None:
    swap("finding_actions", "action_allowed", NEW_ACTION)
    swap("finding_actions", "transition_consistent", NEW_TRANSITION)
    swap("finding_batches", "request", NEW_BATCH)
    op.execute("""DROP INDEX cehub_ai.uq_finding_actions_terminal;
    CREATE UNIQUE INDEX uq_finding_actions_terminal ON cehub_ai.finding_actions
    (tenant_id,finding_id,action) WHERE action IN ('created','applied');""")
    op.execute(NEW_GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_ai.finding_actions WHERE action='review_undone')
      OR EXISTS (SELECT 1 FROM cehub_ai.finding_batches WHERE action='review_undone')
      OR EXISTS (SELECT 1 FROM cehub_ai.finding_actions WHERE action IN ('accepted','rejected')
         GROUP BY tenant_id,finding_id,action HAVING count(*)>1) THEN
      RAISE EXCEPTION 'Finding undo and subsequent review history must be retained';
    END IF;
    END $$;
    DROP INDEX cehub_ai.uq_finding_actions_terminal;
    CREATE UNIQUE INDEX uq_finding_actions_terminal ON cehub_ai.finding_actions
    (tenant_id,finding_id,action) WHERE action NOT IN ('archived','restored');""")
    op.execute(OLD_GUARD)
    swap("finding_batches", "request", OLD_BATCH)
    swap("finding_actions", "transition_consistent", OLD_TRANSITION)
    swap("finding_actions", "action_allowed", OLD_ACTION)
