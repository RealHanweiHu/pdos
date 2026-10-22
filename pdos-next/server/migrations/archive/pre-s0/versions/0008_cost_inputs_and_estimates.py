"""Bind immutable cost inputs and deterministic estimates to fixed Build demand."""

from alembic import op

from migrations.schema_0008 import SCHEMA_SQL, TABLES

revision = "next_0008"
down_revision = "next_0007"
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
        CREATE FUNCTION protect_cost_pointer() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Cost current pointer cannot be deleted';
          ELSIF TG_OP = 'INSERT' THEN
            IF NEW.input_revision <> 1 OR NOT EXISTS (
              SELECT 1 FROM cost_input_snapshots n
              WHERE n.id = NEW.input_id AND n.tenant_id = NEW.tenant_id
                AND n.product_id = NEW.product_id AND n.build_id = NEW.build_id
                AND n.revision = 1 AND n.previous_input_id IS NULL
                AND n.previous_revision IS NULL
            ) THEN
              RAISE EXCEPTION 'First cost pointer must identify the original version';
            END IF;
          ELSIF ROW(NEW.id, NEW.tenant_id, NEW.product_id, NEW.build_id, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.tenant_id, OLD.product_id, OLD.build_id, OLD.created_at)
             OR NEW.input_revision <> OLD.input_revision + 1
             OR NOT EXISTS (
               SELECT 1 FROM cost_input_snapshots n
               WHERE n.id = NEW.input_id AND n.tenant_id = OLD.tenant_id
                 AND n.product_id = OLD.product_id AND n.build_id = OLD.build_id
                 AND n.previous_input_id = OLD.input_id
                 AND n.previous_revision = OLD.input_revision
             ) THEN
            RAISE EXCEPTION 'Cost pointer must advance along the fixed history';
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
        pointer = name == "cost_current_inputs"
        permissions = "SELECT, INSERT, UPDATE" if pointer else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        function = "protect_cost_pointer" if pointer else "protect_next_snapshot"
        actions = "INSERT OR UPDATE OR DELETE" if pointer else "UPDATE OR DELETE"
        op.execute(
            f'CREATE TRIGGER fixed_snapshot BEFORE {actions} ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_cost_pointer()")
