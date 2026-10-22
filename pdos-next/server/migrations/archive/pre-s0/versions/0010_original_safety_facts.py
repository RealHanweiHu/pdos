"""Bind original consumption to immutable scans and a separate protection epoch."""
# ruff: noqa: E501

from alembic import op

from migrations.schema_0010 import SCHEMA_SQL, TABLES

revision = "next_0010"
down_revision = "next_0009"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("principals", "grants"):
        op.execute(f'ALTER TABLE "{name}" ADD COLUMN access_epoch INTEGER NOT NULL DEFAULT 1')
        op.execute(f'ALTER TABLE "{name}" ALTER COLUMN access_epoch DROP DEFAULT')
    op.execute("""
        CREATE FUNCTION advance_access_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.access_epoch = OLD.access_epoch + 1; RETURN NEW; END $$
    """)
    for name in ("principals", "grants"):
        op.execute(f'CREATE TRIGGER monotonic_access BEFORE UPDATE ON "{name}" '
                   'FOR EACH ROW EXECUTE FUNCTION advance_access_epoch()')
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
        INSERT INTO original_security
            (id,tenant_id,product_id,original_id,epoch,source_state,disposition,created_at)
        SELECT o.id,o.tenant_id,o.product_id,o.id,1,
            CASE WHEN EXISTS (SELECT 1 FROM artifact_versions a
                              WHERE a.original_id=o.id AND a.status<>'active')
                 THEN 'withdrawn' ELSE 'active' END,
            'active',CURRENT_TIMESTAMP
        FROM uploaded_originals o
    """)
    op.execute("""
        CREATE FUNCTION protect_original_security() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Original security history cannot be deleted';
          ELSIF TG_OP = 'INSERT' THEN
            IF NEW.epoch <> 1 OR NEW.current_request_id IS NOT NULL THEN
              RAISE EXCEPTION 'Original security begins without a scan fact';
            END IF;
          ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.original_id,NEW.created_at)
                IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.original_id,OLD.created_at)
                OR NEW.epoch <> OLD.epoch + 1
                OR (OLD.source_state = 'withdrawn' AND NEW.source_state <> 'withdrawn') THEN
            RAISE EXCEPTION 'Original protection epoch must advance without reviving withdrawn sources';
          END IF;
          IF NEW.current_request_id IS NOT NULL AND
             (TG_OP = 'INSERT' OR NEW.current_request_id IS DISTINCT FROM OLD.current_request_id)
             AND NOT EXISTS (SELECT 1 FROM original_scan_requests r
                             WHERE r.id=NEW.current_request_id AND r.tenant_id=NEW.tenant_id
                               AND r.product_id=NEW.product_id AND r.original_id=NEW.original_id
                               AND r.revision=NEW.epoch) THEN
            RAISE EXCEPTION 'Scan pointer must bind the current protection epoch';
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
        current = name == "original_security"
        permissions = "SELECT, INSERT, UPDATE" if current else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        actions = "INSERT OR UPDATE OR DELETE" if current else "UPDATE OR DELETE"
        function = "protect_original_security" if current else "protect_next_snapshot"
        op.execute(
            f'CREATE TRIGGER fixed_snapshot BEFORE {actions} ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_original_security()")
    for name in ("principals", "grants"):
        op.execute(f'DROP TRIGGER monotonic_access ON "{name}"')
        op.drop_column(name, "access_epoch")
    op.execute("DROP FUNCTION advance_access_epoch()")
