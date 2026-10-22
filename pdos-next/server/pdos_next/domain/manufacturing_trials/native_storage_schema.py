"""Uninstalled native Pilot storage; the migration caller owns role selection.

The actual domain host consumes the existing common T1 confirmation. These SQL
guards bind its real receipt/audit/event/original private request to the saved
row; they neither mint confirmation nor attest resource/start/release rights.
Public lifecycle catalogs and native-subject registrations belong to root's
serial migration. This module never connects, commits or changes shared code.
"""

# ruff: noqa: E501 -- Reviewed PostgreSQL keeps its clauses readable.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, DropConstraint

from .native_models import NativePilotCurrent, NativePilotObservation, NativePilotRun

TABLES = (
    NativePilotRun.__table__,
    NativePilotCurrent.__table__,
    NativePilotObservation.__table__,
)
OPERATIONS = "('npi.pilot.create','npi.pilot.result.record')"
SUBJECTS = "('pilot_run','pilot_observation')"


def table_sql():
    dialect = postgresql.dialect()
    return (
        *(
            str(statement.compile(dialect=dialect))
            for table in TABLES
            for statement in (
                CreateTable(table),
                *(CreateIndex(i) for i in sorted(table.indexes, key=lambda value: value.name)),
            )
        ),
        *(
            str(AddConstraint(fk).compile(dialect=dialect))
            for table in TABLES
            for fk in sorted(table.foreign_key_constraints, key=lambda value: value.name or "")
            if fk.use_alter
        ),
    )


def _function(name, arguments, body, *, returns="trigger"):
    return (
        f"CREATE FUNCTION public.{name}({arguments}) RETURNS {returns}\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp "
        f"AS $native_pilot$\n{body.rstrip()};\n$native_pilot$"
    )


# Historic replay validates the actual immutable common group. It deliberately
# does not require the original Product revision, Current, ACL or qualification
# to remain live when a later RequestKey alias is added by the common host.
MEMBERS = r"""
DECLARE v record; c public.confirmations; r public.action_receipts; command jsonb; event_name text;
BEGIN
 IF kind='pilot_run' THEN
  SELECT * INTO STRICT v FROM public.native_pilot_runs WHERE tenant_id=t AND id=target;
  event_name='pilot.created';
 ELSIF kind='pilot_observation' THEN
  SELECT * INTO STRICT v FROM public.native_pilot_observations WHERE tenant_id=t AND id=target;
  event_name='pilot.results_recorded';
 ELSE RAISE EXCEPTION 'Unknown native Pilot subject' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 command=v.input_snapshot->'command';
 IF ROW(c.category_id,c.product_id,c.actor_id,c.subject_type,c.subject_id,c.operation,c.revision)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,'product'::varchar,
    v.product_id,v.operation,v.shared_proof_revision)
  OR c.consumed IS DISTINCT FROM true OR c.token_hash IS DISTINCT FROM v.token_sha256
  OR c.payload_digest IS DISTINCT FROM v.material_sha256
  OR c.snapshot IS DISTINCT FROM v.input_snapshot->'review'
  OR c.expires_at IS NULL OR c.expires_at IS DISTINCT FROM v.proof_expires_at
  OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at
    AND v.created_at<=r.created_at AND r.created_at<c.expires_at)
  OR ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,
    r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.shared_proof_id,
    v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status','recorded')
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t
    AND x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.category_id=v.category_id
    AND a.receipt_id=r.id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.category_id=v.category_id
    AND e.receipt_id=r.id AND e.actor_id=v.actor_id AND e.type=event_name AND e.subject_id=v.id
    AND e.subject_revision=v.revision AND e.schema_version=1 AND e.correlation_id=v.command_id
    AND e.created_at>=v.created_at)
  OR v.input_snapshot->>'original_key_sha256' IS NULL
  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR command ? 'idempotency_key' OR (command->'payload') ? 'confirmation_token'
  OR (v.input_snapshot->'semantic') ? 'confirmation_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id
    AND k.receipt_id=r.id AND k.actor_id=v.actor_id AND k.digest=v.request_digest
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256')
 THEN RAISE EXCEPTION 'Native Pilot original T1 proof receipt audit event or request mismatch'
  USING ERRCODE='23514'; END IF;
END
"""

# SourceRef is the real artifact/line/hash shape, not a payload-supplied positive
# flag. The application owner additionally validates duplicate JSON keys and all
# typed original values before actual confirmation; SQL binds the stored values
# to that same real artifact line and exact UTF-8 line hash.
SOURCE_LINE = r"""
DECLARE a public.artifact_versions; position text[]; line text;
BEGIN
 position=regexp_match(src->>'position','^line:([1-9][0-9]*);quote_sha256:([a-f0-9]{64})$');
 IF src->>'kind' IS DISTINCT FROM 'artifact' OR position IS NULL
  OR jsonb_typeof(src->'revision') IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'Native Pilot original requires its exact artifact line' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT a FROM public.artifact_versions WHERE tenant_id=t AND category_id=category
  AND (product_id IS NULL OR product_id=product) AND id::text=src->>'id'
  AND revision::text=src->>'revision' AND status='active';
 line=(regexp_split_to_array(a.content,E'\r\n|[\n\r\013\014\034-\036\u0085\u2028\u2029]'))[position[1]::integer];
 IF line IS NULL OR encode(sha256(convert_to(line,'UTF8')),'hex')<>position[2] THEN
  RAISE EXCEPTION 'Native Pilot original line hash changed' USING ERRCODE='23514'; END IF;
 RETURN line;
END
"""

ORIGINAL = """BEGIN
 RETURN public.native_pilot_source_line(t,category,product,src)::jsonb;
EXCEPTION WHEN invalid_text_representation THEN
 RAISE EXCEPTION 'Native Pilot original values must be a supported JSON line' USING ERRCODE='23514';
END"""

