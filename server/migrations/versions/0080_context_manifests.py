"""Freeze event runtime assets and bind admitted model attempts to context revisions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0080_context_manifests"
down_revision: str | Sequence[str] | None = "0079_event_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
ALTER TABLE cehub_ai.agent_runs ADD COLUMN execution_bundle jsonb,
 ADD CONSTRAINT ck_agent_runs_execution_bundle CHECK(
  execution_bundle IS NULL OR jsonb_typeof(execution_bundle)='object');
ALTER TABLE cehub_ai.budget_journal ADD CONSTRAINT uq_budget_journal_scope
 UNIQUE(tenant_id,run_id,id);
CREATE TABLE cehub_ai.agent_context_manifests (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,authorization_id uuid NOT NULL,
 context_receipt_id uuid NOT NULL,admission_id uuid NOT NULL,attempt_id uuid NOT NULL,
 revision_no integer NOT NULL,parent_revision_id uuid,body jsonb NOT NULL,pins jsonb NOT NULL,
 created_at timestamptz NOT NULL,
 CONSTRAINT uq_context_manifest_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_context_manifest_revision UNIQUE(tenant_id,run_id,revision_no),
 CONSTRAINT uq_context_manifest_attempt UNIQUE(tenant_id,run_id,attempt_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,authorization_id)
  REFERENCES cehub_ai.agent_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,context_receipt_id)
  REFERENCES cehub_ai.agent_context_receipts(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,admission_id)
  REFERENCES cehub_ai.budget_journal(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,parent_revision_id)
  REFERENCES cehub_ai.agent_context_manifests(tenant_id,run_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_context_manifests_revision CHECK(
  revision_no>0 AND (revision_no=1)=(parent_revision_id IS NULL)),
 CONSTRAINT ck_agent_context_manifests_body CHECK(
  jsonb_typeof(body)='object' AND jsonb_typeof(pins)='object')
);
CREATE TRIGGER protect_context_manifest BEFORE UPDATE OR DELETE ON cehub_ai.agent_context_manifests
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.agent_context_manifests FROM PUBLIC;

CREATE FUNCTION cehub_ai.protect_execution_bundle() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='UPDATE' AND OLD.execution_bundle IS NOT NULL
  AND NEW.execution_bundle IS DISTINCT FROM OLD.execution_bundle THEN
  RAISE EXCEPTION 'event execution bundle is immutable' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_execution_bundle() FROM PUBLIC;
CREATE TRIGGER protect_execution_bundle BEFORE UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_execution_bundle();
"""

