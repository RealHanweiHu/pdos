"""Preserve human field originals and one explicit Issue conversion."""

import sqlalchemy as sa
from alembic import op

revision = "0217_field_captures"
down_revision = "0216_conversation_discussions"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_quality.field_captures (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	original_text TEXT NOT NULL,
	filename VARCHAR(512),
	media_type VARCHAR(128),
	size_bytes BIGINT,
	sha256 VARCHAR(64),
	object_key VARCHAR(1024),
	request_digest VARCHAR(64) NOT NULL,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	issue_id UUID,
	review JSONB,
	submitted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_field_captures PRIMARY KEY (id),
        CONSTRAINT fk_field_captures_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_field_captures_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_field_captures_tenant_id_issues FOREIGN KEY(tenant_id, project_id,
issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_field_capture_issue UNIQUE (tenant_id, issue_id),
        CONSTRAINT ck_field_captures_input CHECK (length(original_text)<=20000 AND
(length(btrim(original_text))>0 OR filename IS NOT NULL)),
        CONSTRAINT ck_field_captures_file CHECK ((filename IS NULL AND media_type IS NULL AND
size_bytes IS NULL AND sha256 IS NULL AND object_key IS NULL AND uploaded_at IS NULL) OR
(filename IS NOT NULL AND media_type IS NOT NULL AND size_bytes IS NOT NULL AND size_bytes
BETWEEN 1 AND 12582912 AND sha256 IS NOT NULL AND sha256 ~ '^[a-f0-9]{64}$' AND object_key IS
NOT NULL)),
        CONSTRAINT ck_field_captures_review CHECK ((issue_id IS NULL AND review IS NULL AND
submitted_at IS NULL) OR (issue_id IS NOT NULL AND review IS NOT NULL AND
jsonb_typeof(review)='object' AND submitted_at IS NOT NULL AND (filename IS NULL OR uploaded_at
IS NOT NULL)))
)

;
CREATE INDEX ix_field_capture_owner ON cehub_quality.field_captures (tenant_id, project_id,
created_by_user_id, created_at);
REVOKE ALL ON cehub_quality.field_captures FROM PUBLIC;
CREATE FUNCTION cehub_quality.protect_field_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Field capture originals are retained'; END IF;
 IF (to_jsonb(NEW)-ARRAY['uploaded_at','issue_id','review','submitted_at']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['uploaded_at','issue_id','review','submitted_at'])
 OR (OLD.uploaded_at IS NOT NULL AND NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at)
 OR (OLD.issue_id IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
 RAISE EXCEPTION 'Field originals and completed review are immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.protect_field_capture() FROM PUBLIC;
CREATE TRIGGER protect_field_capture BEFORE UPDATE OR DELETE ON cehub_quality.field_captures
FOR EACH ROW EXECUTE FUNCTION cehub_quality.protect_field_capture();
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.field_captures)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard original field captures")
    op.drop_table("field_captures", schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.protect_field_capture()")
