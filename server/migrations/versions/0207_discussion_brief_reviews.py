"""Retain source-bound human comparison of actual discussion briefs."""

import sqlalchemy as sa
from alembic import op

revision = "0207_discussion_brief_reviews"
down_revision = "0206_discussion_run_bindings"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.debate_brief_reviews (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        run_id UUID NOT NULL,
        request_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        brief_digest VARCHAR(64) NOT NULL,
        source_digest VARCHAR(64) NOT NULL,
        snapshot JSONB NOT NULL,
        body JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_debate_brief_reviews PRIMARY KEY (id),
        CONSTRAINT uq_debate_brief_review_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_debate_brief_reviews_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
        CONSTRAINT fk_debate_brief_reviews_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_debate_brief_reviews_shape CHECK (jsonb_typeof(snapshot)='object' AND
jsonb_typeof(body)='object' AND body->>'outcome' IN ('validated','rejected') AND brief_digest ~
'^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$')
)
;

CREATE TRIGGER protect_debate_brief_reviews BEFORE UPDATE OR DELETE ON
cehub_ai.debate_brief_reviews FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.debate_brief_reviews FROM PUBLIC;
CREATE FUNCTION cehub_ai.guard_debate_brief_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original cehub_ai.debate_run_bindings; running cehub_ai.agent_runs; actual_turns jsonb;
BEGIN
 SELECT * INTO running FROM cehub_ai.agent_runs r
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id FOR UPDATE;
 SELECT * INTO original FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id;
 IF original.id IS NULL OR running.status IN ('queued','running')
 OR (running.status='degraded' AND running.error_code='APPLICATION_RUN_LEASE_EXPIRED'
 AND coalesce((running.run_context->>'discussion_recovery_requested')::boolean,false)) THEN
 RAISE EXCEPTION 'brief comparison requires a stopped bound discussion' USING ERRCODE='23514';
 END IF;
 SELECT coalesce(jsonb_agg(t.id::text ORDER BY t.sequence),'[]'::jsonb) INTO actual_turns
 FROM cehub_ai.debate_turns t
 WHERE t.tenant_id=NEW.tenant_id AND t.session_id=original.session_id;
 IF NEW.snapshot->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR NEW.snapshot->>'source_digest' IS DISTINCT FROM original.source->>'digest'
 OR NEW.snapshot->>'run_status' IS DISTINCT FROM running.status
 OR NEW.snapshot->'turn_ids' IS DISTINCT FROM actual_turns
 OR NEW.body->>'expected_digest' IS DISTINCT FROM NEW.brief_digest
 OR NEW.body->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NOT EXISTS(SELECT 1 FROM cehub_ai.debate_turn_receipts r
 WHERE r.tenant_id=NEW.tenant_id AND r.run_id=NEW.run_id) THEN
 RAISE EXCEPTION 'brief comparison must retain actual discussion evidence'
 USING ERRCODE='23514'; END IF;
 IF NEW.body->>'outcome'='validated' AND (
 NEW.source_digest IS DISTINCT FROM original.source->>'digest'
 OR NEW.body->'evidence_checked' IS DISTINCT FROM 'true'::jsonb
 OR NEW.body->'disagreements_complete' IS DISTINCT FROM 'true'::jsonb
 OR jsonb_typeof(NEW.body->'alternatives') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.body->'alternatives')<2) THEN
 RAISE EXCEPTION 'validated comparison requires sources and alternatives'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_debate_brief_review BEFORE INSERT ON cehub_ai.debate_brief_reviews
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_debate_brief_review();
REVOKE ALL ON FUNCTION cehub_ai.guard_debate_brief_review() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_brief_reviews)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard named discussion comparison history")
    op.execute("DROP TABLE cehub_ai.debate_brief_reviews")
    op.execute("DROP FUNCTION cehub_ai.guard_debate_brief_review()")