PORTS = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_manifest_sources_are_current(
 wanted_tenant uuid,wanted_run uuid,wanted_receipt uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE pid uuid;
BEGIN
 SELECT project_id INTO pid FROM cehub_ai.agent_runs
  WHERE tenant_id=wanted_tenant AND id=wanted_run;
 IF NOT FOUND OR NOT cehub_ai.event_authorization_is_current(wanted_run) THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(coalesce(o.output_body->'items','[]'::jsonb)) item
  WHERE link.tenant_id=wanted_tenant AND link.run_id=wanted_run
   AND link.context_receipt_id=wanted_receipt AND o.tool_key='search_memory' AND NOT EXISTS(
    SELECT 1 FROM cehub_memory.memories memory JOIN cehub_memory.memory_embeddings embedding
     ON embedding.tenant_id=memory.tenant_id AND embedding.project_id=memory.project_id
      AND embedding.memory_id=memory.id AND embedding.content_sha256=memory.content_sha256
     WHERE memory.tenant_id=wanted_tenant AND memory.project_id=pid AND memory.status='verified'
      AND memory.id::text=item->>'memory_id' AND memory.content_sha256=item->>'content_sha256'));
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_manifest_sources_are_current(uuid,uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_context_sources(wanted_receipt uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context source lease is invalid' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_receipts
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=wanted_receipt) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_RECEIPT_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=r.id)
  AND NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,wanted_receipt) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN true;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_context_sources(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_manifest_sources()
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest source lease is invalid' USING ERRCODE='42501';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_context_manifests m
  WHERE m.tenant_id=r.tenant_id AND m.run_id=r.id
   AND EXISTS(SELECT 1 FROM cehub_ai.budget_journal j
    WHERE j.tenant_id=m.tenant_id AND j.run_id=m.run_id AND j.attempt_id=m.attempt_id
     AND j.dispatched_at IS NOT NULL)
   AND NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,m.context_receipt_id)) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN true;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_manifest_sources() FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.bind_agent_runtime_bundle(body_text text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; supplied jsonb;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent bundle lease is invalid' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=r.id) THEN
  RETURN NULL;
 END IF;
 IF body_text IS NULL OR octet_length(body_text)>524288 THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_INVALID' USING ERRCODE='22023';
 END IF;
 supplied:=body_text::jsonb;
 IF supplied->>'version' IS DISTINCT FROM 'event-runtime-bundle.v1'
  OR supplied#>>'{compiled,agent_key}' IS DISTINCT FROM r.agent_key
  OR (supplied->>'release_bundle_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'capability_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'toolset_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'projection_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'policy_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_INVALID' USING ERRCODE='22023';
 END IF;
 IF r.execution_bundle IS NOT NULL THEN
  IF r.execution_bundle IS DISTINCT FROM supplied THEN
   RAISE EXCEPTION 'AGENT_BUNDLE_VERSION_CHANGED' USING ERRCODE='22023';
  END IF;
  RETURN r.execution_bundle;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents WHERE run_id=r.id)
  OR EXISTS(SELECT 1 FROM cehub_ai.model_invocations WHERE run_id=r.id)
  OR EXISTS(SELECT 1 FROM cehub_ai.agent_result_checkpoints WHERE run_id=r.id) THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_HISTORY_UNAVAILABLE' USING ERRCODE='22023';
 END IF;
 UPDATE cehub_ai.agent_runs SET execution_bundle=supplied WHERE id=r.id;
 RETURN supplied;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.bind_agent_runtime_bundle(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.freeze_agent_context_manifest(
 wanted_receipt uuid,wanted_attempt uuid,pins_text text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;receipt cehub_ai.agent_context_receipts%ROWTYPE;
 admission cehub_ai.budget_journal%ROWTYPE;previous cehub_ai.agent_context_manifests%ROWTYPE;
 first_manifest cehub_ai.agent_context_manifests%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
 aid uuid;mid uuid:=gen_random_uuid();stamp timestamptz:=clock_timestamp();n integer;
 pins jsonb;body jsonb;observations jsonb;sources jsonb;missing jsonb;omissions jsonb;
 has_partial boolean;watermark bigint;model_version text;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT id INTO aid FROM cehub_ai.agent_authorizations WHERE run_id=r.id AND tenant_id=r.tenant_id;
 IF aid IS NULL THEN RETURN NULL; END IF;
 IF r.execution_bundle IS NULL THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_REQUIRED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO receipt FROM cehub_ai.agent_context_receipts
  WHERE id=wanted_receipt AND tenant_id=r.tenant_id AND run_id=r.id AND authorization_id=aid;
 IF NOT FOUND THEN RAISE EXCEPTION 'AGENT_MANIFEST_RECEIPT_INVALID' USING ERRCODE='22023'; END IF;
 SELECT * INTO admission FROM cehub_ai.budget_journal
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND attempt_id=wanted_attempt
  ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND OR admission.call_kind<>'model' OR admission.reservation_status<>'reserved'
  OR admission.dispatched_at IS NOT NULL OR admission.output_tokens<=0
  OR admission.request_binding->>'model_call_id' IS DISTINCT FROM receipt.model_call_id::text THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_ADMISSION_INVALID' USING ERRCODE='22023';
 END IF;
 IF pins_text IS NULL OR octet_length(pins_text)>65536 THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_PINS_INVALID' USING ERRCODE='22023';
 END IF;
 pins:=pins_text::jsonb;
 IF pins#>>'{qualification,status}' IS DISTINCT FROM 'passed'
  OR pins#>>'{qualification,provider}' IS DISTINCT FROM admission.request_binding->>'provider'
  OR pins#>>'{qualification,model}' IS DISTINCT FROM admission.request_binding->>'model'
  OR jsonb_typeof(pins->'removed_paths') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_PINS_INVALID' USING ERRCODE='22023';
 END IF;
 model_version:='sha256:' || encode(sha256(convert_to(jsonb_build_object(
  'qualification',pins->'qualification','meter_ref',admission.request_binding->'qualification_ref',
  'meter_version',admission.request_binding->'meter_version',
  'loop_qualification',r.loop_binding)::text,'UTF8')),'hex');
 IF NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,receipt.id) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND attempt_id=wanted_attempt;
 IF FOUND THEN
  IF previous.context_receipt_id<>wanted_receipt OR previous.pins IS DISTINCT FROM pins THEN
   RAISE EXCEPTION 'AGENT_MANIFEST_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN previous.body;
 END IF;
 SELECT * INTO first_manifest FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id ORDER BY revision_no LIMIT 1;
 IF FOUND AND (first_manifest.body->>'model_qualification_version'<>model_version
  OR first_manifest.body->>'prompt_version' IS DISTINCT FROM receipt.body->>'prompt_version'
  OR first_manifest.body->>'output_schema_version' IS DISTINCT FROM
     'sha256:' || (receipt.body->>'output_schema_sha256')) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_VERSION_CHANGED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id ORDER BY revision_no DESC LIMIT 1;
 n:=coalesce(previous.revision_no,0)+1;
 SELECT coalesce(jsonb_agg(o.id ORDER BY link.position),'[]'::jsonb),
  coalesce(jsonb_agg(o.tool_key || ':' || (o.metadata->>'status') || ':' || o.sequence)
   FILTER(WHERE o.metadata->>'status' IN ('failed','unavailable','cancelled')),'[]'::jsonb),
  coalesce(bool_or(o.metadata->>'status'='partial'),false)
 INTO observations,missing,has_partial
 FROM cehub_ai.agent_context_observations link JOIN cehub_ai.agent_tool_observations o
  ON o.tenant_id=link.tenant_id AND o.run_id=link.run_id AND o.id=link.observation_id
 WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id AND link.context_receipt_id=receipt.id;
 SELECT coalesce(jsonb_agg(s ORDER BY s::text),'[]'::jsonb) INTO sources FROM (
  SELECT DISTINCT s FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(o.metadata->'sources') s
  WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id
   AND link.context_receipt_id=receipt.id) selected;
 SELECT greatest(r.last_event_row_id,coalesce(max((s->>'ref_id')::bigint),0)) INTO watermark
  FROM jsonb_array_elements(sources) s WHERE s->>'kind'='event';
 SELECT coalesce(jsonb_agg('projection_removed:' || value),'[]'::jsonb) INTO omissions
  FROM jsonb_array_elements_text(pins->'removed_paths');
 SELECT omissions || coalesce(jsonb_agg('tool_omitted:' || o.tool_key || ':' || o.sequence
  || ' shown=' || (o.metadata->>'shown_count') || ' total='
  || coalesce(o.metadata->>'total_count','unknown')),'[]'::jsonb) INTO omissions
 FROM cehub_ai.agent_context_observations link JOIN cehub_ai.agent_tool_observations o
  ON o.id=link.observation_id AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id
 WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id AND link.context_receipt_id=receipt.id
  AND o.metadata->>'status' IN ('partial','unavailable','failed','cancelled');
 stamp:=clock_timestamp();
 body:=jsonb_build_object('id',mid,'tenant_id',r.tenant_id,'run_id',r.id,'authorization_id',aid,
  'revision_no',n,'parent_revision_id',previous.id,'goal_revision',1,
  'release_bundle_version',r.execution_bundle->'release_bundle_version',
  'capability_version',r.execution_bundle->'capability_version',
  'prompt_version',receipt.body->'prompt_version','skill_versions','[]'::jsonb,
  'toolset_version',r.execution_bundle->'toolset_version',
  'projection_version',r.execution_bundle->'projection_version',
  'model_qualification_version',model_version,
  'output_schema_version','sha256:' || (receipt.body->>'output_schema_sha256'),
  'policy_version',r.execution_bundle->'policy_version','observation_ids',observations,
  'event_watermark',watermark,'selected_sources',sources,'omission_reasons',omissions,
  'estimated_input_tokens',admission.input_tokens,'reserved_output_tokens',admission.output_tokens,
  'completeness',CASE WHEN jsonb_array_length(missing)>0 THEN 'context_incomplete'
   WHEN has_partial THEN 'partial' ELSE 'complete' END,'missing',missing,'built_at',stamp);
 body:=body || jsonb_build_object('digest',encode(sha256(convert_to(body::text,'UTF8')),'hex'));
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_context_manifests VALUES(mid,r.tenant_id,r.id,aid,receipt.id,
  admission.id,wanted_attempt,n,previous.id,body,pins,stamp);
 RETURN body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_agent_context_manifest(uuid,uuid,text) FROM PUBLIC;
"""

GUARDS = r"""
CREATE FUNCTION cehub_ai.require_model_manifest() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved'
  AND NEW.dispatched_at IS NOT NULL
  AND EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations a
    WHERE a.tenant_id=NEW.tenant_id AND a.run_id=NEW.run_id)
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_manifests m
    WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id AND m.attempt_id=NEW.attempt_id) THEN
  RAISE EXCEPTION 'BUDGET_CONTEXT_MANIFEST_REQUIRED' USING ERRCODE='22023';
 END IF;
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved'
  AND NEW.dispatched_at IS NOT NULL AND EXISTS(SELECT 1 FROM cehub_ai.agent_context_manifests m
   WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id AND m.attempt_id=NEW.attempt_id
    AND NOT cehub_ai.agent_manifest_sources_are_current(
      m.tenant_id,m.run_id,m.context_receipt_id)) THEN
  RAISE EXCEPTION 'BUDGET_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_model_manifest() FROM PUBLIC;
