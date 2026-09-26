"""Persistent event-triggered knowledge retrieval with retained model receipts."""

from alembic import op

revision = "0264_knowledge_reuse_jobs"
down_revision = "0263_risk_followup_results"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_memory.knowledge_reuse_jobs (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	recipient_user_id UUID NOT NULL, 
	context_kind VARCHAR(32) NOT NULL, 
	context_entity_id UUID NOT NULL, 
	context_sha256 VARCHAR(64) NOT NULL, 
	query_text TEXT NOT NULL, 
	source_audit_id BIGINT NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	embedding_receipt JSON, 
	push_ids JSON NOT NULL, 
	reason VARCHAR(128), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_knowledge_reuse_jobs PRIMARY KEY (id), 
        CONSTRAINT ck_knowledge_reuse_jobs_context_allowed CHECK (context_kind IN
('project_kickoff','part_selection','change_request','task_takeover')),
        CONSTRAINT ck_knowledge_reuse_jobs_state_allowed CHECK (state IN
('pending','running','ready','empty','stale','failed','uncertain')),
        CONSTRAINT uq_knowledge_reuse_context UNIQUE (tenant_id, recipient_user_id,
context_kind, context_entity_id, context_sha256),
        CONSTRAINT fk_knowledge_reuse_project FOREIGN KEY(tenant_id, project_id) REFERENCES
cehub_project.projects (tenant_id, id),
        CONSTRAINT fk_knowledge_reuse_recipient FOREIGN KEY(tenant_id, recipient_user_id)
REFERENCES cehub_core.users (tenant_id, id),
        CONSTRAINT fk_knowledge_reuse_audit FOREIGN KEY(tenant_id, source_audit_id) REFERENCES
cehub_audit.audit_log (tenant_id, id)
)

;
CREATE INDEX ix_knowledge_reuse_pending ON cehub_memory.knowledge_reuse_jobs (state, created_at);
"""

GUARD = """
CREATE FUNCTION cehub_memory.guard_knowledge_reuse_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge reuse history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'pending' OR NEW.embedding_receipt IS NOT NULL OR NEW.push_ids::jsonb<>'[]'::jsonb
   OR NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
      WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
       AND a.id=NEW.source_audit_id AND a.entity_id=NEW.context_entity_id) THEN
   RAISE EXCEPTION 'Reuse requests require a real business source' USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at']) IS
DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at'])
   OR NOT ((OLD.state='pending' AND NEW.state IN ('running','stale'))
     OR (OLD.state='running' AND NEW.state IN
('running','ready','empty','stale','failed','uncertain')))
   OR (OLD.embedding_receipt IS NOT NULL AND OLD.embedding_receipt::jsonb IS DISTINCT FROM
NEW.embedding_receipt::jsonb) THEN
   RAISE EXCEPTION 'Reuse source and successful embedding receipt are immutable' USING
ERRCODE='23514';
  END IF;
 END IF;
 IF jsonb_typeof(NEW.push_ids::jsonb)<>'array' OR jsonb_array_length(NEW.push_ids::jsonb)>5
   OR (NEW.state='ready' AND jsonb_array_length(NEW.push_ids::jsonb)=0)
   OR (NEW.state<>'ready' AND NEW.push_ids::jsonb<>'[]'::jsonb)
   OR (NEW.state IN ('ready','empty') AND NEW.embedding_receipt IS NULL) THEN
  RAISE EXCEPTION 'Invalid knowledge reuse result' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.push_ids::jsonb) x(id)
  WHERE NOT EXISTS(SELECT 1 FROM cehub_memory.knowledge_pushes p WHERE p.id=x.id::uuid
   AND p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id
   AND p.context_kind=NEW.context_kind AND p.context_entity_id=NEW.context_entity_id
   AND p.context_sha256=NEW.context_sha256)) THEN
  RAISE EXCEPTION 'Reuse results must match the original business input' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_reuse_job() FROM PUBLIC;
CREATE TRIGGER guard_knowledge_reuse_job BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_memory.knowledge_reuse_jobs FOR EACH ROW EXECUTE FUNCTION
cehub_memory.guard_knowledge_reuse_job();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    import sqlalchemy as sa

    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_memory.knowledge_reuse_jobs)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard knowledge reuse requests and receipts")
    op.drop_table("knowledge_reuse_jobs", schema="cehub_memory")
    op.execute("DROP FUNCTION cehub_memory.guard_knowledge_reuse_job()")
