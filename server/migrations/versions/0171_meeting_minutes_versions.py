"""Retain human-confirmed minutes versions and their exact transcript origins."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0171_meeting_minutes_versions"
down_revision = "0170_meeting_reading_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_minutes_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("unresolved_points", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("document_digest", sa.String(64), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "version_no >= 1", name=op.f("ck_meeting_minutes_versions_version_positive")
        ),
        sa.CheckConstraint(
            "btrim(body) <> '' AND btrim(unresolved_points) <> '' AND btrim(reason) <> ''",
            name=op.f("ck_meeting_minutes_versions_content_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(citations) = 'array' AND jsonb_array_length(citations) BETWEEN 1 AND 100",
            name=op.f("ck_meeting_minutes_versions_citations_array"),
        ),
        sa.CheckConstraint(
            "document_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_meeting_minutes_versions_digests_sha256"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_minutes_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "meeting_id", "version_no", name="uq_minutes_meeting_version"
        ),
        sa.UniqueConstraint(
            "tenant_id", "confirmed_by_user_id", "request_id", name="uq_minutes_request"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["cehub_project.meetings.tenant_id", "cehub_project.meetings.id"],
            name="fk_minutes_meeting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmed_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_minutes_confirmer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "previous_version_id"],
            [
                "cehub_project.meeting_minutes_versions.tenant_id",
                "cehub_project.meeting_minutes_versions.id",
            ],
            name="fk_minutes_previous",
            ondelete="RESTRICT",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_minutes_project",
        "meeting_minutes_versions",
        ["tenant_id", "project_id", "meeting_id"],
        schema="cehub_project",
    )
    op.execute("""
CREATE FUNCTION cehub_project.guard_meeting_minutes_version() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c jsonb; previous_version integer;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Confirmed minutes are immutable; confirm a new version' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.meetings m WHERE m.tenant_id=NEW.tenant_id
  AND m.id=NEW.meeting_id AND m.project_id=NEW.project_id AND m.status='completed'
  AND m.archived_at IS NULL AND m.deleted_at IS NULL) THEN
  RAISE EXCEPTION 'Minutes require a completed, editable meeting in this project'
   USING ERRCODE='23514';
 END IF;
 SELECT coalesce(max(v.version_no),0) INTO previous_version
 FROM cehub_project.meeting_minutes_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.meeting_id=NEW.meeting_id;
 IF NEW.version_no<>previous_version+1 OR
  (previous_version=0 AND NEW.previous_version_id IS NOT NULL) OR
  (previous_version>0 AND NOT EXISTS(SELECT 1 FROM cehub_project.meeting_minutes_versions v
   WHERE v.tenant_id=NEW.tenant_id AND v.project_id=NEW.project_id AND v.meeting_id=NEW.meeting_id
    AND v.id=NEW.previous_version_id AND v.version_no=previous_version)) THEN
  RAISE EXCEPTION 'Minutes must extend the current version' USING ERRCODE='23514';
 END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(NEW.citations) LOOP
  IF NOT EXISTS(SELECT 1 FROM cehub_project.meeting_transcripts t
   JOIN cehub_project.meeting_transcript_segments s
    ON s.tenant_id=t.tenant_id AND s.transcript_id=t.id
   WHERE t.tenant_id=NEW.tenant_id AND t.meeting_id=NEW.meeting_id
    AND t.id=(c->>'transcript_id')::uuid AND s.id=(c->>'segment_id')::uuid
    AND t.original_content IS NOT NULL AND t.superseded_at IS NULL
    AND t.content_digest=c->>'content_digest'
    AND s.sequence=(c->>'sequence')::integer
    AND s.speaker_label IS NOT DISTINCT FROM c->>'speaker_label'
    AND s.speaker_user_id IS NOT DISTINCT FROM (c->>'speaker_user_id')::uuid
    AND btrim(c->>'exact_quote')<>'' AND strpos(s.content,c->>'exact_quote')>0) THEN
   RAISE EXCEPTION 'Minutes citation must match this meeting transcript and attribution'
    USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_meeting_minutes_version() FROM PUBLIC;
CREATE TRIGGER guard_meeting_minutes_version BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_project.meeting_minutes_versions FOR EACH ROW
 EXECUTE FUNCTION cehub_project.guard_meeting_minutes_version();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_minutes_versions)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard confirmed meeting minutes")
    op.drop_table("meeting_minutes_versions", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_meeting_minutes_version()")
