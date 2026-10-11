"""Independent new-engineering migration history: trusted source/command/work slice."""

from alembic import op

from migrations.schema_0001 import SCHEMA_SQL, TABLES

revision = "next_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    for name in TABLES:
        if name == "login_sessions":
            op.execute("GRANT SELECT ON login_sessions TO pdos_next_auth")
            continue
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)"
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON "{name}" TO pdos_next_app')
    # Capability eligibility is provisioned only by a separate trusted authority.
    op.execute("REVOKE INSERT, UPDATE ON qualifications FROM pdos_next_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")
    op.execute("""
      CREATE FUNCTION protect_artifact_original() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.content IS DISTINCT FROM OLD.content
          OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
          OR NEW.product_id IS DISTINCT FROM OLD.product_id
          OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
          OR NEW.visibility IS DISTINCT FROM OLD.visibility THEN
          RAISE EXCEPTION 'artifact original is immutable';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute("""
      CREATE TRIGGER artifact_original_immutable BEFORE UPDATE ON artifact_versions
      FOR EACH ROW EXECUTE FUNCTION protect_artifact_original()
    """)
    for name in ("action_receipts", "audit_entries"):
        op.execute(f'REVOKE UPDATE ON "{name}" FROM pdos_next_app')


def downgrade():
    op.execute("DROP TRIGGER artifact_original_immutable ON artifact_versions")
    op.execute("DROP FUNCTION protect_artifact_original")
    for name in reversed(TABLES):
        op.execute(f'DROP TABLE "{name}"')
