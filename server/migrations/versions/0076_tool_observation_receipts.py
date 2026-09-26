"""Persist lease-scoped tool observations and the actual context consumed by a model call."""

from collections.abc import Sequence

from alembic import op

revision: str = "0076_tool_observation_receipts"
down_revision: str | Sequence[str] | None = "0075_event_trigger_scheduling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE TABLE cehub_ai.agent_tool_observations (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,
 sequence integer NOT NULL,call_key varchar(128) NOT NULL,tool_key varchar(64) NOT NULL,
 input_body jsonb NOT NULL,output_body jsonb NOT NULL,metadata jsonb NOT NULL,
 created_at timestamptz NOT NULL,
 CONSTRAINT uq_tool_observation_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_tool_observation_sequence UNIQUE(tenant_id,run_id,sequence),
 CONSTRAINT uq_tool_observation_call UNIQUE(tenant_id,run_id,call_key),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_tool_observations_shape CHECK(sequence>0 AND btrim(call_key)<>''
  AND btrim(tool_key)<>'' AND jsonb_typeof(input_body)='object'
  AND jsonb_typeof(output_body)='object' AND jsonb_typeof(metadata)='object')
);
CREATE TABLE cehub_ai.agent_context_receipts (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,model_call_id uuid NOT NULL,
 body jsonb NOT NULL,body_sha256 varchar(64) NOT NULL,created_at timestamptz NOT NULL,
 CONSTRAINT uq_context_receipt_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_context_receipt_call UNIQUE(tenant_id,run_id,model_call_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_context_receipts_shape CHECK(jsonb_typeof(body)='object'
  AND length(body_sha256)=64)
);
CREATE TABLE cehub_ai.agent_context_observations (
 tenant_id uuid NOT NULL,run_id uuid NOT NULL,context_receipt_id uuid NOT NULL,
 observation_id uuid NOT NULL,position integer NOT NULL,
 PRIMARY KEY(context_receipt_id,position),
 CONSTRAINT uq_context_observation_once UNIQUE(context_receipt_id,observation_id),
 FOREIGN KEY(tenant_id,run_id,context_receipt_id)
  REFERENCES cehub_ai.agent_context_receipts(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,observation_id)
  REFERENCES cehub_ai.agent_tool_observations(tenant_id,run_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_context_observations_position CHECK(position>0)
);
ALTER TABLE cehub_ai.model_invocations ADD COLUMN context_receipt_id uuid,
 ADD CONSTRAINT ck_model_invocations_context_run
 CHECK(context_receipt_id IS NULL OR run_id IS NOT NULL),
 ADD CONSTRAINT fk_model_context_receipt FOREIGN KEY(tenant_id,run_id,context_receipt_id)
 REFERENCES cehub_ai.agent_context_receipts(tenant_id,run_id,id) ON DELETE RESTRICT;
CREATE TRIGGER protect_tool_observation BEFORE UPDATE OR DELETE ON cehub_ai.agent_tool_observations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER protect_context_receipt BEFORE UPDATE OR DELETE ON cehub_ai.agent_context_receipts
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER protect_context_observation BEFORE UPDATE OR DELETE
 ON cehub_ai.agent_context_observations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.agent_tool_observations,cehub_ai.agent_context_receipts,
 cehub_ai.agent_context_observations FROM PUBLIC;
"""

PORTS = r"""CREATE OR REPLACE FUNCTION cehub_ai.append_agent_tool_observation(
 wanted_key varchar,wanted_tool varchar,input_text text,output_text text,metadata_text text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_observations%ROWTYPE;
 args jsonb; result jsonb; meta jsonb; observation_id uuid:=gen_random_uuid();
 next_sequence integer;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR input_text IS NULL OR output_text IS NULL OR metadata_text IS NULL
  OR octet_length(input_text)+octet_length(output_text)+octet_length(metadata_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb; result:=output_text::jsonb; meta:=metadata_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object' OR jsonb_typeof(result) IS DISTINCT FROM 'object'
  OR jsonb_typeof(meta) IS DISTINCT FROM 'object'
  OR args->>'project_id' IS DISTINCT FROM r.project_id::text
  OR meta->>'tenant_id' IS DISTINCT FROM r.tenant_id::text
  OR meta->>'run_id' IS DISTINCT FROM r.id::text
  OR jsonb_typeof(meta->'sources') IS DISTINCT FROM 'array'
  OR (meta->>'status' IN ('completed','partial','unavailable','failed','cancelled')) IS NOT TRUE
  OR meta->>'input_digest' !~ '^[a-f0-9]{64}$' OR meta->>'input_digest' IS NULL
  OR meta->>'output_digest' !~ '^[a-f0-9]{64}$' OR meta->>'output_digest' IS NULL THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(meta->'sources') s
   WHERE s->>'tenant_id' IS DISTINCT FROM r.tenant_id::text) THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_SOURCE_SCOPE' USING ERRCODE='22023';
 END IF;
 meta:=meta || jsonb_build_object(
  'input_digest',encode(sha256(convert_to(args::text,'UTF8')),'hex'),
  'output_digest',encode(sha256(convert_to(result::text,'UTF8')),'hex'));
 SELECT * INTO old FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.tool_key IS DISTINCT FROM wanted_tool OR old.input_body IS DISTINCT FROM args
   OR old.output_body IS DISTINCT FROM result OR
   (old.metadata - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') IS DISTINCT FROM
   (meta - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') OR
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(old.metadata->'sources') s)
   IS DISTINCT FROM
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(meta->'sources') s) THEN
   RAISE EXCEPTION 'AGENT_OBSERVATION_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.metadata;
 END IF;
 SELECT coalesce(max(sequence),0)+1 INTO next_sequence FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 meta:=meta || jsonb_build_object('id',observation_id,'sequence',next_sequence,
                                 'observed_at',clock_timestamp());
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_observations VALUES(observation_id,r.tenant_id,r.id,
  next_sequence,wanted_key,wanted_tool,args,result,meta,clock_timestamp());
 RETURN meta;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.append_agent_tool_observation(varchar,varchar,text,text,text)
 FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.freeze_agent_context_receipt(
 wanted_call uuid,body_text text,observation_ids uuid[]
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; previous cehub_ai.agent_context_receipts%ROWTYPE;
 payload jsonb; receipt_id uuid:=gen_random_uuid(); previous_ids uuid[]; actual_ids uuid[];
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_call IS NULL OR body_text IS NULL OR octet_length(body_text)>262144
  OR observation_ids IS NULL OR coalesce(cardinality(observation_ids),0) NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_INVALID' USING ERRCODE='22023';
 END IF;
 payload:=body_text::jsonb;
 IF payload#>>'{context,project,id}' IS DISTINCT FROM r.project_id::text THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_SCOPE' USING ERRCODE='22023';
 END IF;
 SELECT array_agg(id ORDER BY sequence) INTO actual_ids FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=ANY(observation_ids);
 IF actual_ids IS DISTINCT FROM observation_ids THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_OBSERVATIONS_INVALID' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_receipts
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND model_call_id=wanted_call;
 IF FOUND THEN
  SELECT array_agg(observation_id ORDER BY position) INTO previous_ids
   FROM cehub_ai.agent_context_observations WHERE context_receipt_id=previous.id;
  IF previous.body IS DISTINCT FROM payload OR previous_ids IS DISTINCT FROM observation_ids THEN
   RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN previous.id;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_context_receipts VALUES(receipt_id,r.tenant_id,r.id,wanted_call,payload,
  encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
 INSERT INTO cehub_ai.agent_context_observations
  SELECT r.tenant_id,r.id,receipt_id,value,ordinality
    FROM unnest(observation_ids) WITH ORDINALITY AS ids(value,ordinality);
 RETURN receipt_id;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[]) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_context_receipt(
 wanted_receipt uuid,wanted_call uuid,body_text text
) RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; receipt cehub_ai.agent_context_receipts%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT * INTO receipt FROM cehub_ai.agent_context_receipts
  WHERE id=wanted_receipt AND tenant_id=r.tenant_id AND run_id=r.id AND model_call_id=wanted_call;
 IF NOT FOUND OR receipt.body IS DISTINCT FROM body_text::jsonb
  OR receipt.body_sha256 IS DISTINCT FROM
  encode(sha256(convert_to(receipt.body::text,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_MISMATCH' USING ERRCODE='22023';
 END IF;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_context_receipt(uuid,uuid,text) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(PORTS)
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION
          cehub_ai.append_agent_tool_observation(varchar,varchar,text,text,text),
          cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[]),
          cehub_ai.verify_agent_context_receipt(uuid,uuid,text) TO pdos_agent;
      END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations)
        OR EXISTS(SELECT 1 FROM cehub_ai.agent_context_receipts) THEN
        RAISE EXCEPTION 'cannot remove persistent tool observation history';
      END IF;
    END $body$;""")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.verify_agent_context_receipt(uuid,uuid,text)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[])")
    op.execute(
        "DROP FUNCTION IF EXISTS cehub_ai.append_agent_tool_observation"
        "(varchar,varchar,text,text,text)"
    )
    op.execute(
        "ALTER TABLE cehub_ai.model_invocations DROP CONSTRAINT ck_model_invocations_context_run"
    )
    op.execute("ALTER TABLE cehub_ai.model_invocations DROP COLUMN context_receipt_id")
    op.execute("DROP TABLE cehub_ai.agent_context_observations")
    op.execute("DROP TABLE cehub_ai.agent_context_receipts")
    op.execute("DROP TABLE cehub_ai.agent_tool_observations")
