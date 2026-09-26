"""Continue frozen discussion steps after known budget or lease interruptions."""

import sqlalchemy as sa
from alembic import op

revision = "0208_discussion_resume"
down_revision = "0207_discussion_brief_reviews"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.debate_resume_requests (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        run_id UUID NOT NULL,
        previous_lease_id UUID NOT NULL,
        requested_by_user_id UUID NOT NULL,
        body JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_debate_resume_requests PRIMARY KEY (id),
        CONSTRAINT uq_debate_resume_scope UNIQUE (tenant_id, run_id, id),
        CONSTRAINT fk_debate_resume_requests_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
        CONSTRAINT fk_debate_resume_requests_tenant_id_application_run_leases FOREIGN
KEY(tenant_id, run_id, previous_lease_id) REFERENCES cehub_ai.application_run_leases (tenant_id,
run_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_debate_resume_requests_tenant_id_users FOREIGN KEY(tenant_id,
requested_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_debate_resume_requests_shape CHECK (jsonb_typeof(body)='object' AND
jsonb_typeof(body->'remaining_calls')='array')
)

;
REVOKE ALL ON cehub_ai.debate_resume_requests FROM PUBLIC;
ALTER TABLE cehub_ai.application_run_leases ADD COLUMN discussion_resume_id uuid,
ADD CONSTRAINT fk_application_lease_discussion_resume FOREIGN
KEY(tenant_id,run_id,discussion_resume_id)
REFERENCES cehub_ai.debate_resume_requests(tenant_id,run_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.application_run_leases DROP CONSTRAINT ck_application_run_leases_generation;
ALTER TABLE cehub_ai.application_run_leases ADD CONSTRAINT ck_application_run_leases_generation
CHECK (generation>0 AND ((generation=1 AND previous_lease_id IS NULL AND recovery_checkpoint_id IS
NULL
AND discussion_resume_id IS NULL) OR (generation>1 AND previous_lease_id IS NOT NULL AND
((recovery_checkpoint_id IS NOT NULL AND discussion_resume_id IS NULL) OR
(recovery_checkpoint_id IS NULL AND discussion_resume_id IS NOT NULL)))));
CREATE FUNCTION cehub_ai.discussion_resume_history_known(t uuid,rid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_sessions s WHERE s.tenant_id=t AND
s.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_events e
   WHERE e.tenant_id=t AND e.session_id=s.id AND e.state='closed'))
 AND NOT EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(j.attempt_id) j.reservation_status FROM cehub_ai.budget_journal j
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=j.tenant_id AND b.lineage_id=j.lineage_id
  WHERE b.tenant_id=t AND b.run_id=rid ORDER BY j.attempt_id,j.revision DESC
 ) latest WHERE latest.reservation_status IN ('reserved','unknown'))
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_journal j WHERE j.tenant_id=t AND j.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
   WHERE cp.tenant_id=t AND cp.run_id=rid AND
cp.model_call_id::text=j.request_binding->>'model_call_id'));
$$;
CREATE FUNCTION cehub_ai.guard_debate_resume_request() RETURNS trigger
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
CREATE TRIGGER guard_debate_resume_request BEFORE INSERT ON cehub_ai.debate_resume_requests
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_debate_resume_request();
CREATE TRIGGER protect_debate_resume_requests BEFORE UPDATE OR DELETE ON
cehub_ai.debate_resume_requests
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();

CREATE FUNCTION cehub_ai.claim_discussion_resume(t uuid,rid uuid,actor uuid,auth integer,
owner uuid,request uuid,policy text,profile jsonb) RETURNS uuid
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; l cehub_ai.application_run_leases;
 a cehub_ai.application_authorizations; req cehub_ai.debate_resume_requests; token uuid; stamp
timestamptz;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:'||t::text,0));
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=t AND id=rid FOR UPDATE;
 SELECT * INTO req FROM cehub_ai.debate_resume_requests WHERE tenant_id=t AND run_id=rid AND
id=request;
 SELECT * INTO l FROM cehub_ai.application_run_leases WHERE tenant_id=t AND run_id=rid
 ORDER BY generation DESC LIMIT 1 FOR UPDATE;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE tenant_id=t AND run_id=rid;
 IF req.id IS NULL OR l.id IS DISTINCT FROM req.previous_lease_id OR l.generation>=3
 OR r.status IS DISTINCT FROM 'degraded' OR r.error_code IS DISTINCT FROM req.body->>'stop_code'
 OR r.run_context->>'discussion_resume_request_id' IS DISTINCT FROM request::text
 OR r.run_context->'discussion_recovery_requested' IS DISTINCT FROM 'true'::jsonb
 OR (l.ended_at IS NULL AND l.expires_at>clock_timestamp())
 OR req.requested_by_user_id IS DISTINCT FROM actor OR a.principal_id IS DISTINCT FROM actor
 OR (a.pins->>'auth_version')::integer IS DISTINCT FROM auth
 OR a.body->>'purpose' IS DISTINCT FROM 'change_discussion'
 OR a.body->>'policy_version' IS DISTINCT FROM policy
 OR NOT EXISTS(SELECT 1 FROM cehub_ai.budget_lineages b WHERE b.tenant_id=t AND b.id=a.lineage_id
 AND b.profile=claim_discussion_resume.profile)
 OR NOT cehub_ai.discussion_resume_history_known(t,rid) THEN
 RAISE EXCEPTION 'APPLICATION_DISCUSSION_RESUME_UNAVAILABLE' USING ERRCODE='22023'; END IF;
 IF l.ended_at IS NULL THEN UPDATE cehub_ai.application_run_leases SET ended_at=clock_timestamp(),
 stop_reason='APPLICATION_RUN_LEASE_EXPIRED' WHERE id=l.id; END IF;
 UPDATE cehub_ai.agent_runs SET status='running',error_code=NULL,completed_at=NULL,
