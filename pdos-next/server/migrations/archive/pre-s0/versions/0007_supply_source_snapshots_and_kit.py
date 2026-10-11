"""Bind external supply observations and coverage to persisted Build demand."""

from alembic import op

from migrations.schema_0007 import SCHEMA_SQL, TABLES

revision = "next_0007"
down_revision = "next_0006"
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
        CREATE FUNCTION protect_supply_pointer() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Supply current pointer cannot be deleted';
          END IF;
          IF ROW(NEW.id, NEW.tenant_id, NEW.product_id, NEW.build_id, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.tenant_id, OLD.product_id, OLD.build_id, OLD.created_at)
             OR NEW.snapshot_revision <> OLD.snapshot_revision + 1
             OR NOT EXISTS (
               SELECT 1 FROM supply_snapshots n
               WHERE n.id = NEW.snapshot_id AND n.tenant_id = OLD.tenant_id
                 AND n.product_id = OLD.product_id AND n.build_id = OLD.build_id
                 AND n.previous_snapshot_id = OLD.snapshot_id
                 AND n.previous_revision = OLD.snapshot_revision
             ) THEN
            RAISE EXCEPTION 'Supply pointer must advance along the fixed history';
          END IF;
          RETURN NEW;
        END $$
    """)
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)"
        )
        pointer = name == "supply_current_snapshots"
        permissions = "SELECT, INSERT, UPDATE" if pointer else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        function = "protect_supply_pointer" if pointer else "protect_next_snapshot"
        op.execute(
            f'CREATE TRIGGER fixed_snapshot BEFORE UPDATE OR DELETE ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_supply_pointer()")