PHYSICAL = r"""
DECLARE r public.native_pilot_runs; b public.builds; l public.build_lots;
 a public.actual_configurations; e public.engineering_configurations; p public.process_revisions;
 pub public.manufacturing_baseline_publications; ref jsonb; applicability jsonb;
BEGIN
 SELECT * INTO STRICT r FROM public.native_pilot_runs WHERE tenant_id=t AND id=pilot;
 SELECT * INTO STRICT b FROM public.builds WHERE tenant_id=t AND id=r.build_id;
 SELECT * INTO STRICT l FROM public.build_lots WHERE tenant_id=t AND id=r.lot_id;
 SELECT * INTO STRICT a FROM public.actual_configurations WHERE tenant_id=t AND id=r.actual_configuration_id;
 SELECT * INTO STRICT e FROM public.engineering_configurations WHERE tenant_id=t AND id=r.engineering_configuration_id;
 SELECT * INTO STRICT p FROM public.process_revisions WHERE tenant_id=t AND id=r.process_id;
 IF ROW(b.category_id,b.product_id,b.project_id,b.revision)
   IS DISTINCT FROM ROW(r.category_id,r.product_id,r.project_id,r.build_revision)
  OR ROW(l.category_id,l.product_id,l.project_id,l.build_id,l.build_revision,l.revision,
    l.actual_configuration_id,l.actual_configuration_revision,l.unit)
   IS DISTINCT FROM ROW(r.category_id,r.product_id,r.project_id,r.build_id,r.build_revision,r.lot_revision,
    r.actual_configuration_id,r.actual_configuration_revision,(r.details->'basis'->>'unit')::varchar)
  OR ROW(a.category_id,a.product_id,a.project_id,a.build_id,a.build_revision,a.revision,
    a.actual_engineering_configuration_id,a.actual_engineering_revision,
    a.actual_manufacturing_configuration_id,a.actual_manufacturing_revision)
   IS DISTINCT FROM ROW(r.category_id,r.product_id,r.project_id,r.build_id,r.build_revision,
    r.actual_configuration_revision,r.engineering_configuration_id,r.engineering_revision,r.process_id,r.process_revision)
  OR ROW(e.category_id,e.product_id,e.revision,p.category_id,p.product_id,p.revision,
    p.engineering_configuration_id,p.engineering_revision)
   IS DISTINCT FROM ROW(r.category_id,r.product_id,r.engineering_revision,r.category_id,r.product_id,
    r.process_revision,r.engineering_configuration_id,r.engineering_revision)
  OR NOT EXISTS(SELECT 1 FROM public.project_product_links link WHERE link.tenant_id=t
    AND link.product_id=r.product_id AND link.project_id=r.project_id
    AND link.definition_id=e.definition_id AND link.definition_revision=e.definition_revision)
  OR snapshot->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',r.product_id,'project_id',r.project_id)
  OR snapshot->>'category_id' IS DISTINCT FROM r.category_id::text
  OR snapshot->>'purpose' IS DISTINCT FROM r.purpose OR snapshot->'basis' IS DISTINCT FROM r.details->'basis'
  OR snapshot->>'qualification' IS DISTINCT FROM 'unknown'
  OR snapshot->'start_authorized' IS DISTINCT FROM 'false'::jsonb
  OR snapshot->'manufacturing_release' IS DISTINCT FROM 'null'::jsonb
  OR snapshot->'build'->>'id' IS DISTINCT FROM b.id::text
  OR snapshot->'build'->>'revision' IS DISTINCT FROM b.revision::text
  OR snapshot->'lot'->>'id' IS DISTINCT FROM l.id::text
  OR snapshot->'lot'->>'revision' IS DISTINCT FROM l.revision::text
  OR snapshot->'lot'->>'observed_unit_count' IS DISTINCT FROM l.observed_unit_count::text
  OR snapshot->'lot'->'observation'->>'nature' IS DISTINCT FROM l.observation_nature
  OR snapshot->'actual_configuration'->>'id' IS DISTINCT FROM a.id::text
  OR snapshot->'actual_configuration'->>'revision' IS DISTINCT FROM a.revision::text
  OR snapshot->'engineering_configuration'->>'id' IS DISTINCT FROM e.id::text
  OR snapshot->'engineering_configuration'->>'revision' IS DISTINCT FROM e.revision::text
  OR snapshot->'process'->>'id' IS DISTINCT FROM p.id::text
  OR snapshot->'process'->>'revision' IS DISTINCT FROM p.revision::text
  OR snapshot->'process'->'operations' IS DISTINCT FROM p.operations
  OR snapshot->'process'->>'site' IS DISTINCT FROM p.site OR snapshot->'process'->>'line' IS DISTINCT FROM p.line
 THEN RAISE EXCEPTION 'Native Pilot actual lot build configurations or project changed' USING ERRCODE='23514'; END IF;
 IF r.publication_id IS NULL THEN
  IF snapshot->'publication' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Native Pilot cannot invent a publication' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT pub FROM public.manufacturing_baseline_publications WHERE tenant_id=t AND id=r.publication_id;
  PERFORM public.assert_manufacturing_publication_members(t,pub.id);
  applicability=pub.body->'declaration'->'applicability';
  IF ROW(pub.category_id,pub.product_id,pub.project_id,pub.revision,pub.process_id,pub.process_revision,pub.purpose)
    IS DISTINCT FROM ROW(r.category_id,r.product_id,r.project_id,r.publication_revision,r.process_id,r.process_revision,r.purpose)
   OR snapshot->'publication'->>'id' IS DISTINCT FROM pub.id::text
   OR snapshot->'publication'->>'revision' IS DISTINCT FROM pub.revision::text
   OR snapshot->'publication'->'body' IS DISTINCT FROM pub.body
   OR (applicability->>'site' IS NOT NULL AND applicability->>'site' IS DISTINCT FROM p.site)
   OR (applicability->>'valid_from' IS NOT NULL AND at<(applicability->>'valid_from')::timestamptz)
   OR (applicability->>'valid_until' IS NOT NULL AND at>=(applicability->>'valid_until')::timestamptz)
   OR (r.details->'line'<>'null'::jsonb AND applicability->'lines'<>'null'::jsonb
    AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(applicability->'lines') x WHERE x=r.details->'line'))
  THEN RAISE EXCEPTION 'Native Pilot fixed publication or applicability mismatch' USING ERRCODE='23514'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(r.details->'instructions')
   UNION ALL SELECT r.details->'control_plan' WHERE r.details->'control_plan'<>'null'::jsonb LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(pub.body->'documents') x
    WHERE x->>'kind'=ref->>'kind' AND x->>'id'=ref->>'id' AND x->'revision'=ref->'revision') THEN
    RAISE EXCEPTION 'Native Pilot instruction is outside its fixed publication' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
END
"""