updated_at=clock_timestamp(),
run_context=run_context||'{"discussion_recovery_requested": false}'::jsonb
 WHERE tenant_id=t AND id=rid;
 IF NOT cehub_ai.application_authorization_is_current(rid) THEN
 RAISE EXCEPTION 'APPLICATION_RECOVERY_AUTHORIZATION_CHANGED' USING ERRCODE='22023'; END IF;
 PERFORM cehub_ai.check_run_active_budget(t,rid);
 token:=gen_random_uuid(); stamp:=clock_timestamp();
 INSERT INTO cehub_ai.application_run_leases(id,tenant_id,run_id,authorization_id,owner_id,
 generation,previous_lease_id,discussion_resume_id,issued_at,renewed_at,expires_at)
 VALUES(token,t,rid,a.id,owner,l.generation+1,l.id,request,stamp,stamp,
 least(stamp+interval '60 seconds',a.expires_at));
 UPDATE cehub_ai.debate_sessions SET status='arguing',stop_reason=NULL,updated_at=stamp
 WHERE tenant_id=t AND id=(SELECT session_id FROM cehub_ai.debate_run_bindings WHERE tenant_id=t
AND run_id=rid);
 RETURN token;
END $$;

CREATE OR REPLACE FUNCTION cehub_ai.protect_application_lease() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (
  (NEW.id,NEW.tenant_id,NEW.run_id,NEW.authorization_id,NEW.owner_id,NEW.issued_at,
   NEW.generation,NEW.previous_lease_id,NEW.recovery_checkpoint_id,NEW.discussion_resume_id)
   IS DISTINCT FROM
  (OLD.id,OLD.tenant_id,OLD.run_id,OLD.authorization_id,OLD.owner_id,OLD.issued_at,
   OLD.generation,OLD.previous_lease_id,OLD.recovery_checkpoint_id,OLD.discussion_resume_id)
  OR OLD.ended_at IS NOT NULL OR NEW.renewed_at<OLD.renewed_at)) THEN
  RAISE EXCEPTION 'application lease identity and ended history are immutable';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_lease() FROM PUBLIC;


CREATE OR REPLACE FUNCTION cehub_ai.require_application_lease_chain() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.discussion_resume_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_resume_requests req
  JOIN cehub_ai.application_run_leases l ON l.tenant_id=req.tenant_id AND l.run_id=req.run_id
  AND l.id=req.previous_lease_id WHERE req.tenant_id=NEW.tenant_id AND req.run_id=NEW.run_id
  AND req.id=NEW.discussion_resume_id AND l.id=NEW.previous_lease_id
  AND l.authorization_id=NEW.authorization_id AND l.generation+1=NEW.generation
  AND l.ended_at IS NOT NULL AND l.ended_at<=NEW.issued_at) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_CHAIN_INVALID' USING ERRCODE='22023'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.generation>1 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases l
  JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=l.tenant_id AND
cp.run_id=l.run_id
  WHERE l.tenant_id=NEW.tenant_id AND l.run_id=NEW.run_id AND l.id=NEW.previous_lease_id
   AND l.generation+1=NEW.generation AND l.ended_at IS NOT NULL
   AND l.ended_at<=NEW.issued_at AND cp.id=NEW.recovery_checkpoint_id
   AND l.authorization_id=NEW.authorization_id) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_CHAIN_INVALID' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
