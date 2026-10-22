"""A resource occupancy must lock the exact physical identity it occupies."""

from alembic import op

revision = "next_0017"
down_revision = "next_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "operational_resource_asset_identity",
        "operational_resource_occupancies",
        "asset_id=resource_id",
    )
    op.execute("""
      CREATE FUNCTION protect_operational_resource_identity() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE asset operational_asset_sentinels%ROWTYPE;
      BEGIN
        SELECT * INTO asset FROM operational_asset_sentinels
          WHERE tenant_id=NEW.tenant_id AND id=NEW.asset_id;
        IF asset.id IS NULL OR asset.kind<>'resource' OR asset.revision<>NEW.resource_revision
          OR asset.data->'resource'->>'id' IS DISTINCT FROM NEW.resource_id::text THEN
          RAISE EXCEPTION 'Resource occupancy must bind its exact current physical sentinel';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER physical_resource_binding BEFORE INSERT ON operational_resource_occupancies
        FOR EACH ROW EXECUTE FUNCTION protect_operational_resource_identity();
    """)


def downgrade():
    op.execute("DROP TRIGGER physical_resource_binding ON operational_resource_occupancies")
    op.execute("DROP FUNCTION protect_operational_resource_identity()")
    op.drop_constraint(
        "operational_resource_asset_identity", "operational_resource_occupancies", type_="check"
    )
