"""Version field drafts and bind exactly one real Issue or Test run."""

import sqlalchemy as sa
from alembic import op

revision = "0218_field_capture_drafts"
down_revision = "0217_field_captures"
branch_labels = None
depends_on = None
DDL = """
ALTER TABLE cehub_quality.field_captures ADD COLUMN test_run_id uuid;
ALTER TABLE cehub_quality.field_captures ADD CONSTRAINT uq_field_capture_scope
UNIQUE(tenant_id,project_id,id);
ALTER TABLE cehub_quality.field_captures ADD CONSTRAINT uq_field_capture_test
UNIQUE(tenant_id,test_run_id);
ALTER TABLE cehub_quality.field_captures ADD CONSTRAINT fk_field_captures_tenant_id_test_runs
FOREIGN KEY(tenant_id,project_id,test_run_id) REFERENCES
cehub_quality.test_runs(tenant_id,project_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_quality.field_captures DROP CONSTRAINT ck_field_captures_review;
ALTER TABLE cehub_quality.field_captures ADD CONSTRAINT ck_field_captures_review CHECK
((issue_id IS NULL AND test_run_id IS NULL AND review IS NULL AND submitted_at IS NULL) OR
(num_nonnulls(issue_id,test_run_id)=1 AND review IS NOT NULL AND jsonb_typeof(review)='object'
AND submitted_at IS NOT NULL AND (filename IS NULL OR uploaded_at IS NOT NULL)));
CREATE OR REPLACE FUNCTION cehub_quality.protect_field_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Field capture originals are retained'; END IF;
 IF (to_jsonb(NEW)-ARRAY['uploaded_at','issue_id','test_run_id','review','submitted_at']) IS
DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['uploaded_at','issue_id','test_run_id','review','submitted_at'])
 OR (OLD.uploaded_at IS NOT NULL AND NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at)
 OR (OLD.submitted_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
 RAISE EXCEPTION 'Field originals and completed review are immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TABLE cehub_quality.field_capture_drafts (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	capture_id UUID NOT NULL,
	request_id UUID NOT NULL,
	version INTEGER NOT NULL,
	body JSONB NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_field_capture_drafts PRIMARY KEY (id),
	CONSTRAINT uq_field_capture_draft_version UNIQUE (tenant_id, capture_id, version),
	CONSTRAINT uq_field_capture_draft_request UNIQUE (tenant_id, capture_id, request_id),
        CONSTRAINT fk_field_capture_drafts_tenant_id_field_captures FOREIGN KEY(tenant_id,
project_id, capture_id) REFERENCES cehub_quality.field_captures (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_field_capture_drafts_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_field_capture_drafts_body CHECK (version>0 AND
jsonb_typeof(body)='object' AND body->>'kind' IN ('issue','test'))
)

;
REVOKE ALL ON cehub_quality.field_capture_drafts FROM PUBLIC;
CREATE FUNCTION cehub_quality.guard_field_capture_draft() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source cehub_quality.field_captures; latest integer;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Field draft versions are immutable'; END IF;
 SELECT * INTO source FROM cehub_quality.field_captures WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.capture_id FOR UPDATE;
 IF NOT FOUND OR source.submitted_at IS NOT NULL OR
source.created_by_user_id<>NEW.created_by_user_id
 THEN RAISE EXCEPTION 'Only the creator can append an unsubmitted field draft'; END IF;
 SELECT coalesce(max(version),0) INTO latest FROM cehub_quality.field_capture_drafts
 WHERE tenant_id=NEW.tenant_id AND capture_id=NEW.capture_id;
 IF NEW.version<>latest+1 THEN RAISE EXCEPTION 'Field draft version changed'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.guard_field_capture_draft() FROM PUBLIC;
CREATE TRIGGER guard_field_capture_draft BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.field_capture_drafts FOR EACH ROW EXECUTE FUNCTION
cehub_quality.guard_field_capture_draft();

"""
OLD_GUARD = """
CREATE OR REPLACE FUNCTION cehub_quality.protect_field_capture() RETURNS trigger
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
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_quality.field_capture_drafts) OR "
                "EXISTS(SELECT 1 FROM cehub_quality.field_captures WHERE test_run_id IS NOT "
                "NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard field draft or test history")
    op.drop_table("field_capture_drafts", schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.guard_field_capture_draft()")
    op.execute(sa.text(OLD_GUARD))
    op.drop_constraint(op.f("ck_field_captures_review"), "field_captures", schema="cehub_quality")
    op.create_check_constraint(
        op.f("ck_field_captures_review"),
        "field_captures",
        "(issue_id IS NULL AND review IS NULL AND submitted_at IS NULL) OR (issue_id IS "
        "NOT NULL AND review IS NOT NULL AND jsonb_typeof(review)='object' AND "
        "submitted_at IS NOT NULL AND (filename IS NULL OR uploaded_at IS NOT NULL))",
        schema="cehub_quality",
    )
    op.drop_constraint(
        "fk_field_captures_tenant_id_test_runs", "field_captures", schema="cehub_quality"
    )
    op.drop_constraint("uq_field_capture_test", "field_captures", schema="cehub_quality")
    op.drop_constraint("uq_field_capture_scope", "field_captures", schema="cehub_quality")
    op.drop_column("field_captures", "test_run_id", schema="cehub_quality")