COMMON_ATOM = r"""
DECLARE v record; root public.native_pilot_runs; c public.confirmations; command jsonb; review jsonb;
 semantic jsonb; body jsonb; basis jsonb; dep jsonb; ref jsonb; vx xid; cx xid; rx xid;
BEGIN
 IF kind='pilot_run' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.native_pilot_runs x WHERE x.tenant_id=t AND x.id=target;
  SELECT * INTO STRICT root FROM public.native_pilot_runs WHERE tenant_id=t AND id=target;
  body=jsonb_build_object('details',v.details,'statistics_basis',v.statistics_basis);
 ELSIF kind='pilot_observation' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.native_pilot_observations x WHERE x.tenant_id=t AND x.id=target;
  SELECT * INTO STRICT root FROM public.native_pilot_runs WHERE tenant_id=t AND id=v.pilot_id;
  body=jsonb_build_object('record',v.record,'fixed_scope',v.fixed_scope,'projection',v.projection,
    'pilot_id',v.pilot_id,'pilot_revision_before',v.pilot_revision_before,'previous_observation_id',v.previous_observation_id);
 ELSE RAISE EXCEPTION 'Unknown native Pilot subject' USING ERRCODE='23514'; END IF;
 vx=v.tx;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=c.id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_native_pilot_members(t,target,kind);
 command=v.input_snapshot->'command'; semantic=v.input_snapshot->'semantic'; review=v.input_snapshot->'review';
 body=body||jsonb_build_object('material',v.material_snapshot,'gaps',v.gaps,'qualification','unknown',
   'start_authorized',false,'manufacturing_release',null,'external_delivery',false);
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.actor_id<>v.requester_id OR v.writer_id<>v.actor_id OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals x WHERE x.tenant_id=t AND x.id=v.actor_id AND x.kind='human' AND x.active)
  OR (v.visibility='private' AND v.owner_id<>v.actor_id)
  OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id
    AND p.id=v.product_id AND p.revision=v.shared_proof_revision)
  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id
    AND p.product_id=v.product_id AND p.id=v.project_id AND p.purpose=root.purpose)
  OR vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx
  OR ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility)
   IS DISTINCT FROM ROW(root.category_id,root.product_id,root.project_id,root.owner_id,root.visibility)
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)
   IS DISTINCT FROM ARRAY['command','original_key_sha256','previous_current','review','semantic']
  OR command->>'operation' IS DISTINCT FROM v.operation
  OR command->>'command_id' IS DISTINCT FROM v.command_id::text
  OR command->>'category_id' IS DISTINCT FROM v.category_id::text
  OR command->>'product_id' IS DISTINCT FROM v.product_id::text
  OR command->>'expected_revision' IS DISTINCT FROM v.shared_proof_revision::text
  OR command->'payload' IS DISTINCT FROM semantic
  OR command->'source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR review->>'operation' IS DISTINCT FROM v.operation OR review->'after' IS DISTINCT FROM body
  OR review->'authority' IS DISTINCT FROM v.authority_snapshot
  OR review->'read_basis' IS DISTINCT FROM v.source_basis
  OR review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR v.material_snapshot->'pilot'->>'product_revision' IS DISTINCT FROM v.shared_proof_revision::text
 THEN RAISE EXCEPTION 'Native Pilot requires its actual human T1 scope material and common transaction' USING ERRCODE='23514'; END IF;
 PERFORM public.assert_native_pilot_physical(t,root.id,v.material_snapshot->'pilot',v.created_at);
 IF EXISTS(SELECT 1 FROM (
   SELECT value AS dependency FROM jsonb_array_elements(v.authority_snapshot->'required_source_read_set')
   UNION ALL SELECT jsonb_build_object('artifact_id',x->>'id','expected_revision',x->'revision') FROM jsonb_array_elements(v.sources) x
   UNION ALL SELECT jsonb_build_object('artifact_id',x->>'id','expected_revision',x->'revision')
    FROM jsonb_path_query(semantic,'$.** ? (@.kind == "artifact" && exists(@.id) && exists(@.revision))') x
   UNION ALL SELECT reads.value FROM jsonb_each(v.material_snapshot->'pilot') child
    CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(child.value->'required_source_read_set')='array'
     THEN child.value->'required_source_read_set' ELSE '[]'::jsonb END) reads
  ) required WHERE NOT v.required_source_read_set @> jsonb_build_array(required.dependency))
  OR (SELECT count(DISTINCT x->>'artifact_id') FROM jsonb_array_elements(v.required_source_read_set) x)
    <>jsonb_array_length(v.required_source_read_set)
 THEN RAISE EXCEPTION 'Native Pilot source closure omits actual material' USING ERRCODE='23514'; END IF;
 basis=v.source_basis->'artifact_sources';
 IF jsonb_typeof(basis) IS DISTINCT FROM 'array' OR jsonb_array_length(basis)<>jsonb_array_length(v.required_source_read_set)
  OR (SELECT count(DISTINCT x->>'id') FROM jsonb_array_elements(basis) x)<>jsonb_array_length(basis) THEN
  RAISE EXCEPTION 'Native Pilot complete source basis missing' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP
  IF jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(basis) x JOIN public.artifact_versions a
    ON a.tenant_id=t AND a.category_id=v.category_id AND a.id::text=x->>'id'
     AND (a.product_id IS NULL OR a.product_id=v.product_id)
    WHERE x->>'id'=ref->>'artifact_id' AND x->>'revision'=ref->>'expected_revision'
     AND jsonb_typeof(x->'revision')='number' AND a.revision::text=x->>'revision'
     AND a.status='active' AND x->>'status'='active' AND a.content_hash=x->>'sha256'
     AND a.owner_id::text=x->>'owner_id' AND a.visibility=x->>'visibility'
     AND (v.visibility='private' OR a.visibility<>'private')
     AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o
      JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
      WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.status='parsed'
       AND o.revision::text=x->>'original_revision' AND o.content_hash=x->>'original_sha256'
       AND o.owner_id::text=x->>'original_owner_id' AND o.visibility=x->>'original_visibility'
       AND sec.epoch::text=x->>'security_epoch' AND sec.source_state='active' AND sec.disposition='active'
       AND (v.visibility='private' OR o.visibility<>'private'))))
  THEN RAISE EXCEPTION 'Native Pilot actual source version security or audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR dep IN SELECT value FROM jsonb_array_elements(v.sources) LOOP
  PERFORM public.native_pilot_source_line(t,v.category_id,v.product_id,dep);
 END LOOP;
 IF v.authority_snapshot->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
  OR v.authority_snapshot->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR v.authority_snapshot->>'operation' IS DISTINCT FROM v.operation
  OR v.authority_snapshot->>'purpose' IS DISTINCT FROM root.purpose
  OR v.authority_snapshot->'authorized' IS DISTINCT FROM 'true'::jsonb
  OR v.authority_snapshot->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR NOT(v.authority_snapshot->'roles' @> '["manufacturing"]'::jsonb)
  OR NOT public.capture_authority_time_current(v.authority_snapshot,v.created_at)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.authority_snapshot->'fact_refs')) THEN
  RAISE EXCEPTION 'Native Pilot actual professional authority missing' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.authority_snapshot->'fact_refs') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f JOIN public.professional_authority_current cur
   ON cur.tenant_id=f.tenant_id AND cur.category_id=f.category_id AND cur.product_id=f.product_id
    AND cur.project_id=f.project_id AND cur.subject_id=f.subject_id AND cur.kind=f.kind AND cur.series_id=f.series_id
    AND cur.fact_id=f.id AND cur.fact_revision=f.revision
   WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id AND f.project_id=v.project_id
    AND f.subject_id=v.actor_id AND f.id::text=ref->>'id' AND f.revision::text=ref->>'revision'
    AND cur.epoch::text=ref->>'epoch' AND f.fact_sha256=ref->>'fact_sha256' AND f.state=ref->>'state'
    AND f.role=ref->>'role' AND f.kind=ref->>'kind' AND f.series_id::text=ref->>'series_id'
    AND f.issuer_key=ref->>'issuer_key' AND f.issuer_version=ref->>'issuer_version' AND f.nature=ref->>'nature'
    AND f.operations=ref->'operations' AND f.purposes=ref->'purposes'
    AND f.valid_from IS NOT DISTINCT FROM (ref->>'valid_from')::timestamptz
    AND f.valid_until IS NOT DISTINCT FROM (ref->>'valid_until')::timestamptz) THEN
   RAISE EXCEPTION 'Native Pilot professional Current or fact changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id
   AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx
   AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Native Pilot common members must commit together' USING ERRCODE='23514'; END IF;
END
"""

