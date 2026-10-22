"""Permit confirmed category creation to register its earlier personal public research."""

from alembic import op

revision = "s0_0706"
down_revision = "s0_0705"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE OR REPLACE FUNCTION kernel_snapshot_guard() RETURNS trigger
      LANGUAGE plpgsql AS $$ DECLARE r agent_runs; a action_receipts;
      BEGIN
        SELECT * INTO r FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.registered_by_run_id;
        SELECT * INTO a FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
        IF r.id IS NULL OR a.id IS NULL OR r.requester_id<>NEW.owner_id OR r.state='cancelled'
          OR a.requester_id<>r.requester_id OR a.category_id IS DISTINCT FROM NEW.category_id
          OR NOT COALESCE(((r.category_id=NEW.category_id AND a.operation='research.snapshot.register'
                    AND a.subject_id=NEW.id)
                  OR (r.category_id IS NULL AND NOT r.private_context AND a.operation='category.create'
                    AND a.subject_id=NEW.category_id)),false)
          OR NEW.visibility<>(CASE WHEN r.private_context THEN 'private' ELSE 'category' END)
          OR NEW.content_hash<>encode(sha256(convert_to(NEW.markdown,'UTF8')),'hex')
        THEN RAISE EXCEPTION 'Snapshot scope/hash/receipt invalid'; END IF;
        RETURN NEW;
      END $$""")


def downgrade():
    # Frozen baseline text, not current metadata generation.
    from migrations.schema_s0_0700 import SQL

    prior = next(sql for sql in SQL if sql.startswith("CREATE FUNCTION kernel_snapshot_guard()"))
    op.execute(prior.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
