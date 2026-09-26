"""Model-backed initiation inside the original discussion scope and budget."""

import sqlalchemy as sa
from alembic import op

revision = "0211_discussion_initiation"
down_revision = "0210_discussion_parent_lineage"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.debate_initiations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	checkpoint_id UUID NOT NULL, 
	output JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_debate_initiations PRIMARY KEY (id), 
	CONSTRAINT uq_debate_initiation_run UNIQUE (tenant_id, run_id), 
    CONSTRAINT fk_debate_initiations_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_initiations_tenant_id_debate_sessions FOREIGN KEY(tenant_id,
session_id) REFERENCES cehub_ai.debate_sessions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_initiations_tenant_id_application_result_checkpoints FOREIGN
KEY(tenant_id, run_id, checkpoint_id) REFERENCES cehub_ai.application_result_checkpoints
(tenant_id, run_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_debate_initiations_shape CHECK (jsonb_typeof(output)='object' AND
output->>'action' IN ('convene','not_needed','insufficient_evidence'))
)

;
"""

GUARD = """

CREATE FUNCTION cehub_ai.guard_debate_initiation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
 JOIN cehub_ai.debate_sessions s ON s.tenant_id=b.tenant_id AND s.id=b.session_id
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=b.tenant_id AND cp.run_id=b.run_id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id AND
o.id=cp.observation_id
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND r.status='running' AND s.initiated_by='agent' AND s.initiator_ref=r.id::text
 AND b.config->'request'->>'participation_mode'='agent_choose'
 AND cp.id=NEW.checkpoint_id AND cp.body->'output'=NEW.output
 AND o.output_body->>'phase'='discussion_initiation'
 AND o.output_body->'projection'->>'id'=b.config->'initiation'->>'id'
 AND o.output_body->'source'->>'digest'=b.source->>'digest'
 AND o.output_body->>'round_number'='1') THEN
 RAISE EXCEPTION 'initiation requires original successful model decision'
 USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(NEW.output->'seats') IS DISTINCT FROM 'array'
 OR (NEW.output->>'action'='convene' AND jsonb_array_length(NEW.output->'seats')<2)
 OR (NEW.output->>'action'<>'convene' AND jsonb_array_length(NEW.output->'seats')<>0)
 OR (SELECT count(*) FROM jsonb_array_elements(NEW.output->'seats')) <>
 (SELECT count(DISTINCT chosen->>'key') FROM jsonb_array_elements(NEW.output->'seats') chosen)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.output->'seats') chosen
 WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b,
 jsonb_array_elements(b.config->'seats') available WHERE b.tenant_id=NEW.tenant_id
 AND b.run_id=NEW.run_id AND available->>'key'=chosen->>'key')) THEN
 RAISE EXCEPTION 'initiation exceeds original candidate seats' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_debate_initiation BEFORE INSERT ON cehub_ai.debate_initiations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_debate_initiation();
CREATE TRIGGER protect_debate_initiation BEFORE UPDATE OR DELETE ON cehub_ai.debate_initiations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.debate_initiations FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_debate_initiation() FROM PUBLIC;

