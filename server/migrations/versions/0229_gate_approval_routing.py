"""Pin project-creation approval dependencies into each Gate review round."""

import sqlalchemy as sa
from alembic import op

revision = "0229_gate_approval_routing"
down_revision = "0228_template_generation_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE cehub_project.gate_signoff_rounds
      ADD COLUMN routing_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE cehub_project.gate_signoff_rounds ADD CONSTRAINT
      ck_gate_signoff_rounds_routing_snapshot_object
      CHECK(jsonb_typeof(routing_snapshot)='object');
    CREATE FUNCTION cehub_project.guard_gate_routing_snapshot() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.routing_snapshot IS DISTINCT FROM OLD.routing_snapshot THEN
        RAISE EXCEPTION 'Gate round routing snapshot is immutable';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_gate_routing_snapshot() FROM PUBLIC;
    CREATE TRIGGER guard_gate_routing_snapshot BEFORE UPDATE
      ON cehub_project.gate_signoff_rounds FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_gate_routing_snapshot();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.gate_signoff_rounds
          WHERE routing_snapshot <> '{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard fixed Gate approval routing history")
    op.execute("""
        DROP TRIGGER guard_gate_routing_snapshot ON cehub_project.gate_signoff_rounds;
        DROP FUNCTION cehub_project.guard_gate_routing_snapshot();
        ALTER TABLE cehub_project.gate_signoff_rounds
          DROP CONSTRAINT ck_gate_signoff_rounds_routing_snapshot_object,
          DROP COLUMN routing_snapshot;
    """)
