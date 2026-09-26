"""Human application of accepted supplier notices to real Issue and ECR records."""

from alembic import op

revision = "0318_supplier_notice_applications"
down_revision = "0317_supplier_notice_reviews"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_notice_applications (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        candidate_id UUID NOT NULL,
        review_id UUID NOT NULL,
        notice_key VARCHAR(64) NOT NULL,
        target_kind VARCHAR(16) NOT NULL,
        issue_id UUID,
        ecr_id UUID,
        linked_from_id UUID,
        command JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_supplier_notice_applications PRIMARY KEY (id),
        CONSTRAINT uq_notice_application_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_notice_application_candidate_kind UNIQUE (candidate_id, target_kind),
        CONSTRAINT uq_notice_application_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_supplier_notice_applications_tenant_id_supplier_noti_cdc9 FOREIGN
KEY(tenant_id, project_id, candidate_id) REFERENCES cehub_supplier.supplier_notice_candidates
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_applications_tenant_id_supplier_noti_8415 FOREIGN
KEY(tenant_id, project_id, review_id) REFERENCES cehub_supplier.supplier_notice_reviews
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_applications_tenant_id_supplier_noti_fdee FOREIGN
KEY(tenant_id, project_id, linked_from_id) REFERENCES cehub_supplier.supplier_notice_applications
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_applications_tenant_id_issues FOREIGN KEY(tenant_id,
project_id, issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_supplier_notice_applications_tenant_id_engineering_c_9fa3 FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_supplier_notice_applications_shape CHECK (((target_kind='issue' AND issue_id
IS NOT NULL AND ecr_id IS NULL) OR (target_kind='ecr' AND ecr_id IS NOT NULL AND issue_id IS
NULL)) AND jsonb_typeof(command)='object' AND jsonb_typeof(snapshot)='object' AND notice_key ~
'^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE UNIQUE INDEX uq_notice_application_canonical ON cehub_supplier.supplier_notice_applications
(tenant_id, project_id, notice_key, target_kind) WHERE linked_from_id IS NULL;
CREATE FUNCTION cehub_supplier.guard_notice_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original_review cehub_supplier.supplier_notice_reviews%ROWTYPE;
        prior cehub_supplier.supplier_notice_applications%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
 SELECT * INTO original_review FROM cehub_supplier.supplier_notice_reviews
 WHERE id=NEW.review_id AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id
 AND candidate_id=NEW.candidate_id;
 IF original_review.id IS NULL OR original_review.decision<>'accepted'
    OR EXISTS (SELECT 1 FROM cehub_supplier.supplier_notice_reviews
       WHERE candidate_id=NEW.candidate_id AND version>original_review.version)
    OR original_review.id::text IS DISTINCT FROM NEW.snapshot#>>'{review,id}'
    OR original_review.version::text IS DISTINCT FROM NEW.snapshot#>>'{review,version}'
    OR original_review.review IS DISTINCT FROM NEW.snapshot#>'{review,review}'
    OR original_review.source_digest IS DISTINCT FROM NEW.snapshot#>>'{review,source_digest}' 
    OR original_review.snapshot IS DISTINCT FROM NEW.snapshot->'source'
    OR NEW.command IS DISTINCT FROM NEW.snapshot->'command'
    OR NEW.command->>'review_id' IS DISTINCT FROM NEW.review_id::text
    OR NEW.command->>'request_id' IS DISTINCT FROM NEW.request_id::text
    OR NEW.command->>'target_kind' IS DISTINCT FROM NEW.target_kind
    OR NEW.notice_key IS DISTINCT FROM NEW.snapshot->>'notice_key' THEN
  RAISE EXCEPTION 'notice application requires latest accepted review and fixed original source';
 END IF;
 IF NEW.command->>'mode' NOT IN ('create','link') THEN
  RAISE EXCEPTION 'notice application mode is required';
 END IF;
 IF NEW.command->>'mode'='link' AND NEW.command->>'target_id' IS DISTINCT FROM
      coalesce(NEW.issue_id,NEW.ecr_id)::text THEN
  RAISE EXCEPTION 'notice link must bind the chosen actual record';
 END IF;
 IF NEW.linked_from_id IS NOT NULL THEN
  SELECT * INTO prior FROM cehub_supplier.supplier_notice_applications
  WHERE id=NEW.linked_from_id AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
  IF prior.id IS NULL OR prior.linked_from_id IS NOT NULL OR prior.notice_key<>NEW.notice_key
     OR prior.target_kind<>NEW.target_kind OR prior.issue_id IS DISTINCT FROM NEW.issue_id
     OR prior.ecr_id IS DISTINCT FROM NEW.ecr_id OR NEW.command->>'mode'<>'link' THEN
   RAISE EXCEPTION 'repeated notice must explicitly reuse the original business record';
  END IF;
 END IF;
 IF NEW.target_kind='issue' THEN
  IF NOT EXISTS (SELECT 1 FROM cehub_project.issues i
    WHERE i.id=NEW.issue_id AND i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id
      AND i.status IN ('open','analysis','action','verification')
      AND (NEW.command->>'mode'='link' OR
         (i.status='open' AND i.title=NEW.command->>'title' AND i.issue_type='supplier'
          AND i.owner_user_id::text=NEW.command->>'owner_user_id'
          AND i.verifier_user_id::text=NEW.command->>'verifier_user_id'
          AND i.target_date::text=NEW.command->>'target_date'
          AND i.closure_criteria=NEW.command->>'closure_criteria'
          AND i.reported_by_user_id=NEW.created_by_user_id))) THEN
   RAISE EXCEPTION 'notice application must bind actual issue responsibility and criteria';
  END IF;
 ELSE
  IF NOT EXISTS (SELECT 1 FROM cehub_product.engineering_change_requests e
    WHERE e.id=NEW.ecr_id AND e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id
      AND e.status IN ('request','impact_analysis')
      AND (NEW.command->>'mode'='link' OR (e.status='request'
          AND e.code=NEW.command->>'code' AND e.title=NEW.command->>'title'
          AND e.requested_by_user_id=NEW.created_by_user_id))) THEN
   RAISE EXCEPTION 'notice application must bind actual original ECR';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_application_guard BEFORE INSERT ON
cehub_supplier.supplier_notice_applications
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_notice_application();
CREATE TRIGGER notice_application_immutable BEFORE UPDATE OR DELETE
 ON cehub_supplier.supplier_notice_applications FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_application() FROM PUBLIC;
REVOKE ALL ON cehub_supplier.supplier_notice_applications FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_notice_applications) THEN
        RAISE EXCEPTION 'retain notice business application history';
      END IF;
    END $$;
    DROP TABLE cehub_supplier.supplier_notice_applications;
    DROP FUNCTION cehub_supplier.guard_notice_application();
    """)
