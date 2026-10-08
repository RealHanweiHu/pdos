"""Durable event delivery, immutable originals/definitions and model call ledger."""

import sqlalchemy as sa
from alembic import op

from migrations.schema_0003 import SCHEMA_SQL, TABLES

revision = "next_0003"
down_revision = "next_0002"
branch_labels = None
depends_on = None


ADDITIONS = {
    "artifact_versions": [("original_id", sa.Uuid(), None)],
    "work_requests": [("signal_epoch", sa.Integer(), "0")],
    "runs": [
        ("lease_id", sa.Uuid(), None),
        ("lease_until", sa.DateTime(timezone=True), None),
        ("token_limit", sa.Integer(), "10000"),
        ("reserved_tokens", sa.Integer(), "0"),
        ("used_tokens", sa.Integer(), "0"),
    ],
    "outbox_events": [
        ("lease_id", sa.Uuid(), None),
        ("lease_until", sa.DateTime(timezone=True), None),
        ("attempts", sa.Integer(), "0"),
        ("last_error", sa.String(80), None),
    ],
}


def upgrade():
    op.create_unique_constraint("uq_outbox_tenant_id", "outbox_events", ["tenant_id", "id"])
    for statement in SCHEMA_SQL:
        op.execute(statement)
    for table, columns in ADDITIONS.items():
        for name, kind, initial in columns:
            op.add_column(
                table, sa.Column(name, kind, nullable=initial is None, server_default=initial)
            )
            if initial is not None:
                op.alter_column(table, name, server_default=None)
    op.create_unique_constraint(
        "uq_artifact_original", "artifact_versions", ["tenant_id", "original_id"]
    )
    op.create_foreign_key(
        "fk_artifact_original",
        "artifact_versions",
        "uploaded_originals",
        ["tenant_id", "product_id", "original_id"],
        ["tenant_id", "product_id", "id"],
    )
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)"
        )
        operations = (
            "SELECT, INSERT" if name.startswith("definition_") else "SELECT, INSERT, UPDATE"
        )
        op.execute(f'GRANT {operations} ON "{name}" TO pdos_next_app')
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")
    op.execute("""
      CREATE FUNCTION protect_fixed_definition() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'definition snapshots are immutable'; END $$
    """)
    for name in ["definition_revisions", "definition_specs", "definition_sources"]:
        op.execute(
            f'CREATE TRIGGER fixed_definition BEFORE UPDATE OR DELETE ON "{name}" '
            "FOR EACH ROW EXECUTE FUNCTION protect_fixed_definition()"
        )
    op.execute("""
      CREATE FUNCTION protect_uploaded_original() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.owner_id,NEW.title,NEW.filename,
               NEW.source_label,NEW.visibility,NEW.media_type,NEW.byte_count,NEW.content_hash,
               NEW.storage_key,NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.owner_id,OLD.title,OLD.filename,
               OLD.source_label,OLD.visibility,OLD.media_type,OLD.byte_count,OLD.content_hash,
               OLD.storage_key,OLD.created_at) THEN
          RAISE EXCEPTION 'uploaded original is immutable';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER uploaded_original_fixed BEFORE UPDATE ON uploaded_originals "
        "FOR EACH ROW EXECUTE FUNCTION protect_uploaded_original()"
    )


def downgrade():
    op.drop_constraint("fk_artifact_original", "artifact_versions", type_="foreignkey")
    op.drop_constraint("uq_artifact_original", "artifact_versions", type_="unique")
    for table, columns in reversed(list(ADDITIONS.items())):
        for name, _kind, _initial in reversed(columns):
            op.drop_column(table, name)
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_uploaded_original()")
    op.execute("DROP FUNCTION protect_fixed_definition()")
    op.drop_constraint("uq_outbox_tenant_id", "outbox_events", type_="unique")
