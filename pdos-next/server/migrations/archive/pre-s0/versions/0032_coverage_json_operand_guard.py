"""Repair JSON containment operand parsing at the coverage commit constraint.

Head31 remains immutable. The whole existing atom guard and its ACL are retained;
only the right JSON operand of containment receives explicit parentheses.
"""

# ruff: noqa: E501 - preserve static reviewed SQL.

from alembic import op
from sqlalchemy import text

revision = "next_0032"
down_revision = "next_0031"
branch_labels = None
depends_on = None

PRIOR_SQL = r"""
CREATE OR REPLACE FUNCTION public.assert_change_coverage_atom(tid uuid,target uuid)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,public AS $$
DECLARE a public.controlled_change_coverage_facts%ROWTYPE;
 r public.action_receipts%ROWTYPE; origin public.change_request_versions%ROWTYPE;
 anchor public.change_request_versions%ROWTYPE; parent public.change_request_versions%ROWTYPE;
 m jsonb; b jsonb; item jsonb; src jsonb; scope_json jsonb;
 nodes text[]; roots text[]; facet_nodes text[]; unit_nodes text[]; facets text[];
 fixed jsonb; steps integer:=0; native public.artifact_versions%ROWTYPE;
 registration public.action_receipts%ROWTYPE; native_basis jsonb;
BEGIN
 IF tid IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid THEN
  RAISE EXCEPTION 'coverage atom tenant mismatch'; END IF;
 SELECT * INTO STRICT a FROM public.controlled_change_coverage_facts
  WHERE tenant_id=tid AND id=target;
 m:=a.material; b:=a.input_snapshot->'origin_binding';
 scope_json:=jsonb_build_object('tenant_id',tid,'product_id',a.product_id,'project_id',a.project_id);
 IF NOT COALESCE(public.coverage_json_keys(m,ARRAY['schema_version','scope','purpose',
  'change_id','origin_version_id','origin_revision','owner_id','visibility','publisher_id',
  'roots','nodes','units','facets','closure_sha256','valid_from','valid_until','nature'])
  AND m->>'schema_version'='pdos-controlled-change-coverage-v1'
  AND m->'scope'=scope_json AND m->>'purpose'=a.purpose
  AND (m->>'change_id')::uuid=a.change_id
  AND (m->>'origin_version_id')::uuid=a.origin_version_id
  AND jsonb_typeof(m->'origin_revision')='number'
  AND m->>'origin_revision' ~ '^[1-9][0-9]*$'
  AND (m->>'origin_revision')::integer=a.origin_revision
  AND (m->>'owner_id')::uuid=a.owner_id AND m->>'visibility'=a.visibility
  AND (m->>'publisher_id')::uuid=a.actor_id
  AND m->>'closure_sha256'=a.closure_sha256
  AND (m->>'valid_from')::timestamptz=a.valid_from
  AND (m->>'valid_until')::timestamptz=a.valid_until AND m->>'nature'=a.nature
  AND a.operation='change.coverage.import' AND a.status='published'
  AND a.revision=a.epoch AND a.dependency_epoch>0
  AND a.valid_from<=a.created_at AND a.created_at<a.valid_until
  AND a.material_sha256 ~ '^[0-9a-f]{64}$' AND a.purpose_sha256 ~ '^[0-9a-f]{64}$'
  AND a.intent_digest ~ '^[0-9a-f]{64}$' AND a.closure_sha256 ~ '^[0-9a-f]{64}$',false)
 THEN RAISE EXCEPTION 'coverage material/header mismatch'; END IF;
 -- Python's canonical digest is checked by the actual owner, not jsonb::text.
 IF NOT COALESCE(jsonb_typeof(m->'nodes')='array'
  AND jsonb_array_length(m->'nodes') BETWEEN 1 AND 250
  AND jsonb_typeof(m->'roots')='array' AND jsonb_array_length(m->'roots') BETWEEN 1 AND 100
  AND jsonb_typeof(m->'units')='array' AND jsonb_array_length(m->'units') BETWEEN 1 AND 250
  AND jsonb_typeof(m->'facets')='array' AND jsonb_array_length(m->'facets')=8,false)
 THEN RAISE EXCEPTION 'coverage bounded enumeration required'; END IF;
 SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
  INTO nodes FROM jsonb_array_elements(m->'nodes') v;
 SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
  INTO roots FROM jsonb_array_elements(m->'roots') v;
 IF cardinality(nodes)<>(SELECT count(DISTINCT v) FROM unnest(nodes) v)
  OR cardinality(roots)<>(SELECT count(DISTINCT v) FROM unnest(roots) v)
  OR NOT roots<@nodes THEN RAISE EXCEPTION 'coverage node/root enumeration mismatch'; END IF;
 SELECT array_agg(v->>'facet' ORDER BY v->>'facet') INTO facets
  FROM jsonb_array_elements(m->'facets') v;
 IF facets IS DISTINCT FROM ARRAY['customer_samples','engineering','evidence_applicability',
  'in_process_builds','manufacturing','production_switch','supply_inventory_wip','training']::text[]
 THEN RAISE EXCEPTION 'coverage requires exact eight facets'; END IF;
 FOR item IN SELECT v FROM jsonb_array_elements(m->'facets') v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['facet','nodes','statement'])
   AND jsonb_typeof(item->'nodes')='array' AND jsonb_array_length(item->'nodes') BETWEEN 1 AND 250
   AND jsonb_typeof(item->'statement')='string'
   AND length(btrim(item->>'statement')) BETWEEN 1 AND 2000,false)
  THEN RAISE EXCEPTION 'coverage facet declaration required'; END IF;
  SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
   INTO facet_nodes FROM jsonb_array_elements(item->'nodes') v;
  IF facet_nodes IS DISTINCT FROM nodes THEN
   RAISE EXCEPTION 'every coverage facet needs the complete fixed node set'; END IF;
 END LOOP;
 FOR item IN SELECT v FROM jsonb_array_elements(m->'units') v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['unit','object_identity'])
   AND jsonb_typeof(item->'unit')='string' AND jsonb_typeof(item->'object_identity')='string'
   AND item->>'unit'='object:'||(item->>'object_identity'),false)
  THEN RAISE EXCEPTION 'coverage supports exact object units only'; END IF;
 END LOOP;
 SELECT array_agg(v->>'object_identity' ORDER BY v->>'object_identity') INTO unit_nodes
  FROM jsonb_array_elements(m->'units') v;
 IF unit_nodes IS DISTINCT FROM nodes THEN RAISE EXCEPTION 'coverage exact units mismatch'; END IF;
 IF NOT COALESCE(public.coverage_json_keys(a.input_snapshot,ARRAY['payload','origin_binding'])
  AND public.coverage_json_keys(a.input_snapshot->'payload',ARRAY['project_id','change_id',
   'purpose','source','expected_previous_id','expected_previous_revision','reason'])
  AND a.input_snapshot->'payload'->>'project_id'=a.project_id::text
  AND a.input_snapshot->'payload'->>'change_id'=a.change_id::text
  AND a.input_snapshot->'payload'->>'purpose'=a.purpose
  AND a.input_snapshot->'payload'->'source'=a.source
  AND jsonb_typeof(a.input_snapshot->'payload'->'reason')='string'
  AND length(btrim(a.input_snapshot->'payload'->>'reason')) BETWEEN 1 AND 2000
  AND public.coverage_json_keys(b,ARRAY['current_id','version_id','revision','origin_version_id',
   'origin_revision','fixed_request']) AND b->>'origin_version_id'=a.origin_version_id::text
  AND (b->>'origin_revision')::integer=a.origin_revision,false)
 THEN RAISE EXCEPTION 'coverage exact import/origin binding required'; END IF;
 IF (a.previous_id IS NULL AND NOT COALESCE(
    a.input_snapshot->'payload'->'expected_previous_id'='null'::jsonb
    AND a.input_snapshot->'payload'->'expected_previous_revision'='null'::jsonb,false))
  OR (a.previous_id IS NOT NULL AND NOT COALESCE(
    (a.input_snapshot->'payload'->>'expected_previous_id')::uuid=a.previous_id
    AND (a.input_snapshot->'payload'->>'expected_previous_revision')::integer=a.previous_revision,false))
 THEN RAISE EXCEPTION 'coverage exact previous publication required'; END IF;
 SELECT * INTO STRICT origin FROM public.change_request_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
  AND id=a.origin_version_id AND revision=a.origin_revision;
 SELECT * INTO STRICT anchor FROM public.change_request_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
  AND id=(b->>'version_id')::uuid AND revision=(b->>'revision')::integer;
 fixed:=jsonb_build_object('scope',origin.request_snapshot->'scope',
  'audience',origin.request_snapshot->'audience','requester_id',origin.request_snapshot->'requester_id',
  'roots',origin.request_snapshot->'roots','references',origin.request_snapshot->'references');
 IF origin.owner_id IS DISTINCT FROM a.owner_id OR origin.visibility IS DISTINCT FROM a.visibility
  OR fixed IS DISTINCT FROM b->'fixed_request' OR fixed->'scope' IS DISTINCT FROM scope_json
  OR fixed->'roots' IS DISTINCT FROM m->'roots' THEN
  RAISE EXCEPTION 'coverage exact origin scope/audience/roots required'; END IF;
 parent:=anchor;
 LOOP
  IF parent.owner_id IS DISTINCT FROM a.owner_id OR parent.visibility IS DISTINCT FROM a.visibility
   OR jsonb_build_object('scope',parent.request_snapshot->'scope',
    'audience',parent.request_snapshot->'audience','requester_id',parent.request_snapshot->'requester_id',
    'roots',parent.request_snapshot->'roots','references',parent.request_snapshot->'references')
     IS DISTINCT FROM fixed THEN RAISE EXCEPTION 'coverage fixed lineage mismatch'; END IF;
  EXIT WHEN parent.id=a.origin_version_id AND parent.revision=a.origin_revision;
  steps:=steps+1;
  IF steps>=100 OR parent.revision<=a.origin_revision
   OR parent.previous_revision IS DISTINCT FROM parent.revision-1
   OR parent.operation NOT IN ('change.impact.compute','change.order.prepare','change.order.approve',
    'change.implementation.record') THEN RAISE EXCEPTION 'coverage bounded lineage required'; END IF;
  SELECT * INTO STRICT parent FROM public.change_request_versions WHERE tenant_id=tid
   AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
   AND id=parent.previous_version_id AND revision=parent.previous_revision;
 END LOOP;
 IF NOT COALESCE(public.coverage_json_keys(a.issuer_stamp,ARRAY['coverage_epoch','coverage_runtime_id',
  'issuer_key','issuer_version','issuer_epoch','nature','pins_sha256'])
  AND jsonb_typeof(a.issuer_stamp->'coverage_epoch')='number'
  AND a.issuer_stamp->>'coverage_epoch' ~ '^[1-9][0-9]*$'
  AND jsonb_typeof(a.issuer_stamp->'issuer_epoch')='number'
  AND a.issuer_stamp->>'issuer_epoch' ~ '^[1-9][0-9]*$'
  AND a.issuer_stamp->>'pins_sha256' ~ '^[0-9a-f]{64}$'
  AND a.issuer_stamp->>'nature'=a.nature
  AND jsonb_typeof(a.issuer_stamp->'issuer_key')='string'
  AND jsonb_typeof(a.issuer_stamp->'issuer_version')='string'
  AND (a.issuer_stamp->>'coverage_runtime_id')::uuid IS NOT NULL
  AND a.authority_snapshot->'scope'=scope_json
  AND a.authority_snapshot->>'subject_id'=a.actor_id::text
  AND a.authority_snapshot->>'operation'='change.impact.compute'
  AND a.authority_snapshot->>'purpose'=a.purpose
  AND a.authority_snapshot->'authorized'='true'::jsonb
  AND a.authority_snapshot->'qualified'='true'::jsonb
  AND a.authority_snapshot->>'facts_revision' ~ '^[0-9a-f]{64}$'
  AND (a.authority_snapshot->>'valid_until')::timestamptz>a.created_at
  AND a.authority_snapshot->'synthetic'=to_jsonb(a.nature='synthetic'),false)
 THEN RAISE EXCEPTION 'coverage saved issuer/authority correspondence required'; END IF;
 IF NOT COALESCE(public.coverage_json_keys(a.source,ARRAY['id','revision','kind','position'])
  AND a.source->>'kind'='artifact' AND jsonb_typeof(a.source->'revision')='number'
  AND a.source->>'revision' ~ '^[1-9][0-9]*$'
  AND a.source->>'position' ~ '^line:[1-9][0-9]*;quote_sha256:[0-9a-f]{64}$'
  AND jsonb_typeof(a.sources)='array' AND jsonb_array_length(a.sources)>=1
  AND a.sources @> jsonb_build_array(a.source)
  AND jsonb_typeof(a.required_source_read_set)='array'
  AND jsonb_array_length(a.required_source_read_set) BETWEEN 1 AND 20
  AND a.source_basis->>'closure_sha256'=a.closure_sha256
  AND (a.source_basis->>'dependency_epoch')::bigint=a.dependency_epoch
  AND a.source_basis->>'temporal_sha256' ~ '^[0-9a-f]{64}$'
  AND jsonb_typeof(a.source_basis->'artifact_basis')='object'
  AND public.coverage_json_keys(a.source_basis,ARRAY['artifact_basis','closure_sha256',
   'dependency_epoch','temporal_sha256']),false)
 THEN RAISE EXCEPTION 'coverage fixed original/read set correspondence required'; END IF;
 FOR src IN SELECT v FROM jsonb_array_elements(a.sources) v LOOP
  IF NOT COALESCE(public.coverage_json_keys(src,ARRAY['id','revision','kind','position'])
   AND (src->>'id')::uuid IS NOT NULL AND jsonb_typeof(src->'revision')='number'
   AND src->>'revision' ~ '^[1-9][0-9]*$' AND src->>'kind' IN ('artifact','domain','command')
   AND jsonb_typeof(src->'position')='string'
   AND length(btrim(src->>'position')) BETWEEN 1 AND 2000,false)
  THEN RAISE EXCEPTION 'coverage source reference shape mismatch'; END IF;
  IF src->>'kind'='artifact' AND NOT a.required_source_read_set @>
    jsonb_build_array(jsonb_build_object('artifact_id',src->>'id','expected_revision',(src->>'revision')::integer))
  THEN RAISE EXCEPTION 'coverage original source must be in exact read set'; END IF;
 END LOOP;
 IF jsonb_array_length(a.sources)<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(a.sources) v)
  OR jsonb_array_length(a.required_source_read_set)<>(SELECT count(DISTINCT v->>'artifact_id')
    FROM jsonb_array_elements(a.required_source_read_set) v)
  OR jsonb_array_length(a.required_source_read_set)<>(SELECT count(*)
    FROM jsonb_object_keys(a.source_basis->'artifact_basis'))
  OR NOT COALESCE(jsonb_typeof(a.authority_snapshot->'required_source_read_set')='array'
   AND a.required_source_read_set @> a.authority_snapshot->'required_source_read_set',false)
 THEN RAISE EXCEPTION 'coverage duplicate/mixed authority read set'; END IF;
 FOR item IN SELECT v FROM jsonb_array_elements(a.required_source_read_set) v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['artifact_id','expected_revision'])
   AND (item->>'artifact_id')::uuid IS NOT NULL
   AND jsonb_typeof(item->'expected_revision')='number'
   AND item->>'expected_revision' ~ '^[1-9][0-9]*$'
   AND a.source_basis->'artifact_basis' ? (item->>'artifact_id')
   AND (a.source_basis->'artifact_basis'->(item->>'artifact_id')->>'revision')::integer
    =(item->>'expected_revision')::integer,false)
  THEN RAISE EXCEPTION 'coverage exact artifact basis required'; END IF;
 END LOOP;
 -- Scope/registration correspondence only: later withdrawal does not erase a
 -- stored publication, and original-byte authenticity remains owner verified.
 SELECT * INTO STRICT native FROM public.artifact_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND id=(a.source->>'id')::uuid;
 SELECT * INTO STRICT registration FROM public.action_receipts x WHERE x.tenant_id=tid
  AND x.product_id=a.product_id AND x.operation='evidence.artifact.register'
  AND x.subject_type='artifact' AND x.subject_id=native.id
  AND x.subject_revision=(a.source->>'revision')::integer;
 native_basis:=a.source_basis->'artifact_basis'->(a.source->>'id');
 IF NOT COALESCE(native_basis->>'source_origin'='registered_native_text'
   AND native_basis->>'registration_receipt_id'=registration.id::text
   AND native_basis->>'registration_command_id'=registration.command_id::text
   AND native_basis->>'registration_actor_id'=registration.actor_id::text
   AND native_basis->>'registration_requester_id'=registration.requester_id::text
   AND native_basis->'registration_run_id'=COALESCE(to_jsonb(registration.run_id::text),'null'::jsonb)
   AND native_basis->>'registration_request_digest'=registration.request_digest
   AND native_basis->>'registration_intent_digest'=registration.intent_digest
   AND native_basis->>'sha256'=native.content_hash
   AND registration.requester_id=native.owner_id AND registration.visibility=native.visibility
   AND registration.result->>'id'=native.id::text
   AND (registration.result->>'revision')::integer=registration.subject_revision
   AND registration.result->>'status'='active',false)
 THEN RAISE EXCEPTION 'coverage requires exact native original registration'; END IF;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=tid
  AND product_id=a.product_id AND operation='change.coverage.import'
  AND subject_type='change_coverage_fact' AND subject_id=a.id AND subject_revision=a.revision;
 IF r.actor_id IS DISTINCT FROM a.actor_id OR r.requester_id IS DISTINCT FROM a.actor_id
  OR r.run_id IS NOT NULL OR r.command_id IS DISTINCT FROM a.command_id
  OR r.intent_digest IS DISTINCT FROM a.intent_digest OR r.request_digest IS DISTINCT FROM a.intent_digest
  OR r.visibility IS DISTINCT FROM a.visibility OR r.result IS DISTINCT FROM
    jsonb_build_object('id',a.id::text,'revision',a.revision,'status',a.status)
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id
   AND x.actor_id=r.actor_id AND x.operation=r.operation)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id
   AND x.actor_id=r.actor_id AND x.type='change.coverage_imported' AND x.subject_id=a.id
   AND x.subject_revision=a.revision AND x.schema_version=1 AND x.correlation_id=r.command_id)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=tid AND k.receipt_id=r.id
   AND k.actor_id=r.actor_id AND k.digest=r.request_digest)
  OR EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=tid AND k.receipt_id=r.id
   AND (k.actor_id IS DISTINCT FROM r.actor_id OR k.digest IS DISTINCT FROM r.request_digest))
 THEN RAISE EXCEPTION 'coverage requires one exact immutable common group'; END IF;
END $$;
"""