CREATE TRIGGER require_model_manifest BEFORE INSERT ON cehub_ai.budget_journal
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_model_manifest();

CREATE FUNCTION cehub_ai.require_trace_manifests() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.structured_attempts>0 AND EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations
    WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id)
  AND EXISTS(SELECT 1 FROM generate_series(1,NEW.structured_attempts) n WHERE NOT EXISTS(
   SELECT 1 FROM cehub_ai.agent_context_manifests m JOIN cehub_ai.budget_journal j
    ON j.id=m.admission_id AND j.tenant_id=m.tenant_id AND j.run_id=m.run_id
   WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id
    AND m.context_receipt_id=NEW.context_receipt_id
    AND j.request_binding->>'model_call_id'=NEW.budget_call_id::text
    AND (j.request_binding->>'structured_attempt')::integer=n)) THEN
  RAISE EXCEPTION 'BUDGET_TRACE_MANIFEST_REQUIRED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_trace_manifests() FROM PUBLIC;
CREATE TRIGGER require_trace_manifests BEFORE INSERT ON cehub_ai.model_invocations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_trace_manifests();
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(PORTS)
    op.execute(GUARDS)
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
      GRANT EXECUTE ON FUNCTION cehub_ai.bind_agent_runtime_bundle(text),
        cehub_ai.freeze_agent_context_manifest(uuid,uuid,text),
        cehub_ai.verify_agent_manifest_sources(),
        cehub_ai.verify_agent_context_sources(uuid) TO pdos_agent;
    END IF; END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE execution_bundle IS NOT NULL)
       OR EXISTS(SELECT 1 FROM cehub_ai.agent_context_manifests) THEN
        RAISE EXCEPTION 'cannot remove persistent context manifest or runtime bundle history';
      END IF;
    END $body$;""")
    op.execute("DROP TRIGGER require_trace_manifests ON cehub_ai.model_invocations")
    op.execute("DROP FUNCTION cehub_ai.require_trace_manifests()")
    op.execute("DROP TRIGGER require_model_manifest ON cehub_ai.budget_journal")
    op.execute("DROP FUNCTION cehub_ai.require_model_manifest()")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.freeze_agent_context_manifest(uuid,uuid,text)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.bind_agent_runtime_bundle(text)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.verify_agent_manifest_sources()")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.verify_agent_context_sources(uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS cehub_ai.agent_manifest_sources_are_current(uuid,uuid,uuid)"
    )
    op.execute("DROP TABLE cehub_ai.agent_context_manifests")
    op.execute("ALTER TABLE cehub_ai.budget_journal DROP CONSTRAINT uq_budget_journal_scope")
    op.execute("DROP TRIGGER protect_execution_bundle ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.protect_execution_bundle()")
    op.execute("ALTER TABLE cehub_ai.agent_runs DROP COLUMN execution_bundle")
