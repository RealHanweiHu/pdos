"""Keep human verification preparation distinct from qualified physical execution."""

from alembic import op

from migrations.schema_0009 import SCHEMA_SQL, TABLES

revision = "next_0009"
down_revision = "next_0008"
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
        CREATE FUNCTION protect_verification_preparation_pointer() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Verification preparation pointer cannot be deleted';
          ELSIF TG_OP = 'INSERT' THEN
            IF NEW.preparation_revision <> 1 OR NOT EXISTS (
              SELECT 1 FROM verification_preparations n
              WHERE n.id = NEW.preparation_id AND n.tenant_id = NEW.tenant_id
                AND n.product_id = NEW.product_id AND n.request_id = NEW.request_id
                AND n.revision = 1 AND n.previous_preparation_id IS NULL
                AND n.previous_revision IS NULL
            ) THEN
              RAISE EXCEPTION 'First preparation pointer must identify the original version';
            END IF;
          ELSIF ROW(NEW.id, NEW.tenant_id, NEW.product_id, NEW.request_id, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.tenant_id, OLD.product_id, OLD.request_id, OLD.created_at)
             OR NEW.preparation_revision <> OLD.preparation_revision + 1
             OR NOT EXISTS (
               SELECT 1 FROM verification_preparations n
               JOIN verification_preparations o ON o.id = OLD.preparation_id
               WHERE n.id = NEW.preparation_id AND n.tenant_id = OLD.tenant_id
                 AND n.product_id = OLD.product_id AND n.request_id = OLD.request_id
                 AND n.project_id = o.project_id AND n.build_id = o.build_id
                 AND n.build_revision = o.build_revision
                 AND n.owner_id = o.owner_id AND n.visibility = o.visibility
                 AND n.previous_preparation_id = OLD.preparation_id
                 AND n.previous_revision = OLD.preparation_revision
             ) THEN
            RAISE EXCEPTION 'Preparation pointer must preserve its fixed history and scope';
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
        pointer = name == "verification_current_preparations"
        permissions = "SELECT, INSERT, UPDATE" if pointer else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        function = (
            "protect_verification_preparation_pointer" if pointer else "protect_next_snapshot"
        )
        actions = "INSERT OR UPDATE OR DELETE" if pointer else "UPDATE OR DELETE"
        op.execute(
            f'CREATE TRIGGER fixed_snapshot BEFORE {actions} ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_verification_preparation_pointer()")