CREATE OR REPLACE FUNCTION cehub_ai.forbid_application_recovery_dispatch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.call_kind='model' AND NEW.dispatched_at IS NOT NULL
 AND NEW.reservation_status='reserved' AND EXISTS(SELECT 1 FROM cehub_ai.application_run_leases
 WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id AND generation>1 AND ended_at IS NULL)
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases l
 JOIN cehub_ai.debate_resume_requests req ON req.tenant_id=l.tenant_id AND req.run_id=l.run_id
 AND req.id=l.discussion_resume_id,
 jsonb_array_elements(req.body->'remaining_calls') step
 WHERE l.tenant_id=NEW.tenant_id AND l.run_id=NEW.run_id AND l.ended_at IS NULL
 AND cehub_ai.application_lease_is_current(l.run_id,l.id)
 AND step->>'model_call_id'=NEW.request_binding->>'model_call_id'
 AND EXISTS(SELECT 1 FROM cehub_ai.application_context_observations o
 WHERE o.tenant_id=NEW.tenant_id AND o.run_id=NEW.run_id
 AND o.model_call_id::text=step->>'model_call_id'
 AND o.output_body->'projection'->>'id'=step->>'seat_id'
 AND o.output_body->>'round_number'=step->>'round_number')
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
 WHERE cp.tenant_id=NEW.tenant_id AND cp.run_id=NEW.run_id
 AND cp.model_call_id::text=step->>'model_call_id')) THEN
 RAISE EXCEPTION 'BUDGET_APPLICATION_RECOVERY_MODEL_FORBIDDEN' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION cehub_ai.discussion_resume_history_known(uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_debate_resume_request() FROM PUBLIC;
REVOKE ALL ON FUNCTION
cehub_ai.claim_discussion_resume(uuid,uuid,uuid,integer,uuid,uuid,text,jsonb) FROM PUBLIC;
"""
BRIEF_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_brief_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original cehub_ai.debate_run_bindings; running cehub_ai.agent_runs; actual_turns jsonb;
BEGIN
 SELECT * INTO running FROM cehub_ai.agent_runs r
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id FOR UPDATE;
 SELECT * INTO original FROM cehub_ai.debate_run_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id;
 IF original.id IS NULL OR running.status IN ('queued','running')
 OR (running.status='degraded'
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
"""
OLD_BRIEF_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_brief_review() RETURNS trigger
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
"""

OLD_FUNCTIONS = """

CREATE OR REPLACE FUNCTION cehub_ai.protect_application_lease() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (
  (NEW.id,NEW.tenant_id,NEW.run_id,NEW.authorization_id,NEW.owner_id,NEW.issued_at,
   NEW.generation,NEW.previous_lease_id,NEW.recovery_checkpoint_id)
   IS DISTINCT FROM
  (OLD.id,OLD.tenant_id,OLD.run_id,OLD.authorization_id,OLD.owner_id,OLD.issued_at,
   OLD.generation,OLD.previous_lease_id,OLD.recovery_checkpoint_id)
  OR OLD.ended_at IS NOT NULL OR NEW.renewed_at<OLD.renewed_at)) THEN
  RAISE EXCEPTION 'application lease identity and ended history are immutable';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_lease() FROM PUBLIC;


CREATE OR REPLACE FUNCTION cehub_ai.require_application_lease_chain() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.generation>1 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases l
  JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=l.tenant_id AND cp.run_id=l.run_id
  WHERE l.tenant_id=NEW.tenant_id AND l.run_id=NEW.run_id AND l.id=NEW.previous_lease_id
   AND l.generation+1=NEW.generation AND l.ended_at IS NOT NULL
   AND l.ended_at<=NEW.issued_at AND cp.id=NEW.recovery_checkpoint_id
   AND l.authorization_id=NEW.authorization_id) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_CHAIN_INVALID' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
CREATE OR REPLACE FUNCTION cehub_ai.forbid_application_recovery_dispatch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.dispatched_at IS NOT NULL
  AND NEW.reservation_status='reserved' AND EXISTS(
   SELECT 1 FROM cehub_ai.application_run_leases WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id
    AND generation>1 AND ended_at IS NULL) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_RECOVERY_MODEL_FORBIDDEN' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(BRIEF_GUARD))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_resume_requests)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard discussion continuation history")
    op.execute(sa.text(OLD_FUNCTIONS))
    op.execute(sa.text(OLD_BRIEF_GUARD))
    op.execute(
        "ALTER TABLE cehub_ai.application_run_leases "
        "DROP CONSTRAINT fk_application_lease_discussion_resume, "
        "DROP CONSTRAINT ck_application_run_leases_generation, "
        "DROP COLUMN discussion_resume_id"
    )
    op.execute(
        "ALTER TABLE cehub_ai.application_run_leases ADD CONSTRAINT "
        "ck_application_run_leases_generation CHECK(generation>0 AND "
        "((generation=1 AND previous_lease_id IS NULL AND recovery_checkpoint_id IS NULL) OR "
        "(generation>1 AND previous_lease_id IS NOT NULL AND recovery_checkpoint_id IS NOT NULL)))"
    )
    op.execute("DROP TABLE cehub_ai.debate_resume_requests")
    op.execute("DROP FUNCTION cehub_ai.guard_debate_resume_request()")
    op.execute(
        "DROP FUNCTION cehub_ai.claim_discussion_resume"
        "(uuid,uuid,uuid,integer,uuid,uuid,text,jsonb)"
    )
    op.execute("DROP FUNCTION cehub_ai.discussion_resume_history_known(uuid,uuid)")
