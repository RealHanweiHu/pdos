"""Persist exact transcript sources and preserve citation anchors during attribution."""

import sqlalchemy as sa
from alembic import op

revision = "0169_meeting_transcript_sources"
down_revision = "0168_meeting_followup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_transcripts", sa.Column("original_content", sa.Text()), schema="cehub_project"
    )
    op.create_check_constraint(
        op.f("ck_meeting_transcripts_original_matches_digest"),
        "meeting_transcripts",
        "original_content IS NULL OR (octet_length(original_content) = byte_size "
        "AND encode(sha256(convert_to(original_content, 'UTF8')), 'hex') = content_digest)",
        schema="cehub_project",
    )
    op.execute("""
CREATE FUNCTION cehub_project.guard_transcript_original() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Transcript source requires a retention operation' USING ERRCODE='23514';
 END IF;
 IF (to_jsonb(NEW)-ARRAY['original_content','segment_count','speaker_labeled','superseded_at'])
    IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['original_content','segment_count','speaker_labeled','superseded_at'])
    OR (OLD.original_content IS NOT NULL AND
      (NEW.original_content IS DISTINCT FROM OLD.original_content
       OR NEW.segment_count IS DISTINCT FROM OLD.segment_count)) THEN
  RAISE EXCEPTION 'Transcript bytes and original identity are immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_transcript_original() FROM PUBLIC;
CREATE TRIGGER guard_transcript_original BEFORE UPDATE OR DELETE
 ON cehub_project.meeting_transcripts FOR EACH ROW
 EXECUTE FUNCTION cehub_project.guard_transcript_original();

CREATE FUNCTION cehub_project.guard_transcript_citation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Transcript citation anchors are retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND
   (to_jsonb(NEW)-ARRAY['speaker_label','speaker_user_id']) IS DISTINCT FROM
   (to_jsonb(OLD)-ARRAY['speaker_label','speaker_user_id']) THEN
  RAISE EXCEPTION 'Citation text, sequence and timing cannot be rewritten' USING ERRCODE='23514';
 END IF;
 IF NEW.speaker_user_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_project.meeting_transcripts t
  JOIN cehub_project.meetings m ON m.tenant_id=t.tenant_id AND m.id=t.meeting_id
  JOIN cehub_project.project_members pm ON pm.tenant_id=m.tenant_id AND pm.project_id=m.project_id
  JOIN cehub_core.users u ON u.tenant_id=pm.tenant_id AND u.id=pm.user_id
  WHERE t.tenant_id=NEW.tenant_id AND t.id=NEW.transcript_id
   AND pm.user_id=NEW.speaker_user_id AND u.is_active
 ) THEN
  RAISE EXCEPTION 'Speaker must be a current member of this project' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_transcript_citation() FROM PUBLIC;
CREATE TRIGGER guard_transcript_citation BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_project.meeting_transcript_segments FOR EACH ROW
 EXECUTE FUNCTION cehub_project.guard_transcript_citation();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_transcripts "
                "WHERE original_content IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard transcript original sources")
    op.execute("""
DROP TRIGGER guard_transcript_citation ON cehub_project.meeting_transcript_segments;
DROP FUNCTION cehub_project.guard_transcript_citation();
DROP TRIGGER guard_transcript_original ON cehub_project.meeting_transcripts;
DROP FUNCTION cehub_project.guard_transcript_original();
""")
    op.drop_constraint(
        op.f("ck_meeting_transcripts_original_matches_digest"),
        "meeting_transcripts",
        schema="cehub_project",
        type_="check",
    )
    op.drop_column("meeting_transcripts", "original_content", schema="cehub_project")