"""

OLD_BINDING = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity=NEW.topic_kind
 AND ((NEW.topic_kind='engineering_change_request' AND s.topic_entity_id=NEW.ecr_id)
 OR (NEW.topic_kind='project' AND s.topic_entity_id=NEW.project_id AND NEW.ecr_id IS NULL
 AND NEW.source->>'source_kind'='project_discussion'
 AND NEW.source->>'topic_id'=NEW.project_id::text
 AND NEW.source->>'actor_id'=r.requested_by_user_id::text)) AND
s.initiated_by_user_id=r.requested_by_user_id
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""

NEW_BINDING = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity=NEW.topic_kind
 AND ((NEW.topic_kind='engineering_change_request' AND s.topic_entity_id=NEW.ecr_id)
 OR (NEW.topic_kind='project' AND s.topic_entity_id=NEW.project_id AND NEW.ecr_id IS NULL
 AND NEW.source->>'source_kind'='project_discussion'
 AND NEW.source->>'topic_id'=NEW.project_id::text
 AND NEW.source->>'actor_id'=r.requested_by_user_id::text)) AND ((s.initiated_by='user' AND
s.initiated_by_user_id=r.requested_by_user_id
 AND NOT (NEW.config ? 'initiation')) OR (s.initiated_by='agent'
 AND s.initiated_by_user_id IS NULL AND s.initiator_ref=r.id::text
 AND NEW.config->'request'->>'participation_mode'='agent_choose'
 AND r.run_context->>'discussion_initiation_version'='discussion-initiation-v1'
 AND jsonb_typeof(NEW.config->'initiation')='object'))
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""

OLD_RESUME = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_resume_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_run_bindings b
 ON b.tenant_id=r.tenant_id AND b.run_id=r.id
 JOIN cehub_ai.application_run_leases l ON l.tenant_id=r.tenant_id AND l.run_id=r.id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND l.id=NEW.previous_lease_id
 AND r.requested_by_user_id=NEW.requested_by_user_id AND r.status='degraded'
 AND r.error_code IN ('APPLICATION_RUN_LEASE_EXPIRED','DAILY_BUDGET_EXCEEDED',
 'BUDGET_TENANT_TOKENS_EXHAUSTED','BUDGET_TENANT_CALL_BUSY','BUDGET_LINEAGE_CALL_BUSY')
 AND r.error_code=NEW.body->>'stop_code' AND b.source->>'digest'=NEW.body->>'source_digest'
 AND l.generation<3 AND (l.ended_at IS NOT NULL OR l.expires_at<=clock_timestamp())
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases n
 WHERE n.tenant_id=l.tenant_id AND n.run_id=l.run_id AND n.generation>l.generation))
 OR NOT cehub_ai.discussion_resume_history_known(NEW.tenant_id,NEW.run_id) THEN
 RAISE EXCEPTION 'APPLICATION_DISCUSSION_RESUME_UNAVAILABLE' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'remaining_calls') step
 WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b,
 jsonb_array_elements(b.config->'seats') seat WHERE b.tenant_id=NEW.tenant_id AND
b.run_id=NEW.run_id
 AND seat->>'id'=step->>'seat_id'
 AND (step->>'round_number')::integer BETWEEN 1 AND (b.config->'request'->>'rounds')::integer))
THEN
 RAISE EXCEPTION 'APPLICATION_DISCUSSION_RESUME_SCOPE_INVALID' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $$;
"""

NEW_RESUME = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_resume_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_run_bindings b
 ON b.tenant_id=r.tenant_id AND b.run_id=r.id
 JOIN cehub_ai.application_run_leases l ON l.tenant_id=r.tenant_id AND l.run_id=r.id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND l.id=NEW.previous_lease_id
 AND r.requested_by_user_id=NEW.requested_by_user_id AND r.status='degraded'
 AND r.error_code IN ('APPLICATION_RUN_LEASE_EXPIRED','DAILY_BUDGET_EXCEEDED',
 'BUDGET_TENANT_TOKENS_EXHAUSTED','BUDGET_TENANT_CALL_BUSY','BUDGET_LINEAGE_CALL_BUSY')
 AND r.error_code=NEW.body->>'stop_code' AND b.source->>'digest'=NEW.body->>'source_digest'
 AND l.generation<3 AND (l.ended_at IS NOT NULL OR l.expires_at<=clock_timestamp())
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases n
 WHERE n.tenant_id=l.tenant_id AND n.run_id=l.run_id AND n.generation>l.generation))
 OR NOT cehub_ai.discussion_resume_history_known(NEW.tenant_id,NEW.run_id) THEN
 RAISE EXCEPTION 'APPLICATION_DISCUSSION_RESUME_UNAVAILABLE' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'remaining_calls') step
 WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b,
 jsonb_array_elements((b.config->'seats') || CASE WHEN b.config ? 'initiation'
 THEN jsonb_build_array(b.config->'initiation') ELSE '[]'::jsonb END) seat WHERE