ROOT_ATOM = r"""
DECLARE v public.native_pilot_runs; expected jsonb; raw jsonb; vx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.native_pilot_runs WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.native_pilot_runs WHERE tenant_id=t AND id=target;
 PERFORM public.assert_native_pilot_common(t,target,'pilot_run');
 IF v.input_snapshot->'semantic' IS DISTINCT FROM jsonb_build_object('project_id',v.project_id,
    'details',v.details,'statistics',v.statistics_basis,'visibility',v.visibility)
  OR v.details->>'pilot_id' IS DISTINCT FROM v.id::text
  OR v.details->>'purpose' IS DISTINCT FROM v.purpose
  OR v.details->'basis' IS DISTINCT FROM jsonb_build_object(
   'build',jsonb_build_object('kind','build','id',v.build_id,'revision',v.build_revision),
   'lot',jsonb_build_object('kind','build_lot','id',v.lot_id,'revision',v.lot_revision),
   'actual_configuration',jsonb_build_object('kind','actual_configuration','id',v.actual_configuration_id,'revision',v.actual_configuration_revision),
   'engineering_configuration',jsonb_build_object('kind','engineering_configuration','id',v.engineering_configuration_id,'revision',v.engineering_revision),
   'process_revision',jsonb_build_object('kind','process_revision','id',v.process_id,'revision',v.process_revision),
   'unit',v.details->'basis'->'unit')
  OR v.details->'manufacturing_baseline' IS DISTINCT FROM (CASE WHEN v.publication_id IS NULL THEN 'null'::jsonb
   ELSE jsonb_build_object('kind','manufacturing_baseline','id',v.publication_id,'revision',v.publication_revision) END)
  OR v.input_snapshot->'previous_current' IS DISTINCT FROM 'null'::jsonb
  OR v.input_snapshot->'review'->'before' IS DISTINCT FROM 'null'::jsonb
  OR NOT EXISTS(SELECT 1 FROM public.native_pilot_currents cur WHERE cur.tenant_id=t
   AND cur.category_id=v.category_id AND cur.product_id=v.product_id AND cur.project_id=v.project_id
   AND cur.pilot_id=v.id AND cur.owner_id=v.owner_id AND cur.visibility=v.visibility
   AND cur.revision=1 AND cur.epoch=1 AND cur.latest_observation_id IS NULL
   AND cur.xmin=vx)
 THEN RAISE EXCEPTION 'Native Pilot immutable root or initial Current mismatch' USING ERRCODE='23514'; END IF;
 IF v.statistics_basis IS NULL THEN
  IF coalesce(v.material_snapshot#>'{statistics,statistics}','null'::jsonb) IS DISTINCT FROM 'null'::jsonb
   OR v.material_snapshot->'fixed_scope' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Missing native Pilot declaration remains unknown' USING ERRCODE='23514'; END IF;
 ELSE
  expected=jsonb_build_object('schema_version','pdos-pilot-statistics-declaration-v1','pilot_id',v.id,
    'statistics',v.statistics_basis-'source');
  raw=public.native_pilot_original_values(t,v.category_id,v.product_id,v.statistics_basis->'source');
  IF raw IS DISTINCT FROM expected
   OR v.material_snapshot->'statistics'->'originals'->'statistics' IS DISTINCT FROM raw
   OR v.material_snapshot->'statistics'->'statistics' IS DISTINCT FROM v.statistics_basis THEN
   RAISE EXCEPTION 'Native Pilot declaration differs from its actual original values' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

OBSERVATION_ATOM = r"""
DECLARE v public.native_pilot_observations; root public.native_pilot_runs;
 previous public.native_pilot_observations; expected jsonb; original_record jsonb; raw jsonb; old_input jsonb; new_input jsonb; vx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.native_pilot_observations WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.native_pilot_observations WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT root FROM public.native_pilot_runs WHERE tenant_id=t AND id=v.pilot_id;
 PERFORM public.assert_native_pilot_common(t,target,'pilot_observation');
 PERFORM public.assert_native_pilot_members(t,root.id,'pilot_run');
 expected=jsonb_build_object('revision',v.pilot_revision_before,'epoch',v.pilot_revision_before,
   'latest_observation_id',v.previous_observation_id);
 IF v.input_snapshot->'semantic' IS DISTINCT FROM jsonb_build_object('pilot_id',v.pilot_id,
    'expected_pilot_revision',v.pilot_revision_before,'record',v.record)
  OR v.record->>'observation_id' IS DISTINCT FROM v.id::text
  OR v.record->>'expected_pilot_revision' IS DISTINCT FROM v.pilot_revision_before::text
  OR v.record->>'previous_observation_id' IS DISTINCT FROM v.previous_observation_id::text
  OR v.record->'scope'->'basis' IS DISTINCT FROM root.details->'basis'
  OR v.record->'scope'->'manufacturing_baseline' IS DISTINCT FROM root.details->'manufacturing_baseline'
  OR v.record->'scope'->'line' IS DISTINCT FROM root.details->'line'
  OR v.record->'scope'->>'nature' IS DISTINCT FROM v.material_snapshot->'pilot'->'lot'->'observation'->>'nature'
  OR (v.record->'observed'->>'occurred_at')::timestamptz>v.created_at
  OR v.input_snapshot->'previous_current' IS DISTINCT FROM expected
  OR v.input_snapshot->'review'->'before' IS DISTINCT FROM expected
  OR NOT EXISTS(SELECT 1 FROM public.native_pilot_currents cur WHERE cur.tenant_id=t
   AND cur.category_id=v.category_id AND cur.product_id=v.product_id AND cur.project_id=v.project_id
   AND cur.pilot_id=v.pilot_id AND cur.owner_id=v.owner_id AND cur.visibility=v.visibility
   AND cur.revision=v.revision AND cur.epoch=v.revision AND cur.latest_observation_id=v.id AND cur.xmin=vx)
  OR v.fixed_scope IS DISTINCT FROM nullif(v.material_snapshot->'fixed_scope','null'::jsonb)
  OR v.material_snapshot->'statistics'->'statistics' IS DISTINCT FROM coalesce(root.statistics_basis,'null'::jsonb)
 THEN RAISE EXCEPTION 'Native Pilot observation original CAS or fixed root mismatch' USING ERRCODE='23514'; END IF;
 IF v.pilot_revision_before=1 THEN
  IF v.previous_observation_id IS NOT NULL OR v.revision<>2 THEN
   RAISE EXCEPTION 'First native Pilot observation starts at revision two' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT previous FROM public.native_pilot_observations WHERE tenant_id=t AND id=v.previous_observation_id;
  PERFORM public.assert_native_pilot_members(t,previous.id,'pilot_observation');
  IF ROW(previous.category_id,previous.product_id,previous.project_id,previous.pilot_id,
    previous.owner_id,previous.visibility,previous.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.pilot_id,v.owner_id,v.visibility,v.pilot_revision_before)
   OR nullif(v.record->>'correction_reason','') IS NULL THEN
   RAISE EXCEPTION 'Native Pilot correction requires its exact predecessor and reason' USING ERRCODE='23514'; END IF;
  IF previous.fixed_scope IS NOT NULL THEN
   old_input=CASE WHEN previous.record->'counts'='null'::jsonb THEN to_jsonb(jsonb_array_length(previous.record->'units'))
     ELSE previous.record->'counts'->'input_count' END;
   new_input=CASE WHEN v.record->'counts'='null'::jsonb THEN to_jsonb(jsonb_array_length(v.record->'units'))
     ELSE v.record->'counts'->'input_count' END;
   IF v.fixed_scope IS NULL OR (v.fixed_scope-'pilot_revision') IS DISTINCT FROM (previous.fixed_scope-'pilot_revision')
    OR old_input IS DISTINCT FROM new_input
    OR (v.record->'observed'->>'occurred_at')::timestamptz<(previous.record->'observed'->>'occurred_at')::timestamptz THEN
    RAISE EXCEPTION 'Native Pilot correction cannot change its fixed scope denominator or reverse time' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF v.fixed_scope IS NULL THEN
  IF v.projection IS NOT NULL THEN
   RAISE EXCEPTION 'Unknown native Pilot scope cannot assert statistics' USING ERRCODE='23514'; END IF;
 ELSE
  IF v.fixed_scope->>'pilot_id' IS DISTINCT FROM v.pilot_id::text
   OR v.fixed_scope->>'pilot_revision' IS DISTINCT FROM v.pilot_revision_before::text
   OR v.fixed_scope->'scope' IS DISTINCT FROM v.material_snapshot->'pilot'->'scope'
   OR v.fixed_scope->'yield_scope' IS DISTINCT FROM v.record->'scope'
   OR (v.projection IS NOT NULL AND (v.projection->'fixed' IS DISTINCT FROM v.fixed_scope
    OR v.projection->>'observation_id' IS DISTINCT FROM v.id::text
    OR v.projection->'metrics'->>'process_capability' IS DISTINCT FROM 'NOT_ASSESSED'
    OR v.projection->'metrics'->>'factory_qualification' IS DISTINCT FROM 'NOT_ASSESSED'
    OR v.projection->'metrics'->'start_authorized' IS DISTINCT FROM 'false'::jsonb
    OR v.projection->'metrics'->'manufacturing_release' IS DISTINCT FROM 'null'::jsonb
    OR v.projection->'metrics'->'external_delivery_authorized' IS DISTINCT FROM 'false'::jsonb)) THEN
   RAISE EXCEPTION 'Native Pilot fixed statistics cannot grant capability start or release' USING ERRCODE='23514'; END IF;
 END IF;
 original_record=(v.record-'source')||jsonb_build_object('observed',(v.record->'observed')-'source',
  'units',(SELECT coalesce(jsonb_agg(x.value-'source' ORDER BY x.ordinality),'[]'::jsonb)
    FROM jsonb_array_elements(v.record->'units') WITH ORDINALITY x),
  'exceptions',(SELECT coalesce(jsonb_agg(x.value-'source'-'disposition' ORDER BY x.ordinality),'[]'::jsonb)
    FROM jsonb_array_elements(v.record->'exceptions') WITH ORDINALITY x));
 expected=jsonb_build_object('schema_version','pdos-pilot-result-values-v1','pilot_id',v.pilot_id,'record',original_record);
 raw=public.native_pilot_original_values(t,v.category_id,v.product_id,v.record->'source');
 IF raw IS DISTINCT FROM expected OR v.material_snapshot->'statistics'->'originals'->'record' IS DISTINCT FROM raw
  OR v.material_snapshot->'statistics'->'record' IS DISTINCT FROM v.record THEN
  RAISE EXCEPTION 'Native Pilot observation values differ from the actual original' USING ERRCODE='23514'; END IF;