REPAIRED_SQL = r"""
CREATE OR REPLACE FUNCTION public.assert_change_coverage_atom(tid uuid,target uuid)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,public AS $$
DECLARE a public.controlled_change_coverage_facts%ROWTYPE;
 r public.action_receipts%ROWTYPE; origin public.change_request_versions%ROWTYPE;
 anchor public.change_request_versions%ROWTYPE; parent public.change_request_versions%ROWTYPE;
 m jsonb; b jsonb; item jsonb; src jsonb; scope_json jsonb;
 nodes text[]; roots text[]; facet_nodes text[]; unit_nodes text[]; facets text[];
 fixed jsonb; steps integer:=0; native public.artifact_versions%ROWTYPE;
 registration public.action_receipts%ROWTYPE; native_basis jsonb;
BEGIN
 IF tid IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid THEN
  RAISE EXCEPTION 'coverage atom tenant mismatch'; END IF;
 SELECT * INTO STRICT a FROM public.controlled_change_coverage_facts
  WHERE tenant_id=tid AND id=target;
 m:=a.material; b:=a.input_snapshot->'origin_binding';
 scope_json:=jsonb_build_object('tenant_id',tid,'product_id',a.product_id,'project_id',a.project_id);
 IF NOT COALESCE(public.coverage_json_keys(m,ARRAY['schema_version','scope','purpose',
  'change_id','origin_version_id','origin_revision','owner_id','visibility','publisher_id',
  'roots','nodes','units','facets','closure_sha256','valid_from','valid_until','nature'])
  AND m->>'schema_version'='pdos-controlled-change-coverage-v1'
  AND m->'scope'=scope_json AND m->>'purpose'=a.purpose
  AND (m->>'change_id')::uuid=a.change_id
  AND (m->>'origin_version_id')::uuid=a.origin_version_id
  AND jsonb_typeof(m->'origin_revision')='number'
  AND m->>'origin_revision' ~ '^[1-9][0-9]*$'
  AND (m->>'origin_revision')::integer=a.origin_revision
  AND (m->>'owner_id')::uuid=a.owner_id AND m->>'visibility'=a.visibility
  AND (m->>'publisher_id')::uuid=a.actor_id
  AND m->>'closure_sha256'=a.closure_sha256
  AND (m->>'valid_from')::timestamptz=a.valid_from
  AND (m->>'valid_until')::timestamptz=a.valid_until AND m->>'nature'=a.nature
  AND a.operation='change.coverage.import' AND a.status='published'
  AND a.revision=a.epoch AND a.dependency_epoch>0
  AND a.valid_from<=a.created_at AND a.created_at<a.valid_until
  AND a.material_sha256 ~ '^[0-9a-f]{64}$' AND a.purpose_sha256 ~ '^[0-9a-f]{64}$'
  AND a.intent_digest ~ '^[0-9a-f]{64}$' AND a.closure_sha256 ~ '^[0-9a-f]{64}$',false)
 THEN RAISE EXCEPTION 'coverage material/header mismatch'; END IF;
 -- Python's canonical digest is checked by the actual owner, not jsonb::text.
 IF NOT COALESCE(jsonb_typeof(m->'nodes')='array'
  AND jsonb_array_length(m->'nodes') BETWEEN 1 AND 250
  AND jsonb_typeof(m->'roots')='array' AND jsonb_array_length(m->'roots') BETWEEN 1 AND 100
  AND jsonb_typeof(m->'units')='array' AND jsonb_array_length(m->'units') BETWEEN 1 AND 250
  AND jsonb_typeof(m->'facets')='array' AND jsonb_array_length(m->'facets')=8,false)
 THEN RAISE EXCEPTION 'coverage bounded enumeration required'; END IF;
 SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
  INTO nodes FROM jsonb_array_elements(m->'nodes') v;
 SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
  INTO roots FROM jsonb_array_elements(m->'roots') v;
 IF cardinality(nodes)<>(SELECT count(DISTINCT v) FROM unnest(nodes) v)
  OR cardinality(roots)<>(SELECT count(DISTINCT v) FROM unnest(roots) v)
  OR NOT roots<@nodes THEN RAISE EXCEPTION 'coverage node/root enumeration mismatch'; END IF;
 SELECT array_agg(v->>'facet' ORDER BY v->>'facet') INTO facets
  FROM jsonb_array_elements(m->'facets') v;
 IF facets IS DISTINCT FROM ARRAY['customer_samples','engineering','evidence_applicability',
  'in_process_builds','manufacturing','production_switch','supply_inventory_wip','training']::text[]
 THEN RAISE EXCEPTION 'coverage requires exact eight facets'; END IF;
 FOR item IN SELECT v FROM jsonb_array_elements(m->'facets') v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['facet','nodes','statement'])
   AND jsonb_typeof(item->'nodes')='array' AND jsonb_array_length(item->'nodes') BETWEEN 1 AND 250
   AND jsonb_typeof(item->'statement')='string'
   AND length(btrim(item->>'statement')) BETWEEN 1 AND 2000,false)
  THEN RAISE EXCEPTION 'coverage facet declaration required'; END IF;
  SELECT array_agg(public.coverage_ref_identity(v) ORDER BY public.coverage_ref_identity(v))
   INTO facet_nodes FROM jsonb_array_elements(item->'nodes') v;
  IF facet_nodes IS DISTINCT FROM nodes THEN
   RAISE EXCEPTION 'every coverage facet needs the complete fixed node set'; END IF;
 END LOOP;
 FOR item IN SELECT v FROM jsonb_array_elements(m->'units') v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['unit','object_identity'])
   AND jsonb_typeof(item->'unit')='string' AND jsonb_typeof(item->'object_identity')='string'
   AND item->>'unit'='object:'||(item->>'object_identity'),false)
  THEN RAISE EXCEPTION 'coverage supports exact object units only'; END IF;
 END LOOP;
 SELECT array_agg(v->>'object_identity' ORDER BY v->>'object_identity') INTO unit_nodes
  FROM jsonb_array_elements(m->'units') v;
 IF unit_nodes IS DISTINCT FROM nodes THEN RAISE EXCEPTION 'coverage exact units mismatch'; END IF;
 IF NOT COALESCE(public.coverage_json_keys(a.input_snapshot,ARRAY['payload','origin_binding'])
  AND public.coverage_json_keys(a.input_snapshot->'payload',ARRAY['project_id','change_id',
   'purpose','source','expected_previous_id','expected_previous_revision','reason'])
  AND a.input_snapshot->'payload'->>'project_id'=a.project_id::text
  AND a.input_snapshot->'payload'->>'change_id'=a.change_id::text
  AND a.input_snapshot->'payload'->>'purpose'=a.purpose
  AND a.input_snapshot->'payload'->'source'=a.source
  AND jsonb_typeof(a.input_snapshot->'payload'->'reason')='string'
  AND length(btrim(a.input_snapshot->'payload'->>'reason')) BETWEEN 1 AND 2000
  AND public.coverage_json_keys(b,ARRAY['current_id','version_id','revision','origin_version_id',
   'origin_revision','fixed_request']) AND b->>'origin_version_id'=a.origin_version_id::text
  AND (b->>'origin_revision')::integer=a.origin_revision,false)
 THEN RAISE EXCEPTION 'coverage exact import/origin binding required'; END IF;
 IF (a.previous_id IS NULL AND NOT COALESCE(
    a.input_snapshot->'payload'->'expected_previous_id'='null'::jsonb
    AND a.input_snapshot->'payload'->'expected_previous_revision'='null'::jsonb,false))
  OR (a.previous_id IS NOT NULL AND NOT COALESCE(
    (a.input_snapshot->'payload'->>'expected_previous_id')::uuid=a.previous_id
    AND (a.input_snapshot->'payload'->>'expected_previous_revision')::integer=a.previous_revision,false))
 THEN RAISE EXCEPTION 'coverage exact previous publication required'; END IF;
 SELECT * INTO STRICT origin FROM public.change_request_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
  AND id=a.origin_version_id AND revision=a.origin_revision;
 SELECT * INTO STRICT anchor FROM public.change_request_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
  AND id=(b->>'version_id')::uuid AND revision=(b->>'revision')::integer;
 fixed:=jsonb_build_object('scope',origin.request_snapshot->'scope',
  'audience',origin.request_snapshot->'audience','requester_id',origin.request_snapshot->'requester_id',
  'roots',origin.request_snapshot->'roots','references',origin.request_snapshot->'references');
 IF origin.owner_id IS DISTINCT FROM a.owner_id OR origin.visibility IS DISTINCT FROM a.visibility
  OR fixed IS DISTINCT FROM b->'fixed_request' OR fixed->'scope' IS DISTINCT FROM scope_json
  OR fixed->'roots' IS DISTINCT FROM m->'roots' THEN
  RAISE EXCEPTION 'coverage exact origin scope/audience/roots required'; END IF;
 parent:=anchor;
 LOOP
  IF parent.owner_id IS DISTINCT FROM a.owner_id OR parent.visibility IS DISTINCT FROM a.visibility
   OR jsonb_build_object('scope',parent.request_snapshot->'scope',
    'audience',parent.request_snapshot->'audience','requester_id',parent.request_snapshot->'requester_id',
    'roots',parent.request_snapshot->'roots','references',parent.request_snapshot->'references')
     IS DISTINCT FROM fixed THEN RAISE EXCEPTION 'coverage fixed lineage mismatch'; END IF;
  EXIT WHEN parent.id=a.origin_version_id AND parent.revision=a.origin_revision;
  steps:=steps+1;
  IF steps>=100 OR parent.revision<=a.origin_revision
   OR parent.previous_revision IS DISTINCT FROM parent.revision-1
   OR parent.operation NOT IN ('change.impact.compute','change.order.prepare','change.order.approve',
    'change.implementation.record') THEN RAISE EXCEPTION 'coverage bounded lineage required'; END IF;
  SELECT * INTO STRICT parent FROM public.change_request_versions WHERE tenant_id=tid
   AND product_id=a.product_id AND project_id=a.project_id AND change_id=a.change_id
   AND id=parent.previous_version_id AND revision=parent.previous_revision;
 END LOOP;
 IF NOT COALESCE(public.coverage_json_keys(a.issuer_stamp,ARRAY['coverage_epoch','coverage_runtime_id',
  'issuer_key','issuer_version','issuer_epoch','nature','pins_sha256'])
  AND jsonb_typeof(a.issuer_stamp->'coverage_epoch')='number'
  AND a.issuer_stamp->>'coverage_epoch' ~ '^[1-9][0-9]*$'
  AND jsonb_typeof(a.issuer_stamp->'issuer_epoch')='number'
  AND a.issuer_stamp->>'issuer_epoch' ~ '^[1-9][0-9]*$'
  AND a.issuer_stamp->>'pins_sha256' ~ '^[0-9a-f]{64}$'
  AND a.issuer_stamp->>'nature'=a.nature
  AND jsonb_typeof(a.issuer_stamp->'issuer_key')='string'
  AND jsonb_typeof(a.issuer_stamp->'issuer_version')='string'
  AND (a.issuer_stamp->>'coverage_runtime_id')::uuid IS NOT NULL
  AND a.authority_snapshot->'scope'=scope_json
  AND a.authority_snapshot->>'subject_id'=a.actor_id::text
  AND a.authority_snapshot->>'operation'='change.impact.compute'
  AND a.authority_snapshot->>'purpose'=a.purpose
  AND a.authority_snapshot->'authorized'='true'::jsonb
  AND a.authority_snapshot->'qualified'='true'::jsonb
  AND a.authority_snapshot->>'facts_revision' ~ '^[0-9a-f]{64}$'
  AND (a.authority_snapshot->>'valid_until')::timestamptz>a.created_at
  AND a.authority_snapshot->'synthetic'=to_jsonb(a.nature='synthetic'),false)
 THEN RAISE EXCEPTION 'coverage saved issuer/authority correspondence required'; END IF;
 IF NOT COALESCE(public.coverage_json_keys(a.source,ARRAY['id','revision','kind','position'])
  AND a.source->>'kind'='artifact' AND jsonb_typeof(a.source->'revision')='number'
  AND a.source->>'revision' ~ '^[1-9][0-9]*$'
  AND a.source->>'position' ~ '^line:[1-9][0-9]*;quote_sha256:[0-9a-f]{64}$'
  AND jsonb_typeof(a.sources)='array' AND jsonb_array_length(a.sources)>=1
  AND a.sources @> jsonb_build_array(a.source)
  AND jsonb_typeof(a.required_source_read_set)='array'
  AND jsonb_array_length(a.required_source_read_set) BETWEEN 1 AND 20
  AND a.source_basis->>'closure_sha256'=a.closure_sha256
  AND (a.source_basis->>'dependency_epoch')::bigint=a.dependency_epoch
  AND a.source_basis->>'temporal_sha256' ~ '^[0-9a-f]{64}$'
  AND jsonb_typeof(a.source_basis->'artifact_basis')='object'
  AND public.coverage_json_keys(a.source_basis,ARRAY['artifact_basis','closure_sha256',
   'dependency_epoch','temporal_sha256']),false)
 THEN RAISE EXCEPTION 'coverage fixed original/read set correspondence required'; END IF;
 FOR src IN SELECT v FROM jsonb_array_elements(a.sources) v LOOP
  IF NOT COALESCE(public.coverage_json_keys(src,ARRAY['id','revision','kind','position'])
   AND (src->>'id')::uuid IS NOT NULL AND jsonb_typeof(src->'revision')='number'
   AND src->>'revision' ~ '^[1-9][0-9]*$' AND src->>'kind' IN ('artifact','domain','command')
   AND jsonb_typeof(src->'position')='string'
   AND length(btrim(src->>'position')) BETWEEN 1 AND 2000,false)
  THEN RAISE EXCEPTION 'coverage source reference shape mismatch'; END IF;
  IF src->>'kind'='artifact' AND NOT a.required_source_read_set @>
    jsonb_build_array(jsonb_build_object('artifact_id',src->>'id','expected_revision',(src->>'revision')::integer))
  THEN RAISE EXCEPTION 'coverage original source must be in exact read set'; END IF;
 END LOOP;
 IF jsonb_array_length(a.sources)<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(a.sources) v)
  OR jsonb_array_length(a.required_source_read_set)<>(SELECT count(DISTINCT v->>'artifact_id')
    FROM jsonb_array_elements(a.required_source_read_set) v)
  OR jsonb_array_length(a.required_source_read_set)<>(SELECT count(*)
    FROM jsonb_object_keys(a.source_basis->'artifact_basis'))
  OR NOT COALESCE(jsonb_typeof(a.authority_snapshot->'required_source_read_set')='array'
   AND a.required_source_read_set @> (a.authority_snapshot->'required_source_read_set'),false)
 THEN RAISE EXCEPTION 'coverage duplicate/mixed authority read set'; END IF;
 FOR item IN SELECT v FROM jsonb_array_elements(a.required_source_read_set) v LOOP
  IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['artifact_id','expected_revision'])
   AND (item->>'artifact_id')::uuid IS NOT NULL
   AND jsonb_typeof(item->'expected_revision')='number'
   AND item->>'expected_revision' ~ '^[1-9][0-9]*$'
   AND a.source_basis->'artifact_basis' ? (item->>'artifact_id')
   AND (a.source_basis->'artifact_basis'->(item->>'artifact_id')->>'revision')::integer
    =(item->>'expected_revision')::integer,false)
  THEN RAISE EXCEPTION 'coverage exact artifact basis required'; END IF;
 END LOOP;
 -- Scope/registration correspondence only: later withdrawal does not erase a
 -- stored publication, and original-byte authenticity remains owner verified.
 SELECT * INTO STRICT native FROM public.artifact_versions WHERE tenant_id=tid
  AND product_id=a.product_id AND id=(a.source->>'id')::uuid;
 SELECT * INTO STRICT registration FROM public.action_receipts x WHERE x.tenant_id=tid
  AND x.product_id=a.product_id AND x.operation='evidence.artifact.register'
  AND x.subject_type='artifact' AND x.subject_id=native.id
  AND x.subject_revision=(a.source->>'revision')::integer;
 native_basis:=a.source_basis->'artifact_basis'->(a.source->>'id');
 IF NOT COALESCE(native_basis->>'source_origin'='registered_native_text'
   AND native_basis->>'registration_receipt_id'=registration.id::text
   AND native_basis->>'registration_command_id'=registration.command_id::text
   AND native_basis->>'registration_actor_id'=registration.actor_id::text
   AND native_basis->>'registration_requester_id'=registration.requester_id::text
   AND native_basis->'registration_run_id'=COALESCE(to_jsonb(registration.run_id::text),'null'::jsonb)
   AND native_basis->>'registration_request_digest'=registration.request_digest
   AND native_basis->>'registration_intent_digest'=registration.intent_digest
   AND native_basis->>'sha256'=native.content_hash
   AND registration.requester_id=native.owner_id AND registration.visibility=native.visibility
   AND registration.result->>'id'=native.id::text
   AND (registration.result->>'revision')::integer=registration.subject_revision
   AND registration.result->>'status'='active',false)
 THEN RAISE EXCEPTION 'coverage requires exact native original registration'; END IF;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=tid
  AND product_id=a.product_id AND operation='change.coverage.import'
  AND subject_type='change_coverage_fact' AND subject_id=a.id AND subject_revision=a.revision;
 IF r.actor_id IS DISTINCT FROM a.actor_id OR r.requester_id IS DISTINCT FROM a.actor_id
  OR r.run_id IS NOT NULL OR r.command_id IS DISTINCT FROM a.command_id
  OR r.intent_digest IS DISTINCT FROM a.intent_digest OR r.request_digest IS DISTINCT FROM a.intent_digest
  OR r.visibility IS DISTINCT FROM a.visibility OR r.result IS DISTINCT FROM
    jsonb_build_object('id',a.id::text,'revision',a.revision,'status',a.status)
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id
   AND x.actor_id=r.actor_id AND x.operation=r.operation)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id
   AND x.actor_id=r.actor_id AND x.type='change.coverage_imported' AND x.subject_id=a.id
   AND x.subject_revision=a.revision AND x.schema_version=1 AND x.correlation_id=r.command_id)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=tid AND k.receipt_id=r.id
   AND k.actor_id=r.actor_id AND k.digest=r.request_digest)
  OR EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=tid AND k.receipt_id=r.id
   AND (k.actor_id IS DISTINCT FROM r.actor_id OR k.digest IS DISTINCT FROM r.request_digest))
 THEN RAISE EXCEPTION 'coverage requires one exact immutable common group'; END IF;
END $$;
"""


def _head(expected):
    if op.get_bind().scalar(text("SELECT version_num FROM alembic_version")) != expected:
        raise RuntimeError("Coverage JSON guard repair requires the exact installed head")
    op.execute(
        "LOCK TABLE controlled_change_coverage_facts,controlled_change_coverage_currents,"
        "action_receipts,audit_entries,outbox_events,request_keys IN SHARE ROW EXCLUSIVE MODE"
    )


def upgrade():
    _head(down_revision)
    op.execute(REPAIRED_SQL)


def downgrade():
    _head(revision)
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM controlled_change_coverage_facts) "
            "OR EXISTS(SELECT 1 FROM controlled_change_coverage_currents) "
            "OR EXISTS(SELECT 1 FROM action_receipts WHERE operation='change.coverage.import' "
            "OR subject_type='change_coverage_fact')"
        )
    ):
        raise RuntimeError("Retained coverage publication prevents destructive downgrade")
    op.execute(PRIOR_SQL)
