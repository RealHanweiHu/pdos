"""Maintain professional Current summaries at import, without consumer recertification."""

from alembic import op

revision = "s0_0400"
down_revision = "s0_0011"
branch_labels = ("business_s0",)
depends_on = None

FIELDS = (
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "subject_id",
    "owner_id",
    "visibility",
    "kind",
    "role",
    "nature",
    "issuer_key",
    "issuer_version",
    "external_id",
    "operations",
    "purposes",
    "state",
    "valid_from",
    "valid_until",
    "series_id",
    "revision",
    "fact_sha256",
    "required_source_read_set",
)


def upgrade():
    op.execute(
        "ALTER TABLE professional_authority_current "
        "ADD COLUMN summary jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    pairs = ",".join(f"'{key}',f.{key}" for key in FIELDS)
    # This adds a projection to existing pointers without advancing their history.
    # ALTER TABLE holds the migration transaction's exclusive lock during backfill.
    op.execute("ALTER TABLE professional_authority_current DISABLE TRIGGER USER")
    op.execute(
        f"UPDATE professional_authority_current c SET summary=jsonb_build_object({pairs}) "
        "FROM professional_authority_facts f WHERE f.id=c.fact_id"
    )
    op.execute("ALTER TABLE professional_authority_current ENABLE TRIGGER USER")
    op.execute(f"""
CREATE FUNCTION professional_current_summary() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 SELECT jsonb_build_object({pairs}) INTO NEW.summary
 FROM professional_authority_facts f
 WHERE f.tenant_id=NEW.tenant_id AND f.category_id=NEW.category_id
  AND f.product_id=NEW.product_id AND f.project_id=NEW.project_id
  AND f.subject_id=NEW.subject_id AND f.id=NEW.fact_id
  AND f.series_id=NEW.series_id AND f.kind=NEW.kind
  AND f.issuer_key=NEW.issuer_key AND f.external_id=NEW.external_id
  AND f.revision=NEW.fact_revision AND NEW.epoch=NEW.fact_revision;
 IF NEW.summary IS NULL THEN RAISE EXCEPTION 'Professional Current scope mismatch'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION professional_current_summary() FROM PUBLIC,pdos_agent;
CREATE TRIGGER professional_current_summary BEFORE INSERT OR UPDATE
 ON professional_authority_current FOR EACH ROW EXECUTE FUNCTION professional_current_summary();
CREATE FUNCTION professional_summary_visible(t uuid,c uuid,p uuid,body jsonb) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT source_object_audience(t,c,'professional_authority_facts',
  (body->>'id')::uuid,(body->>'owner_id')::uuid,body->>'visibility')
  AND direct_source_set_visible(t,c,p,body->'required_source_read_set')
  AND EXISTS(SELECT 1 FROM projects x WHERE x.tenant_id=t AND x.category_id=c
   AND x.product_id=p AND x.id=(body->>'project_id')::uuid
   AND source_object_audience(t,c,'projects',x.id,x.owner_id,x.visibility))
$$;
REVOKE ALL ON FUNCTION professional_summary_visible(uuid,uuid,uuid,jsonb) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION professional_summary_visible(uuid,uuid,uuid,jsonb) TO pdos_next_app;
CREATE POLICY professional_summary_audience ON professional_authority_current AS RESTRICTIVE
 FOR SELECT TO pdos_next_app USING
 (professional_summary_visible(tenant_id,category_id,product_id,summary));
""")


def downgrade():
    op.execute("DROP POLICY professional_summary_audience ON professional_authority_current")
    op.execute("DROP FUNCTION professional_summary_visible(uuid,uuid,uuid,jsonb)")
    op.execute("DROP TRIGGER professional_current_summary ON professional_authority_current")
    op.execute("DROP FUNCTION professional_current_summary()")
    op.execute("ALTER TABLE professional_authority_current DROP COLUMN summary")
