"""Bind professional discussion sessions to actual budgeted model runs and turn receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0206_discussion_run_bindings"
down_revision = "0205_quiet_creation_and_adoption"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.debate_run_bindings (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    run_id UUID NOT NULL,
    session_id UUID NOT NULL,
    ecr_id UUID NOT NULL,
    source JSONB NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_debate_run_bindings PRIMARY KEY (id),
    CONSTRAINT uq_debate_binding_run UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_debate_binding_session UNIQUE (tenant_id, session_id),
    CONSTRAINT fk_debate_run_bindings_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id)
REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_run_bindings_tenant_id_debate_sessions FOREIGN KEY(tenant_id,
session_id) REFERENCES cehub_ai.debate_sessions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_run_bindings_tenant_id_engineering_change_requests FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_debate_run_bindings_shape CHECK (jsonb_typeof(source)='object' AND
jsonb_typeof(config)='object')
)

;

CREATE TABLE cehub_ai.debate_turn_receipts (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    run_id UUID NOT NULL,
    session_id UUID NOT NULL,
    seat_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    turn_id UUID NOT NULL,
    checkpoint_id UUID NOT NULL,
    output JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_debate_turn_receipts PRIMARY KEY (id),
    CONSTRAINT uq_debate_turn_receipt_step UNIQUE (tenant_id, session_id, seat_id,
round_number),
    CONSTRAINT uq_debate_turn_receipt_turn UNIQUE (turn_id),
    CONSTRAINT fk_debate_turn_receipts_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_turn_receipts_tenant_id_application_result_ch_439b FOREIGN
KEY(tenant_id, run_id, checkpoint_id) REFERENCES cehub_ai.application_result_checkpoints
(tenant_id, run_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_turn_receipts_tenant_id_debate_seats FOREIGN KEY(tenant_id, seat_id)
REFERENCES cehub_ai.debate_seats (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_debate_turn_receipts_tenant_id_debate_turns FOREIGN KEY(tenant_id, turn_id)
REFERENCES cehub_ai.debate_turns (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_debate_turn_receipts_shape CHECK (round_number BETWEEN 1 AND 3 AND
jsonb_typeof(output)='object')
)

;
CREATE TRIGGER protect_debate_run_bindings BEFORE UPDATE OR DELETE ON
cehub_ai.debate_run_bindings FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.debate_run_bindings FROM PUBLIC;
CREATE TRIGGER protect_debate_turn_receipts BEFORE UPDATE OR DELETE ON
cehub_ai.debate_turn_receipts FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.debate_turn_receipts FROM PUBLIC;
ALTER TABLE cehub_ai.debate_seats DROP CONSTRAINT ck_debate_seats_seat_key_allowed;
ALTER TABLE cehub_ai.debate_seats ADD CONSTRAINT ck_debate_seats_seat_key_allowed CHECK
(seat_key IN
('product_manager','project_manager','structure_engineer','hardware_engineer','dqe','supplier','id_designer','firmware_engineer','sqe','ie'));
ALTER TABLE cehub_ai.debate_sessions DROP CONSTRAINT ck_debate_sessions_status_allowed;
ALTER TABLE cehub_ai.debate_sessions ADD CONSTRAINT ck_debate_sessions_status_allowed CHECK
(status IN
('convened','arguing','converged','budget_stopped','briefed','cancelled','completed','interrupted'));
"""
GUARDS = """
CREATE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity='engineering_change_request'
 AND s.topic_entity_id=NEW.ecr_id AND s.initiated_by_user_id=r.requested_by_user_id
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_debate_binding BEFORE INSERT ON cehub_ai.debate_run_bindings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_debate_binding();
CREATE FUNCTION cehub_ai.guard_debate_turn_receipt() RETURNS trigger
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
CREATE TRIGGER guard_debate_turn_receipt BEFORE INSERT ON cehub_ai.debate_turn_receipts
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_debate_turn_receipt();
CREATE FUNCTION cehub_ai.protect_bound_debate_seat() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE wanted_tenant uuid; wanted_session uuid;
BEGIN
 IF TG_OP IN ('UPDATE','DELETE') THEN
  IF EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
  WHERE b.tenant_id=OLD.tenant_id AND b.session_id=OLD.session_id) THEN
   RAISE EXCEPTION 'bound discussion projections are immutable' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN wanted_tenant:=OLD.tenant_id; wanted_session:=OLD.session_id;
 ELSE wanted_tenant:=NEW.tenant_id; wanted_session:=NEW.session_id; END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=wanted_tenant AND b.session_id=wanted_session) THEN
 RAISE EXCEPTION 'bound discussion projections are immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER protect_bound_debate_seat BEFORE INSERT OR UPDATE OR DELETE ON
cehub_ai.debate_seats
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_bound_debate_seat();
CREATE FUNCTION cehub_ai.require_bound_debate_turn_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.speaker_kind='seat' AND EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.session_id=NEW.session_id)
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.debate_turn_receipts r
 WHERE r.tenant_id=NEW.tenant_id AND r.turn_id=NEW.id) THEN
 RAISE EXCEPTION 'bound discussion requires a model receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER require_bound_debate_turn_receipt AFTER INSERT ON
cehub_ai.debate_turns
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_ai.require_bound_debate_turn_receipt();
REVOKE ALL ON FUNCTION cehub_ai.guard_debate_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_debate_turn_receipt() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.protect_bound_debate_seat() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.require_bound_debate_turn_receipt() FROM PUBLIC;

CREATE FUNCTION cehub_ai.protect_bound_debate_turn() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=OLD.tenant_id AND b.session_id=OLD.session_id) THEN
 RAISE EXCEPTION 'bound discussion turns are immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER protect_bound_debate_turn BEFORE UPDATE OR DELETE ON cehub_ai.debate_turns
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_bound_debate_turn();
REVOKE ALL ON FUNCTION cehub_ai.protect_bound_debate_turn() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARDS))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard bound discussion history")
    op.execute("DROP TRIGGER protect_bound_debate_turn ON cehub_ai.debate_turns")
    op.execute("DROP FUNCTION cehub_ai.protect_bound_debate_turn()")
    op.execute("DROP TRIGGER require_bound_debate_turn_receipt ON cehub_ai.debate_turns")
    op.execute("DROP TRIGGER protect_bound_debate_seat ON cehub_ai.debate_seats")
    op.execute("DROP TABLE cehub_ai.debate_turn_receipts")
    op.execute("DROP TABLE cehub_ai.debate_run_bindings")
    for name in (
        "guard_debate_binding",
        "guard_debate_turn_receipt",
        "protect_bound_debate_seat",
        "require_bound_debate_turn_receipt",
    ):
        op.execute("DROP FUNCTION cehub_ai." + name + "()")
    op.drop_constraint(op.f("ck_debate_seats_seat_key_allowed"), "debate_seats", schema="cehub_ai")
    op.create_check_constraint(
        op.f("ck_debate_seats_seat_key_allowed"),
        "debate_seats",
        "seat_key IN ('product_manager','project_manager','structure_engineer',"
        "'hardware_engineer','dqe','supplier')",
        schema="cehub_ai",
    )
    op.drop_constraint(
        op.f("ck_debate_sessions_status_allowed"), "debate_sessions", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_debate_sessions_status_allowed"),
        "debate_sessions",
        "status IN ('convened','arguing','converged','budget_stopped','briefed','cancelled')",
        schema="cehub_ai",
    )
