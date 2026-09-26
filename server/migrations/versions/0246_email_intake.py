"""Persist uploaded email extraction scope and allow evidence-backed email intake."""

from alembic import op

revision = "0246_email_intake"
down_revision = "0245_pdf_intake_previews"
branch_labels = None
depends_on = None

OLD_ATTACHMENT_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_attachment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Private source evidence uses revocation' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND id=NEW.conversation_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR c.created_by_user_id<>NEW.uploaded_by_user_id THEN
  RAISE EXCEPTION 'Attachment must belong to its private creator' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF c.archived_at IS NOT NULL OR NEW.status<>'awaiting_upload'
   OR NEW.revoked_at IS NOT NULL OR NEW.parser_version<>'conversation-pdf-xlsx.v1' THEN
   RAISE EXCEPTION 'New attachment must await upload in an active conversation'
    USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','error_code','fragments','updated_at','revoked_at'])
   IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','fragments','updated_at','revoked_at'])
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
   OR (OLD.status IN ('extracted','ocr_required') AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.error_code IS DISTINCT FROM OLD.error_code))
   OR (OLD.status='awaiting_upload' AND NEW.status NOT IN ('awaiting_upload','uploaded'))
   OR (OLD.status IN ('uploaded','failed') AND
    NEW.status NOT IN ('uploaded','failed','extracted','ocr_required'))
   OR ((c.archived_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments)) THEN
   RAISE EXCEPTION 'Attachment content, scope and completed extraction are immutable'
    USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""

ATTACHMENT_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_attachment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Private source evidence uses revocation' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND id=NEW.conversation_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR c.created_by_user_id<>NEW.uploaded_by_user_id THEN
  RAISE EXCEPTION 'Attachment must belong to its private creator' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF c.archived_at IS NOT NULL OR NEW.status<>'awaiting_upload'
   OR NEW.revoked_at IS NOT NULL
   OR NEW.parser_version NOT IN ('conversation-pdf-xlsx.v1','conversation-eml.v1')
   OR NEW.extraction_metadata<>'{}'::jsonb
   OR ((NEW.parser_version='conversation-eml.v1')
       IS DISTINCT FROM (NEW.media_type='message/rfc822')) THEN
   RAISE EXCEPTION 'New attachment must await upload in an active conversation'
    USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
   OR (OLD.status IN ('extracted','ocr_required') AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata
     OR NEW.error_code IS DISTINCT FROM OLD.error_code))
   OR (OLD.status='awaiting_upload' AND (NEW.status NOT IN ('awaiting_upload','uploaded')
    OR NEW.extraction_metadata<>'{}'::jsonb))
   OR (OLD.status IN ('uploaded','failed') AND
    NEW.status NOT IN ('uploaded','failed','extracted','ocr_required'))
   OR ((c.archived_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata)) THEN
   RAISE EXCEPTION 'Attachment content, scope and completed extraction are immutable'
    USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    for schema, table in (("cehub_ai", "conversation_attachments"), ("cehub_project", "documents")):
        op.execute(
            f"ALTER TABLE {schema}.{table} ADD COLUMN extraction_metadata "
            "JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
        op.execute(
            f"ALTER TABLE {schema}.{table} ADD CONSTRAINT ck_{table}_extraction_metadata_object "
            "CHECK (jsonb_typeof(extraction_metadata)='object')"
        )
    op.execute(ATTACHMENT_GUARD)
    op.execute("""CREATE FUNCTION cehub_project.guard_document_extraction_metadata()
    RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
      IF NEW.extraction_metadata IS DISTINCT FROM OLD.extraction_metadata THEN
        RAISE EXCEPTION 'Original extraction metadata is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_document_extraction_metadata() FROM PUBLIC;
    CREATE TRIGGER guard_document_extraction_metadata BEFORE UPDATE ON cehub_project.documents
    FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_document_extraction_metadata();""")
    for kind in ("issue", "decision"):
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews DROP CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser"
        )
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews ADD CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' "
            "AND btrim(purpose)<>'' AND parser_version IN "
            f"('{kind}-list-extracted-v1','{kind}-pdf-extracted-v1','{kind}-email-extracted-v1'))"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_ai.conversation_attachments
                 WHERE parser_version='conversation-eml.v1' OR extraction_metadata<>'{}'::jsonb)
      OR EXISTS (SELECT 1 FROM cehub_project.documents
                 WHERE media_type='message/rfc822' OR extraction_metadata<>'{}'::jsonb)
      OR EXISTS (SELECT 1 FROM cehub_ai.issue_intake_previews
                 WHERE parser_version='issue-email-extracted-v1')
      OR EXISTS (SELECT 1 FROM cehub_ai.decision_intake_previews
                 WHERE parser_version='decision-email-extracted-v1')
      THEN RAISE EXCEPTION 'Email evidence must be retained'; END IF;
    END $$;""")
    for kind in ("issue", "decision"):
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews DROP CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser"
        )
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews ADD CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' "
            "AND btrim(purpose)<>'' AND parser_version IN "
            f"('{kind}-list-extracted-v1','{kind}-pdf-extracted-v1'))"
        )
    op.execute(OLD_ATTACHMENT_GUARD)
    op.execute("DROP TRIGGER guard_document_extraction_metadata ON cehub_project.documents")
    op.execute("DROP FUNCTION cehub_project.guard_document_extraction_metadata()")
    for schema, table in (("cehub_ai", "conversation_attachments"), ("cehub_project", "documents")):
        op.execute(
            f"ALTER TABLE {schema}.{table} DROP CONSTRAINT ck_{table}_extraction_metadata_object"
        )
        op.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN extraction_metadata")
