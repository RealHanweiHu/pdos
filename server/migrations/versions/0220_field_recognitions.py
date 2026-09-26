"""Immutable offline OCR/voice receipts and human draft source binding."""

import sqlalchemy as sa
from alembic import op

revision = "0220_field_recognitions"
down_revision = "0219_drawing_originals"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_quality.field_capture_recognitions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	capture_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	kind VARCHAR(16) NOT NULL,
	language VARCHAR(16) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	profile JSONB NOT NULL,
	status VARCHAR(16) NOT NULL,
	result JSONB,
	error_code VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_field_capture_recognitions PRIMARY KEY (id),
        CONSTRAINT fk_field_capture_recognitions_tenant_id_field_captures FOREIGN KEY(tenant_id,
project_id, capture_id) REFERENCES cehub_quality.field_captures (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_field_capture_recognitions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_field_capture_recognitions_input CHECK (kind IN ('ocr','speech') AND
language IN ('zh','en','auto') AND jsonb_typeof(profile)='object' AND source_sha256 ~
'^[a-f0-9]{64}$'),
        CONSTRAINT ck_field_capture_recognitions_state CHECK ((status IN ('queued','running')
AND completed_at IS NULL AND result IS NULL AND error_code IS NULL) OR (status='succeeded' AND
completed_at IS NOT NULL AND result IS NOT NULL AND jsonb_typeof(result)='object' AND error_code
IS NULL) OR (status IN ('failed','cancelled') AND completed_at IS NOT NULL AND result IS NULL
AND error_code IS NOT NULL))
)

;
CREATE UNIQUE INDEX ix_capture_recognition_active ON cehub_quality.field_capture_recognitions
(tenant_id, capture_id) WHERE status IN ('queued','running');
CREATE INDEX ix_capture_recognition_queue ON cehub_quality.field_capture_recognitions (status,
created_at);

REVOKE ALL ON cehub_quality.field_capture_recognitions FROM PUBLIC;
CREATE FUNCTION cehub_quality.guard_field_recognition() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source cehub_quality.field_captures;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Recognition receipts are retained'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO source FROM cehub_quality.field_captures WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND id=NEW.capture_id FOR UPDATE;
  IF NOT FOUND OR source.submitted_at IS NOT NULL OR source.uploaded_at IS NULL
   OR source.sha256<>NEW.source_sha256 OR source.created_by_user_id<>NEW.created_by_user_id
   OR NEW.status<>'queued' OR NEW.started_at IS NOT NULL THEN
   RAISE EXCEPTION 'Recognition must bind its creator and uploaded unsubmitted original';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','result','error_code','started_at','completed_at','expires_at'])
   IS DISTINCT FROM
   (to_jsonb(OLD)-ARRAY['status','result','error_code','started_at','completed_at','expires_at'])
   OR OLD.status IN ('succeeded','failed','cancelled') OR
   NOT ((OLD.status='queued' AND NEW.status IN ('running','failed','cancelled')) OR
        (OLD.status='running' AND NEW.status IN ('succeeded','failed','cancelled')))
   OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
   OR (NEW.status='running' AND NEW.started_at IS NULL) THEN
    RAISE EXCEPTION 'Recognition identity, transitions and completed receipts are fixed';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.guard_field_recognition() FROM PUBLIC;
CREATE TRIGGER guard_field_recognition BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.field_capture_recognitions FOR EACH ROW EXECUTE FUNCTION
cehub_quality.guard_field_recognition();
CREATE FUNCTION cehub_quality.check_field_recognition_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE recognition uuid;
BEGIN
 recognition := (NEW.body->>'recognition_id')::uuid;
 IF recognition IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_quality.field_capture_recognitions r
  WHERE r.id=recognition AND r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id
  AND r.capture_id=NEW.capture_id AND r.created_by_user_id=NEW.created_by_user_id
  AND r.status='succeeded') THEN
  RAISE EXCEPTION 'Draft extraction source must be this originals completed receipt';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.check_field_recognition_source() FROM PUBLIC;
CREATE TRIGGER check_field_recognition_source BEFORE INSERT ON cehub_quality.field_capture_drafts
FOR EACH ROW EXECUTE FUNCTION cehub_quality.check_field_recognition_source();
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.field_capture_recognitions)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard recognition requests and results")
    op.execute("DROP TRIGGER check_field_recognition_source ON cehub_quality.field_capture_drafts")
    op.execute("DROP FUNCTION cehub_quality.check_field_recognition_source()")
    op.drop_table("field_capture_recognitions", schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.guard_field_recognition()")