END
"""

CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision=1 AND NEW.epoch=1 AND NEW.latest_observation_id IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['revision','epoch','latest_observation_id'])
    IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['revision','epoch','latest_observation_id'])
   AND NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1
   AND EXISTS(SELECT 1 FROM public.native_pilot_observations v WHERE v.tenant_id=NEW.tenant_id
    AND v.category_id=NEW.category_id AND v.product_id=NEW.product_id AND v.project_id=NEW.project_id
    AND v.pilot_id=NEW.pilot_id AND v.owner_id=NEW.owner_id AND v.visibility=NEW.visibility
    AND v.id=NEW.latest_observation_id AND v.revision=NEW.revision
    AND v.pilot_revision_before=OLD.revision AND v.previous_observation_id IS NOT DISTINCT FROM OLD.latest_observation_id)
   THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION 'Native Pilot Current only advances one exact observation and epoch' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE current_row public.native_pilot_currents; root public.native_pilot_runs; cx xid; rx xid;
BEGIN
 SELECT * INTO STRICT current_row FROM public.native_pilot_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO STRICT root FROM public.native_pilot_runs WHERE tenant_id=NEW.tenant_id AND id=current_row.pilot_id;
 SELECT xmin INTO cx FROM public.native_pilot_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO rx FROM public.native_pilot_runs WHERE tenant_id=NEW.tenant_id AND id=current_row.pilot_id;
 IF ROW(current_row.category_id,current_row.product_id,current_row.project_id,current_row.owner_id,current_row.visibility)
   IS DISTINCT FROM ROW(root.category_id,root.product_id,root.project_id,root.owner_id,root.visibility)
  OR current_row.revision<>current_row.epoch
  OR (SELECT count(*) FROM public.native_pilot_observations v WHERE v.tenant_id=root.tenant_id
    AND v.pilot_id=root.id)<>current_row.revision-1 THEN
  RAISE EXCEPTION 'Native Pilot Current requires the complete contiguous observation chain' USING ERRCODE='23514'; END IF;
 IF current_row.revision=1 THEN
  IF current_row.latest_observation_id IS NOT NULL OR cx IS DISTINCT FROM rx THEN
   RAISE EXCEPTION 'Initial native Pilot Current is part of root creation' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM public.native_pilot_observations v WHERE v.tenant_id=root.tenant_id
    AND v.id=current_row.latest_observation_id AND v.pilot_id=root.id
    AND v.revision=current_row.revision AND v.xmin=cx) THEN
   RAISE EXCEPTION 'Native Pilot Current requires its actual latest observation transaction' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

PROOF = f"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN {OPERATIONS}; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN {OPERATIONS}; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN
   RAISE EXCEPTION 'Native Pilot confirmation history is retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false OR NEW.expires_at IS NULL THEN
    RAISE EXCEPTION 'Native Pilot T1 proof starts unconsumed with its actual deadline' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Native Pilot confirmation permits only original false to true' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

TRANSITION = f"""
BEGIN
 IF NEW.operation IN {OPERATIONS} THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM (
    SELECT id FROM public.native_pilot_runs WHERE tenant_id=NEW.tenant_id AND shared_proof_id=NEW.id AND operation=NEW.operation
    UNION ALL SELECT id FROM public.native_pilot_observations WHERE tenant_id=NEW.tenant_id AND shared_proof_id=NEW.id AND operation=NEW.operation
   ) actual)<>1 THEN
   RAISE EXCEPTION 'Consumed native Pilot T1 proof requires exactly one actual subject' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {OPERATIONS} OR OLD.subject_type IN {SUBJECTS}; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {OPERATIONS} OR NEW.subject_type IN {SUBJECTS}; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Native Pilot receipt is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

