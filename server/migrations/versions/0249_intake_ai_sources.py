"""Immutable source selections and revision lineage for AI intake organization."""

from alembic import op

revision = "0249_intake_ai_sources"
down_revision = "0248_email_parts"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.intake_ai_briefs (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        conversation_id UUID NOT NULL,
        message_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        revision INTEGER NOT NULL,
        previous_brief_id UUID,
        root_brief_id UUID NOT NULL,
        purpose TEXT NOT NULL,
        source_snapshot JSONB NOT NULL,
        source_digest VARCHAR(64) NOT NULL,
        source_version VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_intake_ai_briefs PRIMARY KEY (id),
        CONSTRAINT uq_intake_ai_brief_scope UNIQUE (tenant_id, conversation_id, message_id, id),
        CONSTRAINT uq_intake_ai_brief_revision UNIQUE (tenant_id, conversation_id, message_id,
revision),
        CONSTRAINT uq_intake_ai_brief_request UNIQUE (tenant_id, conversation_id, request_id),
        CONSTRAINT fk_intake_ai_briefs_tenant_id_conversation_messages FOREIGN KEY(tenant_id,
project_id, conversation_id, message_id) REFERENCES cehub_ai.conversation_messages (tenant_id,
project_id, conversation_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_intake_ai_previous_brief_id FOREIGN KEY(tenant_id, conversation_id,
message_id, previous_brief_id) REFERENCES cehub_ai.intake_ai_briefs (tenant_id, conversation_id,
message_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_intake_ai_root_brief_id FOREIGN KEY(tenant_id, conversation_id, message_id,
root_brief_id) REFERENCES cehub_ai.intake_ai_briefs (tenant_id, conversation_id, message_id, id)
ON DELETE RESTRICT,
        CONSTRAINT fk_intake_ai_briefs_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_intake_ai_briefs_identity CHECK (revision>0 AND
source_version='intake-source-v1' AND source_digest ~ '^[0-9a-f]{64}$' AND request_digest ~
'^[0-9a-f]{64}$' AND length(btrim(purpose)) BETWEEN 1 AND 2000),
        CONSTRAINT ck_intake_ai_briefs_shape CHECK ((jsonb_typeof(source_snapshot)='object' AND
jsonb_typeof(source_snapshot->'sources')='object' AND
jsonb_typeof(source_snapshot->'fragments')='array' AND
jsonb_array_length(source_snapshot->'fragments') BETWEEN 1 AND 200 AND
(source_snapshot->>'characters')::int BETWEEN 1 AND 180000) IS TRUE)
)

;
"""

GUARD = """
CREATE FUNCTION cehub_ai.guard_intake_ai_brief() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE latest cehub_ai.intake_ai_briefs; src record; frag jsonb;
 file cehub_ai.conversation_attachments;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Intake AI source history is immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.conversation_id
  AND created_by_user_id=NEW.created_by_user_id AND archived_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Intake AI conversation differs' USING ERRCODE='23514'; END IF;
 SELECT * INTO latest FROM cehub_ai.intake_ai_briefs WHERE tenant_id=NEW.tenant_id
  AND conversation_id=NEW.conversation_id AND message_id=NEW.message_id
  ORDER BY revision DESC LIMIT 1;
 IF NEW.revision<>coalesce(latest.revision,0)+1
  OR NEW.previous_brief_id IS DISTINCT FROM latest.id
  OR NEW.root_brief_id IS DISTINCT FROM coalesce(latest.root_brief_id,NEW.id) THEN
  RAISE EXCEPTION 'Intake source lineage differs' USING ERRCODE='23514'; END IF;
 FOR src IN SELECT key,value FROM jsonb_each(NEW.source_snapshot->'sources') LOOP
  SELECT * INTO file FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND conversation_id=NEW.conversation_id AND id=src.key::uuid;
  IF file.id IS NULL OR file.revoked_at IS NOT NULL OR file.status<>'extracted'
   OR file.classification<>'internal'
   OR NOT ((src.value->'identity'->>'attachment_id'=file.id::text
    AND src.value->'identity'->>'sha256'=file.sha256) IS TRUE)
   OR NOT EXISTS (SELECT 1 FROM cehub_ai.conversation_message_attachments a
    WHERE a.tenant_id=NEW.tenant_id AND a.conversation_id=NEW.conversation_id
     AND a.message_id=NEW.message_id AND a.attachment_id=file.id) THEN
   RAISE EXCEPTION 'Intake source must be a current message attachment' USING ERRCODE='23514';
  END IF;
 END LOOP;
 FOR frag IN SELECT value FROM jsonb_array_elements(NEW.source_snapshot->'fragments') LOOP
  IF NOT (NEW.source_snapshot->'sources' ? (frag->>'attachment_id'))
   OR NOT EXISTS (SELECT 1 FROM cehub_ai.conversation_attachments a
    WHERE a.tenant_id=NEW.tenant_id AND a.conversation_id=NEW.conversation_id
     AND a.id=(frag->>'attachment_id')::uuid
     AND a.fragments @> jsonb_build_array(frag-'attachment_id'-'reference_id')) THEN
   RAISE EXCEPTION 'Intake excerpt differs from actual fragment' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_intake_ai_brief() FROM PUBLIC;
CREATE TRIGGER guard_intake_ai_brief BEFORE INSERT OR UPDATE OR DELETE ON cehub_ai.intake_ai_briefs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_intake_ai_brief();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
     IF EXISTS (SELECT 1 FROM cehub_ai.intake_ai_briefs) THEN
      RAISE EXCEPTION 'Intake source history must be retained'; END IF;
    END $$""")
    op.execute("DROP TABLE cehub_ai.intake_ai_briefs")
    op.execute("DROP FUNCTION cehub_ai.guard_intake_ai_brief()")
