"""Issue service authorization for budget-bound event runs and enforce revocation."""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0079_event_authorization"
down_revision: str | Sequence[str] | None = "0078_event_loop_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE TABLE cehub_ai.agent_service_principals (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,subscription_id uuid NOT NULL,
 name varchar(128) NOT NULL,status varchar(16) NOT NULL,revision integer NOT NULL,
 created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
 CONSTRAINT uq_service_principal_scope UNIQUE(tenant_id,id),
 CONSTRAINT uq_service_principal_subscription UNIQUE(tenant_id,subscription_id),
 FOREIGN KEY(tenant_id,subscription_id)
  REFERENCES cehub_ai.agent_subscriptions(tenant_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_service_principals_state CHECK(status IN ('active','paused') AND revision>0)
);
CREATE TABLE cehub_ai.agent_authorizations (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,lineage_id uuid NOT NULL,
 principal_id uuid NOT NULL,principal_revision integer NOT NULL,
 body jsonb NOT NULL,issued_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 CONSTRAINT uq_agent_authorization_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_agent_authorization_run UNIQUE(tenant_id,run_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,lineage_id,run_id)
  REFERENCES cehub_ai.budget_run_links(tenant_id,lineage_id,run_id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,principal_id)
  REFERENCES cehub_ai.agent_service_principals(tenant_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_authorizations_lifetime CHECK(expires_at>issued_at AND principal_revision>0
  AND jsonb_typeof(body)='object')
);
ALTER TABLE cehub_ai.agent_tool_observations ADD COLUMN authorization_id uuid,
 ADD CONSTRAINT fk_tool_observation_authorization FOREIGN KEY(tenant_id,run_id,authorization_id)
 REFERENCES cehub_ai.agent_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.agent_context_receipts ADD COLUMN authorization_id uuid,
 ADD CONSTRAINT fk_context_receipt_authorization FOREIGN KEY(tenant_id,run_id,authorization_id)
 REFERENCES cehub_ai.agent_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT;
CREATE TRIGGER protect_event_authorization BEFORE UPDATE OR DELETE ON cehub_ai.agent_authorizations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.agent_service_principals,cehub_ai.agent_authorizations FROM PUBLIC;

CREATE FUNCTION cehub_ai.protect_service_principal() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR pg_trigger_depth()<2 THEN
  RAISE EXCEPTION 'service principal follows subscription lifecycle' USING ERRCODE='42501';
 END IF;
 IF ROW(NEW.id,NEW.tenant_id,NEW.subscription_id,NEW.name,NEW.created_at) IS DISTINCT FROM
  ROW(OLD.id,OLD.tenant_id,OLD.subscription_id,OLD.name,OLD.created_at)
  OR NEW.revision<>OLD.revision+1 THEN
  RAISE EXCEPTION 'service principal identity is immutable' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_service_principal() FROM PUBLIC;
CREATE TRIGGER protect_service_principal BEFORE UPDATE OR DELETE
 ON cehub_ai.agent_service_principals
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_service_principal();

CREATE FUNCTION cehub_ai.track_service_principal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.status IS DISTINCT FROM OLD.status THEN
  UPDATE cehub_ai.agent_service_principals SET status=NEW.status,revision=revision+1,
    updated_at=clock_timestamp() WHERE tenant_id=NEW.tenant_id AND subscription_id=NEW.id;
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.track_service_principal() FROM PUBLIC;
CREATE TRIGGER track_service_principal AFTER UPDATE OF status ON cehub_ai.agent_subscriptions
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.track_service_principal();
"""

AUTHORITY = (
    "\nCREATE OR REPLACE FUNCTION cehub_ai.event_authorization_his"
    "tory_missing(wanted_run uuid)\nRETURNS boolean LANGUAGE sql V"
    "OLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body"
    "$\n SELECT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links WHE"
    "RE run_id=wanted_run)\n AND NOT EXISTS(SELECT 1 FROM cehub_ai"
    ".agent_authorizations WHERE run_id=wanted_run)\n AND (EXISTS("
    "SELECT 1 FROM cehub_ai.agent_tool_intents WHERE run_id=wante"
    "d_run)\n   OR EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observ"
    "ations WHERE run_id=wanted_run)\n   OR EXISTS(SELECT 1 FROM c"
    "ehub_ai.model_invocations WHERE run_id=wanted_run)\n   OR EXI"
    "STS(SELECT 1 FROM cehub_ai.agent_result_checkpoints WHERE ru"
    "n_id=wanted_run)\n   OR EXISTS(SELECT 1 FROM cehub_ai.agent_r"
    "un_recoveries WHERE run_id=wanted_run));\n$body$;\nREVOKE ALL "
    "ON FUNCTION cehub_ai.event_authorization_history_missing(uui"
    "d) FROM PUBLIC;\n\nCREATE OR REPLACE FUNCTION cehub_ai.event_a"
    "uthorization_is_current(wanted_run uuid)\nRETURNS boolean LAN"
    "GUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catal"
    "og AS $body$\n SELECT NOT EXISTS(SELECT 1 FROM cehub_ai.budge"
    "t_run_links b WHERE b.run_id=wanted_run)\n  OR EXISTS(SELECT "
    "1 FROM cehub_ai.agent_authorizations a\n    JOIN cehub_ai.age"
    "nt_runs r ON r.tenant_id=a.tenant_id AND r.id=a.run_id\n    J"
    "OIN cehub_ai.agent_service_principals p ON p.tenant_id=a.ten"
    "ant_id AND p.id=a.principal_id\n    JOIN cehub_ai.agent_subsc"
    "riptions s ON s.tenant_id=p.tenant_id AND s.id=p.subscriptio"
    "n_id\n    WHERE a.run_id=wanted_run AND a.expires_at>clock_ti"
    "mestamp()\n      AND p.revision=a.principal_revision AND p.st"
    "atus='active' AND s.status='active'\n      AND r.subscription"
    "_id=s.id AND r.agent_key=s.agent_key\n      AND a.body#>>'{sc"
    "ope,ref_id}'=r.project_id::text);\n$body$;\nREVOKE ALL ON FUNC"
    "TION cehub_ai.event_authorization_is_current(uuid) FROM PUBL"
    "IC;\n\nCREATE OR REPLACE FUNCTION cehub_ai.issue_event_authori"
    "zation(wanted_run uuid,wanted_token uuid)\nRETURNS void LANGU"
    "AGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $"
    "body$\nDECLARE r cehub_ai.agent_runs%ROWTYPE;s cehub_ai.agent"
    "_subscriptions%ROWTYPE;\n p cehub_ai.agent_service_principals"
    "%ROWTYPE;lid uuid;deadline timestamptz;\n auth_id uuid:=gen_r"
    "andom_uuid();stamp timestamptz:=clock_timestamp();body jsonb"
    ";\n actor uuid; actor_count bigint; project_source jsonb; sub"
    "scription_source jsonb;\nBEGIN\n SELECT * INTO r FROM cehub_ai"
    ".agent_runs WHERE id=wanted_run FOR UPDATE;\n IF NOT FOUND OR"
    " NOT cehub_ai.agent_base_lease_is_current(r.id,wanted_token)"
    " THEN\n  RAISE EXCEPTION 'Agent authorization lease is invali"
    "d' USING ERRCODE='42501';\n END IF;\n SELECT l.id,least(l.abso"
    "lute_deadline,r.dispatch_deadline) INTO lid,deadline\n  FROM "
    "cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links b\n"
    "   ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id WHERE b."
    "run_id=r.id AND b.tenant_id=r.tenant_id;\n IF lid IS NULL THE"
    "N RETURN; END IF;\n IF EXISTS(SELECT 1 FROM cehub_ai.agent_au"
    "thorizations\n   WHERE run_id=r.id AND tenant_id=r.tenant_id)"
    " THEN\n  IF NOT cehub_ai.event_authorization_is_current(r.id)"
    " THEN\n   RAISE EXCEPTION 'Agent authorization lease is no lo"
    "nger valid' USING ERRCODE='42501';\n  END IF;\n  RETURN;\n END "
    "IF;\n IF cehub_ai.event_authorization_history_missing(r.id) T"
    "HEN\n  RAISE EXCEPTION 'Agent authorization lease history is "
    "unavailable' USING ERRCODE='42501';\n END IF;\n SELECT * INTO "
    "s FROM cehub_ai.agent_subscriptions\n  WHERE tenant_id=r.tena"
    "nt_id AND id=r.subscription_id FOR SHARE;\n stamp:=clock_time"
    "stamp();\n IF NOT FOUND OR s.status<>'active' OR s.agent_key<"
    ">r.agent_key OR deadline<=stamp THEN\n  RAISE EXCEPTION 'Agen"
    "t authorization lease policy is invalid' USING ERRCODE='4250"
    "1';\n END IF;\n INSERT INTO cehub_ai.agent_service_principals\n"
    "  VALUES(s.id,s.tenant_id,s.id,'event-agent:' || s.agent_key"
    ",'active',1,stamp,stamp)\n  ON CONFLICT(tenant_id,subscriptio"
    "n_id) DO NOTHING;\n SELECT * INTO p FROM cehub_ai.agent_servi"
    "ce_principals\n  WHERE tenant_id=s.tenant_id AND subscription"
    "_id=s.id;\n SELECT count(DISTINCT a.actor_user_id),(array_agg"
    "(DISTINCT a.actor_user_id)\n   FILTER(WHERE a.actor_user_id I"
    "S NOT NULL))[1] INTO actor_count,actor\n  FROM cehub_audit.au"
    "dit_log a JOIN cehub_event.events e\n   ON e.tenant_id=a.tena"
    "nt_id AND e.event_id=a.event_id\n  WHERE e.id=r.last_event_ro"
    "w_id AND e.tenant_id=r.tenant_id AND a.project_id=r.project_"
    "id;\n IF actor_count<>1 THEN actor:=NULL; END IF;\n project_so"
    "urce:=jsonb_build_object('tenant_id',r.tenant_id,'project_id"
    "',r.project_id,\n  'kind','project','ref_id',r.project_id,'as"
    "_of',stamp,'digest',\n  encode(sha256(convert_to(jsonb_build_"
    "object('tenant_id',r.tenant_id,'id',r.project_id)::text,\n   "
    " 'UTF8')),'hex'));\n subscription_source:=jsonb_build_object("
    "'tenant_id',r.tenant_id,'kind','agent_subscription',\n  'ref_"
    "id',s.id,'as_of',stamp,'digest',encode(sha256(convert_to(jso"
    "nb_build_object(\n    'id',s.id,'tenant_id',s.tenant_id,'agen"
    "t_key',s.agent_key,'principal_revision',p.revision)::text,\n "
    "   'UTF8')),'hex'));\n body:=jsonb_build_object('schema_versi"
    "on',1,'id',auth_id,'tenant_id',r.tenant_id,\n  'scope',jsonb_"
    "build_object('kind','project','ref_id',r.project_id),'versio"
    "n',1,\n  'owner_user_id',NULL,'sources',jsonb_build_array(pro"
    "ject_source,subscription_source),\n  'run_id',r.id,'lineage_i"
    "d',lid,'principal_kind','service','principal_id',p.id,\n  'tr"
    "igger_actor_user_id',actor,'delegation_id',NULL,'policy_vers"
    "ion','event-service-project.v1',\n  'purpose','event_assessme"
    "nt','issued_at',stamp,'expires_at',deadline,\n  'capability_v"
    "ersion',r.agent_key || '.event.v1','toolset_version','intern"
    "al-read-tools.v1');\n INSERT INTO cehub_ai.agent_authorizatio"
    "ns VALUES(auth_id,r.tenant_id,r.id,lid,p.id,p.revision,\n  bo"
    "dy,stamp,deadline);\nEND $body$;\nREVOKE ALL ON FUNCTION cehub"
    "_ai.issue_event_authorization(uuid,uuid) FROM PUBLIC;\n\nCREAT"
    "E OR REPLACE FUNCTION cehub_ai.read_agent_authorization()\nRE"
    "TURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET s"
    "earch_path=pg_catalog AS $body$\nDECLARE rid uuid:=nullif(cur"
    "rent_setting('pdos.agent_run_id',true),'')::uuid;body jsonb;"
    "\n token uuid:=nullif(current_setting('pdos.agent_lease_token"
    "',true),'')::uuid;\nBEGIN\n IF NOT cehub_ai.agent_lease_is_cur"
    "rent(rid,token) THEN\n  RAISE EXCEPTION 'Agent authorization "
    "lease is invalid' USING ERRCODE='42501';\n END IF;\n SELECT a."
    "body INTO body FROM cehub_ai.agent_authorizations a WHERE ru"
    "n_id=rid;\n RETURN body;\nEND $body$;\nREVOKE ALL ON FUNCTION c"
    "ehub_ai.read_agent_authorization() FROM PUBLIC;\n\nCREATE OR R"
    "EPLACE FUNCTION cehub_ai.attach_event_authorization()\nRETURN"
    "S trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path="
    "pg_catalog AS $body$\nDECLARE aid uuid;\nBEGIN\n SELECT id INTO"
    " aid FROM cehub_ai.agent_authorizations\n  WHERE tenant_id=NE"
    "W.tenant_id AND run_id=NEW.run_id;\n IF NOT cehub_ai.event_au"
    "thorization_is_current(NEW.run_id)\n   OR NEW.authorization_i"
    "d IS NOT NULL AND NEW.authorization_id IS DISTINCT FROM aid "
    "THEN\n  RAISE EXCEPTION 'Agent receipt authorization lease is"
    " invalid' USING ERRCODE='42501';\n END IF;\n NEW.authorization"
    "_id:=aid;\n RETURN NEW;\nEND $body$;\nREVOKE ALL ON FUNCTION ce"
    "hub_ai.attach_event_authorization() FROM PUBLIC;\n\nCREATE OR "
    "REPLACE FUNCTION cehub_ai.agent_authorized_project_allows(\n "
    "wanted_tenant uuid,wanted_project uuid\n) RETURNS boolean LAN"
    "GUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catal"
    "og AS $body$\n SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_run"
    "s r\n  WHERE r.id=nullif(current_setting('pdos.agent_run_id',"
    "true),'')::uuid\n   AND r.tenant_id=wanted_tenant\n  AND cehub"
    "_ai.agent_lease_is_current(r.id,\n    nullif(current_setting("
    "'pdos.agent_lease_token',true),'')::uuid)\n  AND (NOT EXISTS("
    "SELECT 1 FROM cehub_ai.budget_run_links b WHERE b.run_id=r.i"
    "d)\n       OR r.project_id=wanted_project));\n$body$;\nREVOKE A"
    "LL ON FUNCTION cehub_ai.agent_authorized_project_allows(uuid"
    ",uuid) FROM PUBLIC;\n"
)

# Immutable function snapshots are inserted below.

OLD_LEASE = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
    wanted_run uuid, wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs AS run
        WHERE run.id = wanted_run AND run.status = 'running'
          AND run.run_context->>'_lease_token' = wanted_token::text
          AND nullif(run.run_context->>'_lease_expires_at', '')::timestamptz > clock_timestamp()
          AND (run.dispatch_deadline IS NULL OR run.dispatch_deadline > clock_timestamp())
    )
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_lease_is_current(uuid, uuid) FROM PUBLIC;
"""

BASE_LEASE = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_base_lease_is_current(
    wanted_run uuid, wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs AS run
        WHERE run.id = wanted_run AND run.status = 'running'
          AND run.run_context->>'_lease_token' = wanted_token::text
          AND nullif(run.run_context->>'_lease_expires_at', '')::timestamptz > clock_timestamp()
          AND (run.dispatch_deadline IS NULL OR run.dispatch_deadline > clock_timestamp())
    )
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_base_lease_is_current(uuid, uuid) FROM PUBLIC;
"""

LEASE = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
 wanted_run uuid,wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT cehub_ai.agent_base_lease_is_current(wanted_run,wanted_token)
    AND cehub_ai.event_authorization_is_current(wanted_run);
$body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_lease_is_current(uuid,uuid) FROM PUBLIC;

"""

OLD_CLAIM = r"""
CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
    claimed_at timestamptz
) RETURNS TABLE (
    id uuid,
    tenant_id uuid,
    project_id uuid,
    subscription_id uuid,
    agent_key varchar,
    status varchar,
    window_started_at timestamptz,
    window_ended_at timestamptz,
    first_event_row_id bigint,
    last_event_row_id bigint,
    event_count integer,
    event_row_ids jsonb,
    lease_token uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    claimed_run cehub_ai.agent_runs%ROWTYPE;
    generated_lease uuid := gen_random_uuid();
BEGIN
    PERFORM cehub_ai.expire_queued_dispatch_runs(1000);
    SELECT * INTO claimed_run
    FROM cehub_ai.agent_runs AS candidate
    WHERE candidate.status = 'queued' AND candidate.request_id IS NULL
      AND candidate.subscription_id IS NOT NULL
      AND (candidate.dispatch_deadline IS NULL OR candidate.dispatch_deadline > clock_timestamp())
    ORDER BY CASE candidate.dispatch_policy WHEN 'milestone.v1' THEN 0 ELSE 1 END,
      candidate.dispatch_deadline NULLS LAST, candidate.created_at, candidate.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    claimed_at := clock_timestamp();
    UPDATE cehub_ai.agent_runs AS target
    SET status = 'running',
        started_at = claimed_at,
        run_context = target.run_context || jsonb_build_object(
            '_lease_token', generated_lease::text,
            '_lease_expires_at',
            least(claimed_at + interval '60 seconds', claimed_run.dispatch_deadline),
            '_lease_renewed_at', claimed_at
        ),
        updated_at = claimed_at
    WHERE target.id = claimed_run.id
    RETURNING * INTO claimed_run;

    RETURN QUERY SELECT
        claimed_run.id,
        claimed_run.tenant_id,
        claimed_run.project_id,
        claimed_run.subscription_id,
        claimed_run.agent_key,
        claimed_run.status,
        claimed_run.window_started_at,
        claimed_run.window_ended_at,
        claimed_run.first_event_row_id,
        claimed_run.last_event_row_id,
        claimed_run.event_count,
        claimed_run.event_row_ids,
        generated_lease;
END
$function$;
"""

CLAIM = r"""
CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
    claimed_at timestamptz
) RETURNS TABLE (
    id uuid,
    tenant_id uuid,
    project_id uuid,
    subscription_id uuid,
    agent_key varchar,
    status varchar,
    window_started_at timestamptz,
    window_ended_at timestamptz,
    first_event_row_id bigint,
    last_event_row_id bigint,
    event_count integer,
    event_row_ids jsonb,
    lease_token uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    claimed_run cehub_ai.agent_runs%ROWTYPE;
    generated_lease uuid := gen_random_uuid();
BEGIN
    PERFORM cehub_ai.expire_queued_dispatch_runs(1000);
    SELECT * INTO claimed_run
    FROM cehub_ai.agent_runs AS candidate
    WHERE candidate.status = 'queued' AND candidate.request_id IS NULL
      AND candidate.subscription_id IS NOT NULL
      AND (candidate.dispatch_deadline IS NULL OR candidate.dispatch_deadline > clock_timestamp())
    ORDER BY CASE candidate.dispatch_policy WHEN 'milestone.v1' THEN 0 ELSE 1 END,
      candidate.dispatch_deadline NULLS LAST, candidate.created_at, candidate.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    claimed_at := clock_timestamp();
    UPDATE cehub_ai.agent_runs AS target
    SET status = 'running',
        started_at = claimed_at,
        run_context = target.run_context || jsonb_build_object(
            '_lease_token', generated_lease::text,
            '_lease_expires_at',
            least(claimed_at + interval '60 seconds', claimed_run.dispatch_deadline),
            '_lease_renewed_at', claimed_at
        ),
        updated_at = claimed_at
    WHERE target.id = claimed_run.id
    RETURNING * INTO claimed_run;

    PERFORM cehub_ai.issue_event_authorization(claimed_run.id,generated_lease);

    RETURN QUERY SELECT
        claimed_run.id,
        claimed_run.tenant_id,
        claimed_run.project_id,
        claimed_run.subscription_id,
        claimed_run.agent_key,
        claimed_run.status,
        claimed_run.window_started_at,
        claimed_run.window_ended_at,
        claimed_run.first_event_row_id,
        claimed_run.last_event_row_id,
        claimed_run.event_count,
        claimed_run.event_row_ids,
        generated_lease;
END
$function$;
"""

OLD_EXPIRY = r"""
CREATE OR REPLACE FUNCTION cehub_ai.expire_queued_dispatch_runs(batch_limit integer)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE count_expired integer;
BEGIN
 IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
  RAISE EXCEPTION 'invalid expiry batch size' USING ERRCODE='22023';
 END IF;
 WITH due AS (SELECT id FROM cehub_ai.agent_runs
   WHERE status IN ('debouncing','queued') AND dispatch_deadline <= clock_timestamp()
   ORDER BY dispatch_deadline,id LIMIT batch_limit FOR UPDATE SKIP LOCKED)
 UPDATE cehub_ai.agent_runs r SET status='failed',error_code='AGENT_TRIGGER_DEADLINE_EXCEEDED',
   completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM due WHERE due.id=r.id;
 GET DIAGNOSTICS count_expired=ROW_COUNT;
 RETURN count_expired;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) FROM PUBLIC;

"""

EXPIRY = r"""
CREATE OR REPLACE FUNCTION cehub_ai.expire_queued_dispatch_runs(batch_limit integer)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE count_expired integer;
BEGIN
 IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
  RAISE EXCEPTION 'invalid expiry batch size' USING ERRCODE='22023';
 END IF;
 WITH due AS (SELECT r.id,CASE
    WHEN r.dispatch_deadline<=clock_timestamp() THEN 'AGENT_TRIGGER_DEADLINE_EXCEEDED'
    WHEN EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b JOIN cehub_ai.budget_lineages l
      ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id WHERE b.run_id=r.id
       AND l.absolute_deadline<=clock_timestamp()) THEN 'BUDGET_LINEAGE_EXPIRED'
    ELSE 'AGENT_AUTHORIZATION_CHANGED' END AS reason
   FROM cehub_ai.agent_runs r WHERE r.status IN ('debouncing','queued')
    AND r.request_id IS NULL AND r.subscription_id IS NOT NULL AND (
     cehub_ai.event_authorization_history_missing(r.id) OR
     r.dispatch_deadline<=clock_timestamp()
     OR EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b JOIN cehub_ai.budget_lineages l
       ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id WHERE b.run_id=r.id
        AND (l.absolute_deadline<=clock_timestamp() OR NOT EXISTS(
          SELECT 1 FROM cehub_ai.agent_subscriptions s WHERE s.id=r.subscription_id
           AND s.tenant_id=r.tenant_id AND s.status='active')))
     OR EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations a WHERE a.run_id=r.id
       AND NOT cehub_ai.event_authorization_is_current(r.id)))
   ORDER BY r.dispatch_deadline,r.id LIMIT batch_limit FOR UPDATE OF r SKIP LOCKED)
 UPDATE cehub_ai.agent_runs r SET status='failed',error_code=due.reason,
   completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM due WHERE due.id=r.id;
 GET DIAGNOSTICS count_expired=ROW_COUNT;
 RETURN count_expired;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) FROM PUBLIC;

"""

OLD_RECOVER = r"""
CREATE OR REPLACE FUNCTION cehub_ai.recover_expired_agent_runs(batch_limit integer)
RETURNS TABLE(run_id uuid,action text,reason text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
    receipt uuid; result_action text; stop_reason text; attempts bigint; attempt_limit integer;
    expired_token uuid; observed_at timestamptz;
BEGIN
    IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
        RAISE EXCEPTION 'invalid recovery batch size' USING ERRCODE='22023';
    END IF;
    FOR r IN SELECT * FROM cehub_ai.agent_runs
      WHERE status='running' AND subscription_id IS NOT NULL AND request_id IS NULL
        AND nullif(run_context->>'_lease_expires_at','')::timestamptz <= clock_timestamp()
        AND nullif(run_context->>'_lease_token','') IS NOT NULL
      ORDER BY updated_at,id LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
        observed_at := clock_timestamp();
        expired_token := (r.run_context->>'_lease_token')::uuid;
        IF cehub_ai.agent_lease_is_current(r.id,expired_token) THEN CONTINUE; END IF;
        SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id;
        SELECT f.id INTO receipt FROM cehub_ai.findings f
          WHERE f.tenant_id=r.tenant_id AND f.run_id=r.id ORDER BY f.created_at,f.id LIMIT 1;
        result_action := 'stopped'; stop_reason := NULL;
        IF receipt IS NOT NULL THEN
            result_action := 'receipt_completed';
        ELSIF EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(e.session_id) e.state FROM cehub_ai.model_call_events e
            JOIN cehub_ai.model_call_sessions s ON s.id=e.session_id
            WHERE s.tenant_id=r.tenant_id AND s.run_id=r.id
            ORDER BY e.session_id,e.revision DESC) latest WHERE state IN ('open','unknown'))
          OR EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(j.attempt_id) j.held_tokens FROM cehub_ai.budget_journal j
            WHERE j.tenant_id=r.tenant_id AND j.run_id=r.id
            ORDER BY j.attempt_id,j.revision DESC) latest WHERE held_tokens>0) THEN
            stop_reason := 'AGENT_RECOVERY_RECEIPT_UNKNOWN';
        ELSIF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
            WHERE d.tenant_id=r.tenant_id AND d.run_id=r.id
              AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations o
                WHERE o.tenant_id=d.tenant_id AND o.run_id=d.run_id
                  AND o.tool_intent_id=d.intent_id)) THEN
            stop_reason := 'AGENT_TOOL_RECEIPT_UNKNOWN';
        ELSIF r.dispatch_deadline <= clock_timestamp() THEN
            stop_reason := 'AGENT_TRIGGER_DEADLINE_EXCEEDED';
        ELSIF checkpoint.id IS NULL THEN
            IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents i
                WHERE i.tenant_id=r.tenant_id AND i.run_id=r.id
                  AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
                    WHERE d.intent_id=i.id)) THEN
                stop_reason := 'AGENT_TOOL_NOT_DISPATCHED';
            ELSE
                stop_reason := 'AGENT_CHECKPOINT_MISSING';
            END IF;
        ELSIF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_subscriptions
            WHERE id=r.subscription_id AND tenant_id=r.tenant_id AND status='active') THEN
            stop_reason := 'AGENT_RECOVERY_SUBSCRIPTION_PAUSED';
        ELSE
            SELECT count(*) INTO attempts FROM cehub_ai.agent_run_recoveries h
              WHERE h.tenant_id=r.tenant_id AND h.run_id=r.id AND h.action='resume_queued';
            SELECT (l.profile->>'transient_attempt_limit')::integer INTO attempt_limit
              FROM cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links b
                ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
              WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
            IF attempts >= coalesce(attempt_limit,2)-1 THEN
                stop_reason := 'AGENT_RECOVERY_ATTEMPT_LIMIT';
            ELSE
                IF attempt_limit IS NOT NULL THEN
                    BEGIN
                        PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
                    EXCEPTION WHEN invalid_parameter_value THEN
                        GET STACKED DIAGNOSTICS stop_reason = MESSAGE_TEXT;
                    END;
                END IF;
                IF stop_reason IS NULL THEN result_action := 'resume_queued'; END IF;
            END IF;
        END IF;
        INSERT INTO cehub_ai.agent_run_recoveries VALUES(gen_random_uuid(),r.tenant_id,r.id,
            checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at);
        IF result_action='resume_queued' THEN
            UPDATE cehub_ai.agent_runs SET status='queued',started_at=NULL,completed_at=NULL,
              error_code=NULL,updated_at=observed_at,
              run_context=(run_context - '_lease_token' - '_lease_expires_at' - '_lease_renewed_at')
                || jsonb_build_object('_resume_checkpoint_id',checkpoint.id)
              WHERE id=r.id;
        ELSE
            UPDATE cehub_ai.agent_runs SET
              status=CASE WHEN result_action='receipt_completed' THEN 'succeeded' ELSE 'failed' END,
              error_code=stop_reason,completed_at=observed_at,updated_at=observed_at WHERE id=r.id;
        END IF;
        RETURN QUERY SELECT r.id,result_action,stop_reason;
    END LOOP;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.recover_expired_agent_runs(integer) FROM PUBLIC;

"""

RECOVER = r"""
CREATE OR REPLACE FUNCTION cehub_ai.recover_expired_agent_runs(batch_limit integer)
RETURNS TABLE(run_id uuid,action text,reason text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
    receipt uuid; result_action text; stop_reason text; attempts bigint; attempt_limit integer;
    expired_token uuid; observed_at timestamptz;
BEGIN
    IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
        RAISE EXCEPTION 'invalid recovery batch size' USING ERRCODE='22023';
    END IF;
    FOR r IN SELECT * FROM cehub_ai.agent_runs
      WHERE status='running' AND subscription_id IS NOT NULL AND request_id IS NULL
        AND (nullif(run_context->>'_lease_expires_at','')::timestamptz <= clock_timestamp()
             OR NOT cehub_ai.event_authorization_is_current(id))
        AND nullif(run_context->>'_lease_token','') IS NOT NULL
      ORDER BY updated_at,id LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
        observed_at := clock_timestamp();
        expired_token := (r.run_context->>'_lease_token')::uuid;
        IF cehub_ai.agent_lease_is_current(r.id,expired_token) THEN CONTINUE; END IF;
        SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id;
        SELECT f.id INTO receipt FROM cehub_ai.findings f
          WHERE f.tenant_id=r.tenant_id AND f.run_id=r.id ORDER BY f.created_at,f.id LIMIT 1;
        result_action := 'stopped'; stop_reason := NULL;
        IF receipt IS NOT NULL THEN
            result_action := 'receipt_completed';
        ELSIF NOT cehub_ai.event_authorization_is_current(r.id)
          AND (r.dispatch_deadline IS NULL OR r.dispatch_deadline>clock_timestamp())
          AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
            JOIN cehub_ai.budget_lineages l ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id
            WHERE b.run_id=r.id AND l.absolute_deadline<=clock_timestamp()) THEN
            stop_reason := 'AGENT_AUTHORIZATION_CHANGED';
        ELSIF EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(e.session_id) e.state FROM cehub_ai.model_call_events e
            JOIN cehub_ai.model_call_sessions s ON s.id=e.session_id
            WHERE s.tenant_id=r.tenant_id AND s.run_id=r.id
            ORDER BY e.session_id,e.revision DESC) latest WHERE state IN ('open','unknown'))
          OR EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(j.attempt_id) j.held_tokens FROM cehub_ai.budget_journal j
            WHERE j.tenant_id=r.tenant_id AND j.run_id=r.id
            ORDER BY j.attempt_id,j.revision DESC) latest WHERE held_tokens>0) THEN
            stop_reason := 'AGENT_RECOVERY_RECEIPT_UNKNOWN';
        ELSIF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
            WHERE d.tenant_id=r.tenant_id AND d.run_id=r.id
              AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations o
                WHERE o.tenant_id=d.tenant_id AND o.run_id=d.run_id
                  AND o.tool_intent_id=d.intent_id)) THEN
            stop_reason := 'AGENT_TOOL_RECEIPT_UNKNOWN';
        ELSIF r.dispatch_deadline <= clock_timestamp() THEN
            stop_reason := 'AGENT_TRIGGER_DEADLINE_EXCEEDED';
        ELSIF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
            JOIN cehub_ai.budget_lineages l ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id
            WHERE b.run_id=r.id AND l.absolute_deadline<=clock_timestamp()) THEN
            stop_reason := 'BUDGET_LINEAGE_EXPIRED';
        ELSIF checkpoint.id IS NULL THEN
            IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents i
                WHERE i.tenant_id=r.tenant_id AND i.run_id=r.id
                  AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
                    WHERE d.intent_id=i.id)) THEN
                stop_reason := 'AGENT_TOOL_NOT_DISPATCHED';
            ELSE
                stop_reason := 'AGENT_CHECKPOINT_MISSING';
            END IF;
        ELSIF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_subscriptions
            WHERE id=r.subscription_id AND tenant_id=r.tenant_id AND status='active') THEN
            stop_reason := 'AGENT_RECOVERY_SUBSCRIPTION_PAUSED';
        ELSE
            SELECT count(*) INTO attempts FROM cehub_ai.agent_run_recoveries h
              WHERE h.tenant_id=r.tenant_id AND h.run_id=r.id AND h.action='resume_queued';
            SELECT (l.profile->>'transient_attempt_limit')::integer INTO attempt_limit
              FROM cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links b
                ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
              WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
            IF attempts >= coalesce(attempt_limit,2)-1 THEN
                stop_reason := 'AGENT_RECOVERY_ATTEMPT_LIMIT';
            ELSE
                IF attempt_limit IS NOT NULL THEN
                    BEGIN
                        PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
                    EXCEPTION WHEN invalid_parameter_value THEN
                        GET STACKED DIAGNOSTICS stop_reason = MESSAGE_TEXT;
                    END;
                END IF;
                IF stop_reason IS NULL THEN result_action := 'resume_queued'; END IF;
            END IF;
        END IF;
        INSERT INTO cehub_ai.agent_run_recoveries VALUES(gen_random_uuid(),r.tenant_id,r.id,
            checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at);
        IF result_action='resume_queued' THEN
            UPDATE cehub_ai.agent_runs SET status='queued',started_at=NULL,completed_at=NULL,
              error_code=NULL,updated_at=observed_at,
              run_context=(run_context - '_lease_token' - '_lease_expires_at' - '_lease_renewed_at')
                || jsonb_build_object('_resume_checkpoint_id',checkpoint.id)
              WHERE id=r.id;
        ELSE
            UPDATE cehub_ai.agent_runs SET
              status=CASE WHEN result_action='receipt_completed' THEN 'succeeded' ELSE 'failed' END,
              error_code=stop_reason,completed_at=observed_at,updated_at=observed_at WHERE id=r.id;
        END IF;
        RETURN QUERY SELECT r.id,result_action,stop_reason;
    END LOOP;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.recover_expired_agent_runs(integer) FROM PUBLIC;

"""

OLD_VIEWS = r"""
CREATE OR REPLACE VIEW cehub_ai.agent_supplier_delay_projection
WITH (security_barrier = true)
AS
SELECT
    event.id AS event_row_id,
    event.tenant_id,
    event.project_id,
    project.code AS project_code,
    supplier.code AS supplier_code,
    supplier.name AS supplier_name,
    event.payload->>'expected_date' AS expected_date,
    event.payload->>'reported_date' AS reported_date,
    event.timestamp AS observed_at
FROM cehub_event.events AS event
JOIN cehub_project.projects AS project
  ON project.tenant_id = event.tenant_id
 AND project.id = event.project_id
JOIN cehub_supplier.suppliers AS supplier
  ON supplier.tenant_id = event.tenant_id
 AND supplier.id::text = event.payload->>'supplier_id'
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        event.tenant_id,
        'supplier_intelligence'
    )
  AND event.event_type = 'SUPPLIER_DELAY_REPORTED';

CREATE OR REPLACE VIEW cehub_ai.agent_portfolio_projection
WITH (security_barrier = true)
AS
SELECT
    project.tenant_id,
    project.id AS project_id,
    project.code,
    project.name,
    project.status,
    coalesce(stage.code, 'unassigned') AS stage_code,
    (
        SELECT count(*) FROM cehub_project.issues AS issue
        WHERE issue.tenant_id = project.tenant_id
          AND issue.project_id = project.id
          AND issue.status <> 'closed'
    ) AS open_issue_count,
    (
        SELECT count(*) FROM cehub_project.risks AS risk
        WHERE risk.tenant_id = project.tenant_id
          AND risk.project_id = project.id
          AND risk.status <> 'closed'
    ) AS open_risk_count,
    (
        SELECT count(*) FROM cehub_project.tasks AS task
        WHERE task.tenant_id = project.tenant_id
          AND task.project_id = project.id
          AND task.due_date < CURRENT_DATE
          AND task.status NOT IN ('done', 'skipped')
    ) AS overdue_task_count,
    (
        SELECT count(*) FROM cehub_project.gates AS gate
        WHERE gate.tenant_id = project.tenant_id
          AND gate.project_id = project.id
          AND gate.status IN ('preparing', 'reviewing')
    ) AS pending_gate_count,
    project.updated_at AS observed_at
FROM cehub_project.projects AS project
LEFT JOIN cehub_project.stages AS stage
  ON stage.tenant_id = project.tenant_id
 AND stage.workflow_id = project.workflow_id
 AND stage.id = project.current_stage_id
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        project.tenant_id,
        'executive_intelligence'
    )
  AND project.status IN ('approved', 'active', 'on_hold');
"""

VIEWS = r"""
CREATE OR REPLACE VIEW cehub_ai.agent_supplier_delay_projection
WITH (security_barrier = true)
AS
SELECT
    event.id AS event_row_id,
    event.tenant_id,
    event.project_id,
    project.code AS project_code,
    supplier.code AS supplier_code,
    supplier.name AS supplier_name,
    event.payload->>'expected_date' AS expected_date,
    event.payload->>'reported_date' AS reported_date,
    event.timestamp AS observed_at
FROM cehub_event.events AS event
JOIN cehub_project.projects AS project
  ON project.tenant_id = event.tenant_id
 AND project.id = event.project_id
JOIN cehub_supplier.suppliers AS supplier
  ON supplier.tenant_id = event.tenant_id
 AND supplier.id::text = event.payload->>'supplier_id'
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        event.tenant_id,
        'supplier_intelligence'
    )
  AND cehub_ai.agent_authorized_project_allows(event.tenant_id,event.project_id)
  AND event.event_type = 'SUPPLIER_DELAY_REPORTED';

CREATE OR REPLACE VIEW cehub_ai.agent_portfolio_projection
WITH (security_barrier = true)
AS
SELECT
    project.tenant_id,
    project.id AS project_id,
    project.code,
    project.name,
    project.status,
    coalesce(stage.code, 'unassigned') AS stage_code,
    (
        SELECT count(*) FROM cehub_project.issues AS issue
        WHERE issue.tenant_id = project.tenant_id
          AND issue.project_id = project.id
          AND issue.status <> 'closed'
    ) AS open_issue_count,
    (
        SELECT count(*) FROM cehub_project.risks AS risk
        WHERE risk.tenant_id = project.tenant_id
          AND risk.project_id = project.id
          AND risk.status <> 'closed'
    ) AS open_risk_count,
    (
        SELECT count(*) FROM cehub_project.tasks AS task
        WHERE task.tenant_id = project.tenant_id
          AND task.project_id = project.id
          AND task.due_date < CURRENT_DATE
          AND task.status NOT IN ('done', 'skipped')
    ) AS overdue_task_count,
    (
        SELECT count(*) FROM cehub_project.gates AS gate
        WHERE gate.tenant_id = project.tenant_id
          AND gate.project_id = project.id
          AND gate.status IN ('preparing', 'reviewing')
    ) AS pending_gate_count,
    project.updated_at AS observed_at
FROM cehub_project.projects AS project
LEFT JOIN cehub_project.stages AS stage
  ON stage.tenant_id = project.tenant_id
 AND stage.workflow_id = project.workflow_id
 AND stage.id = project.current_stage_id
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        project.tenant_id,
        'executive_intelligence'
    )
  AND cehub_ai.agent_authorized_project_allows(project.tenant_id,project.id)
  AND project.status IN ('approved', 'active', 'on_hold');
"""

OLD_LIFECYCLE = r"""
ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_lifecycle_consistent,
 ADD CONSTRAINT ck_agent_runs_lifecycle_consistent CHECK (
  (status IN ('debouncing','queued') AND started_at IS NULL AND completed_at IS NULL) OR
  (status='running' AND started_at IS NOT NULL AND completed_at IS NULL) OR
  (status IN ('succeeded','degraded','failed') AND started_at IS NOT NULL
    AND completed_at IS NOT NULL) OR
  (status='failed' AND started_at IS NULL AND completed_at IS NOT NULL
    AND dispatch_policy='milestone.v1' AND dispatch_deadline IS NOT NULL
    AND error_code='AGENT_TRIGGER_DEADLINE_EXCEEDED') IS TRUE);
"""

LIFECYCLE = r"""
ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_lifecycle_consistent,
 ADD CONSTRAINT ck_agent_runs_lifecycle_consistent CHECK (
  (status IN ('debouncing','queued') AND started_at IS NULL AND completed_at IS NULL) OR
  (status='running' AND started_at IS NOT NULL AND completed_at IS NULL) OR
  (status IN ('succeeded','degraded','failed') AND started_at IS NOT NULL
    AND completed_at IS NOT NULL) OR
  (status='failed' AND started_at IS NULL AND completed_at IS NOT NULL
    AND ((dispatch_policy='milestone.v1' AND dispatch_deadline IS NOT NULL
      AND error_code='AGENT_TRIGGER_DEADLINE_EXCEEDED')
      OR error_code IN ('BUDGET_LINEAGE_EXPIRED','AGENT_AUTHORIZATION_CHANGED'))) IS TRUE);
"""


def _replace_existing_views(sql: str) -> None:
    # Projection installation belongs to the DBA template; migrate installed views only.
    for definition in sql.split("CREATE OR REPLACE VIEW ")[1:]:
        name = definition.split()[0]
        if op.get_bind().scalar(text("SELECT to_regclass(:name)"), {"name": name}):
            op.execute("CREATE OR REPLACE VIEW " + definition)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(BASE_LEASE)
    op.execute(AUTHORITY)
    op.execute(LEASE)
    op.execute(CLAIM)
    op.execute(EXPIRY)
    op.execute(RECOVER)
    _replace_existing_views(VIEWS)
    op.execute(LIFECYCLE)
    op.execute("""CREATE TRIGGER attach_event_authorization BEFORE INSERT
      ON cehub_ai.agent_tool_observations FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.attach_event_authorization();
      CREATE TRIGGER attach_event_authorization BEFORE INSERT
      ON cehub_ai.agent_context_receipts FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.attach_event_authorization();
      DO $body$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.read_agent_authorization(),
          cehub_ai.agent_authorized_project_allows(uuid,uuid) TO pdos_agent;
      END IF; END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations) THEN
        RAISE EXCEPTION 'cannot remove persistent event authorization history';
      END IF;
    END $body$;""")
    for sql in (OLD_LEASE, OLD_CLAIM, OLD_EXPIRY, OLD_RECOVER, OLD_LIFECYCLE):
        op.execute(sql)
    _replace_existing_views(OLD_VIEWS)
    op.execute("DROP TRIGGER attach_event_authorization ON cehub_ai.agent_tool_observations")
    op.execute("DROP TRIGGER attach_event_authorization ON cehub_ai.agent_context_receipts")
    op.execute("ALTER TABLE cehub_ai.agent_tool_observations DROP COLUMN authorization_id")
    op.execute("ALTER TABLE cehub_ai.agent_context_receipts DROP COLUMN authorization_id")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.read_agent_authorization()")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.agent_authorized_project_allows(uuid,uuid)")
    op.execute("DROP FUNCTION cehub_ai.attach_event_authorization()")
    op.execute("DROP FUNCTION cehub_ai.issue_event_authorization(uuid,uuid)")
    op.execute("DROP FUNCTION cehub_ai.event_authorization_is_current(uuid)")
    op.execute("DROP FUNCTION cehub_ai.event_authorization_history_missing(uuid)")
    op.execute("DROP FUNCTION cehub_ai.agent_base_lease_is_current(uuid,uuid)")
    op.execute("DROP TRIGGER track_service_principal ON cehub_ai.agent_subscriptions")
    op.execute("DROP FUNCTION cehub_ai.track_service_principal()")
    op.execute("DROP TABLE cehub_ai.agent_authorizations")
    op.execute("DROP TABLE cehub_ai.agent_service_principals")
    op.execute("DROP FUNCTION cehub_ai.protect_service_principal()")