b.tenant_id=NEW.tenant_id AND
b.run_id=NEW.run_id
 AND seat->>'id'=step->>'seat_id'
 AND (step->>'round_number')::integer BETWEEN 1 AND (b.config->'request'->>'rounds')::integer))
THEN
 RAISE EXCEPTION 'APPLICATION_DISCUSSION_RESUME_SCOPE_INVALID' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $$;
"""

OLD_TURN = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_turn_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=b.tenant_id AND
cp.run_id=b.run_id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id AND
o.id=cp.observation_id
 JOIN cehub_ai.debate_turns t ON t.tenant_id=b.tenant_id AND t.session_id=b.session_id
 JOIN cehub_ai.debate_seats s ON s.tenant_id=t.tenant_id AND s.session_id=t.session_id AND
s.id=t.seat_id
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND cp.id=NEW.checkpoint_id AND cp.body->'output'=NEW.output AND t.id=NEW.turn_id
 AND t.speaker_kind='seat' AND t.seat_id=NEW.seat_id AND t.round_number=NEW.round_number
 AND o.output_body->'projection'->>'id'=NEW.seat_id::text
 AND (o.output_body->>'round_number')::integer=NEW.round_number) THEN
 RAISE EXCEPTION 'discussion turn lacks original successful model receipt'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

NEW_TURN = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_turn_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=b.tenant_id AND
cp.run_id=b.run_id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id AND
o.id=cp.observation_id
 JOIN cehub_ai.debate_turns t ON t.tenant_id=b.tenant_id AND t.session_id=b.session_id
 JOIN cehub_ai.debate_seats s ON s.tenant_id=t.tenant_id AND s.session_id=t.session_id AND
s.id=t.seat_id
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND cp.id=NEW.checkpoint_id AND cp.body->'output'=NEW.output AND t.id=NEW.turn_id
 AND t.speaker_kind='seat' AND t.seat_id=NEW.seat_id AND t.round_number=NEW.round_number
 AND o.output_body->'projection'->>'id'=NEW.seat_id::text
 AND (o.output_body->>'round_number')::integer=NEW.round_number) THEN
 RAISE EXCEPTION 'discussion turn lacks original successful model receipt'
 USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.config ? 'initiation')
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.debate_initiations i
 JOIN cehub_ai.debate_seats s ON s.tenant_id=i.tenant_id AND s.session_id=i.session_id
 WHERE i.tenant_id=NEW.tenant_id AND i.run_id=NEW.run_id AND s.id=NEW.seat_id
 AND i.output->>'action'='convene' AND EXISTS(SELECT 1
 FROM jsonb_array_elements(i.output->'seats') chosen WHERE chosen->>'key'=s.seat_key)) THEN
 RAISE EXCEPTION 'seat was not convened by original model receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""


OLD_STATUSES = (
    "'convened','arguing','converged','budget_stopped','briefed',"
    "'cancelled','completed','interrupted'"
)


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARD))
    op.execute(sa.text(NEW_BINDING))
    op.execute(sa.text(NEW_RESUME))
    op.execute(sa.text(NEW_TURN))
    op.drop_constraint(
        op.f("ck_debate_sessions_status_allowed"), "debate_sessions", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_debate_sessions_status_allowed"),
        "debate_sessions",
        "status IN ('preparing'," + OLD_STATUSES + ")",
        schema="cehub_ai",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings "
                "WHERE config ? 'initiation')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard agent initiation history")
    op.execute(sa.text(OLD_BINDING))
    op.execute(sa.text(OLD_RESUME))
    op.execute(sa.text(OLD_TURN))
    op.execute("DROP TABLE cehub_ai.debate_initiations")
    op.execute("DROP FUNCTION cehub_ai.guard_debate_initiation()")
    op.drop_constraint(
        op.f("ck_debate_sessions_status_allowed"), "debate_sessions", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_debate_sessions_status_allowed"),
        "debate_sessions",
        "status IN (" + OLD_STATUSES + ")",
        schema="cehub_ai",
    )
