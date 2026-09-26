"""Bind supplier notice reviews to submitted and approved ECR impact analyses."""

from alembic import op

revision = "0319_supplier_notice_impact"
down_revision = "0318_supplier_notice_applications"
branch_labels = None
depends_on = None

DDL = """
CREATE FUNCTION cehub_supplier.guard_notice_ecr_impact() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE application cehub_supplier.supplier_notice_applications%ROWTYPE;
        review cehub_supplier.supplier_notice_reviews%ROWTYPE;
        section jsonb; entry jsonb; response jsonb; total integer;
BEGIN
 IF NEW.status NOT IN ('approval','approved') THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status
    AND NEW.impact_analysis IS NOT DISTINCT FROM OLD.impact_analysis THEN RETURN NEW; END IF;
 SELECT count(*) INTO total FROM cehub_supplier.supplier_notice_applications
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND ecr_id=NEW.id;
 IF total=0 THEN RETURN NEW; END IF;
 section:=NEW.impact_analysis->'supplier_notices';
 IF section IS NULL OR section#>>'{basis,version}' IS DISTINCT FROM 'supplier-notice-impact-v1'
    OR jsonb_typeof(section#>'{basis,sources}') IS DISTINCT FROM 'array'
    OR jsonb_array_length(section#>'{basis,sources}')<>total
    OR jsonb_typeof(section->'source_responses') IS DISTINCT FROM 'object'
    OR jsonb_typeof(section->'assessments') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'notice impact analysis must bind every application';
 END IF;
 IF (SELECT count(*) FROM jsonb_object_keys(section->'source_responses'))<>total
    OR (SELECT count(*) FROM jsonb_object_keys(section->'assessments'))<>9
    OR NOT (section->'assessments' ?& ARRAY['requirements','mechanical','hardware','firmware',
          'verification','supply','cost','schedule','handoffs']) THEN
  RAISE EXCEPTION 'notice impact requires exact source responses and nine assessment axes';
 END IF;
 FOR application IN SELECT * FROM cehub_supplier.supplier_notice_applications
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND ecr_id=NEW.id LOOP
  SELECT * INTO review FROM cehub_supplier.supplier_notice_reviews
   WHERE candidate_id=application.candidate_id ORDER BY version DESC LIMIT 1;
  SELECT value INTO entry FROM jsonb_array_elements(section#>'{basis,sources}')
   WHERE value->>'application_id'=application.id::text;
  response:=section->'source_responses'->application.id::text;
  IF review.id IS NULL OR review.decision<>'accepted' OR entry IS NULL OR response IS NULL
     OR entry->>'ready' IS DISTINCT FROM 'true'
     OR entry->>'candidate_id' IS DISTINCT FROM application.candidate_id::text
     OR entry->>'application_review_id' IS DISTINCT FROM application.review_id::text
     OR entry->>'review_id' IS DISTINCT FROM review.id::text
     OR entry->>'review_version' IS DISTINCT FROM review.version::text
     OR entry->>'current_source_digest' IS DISTINCT FROM review.source_digest
     OR entry->>'bom_id' IS DISTINCT FROM
          review.snapshot#>>'{original,watch_source,bom_item,bom_id}'
     OR entry->>'bom_item_id' IS DISTINCT FROM
          review.snapshot#>>'{original,watch_source,bom_item,id}'
  THEN RAISE EXCEPTION 'notice impact must use latest accepted human review'; END IF;
  IF response->>'conclusion'='affected' AND NOT EXISTS (
    SELECT 1 FROM cehub_product.ecr_affected_boms b WHERE b.tenant_id=NEW.tenant_id
     AND b.project_id=NEW.project_id AND b.ecr_id=NEW.id AND b.bom_id::text=entry->>'bom_id'
  ) THEN RAISE EXCEPTION 'affected notice must include the actual in-use BOM'; END IF;
 END LOOP;
 FOR response IN SELECT value FROM jsonb_each(section->'source_responses')
    UNION ALL SELECT value FROM jsonb_each(section->'assessments') LOOP
  IF coalesce(response->>'conclusion','') NOT IN ('affected','unaffected','unknown')
     OR nullif(btrim(response->>'basis'),'') IS NULL
     OR (response->>'conclusion'<>'unaffected'
         AND nullif(btrim(response->>'next_action'),'') IS NULL)
     OR (NEW.status='approved' AND response->>'conclusion'='unknown') THEN
   RAISE EXCEPTION 'notice impact requires explicit conclusions and resolved approval gaps';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_ecr_impact_guard BEFORE INSERT OR UPDATE
 ON cehub_product.engineering_change_requests FOR EACH ROW
 EXECUTE FUNCTION cehub_supplier.guard_notice_ecr_impact();
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_ecr_impact() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_product.engineering_change_requests
         WHERE impact_analysis ? 'supplier_notices') THEN
        RAISE EXCEPTION 'retain notice-bound impact analysis enforcement';
      END IF;
    END $$;
    DROP TRIGGER notice_ecr_impact_guard ON cehub_product.engineering_change_requests;
    DROP FUNCTION cehub_supplier.guard_notice_ecr_impact();
    """)
