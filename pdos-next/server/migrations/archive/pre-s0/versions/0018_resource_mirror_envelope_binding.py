"""Validate occupancy against the shared mirror's retained state/value envelope."""

from alembic import op

revision = "next_0018"
down_revision = "next_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE OR REPLACE FUNCTION protect_operational_resource_identity()
      RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE asset operational_asset_sentinels%ROWTYPE;
      BEGIN
        SELECT * INTO asset FROM operational_asset_sentinels
          WHERE tenant_id=NEW.tenant_id AND id=NEW.asset_id;
        IF asset.id IS NULL OR asset.kind<>'resource' OR asset.revision<>NEW.resource_revision
          OR asset.identity->>'id' IS DISTINCT FROM NEW.resource_id::text
          OR asset.data->>'state' IS DISTINCT FROM 'active'
          OR asset.data->'value'->'resource'->>'id' IS DISTINCT FROM NEW.resource_id::text
          OR asset.data->'value'->'resource'->>'kind' IS DISTINCT FROM asset.identity->>'kind'
          OR (asset.data->'value'->'resource'->>'revision')::int
             IS DISTINCT FROM NEW.resource_revision THEN
          RAISE EXCEPTION 'Resource occupancy must bind its exact current physical sentinel';
        END IF;
        RETURN NEW;
      END $$;
    """)


def downgrade():
    op.execute("""
      CREATE OR REPLACE FUNCTION protect_operational_resource_identity()
      RETURNS trigger LANGUAGE plpgsql AS $$
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
    """)