MEMBER_GUARD = f"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
   AND (r.operation IN {OPERATIONS} OR r.subject_type IN {SUBJECTS})) INTO scoped;
 END IF;
 IF TG_OP<>'INSERT' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id
   AND (r.operation IN {OPERATIONS} OR r.subject_type IN {SUBJECTS})) INTO old_scoped;
 END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'
   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error'])
    IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Native Pilot original audit event or request is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

MEMBER_TARGET = f"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW;
 ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation IN {OPERATIONS} OR r.subject_type IN {SUBJECTS} THEN
  PERFORM public.assert_native_pilot_members(r.tenant_id,r.subject_id,r.subject_type::text);
 END IF;
 RETURN NULL;
END
"""

FUNCTION_SQL = {
    "assert_native_pilot_members(uuid,uuid,text)": _function(
        "assert_native_pilot_members", "t uuid,target uuid,kind text", MEMBERS, returns="void"
    ),
    "native_pilot_source_line(uuid,uuid,uuid,jsonb)": _function(
        "native_pilot_source_line",
        "t uuid,category uuid,product uuid,src jsonb",
        SOURCE_LINE,
        returns="text",
    ),
    "native_pilot_original_values(uuid,uuid,uuid,jsonb)": _function(
        "native_pilot_original_values",
        "t uuid,category uuid,product uuid,src jsonb",
        ORIGINAL,
        returns="jsonb",
    ),
    "assert_native_pilot_physical(uuid,uuid,jsonb,timestamptz)": _function(
        "assert_native_pilot_physical",
        "t uuid,pilot uuid,snapshot jsonb,at timestamptz",
        PHYSICAL,
        returns="void",
    ),
    "assert_native_pilot_common(uuid,uuid,text)": _function(
        "assert_native_pilot_common", "t uuid,target uuid,kind text", COMMON_ATOM, returns="void"
    ),
    "assert_native_pilot_root(uuid,uuid)": _function(
        "assert_native_pilot_root", "t uuid,target uuid", ROOT_ATOM, returns="void"
    ),
    "assert_native_pilot_observation(uuid,uuid)": _function(
        "assert_native_pilot_observation", "t uuid,target uuid", OBSERVATION_ATOM, returns="void"
    ),
    "protect_native_pilot_current()": _function("protect_native_pilot_current", "", CURRENT_GUARD),
    "require_native_pilot_current()": _function("require_native_pilot_current", "", CURRENT_ATOM),
    "protect_native_pilot_proof()": _function("protect_native_pilot_proof", "", PROOF),
    "require_native_pilot_transition()": _function(
        "require_native_pilot_transition", "", TRANSITION
    ),
    "protect_native_pilot_receipt()": _function("protect_native_pilot_receipt", "", RECEIPT_GUARD),
    "protect_native_pilot_member()": _function("protect_native_pilot_member", "", MEMBER_GUARD),
    "require_native_pilot_member()": _function("require_native_pilot_member", "", MEMBER_TARGET),
    "require_native_pilot_root()": _function(
        "require_native_pilot_root",
        "",
        "BEGIN PERFORM public.assert_native_pilot_root(NEW.tenant_id,NEW.id); RETURN NULL; END",
    ),
    "require_native_pilot_observation()": _function(
        "require_native_pilot_observation",
        "",
        "BEGIN PERFORM public.assert_native_pilot_observation(NEW.tenant_id,NEW.id); RETURN NULL; END",
    ),
    "reject_native_pilot_mutation()": _function(
        "reject_native_pilot_mutation",
        "",
        "BEGIN RAISE EXCEPTION 'Native Pilot roots and observations are immutable' USING ERRCODE='23514'; END",
    ),
}


def policy_sql():
    ledger = TABLES[0].name
    human = (
        "public.category_access(tenant_id,category_id,true) "
        "AND public.scope_actor()=public.scope_requester() "
        "AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
        "AND p.id=public.scope_actor() AND p.kind='human' AND p.active)"
    )
    visible = (
        "public.category_access(tenant_id,category_id) "
        f"AND ({ledger}.visibility='category' OR {ledger}.owner_id=public.scope_requester() "
        "OR EXISTS(SELECT 1 FROM public.object_audiences a "
        f"WHERE a.tenant_id={ledger}.tenant_id AND a.category_id={ledger}.category_id "
        f"AND a.object_type='{ledger}' AND a.subject_id={ledger}.id "
        f"AND a.owner_id={ledger}.owner_id AND a.principal_id=public.scope_requester())) "
        f"AND EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id={ledger}.tenant_id AND p.category_id={ledger}.category_id AND p.id={ledger}.product_id) "
        f"AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={ledger}.tenant_id AND p.category_id={ledger}.category_id AND p.product_id={ledger}.product_id AND p.id={ledger}.project_id) "
        f"AND EXISTS(SELECT 1 FROM public.builds b WHERE b.tenant_id={ledger}.tenant_id AND b.product_id={ledger}.product_id AND b.project_id={ledger}.project_id AND b.id={ledger}.build_id) "
        f"AND EXISTS(SELECT 1 FROM public.build_lots l WHERE l.tenant_id={ledger}.tenant_id AND l.product_id={ledger}.product_id AND l.project_id={ledger}.project_id AND l.id={ledger}.lot_id) "
        f"AND EXISTS(SELECT 1 FROM public.actual_configurations a WHERE a.tenant_id={ledger}.tenant_id AND a.product_id={ledger}.product_id AND a.id={ledger}.actual_configuration_id) "
        f"AND EXISTS(SELECT 1 FROM public.engineering_configurations e WHERE e.tenant_id={ledger}.tenant_id AND e.product_id={ledger}.product_id AND e.id={ledger}.engineering_configuration_id) "
        f"AND EXISTS(SELECT 1 FROM public.process_revisions p WHERE p.tenant_id={ledger}.tenant_id AND p.product_id={ledger}.product_id AND p.id={ledger}.process_id) "
        f"AND ({ledger}.publication_id IS NULL OR EXISTS(SELECT 1 FROM public.manufacturing_baseline_publications p WHERE p.tenant_id={ledger}.tenant_id AND p.product_id={ledger}.product_id AND p.id={ledger}.publication_id)) "
        f"AND public.direct_source_set_visible(tenant_id,category_id,product_id,{ledger}.required_source_read_set)"
    )
    statements = []
    for table in TABLES:
        name = table.name
        read = (
            visible
            if name == ledger
            else (
                "public.category_access(tenant_id,category_id) "
                f"AND EXISTS(SELECT 1 FROM public.{ledger} p WHERE p.tenant_id={name}.tenant_id "
                f"AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.project_id={name}.project_id "
                f"AND p.owner_id={name}.owner_id AND p.visibility={name}.visibility AND p.id={name}.pilot_id)"
                + (
                    f" AND public.direct_source_set_visible(tenant_id,category_id,product_id,{name}.required_source_read_set)"
                    if table is TABLES[2]
                    else ""
                )
            )
        )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING (true) WITH CHECK (true)',
                f'CREATE POLICY native_pilot_read ON public."{name}" FOR SELECT TO pdos_next_app USING ({read})',
                f'CREATE POLICY native_pilot_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK ({human} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table is TABLES[1]:
            statements.extend(
                (
                    f'CREATE POLICY native_pilot_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING ({human} AND {read}) WITH CHECK ({human} AND {read})',
                    f'GRANT UPDATE(revision,epoch,latest_observation_id) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER native_pilot_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER native_pilot_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    for table in (TABLES[0], TABLES[2]):
        statements.append(
            f"CREATE TRIGGER native_pilot_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.reject_native_pilot_mutation()"
        )
    statements.extend(
        (
            "CREATE TRIGGER native_pilot_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.native_pilot_currents FOR EACH ROW EXECUTE FUNCTION public.protect_native_pilot_current()",
            "CREATE CONSTRAINT TRIGGER native_pilot_current_atom AFTER INSERT OR UPDATE ON public.native_pilot_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_native_pilot_current()",
            "CREATE CONSTRAINT TRIGGER native_pilot_root_atom AFTER INSERT ON public.native_pilot_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_native_pilot_root()",
            "CREATE CONSTRAINT TRIGGER native_pilot_observation_atom AFTER INSERT ON public.native_pilot_observations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_native_pilot_observation()",
            "CREATE TRIGGER native_pilot_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_native_pilot_proof()",
            "CREATE CONSTRAINT TRIGGER native_pilot_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_native_pilot_transition()",
            "CREATE TRIGGER native_pilot_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_native_pilot_receipt()",
        )
    )
    for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER native_pilot_member_atom AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_native_pilot_member()"
        )
        if name != "action_receipts":
            statements.append(
                f"CREATE TRIGGER native_pilot_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.protect_native_pilot_member()"
            )
    return tuple(statements)


def install_sql():
    return (
        *table_sql(),
        *FUNCTION_SQL.values(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in FUNCTION_SQL
        ),
        *policy_sql(),
        *trigger_sql(),
    )


def uninstall_sql():
    dialect = postgresql.dialect()
    return (
        "LOCK TABLE public.native_pilot_runs,public.native_pilot_currents,public.native_pilot_observations,public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        f"""DO $native_pilot$ BEGIN
 IF EXISTS(SELECT 1 FROM public.native_pilot_runs) OR EXISTS(SELECT 1 FROM public.native_pilot_currents)
  OR EXISTS(SELECT 1 FROM public.native_pilot_observations)
  OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {OPERATIONS})
  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPERATIONS} OR subject_type IN {SUBJECTS}) THEN
  RAISE EXCEPTION 'Native Pilot business history is retained; downgrade refused' USING ERRCODE='23514';
 END IF;
END; $native_pilot$""",
        "DROP TRIGGER native_pilot_proof_guard ON public.confirmations",
        "DROP TRIGGER native_pilot_proof_target ON public.confirmations",
        "DROP TRIGGER native_pilot_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER native_pilot_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER native_pilot_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(
            str(DropConstraint(fk).compile(dialect=dialect))
            for table in TABLES
            for fk in sorted(table.foreign_key_constraints, key=lambda value: value.name or "")
            if fk.use_alter
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(FUNCTION_SQL)),
    )


def install(connection):
    """Use the selected ordinary owner and caller's migration transaction."""
    for statement in install_sql():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})


def uninstall(connection):
    """Refuse any retained native business history before dropping its family."""
    for statement in uninstall_sql():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
