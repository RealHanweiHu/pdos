"""Append named public research excerpts to the original bounded discussion."""

import sqlalchemy as sa
from alembic import op

revision = "0212_discussion_research"
down_revision = "0211_discussion_initiation"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.debate_research_inputs (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	snapshot_id UUID NOT NULL, 
	turn_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request JSONB NOT NULL, 
	reference JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_debate_research_inputs PRIMARY KEY (id), 
    CONSTRAINT uq_discussion_research_request UNIQUE (tenant_id, run_id, actor_user_id,
request_id),
    CONSTRAINT fk_debate_research_inputs_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_research_inputs_tenant_id_debate_sessions FOREIGN KEY(tenant_id,
session_id) REFERENCES cehub_ai.debate_sessions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_research_inputs_tenant_id_debate_turns FOREIGN KEY(tenant_id, turn_id)
REFERENCES cehub_ai.debate_turns (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_research_inputs_tenant_id_evidence_snapshots FOREIGN KEY(tenant_id,
snapshot_id) REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_research_inputs_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_debate_research_inputs_shape CHECK (jsonb_typeof(request)='object' AND
jsonb_typeof(reference)='object')
)

;
"""

GUARD = """

CREATE FUNCTION cehub_ai.guard_discussion_research() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
 JOIN cehub_ai.debate_turns t ON t.tenant_id=b.tenant_id AND t.session_id=b.session_id
 JOIN cehub_evidence.evidence_snapshots s ON s.tenant_id=b.tenant_id AND s.id=NEW.snapshot_id
 JOIN cehub_evidence.research_sources rs ON rs.tenant_id=s.tenant_id AND rs.id=s.source_id
 JOIN cehub_evidence.evidence_contents ec
 ON ec.tenant_id=s.tenant_id AND ec.content_digest=s.content_digest
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND r.status IN ('queued','running') AND t.id=NEW.turn_id AND t.speaker_kind='human'
 AND t.author_user_id=NEW.actor_user_id AND rs.status='active'
 AND rs.source_type IN ('web','api') AND s.url IS NOT NULL AND s.taint='untrusted_external'
 AND NEW.request->>'snapshot_id'=s.id::text
 AND NEW.request->>'request_id'=NEW.request_id::text
 AND NEW.request->>'expected_digest'=NEW.reference->>'digest'
 AND NEW.reference->>'category'='public_research_snapshot'
 AND NEW.reference->'fields'->>'id'=s.id::text
 AND NEW.reference->'fields'->>'content_digest'=s.content_digest
 AND NEW.reference->'fields'->>'source_id'=s.source_id::text
 AND NEW.reference->'fields'->>'url'=s.url
 AND NEW.reference->'fields'->>'taint'=s.taint
 AND (NEW.request->>'offset')::integer BETWEEN 0 AND 2000000
 AND (NEW.request->>'length')::integer BETWEEN 1 AND 6000
 AND NEW.reference->'fields'->>'excerpt'=substring(ec.body
 FROM (NEW.request->>'offset')::integer+1 FOR (NEW.request->>'length')::integer)) THEN
 RAISE EXCEPTION 'research input requires actual public snapshot and named addition'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_discussion_research BEFORE INSERT ON cehub_ai.debate_research_inputs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_research();
CREATE TRIGGER protect_discussion_research BEFORE UPDATE OR DELETE
 ON cehub_ai.debate_research_inputs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.debate_research_inputs FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_research() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARD))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_research_inputs)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard original research input history")
    op.execute("DROP TABLE cehub_ai.debate_research_inputs")
    op.execute("DROP FUNCTION cehub_ai.guard_discussion_research()")
