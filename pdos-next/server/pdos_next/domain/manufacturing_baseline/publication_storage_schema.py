"""Installable publication storage contract; no migration or public registration.

The migration caller must select the existing ordinary ``pdos_next_owner`` role.
This module never connects, commits, changes roles or alters common namespaces.
The shared immutable record retains the original key's raw UTF-8 SHA256 only.
Common RequestKey rows keep their existing own-actor RLS and full original key.
"""

# ruff: noqa: E501 -- PostgreSQL statements retain readable, reviewed clauses.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .publication_models import (
    ManufacturingBaselinePublication,
    ManufacturingBaselinePublicationCurrent,
    ManufacturingPublicationDocument,
)

TABLES = (
    ManufacturingBaselinePublication.__table__,
    ManufacturingBaselinePublicationCurrent.__table__,
    ManufacturingPublicationDocument.__table__,
)


def table_sql():
    dialect = postgresql.dialect()
    return tuple(
        str(statement.compile(dialect=dialect))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(i) for i in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def _function(name, arguments, body, *, returns="trigger"):
    return (
        f"CREATE FUNCTION public.{name}({arguments}) RETURNS {returns}\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp "
        f"AS $publication$\n{body.rstrip()};\n$publication$"
    )


# Full immutable group checks are also used for a later RequestKey alias. They
# deliberately do not reauthorize a historic signature or require its old Current.
MEMBERS = r"""
DECLARE v public.manufacturing_baseline_publications; c public.confirmations;
 r public.action_receipts; command jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.manufacturing_baseline_publications
  WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 command=v.input_snapshot->'command';
 IF ROW(c.category_id,c.product_id,c.actor_id,c.subject_type,c.subject_id,c.operation,c.revision)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,'product'::varchar,
    v.product_id,v.operation,v.shared_proof_revision)
  OR c.consumed IS DISTINCT FROM true OR c.token_hash IS DISTINCT FROM v.token_sha256
  OR c.payload_digest IS DISTINCT FROM v.material_sha256
  OR c.snapshot IS DISTINCT FROM v.input_snapshot->'review'
  OR c.expires_at IS DISTINCT FROM v.proof_expires_at
  OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at
    AND v.created_at<=r.created_at
    AND (c.expires_at IS NULL OR r.created_at<c.expires_at))
  OR ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,
    r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,
    r.request_digest,r.intent_digest)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.shared_proof_id,
    v.actor_id,v.requester_id,v.operation,'manufacturing_publication'::varchar,
    v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR r.result->>'id' IS DISTINCT FROM v.id::text
  OR r.result->>'revision' IS DISTINCT FROM v.revision::text
  OR jsonb_typeof(r.result->'revision') IS DISTINCT FROM 'number'
  OR r.result->>'status' IS DISTINCT FROM 'published'
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t
    AND x.operation=v.operation AND x.subject_type='manufacturing_publication'
    AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t
    AND a.category_id=v.category_id AND a.receipt_id=r.id AND a.actor_id=v.actor_id
    AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t
    AND e.category_id=v.category_id AND e.receipt_id=r.id AND e.actor_id=v.actor_id
    AND e.type='manufacturing_baseline.published' AND e.subject_id=v.id
    AND e.subject_revision=v.revision AND e.schema_version=1
    AND e.correlation_id=v.command_id AND e.created_at>=v.created_at)
  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR v.input_snapshot->>'original_key_sha256' IS NULL
  OR command ? 'idempotency_key' OR (command->'payload') ? 'approval_token'
  OR (v.input_snapshot->'semantic') ? 'approval_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t
    AND k.category_id=v.category_id AND k.receipt_id=r.id AND k.actor_id=v.actor_id
    AND k.digest=v.request_digest
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256')
 THEN RAISE EXCEPTION 'Publication original confirmation receipt audit event or request mismatch'
  USING ERRCODE='23514'; END IF;
END
"""

ATOM = r"""
DECLARE v public.manufacturing_baseline_publications; b public.manufacturing_preparation_versions;
 p public.process_revisions; c public.confirmations; plan jsonb; review jsonb; command jsonb;
 ref jsonb; basis jsonb; doc jsonb; vx xid; cx xid; rx xid;
BEGIN
 SELECT x.* INTO STRICT v FROM public.manufacturing_baseline_publications x
  WHERE x.tenant_id=t AND x.id=target;
 SELECT xmin INTO vx FROM public.manufacturing_baseline_publications WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT b FROM public.manufacturing_preparation_versions
  WHERE tenant_id=t AND id=v.baseline_id;
 SELECT * INTO STRICT p FROM public.process_revisions WHERE tenant_id=t AND id=v.process_id;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=c.id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 plan=v.input_snapshot->'plan'; review=v.input_snapshot->'review';
 command=v.input_snapshot->'command';
 IF v.actor_id IS DISTINCT FROM public.scope_actor()
  OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.actor_id IS DISTINCT FROM v.requester_id OR v.writer_id IS DISTINCT FROM v.actor_id
  OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id
    AND a.kind='human' AND a.active)
  OR (v.visibility='private' AND v.owner_id<>v.actor_id)
  OR NOT EXISTS(SELECT 1 FROM public.products x WHERE x.tenant_id=t AND x.id=v.product_id
    AND x.category_id=v.category_id AND x.revision=c.revision)
  OR NOT EXISTS(SELECT 1 FROM public.projects x WHERE x.tenant_id=t AND x.id=v.project_id
    AND x.product_id=v.product_id AND x.category_id=v.category_id
    AND x.purpose=v.purpose)
  OR vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx
 THEN RAISE EXCEPTION 'Publication requires the current named human scope and one transaction'
  USING ERRCODE='23514'; END IF;
 PERFORM public.assert_manufacturing_publication_members(t,target);
 IF plan->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,
    'project_id',v.project_id)
  OR plan->>'category_id' IS DISTINCT FROM v.category_id::text
  OR plan->>'product_revision' IS DISTINCT FROM c.revision::text
  OR plan->>'owner_id' IS DISTINCT FROM v.owner_id::text
  OR plan->>'visibility' IS DISTINCT FROM v.visibility OR plan->>'purpose' IS DISTINCT FROM v.purpose
  OR plan->'body' IS DISTINCT FROM v.body OR plan->>'body_sha256' IS DISTINCT FROM v.body_sha256
  OR plan->>'payload_sha256' IS DISTINCT FROM v.payload_sha256
  OR plan->'sources' IS DISTINCT FROM v.sources
  OR plan->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR plan->'gaps' IS DISTINCT FROM v.gaps
  OR plan->'input_snapshot' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR plan->'baseline' IS DISTINCT FROM jsonb_build_object('kind','manufacturing_baseline',
    'id',v.baseline_id,'revision',v.baseline_revision)
  OR plan->'process' IS DISTINCT FROM jsonb_build_object('id',v.process_id,'revision',v.process_revision)
  OR v.body->'scope' IS DISTINCT FROM plan->'scope'
  OR v.body->>'category_id' IS DISTINCT FROM v.category_id::text
  OR v.body->>'owner_id' IS DISTINCT FROM v.owner_id::text
  OR v.body->'declaration' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR v.body->'baseline_snapshot' IS DISTINCT FROM b.body
  OR v.body->'fixed_process' IS DISTINCT FROM plan->'process'
  OR v.body->>'qualification' IS DISTINCT FROM 'unknown'
  OR v.body->'manufacturing_release' IS DISTINCT FROM 'null'::jsonb
  OR review->>'operation' IS DISTINCT FROM v.operation
  OR review->'after'->'body' IS DISTINCT FROM v.body
  OR review->'after'->>'revision' IS DISTINCT FROM v.revision::text
  OR jsonb_typeof(review->'after'->'revision') IS DISTINCT FROM 'number'
  OR review->'after'->>'status' IS DISTINCT FROM 'published'
  OR review->'authority' IS DISTINCT FROM v.authority_snapshot
  OR review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR review->'read_basis' IS DISTINCT FROM v.source_basis
  OR review->'gaps' IS DISTINCT FROM v.gaps
  OR command->>'operation' IS DISTINCT FROM v.operation
  OR command->>'category_id' IS DISTINCT FROM v.category_id::text
  OR command->>'product_id' IS DISTINCT FROM v.product_id::text
  OR command->>'command_id' IS DISTINCT FROM v.command_id::text
  OR command->>'expected_revision' IS DISTINCT FROM c.revision::text
  OR command->'source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR command->'payload' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR v.input_snapshot->'semantic'->>'previous_id' IS DISTINCT FROM v.previous_id::text
  OR v.input_snapshot->'semantic'->>'expected_previous_revision' IS DISTINCT FROM v.previous_revision::text
 THEN RAISE EXCEPTION 'Publication fixed body original command and reviewed material mismatch'
  USING ERRCODE='23514'; END IF;
 IF ROW(b.category_id,b.product_id,b.project_id,b.kind,b.revision,b.owner_id,b.visibility,
    b.process_id,b.process_revision)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,'manufacturing_baseline'::varchar,
    v.baseline_revision,v.owner_id,v.visibility,v.process_id,v.process_revision)
  OR b.status<>'draft' OR p.product_id<>v.product_id OR p.category_id<>v.category_id
  OR p.revision<>v.process_revision
  OR v.body->'process_snapshot'->>'id' IS DISTINCT FROM p.id::text
  OR v.body->'process_snapshot'->>'revision' IS DISTINCT FROM p.revision::text
  OR v.body->'process_snapshot'->'operations' IS DISTINCT FROM p.operations
  OR v.body->'process_snapshot'->>'engineering_configuration_id'
    IS DISTINCT FROM p.engineering_configuration_id::text
  OR v.body->'process_snapshot'->>'engineering_revision' IS DISTINCT FROM p.engineering_revision::text
  OR v.body->'process_snapshot'->'site' IS DISTINCT FROM b.body->'process_snapshot'->'site'
  OR v.body->'process_snapshot'->'line' IS DISTINCT FROM b.body->'process_snapshot'->'line'
  OR v.body->'process_snapshot'->>'site' IS DISTINCT FROM p.site
  OR v.body->'process_snapshot'->>'line' IS DISTINCT FROM p.line
  OR NOT EXISTS(SELECT 1 FROM public.engineering_configurations e
    JOIN public.project_product_links l ON l.tenant_id=e.tenant_id AND l.product_id=e.product_id
    WHERE e.tenant_id=t AND e.product_id=v.product_id AND e.id=p.engineering_configuration_id
    AND e.revision=p.engineering_revision AND l.project_id=v.project_id
    AND e.definition_id=l.definition_id AND e.definition_revision=l.definition_revision)
 THEN RAISE EXCEPTION 'Publication fixed preparation process engineering or project mismatch'
  USING ERRCODE='23514'; END IF;
 IF v.previous_id IS NULL THEN
  IF plan->'previous' IS DISTINCT FROM 'null'::jsonb
   OR v.input_snapshot->'previous_current' IS DISTINCT FROM 'null'::jsonb
   OR review->'before' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'First publication has no invented predecessor' USING ERRCODE='23514'; END IF;
 ELSE
  IF plan->'previous' IS DISTINCT FROM jsonb_build_object('id',v.previous_id,'revision',v.previous_revision)
   OR v.input_snapshot->'previous_current'->'version' IS DISTINCT FROM plan->'previous'
   OR v.input_snapshot->'previous_current'->'scope' IS DISTINCT FROM plan->'scope'
   OR v.input_snapshot->'previous_current'->>'category_id' IS DISTINCT FROM v.category_id::text
   OR v.input_snapshot->'previous_current'->>'series_id' IS DISTINCT FROM v.series_id::text
   OR v.input_snapshot->'previous_current'->>'owner_id' IS DISTINCT FROM v.owner_id::text
   OR v.input_snapshot->'previous_current'->>'visibility' IS DISTINCT FROM v.visibility
   OR NOT EXISTS(SELECT 1 FROM public.manufacturing_baseline_publications old
    WHERE old.tenant_id=t AND old.id=v.previous_id AND old.revision=v.previous_revision
     AND old.series_id=v.series_id AND old.category_id=v.category_id AND old.product_id=v.product_id
     AND old.project_id=v.project_id AND old.owner_id=v.owner_id AND old.visibility=v.visibility)
  THEN RAISE EXCEPTION 'Publication predecessor and saved CAS mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.manufacturing_publication_currents cur
   WHERE cur.tenant_id=t AND cur.category_id=v.category_id AND cur.product_id=v.product_id
    AND cur.project_id=v.project_id AND cur.series_id=v.series_id AND cur.owner_id=v.owner_id
    AND cur.visibility=v.visibility AND cur.version_id=v.id AND cur.revision=v.revision
    AND cur.epoch=CASE WHEN v.previous_id IS NULL THEN 1
      ELSE (v.input_snapshot->'previous_current'->>'epoch')::integer+1 END)
 THEN RAISE EXCEPTION 'Publication requires its exact Current and CAS epoch' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(v.body->'documents') IS DISTINCT FROM 'array'
  OR (SELECT count(*) FROM public.manufacturing_publication_documents d
    WHERE d.tenant_id=t AND d.publication_id=v.id)<>jsonb_array_length(v.body->'documents')
  OR jsonb_array_length(v.body->'documents')<>jsonb_array_length(b.body->'document_bindings')
  OR (SELECT count(*) FROM (SELECT DISTINCT x->>'operation_key',x->>'kind'
    FROM jsonb_array_elements(v.body->'documents') x) unique_documents)
    <>jsonb_array_length(v.body->'documents')
 THEN RAISE EXCEPTION 'Publication fixed document set mismatch' USING ERRCODE='23514'; END IF;
 FOR doc IN SELECT value FROM jsonb_array_elements(v.body->'documents') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.manufacturing_publication_documents d
   JOIN public.manufacturing_preparation_versions child ON child.tenant_id=d.tenant_id
    AND child.category_id=d.category_id AND child.product_id=d.product_id AND child.id=d.document_id
   WHERE d.tenant_id=t AND d.category_id=v.category_id AND d.product_id=v.product_id
    AND d.project_id=v.project_id AND d.publication_id=v.id AND d.publication_revision=v.revision
    AND d.process_id=v.process_id AND d.process_revision=v.process_revision
    AND d.operation_key=doc->>'operation_key' AND d.document_kind=doc->>'kind'
    AND d.document_id::text=doc->>'id' AND d.document_revision::text=doc->>'revision'
    AND child.project_id=v.project_id AND child.process_id=v.process_id
    AND child.process_revision=v.process_revision AND child.operation_key=d.operation_key
    AND child.kind=d.document_kind AND child.revision=d.document_revision
    AND child.body=doc->'body' AND child.body_sha256=doc->>'body_sha256'
    AND (v.visibility='private' OR child.visibility<>'private'))
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(b.body->'document_bindings') fixed
     WHERE fixed=doc-'body') THEN
   RAISE EXCEPTION 'Publication exact operation document or fixed body mismatch'
    USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(
  SELECT 1 FROM (
   SELECT value AS dependency FROM jsonb_array_elements(b.required_source_read_set)
   UNION ALL SELECT value FROM jsonb_array_elements(p.required_source_read_set)
   UNION ALL SELECT value FROM jsonb_array_elements(v.authority_snapshot->'required_source_read_set')
   UNION ALL SELECT jsonb_build_object('artifact_id',src->>'artifact_id',
    'expected_revision',src->'expected_revision') FROM jsonb_array_elements(v.sources) src
   UNION ALL SELECT dep.value FROM public.manufacturing_publication_documents link
    JOIN public.manufacturing_preparation_versions child ON child.tenant_id=link.tenant_id
     AND child.id=link.document_id
    CROSS JOIN LATERAL jsonb_array_elements(child.required_source_read_set) dep
    WHERE link.tenant_id=t AND link.publication_id=v.id
  ) required WHERE NOT v.required_source_read_set @> jsonb_build_array(required.dependency))
  OR EXISTS(SELECT 1 FROM jsonb_path_query(v.input_snapshot->'semantic',
    '$.** ? (exists(@.artifact_id) && exists(@.expected_revision))') src
   WHERE NOT v.required_source_read_set @> jsonb_build_array(jsonb_build_object(
    'artifact_id',src->>'artifact_id','expected_revision',src->'expected_revision')))
 THEN RAISE EXCEPTION 'Publication source closure omits a fixed material dependency'
  USING ERRCODE='23514'; END IF;
 basis=v.source_basis->'artifact_sources';
 IF jsonb_typeof(basis) IS DISTINCT FROM 'array'
  OR jsonb_array_length(basis)<>jsonb_array_length(v.required_source_read_set)
  OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(basis))<>jsonb_array_length(basis)
 THEN RAISE EXCEPTION 'Publication complete source basis missing' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP
  IF jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(basis) x
    JOIN public.artifact_versions a ON a.tenant_id=t AND a.category_id=v.category_id
     AND a.id::text=x->>'id' AND (a.product_id IS NULL OR a.product_id=v.product_id)
    WHERE x->>'id'=ref->>'artifact_id' AND x->>'revision'=ref->>'expected_revision'
     AND jsonb_typeof(x->'revision')='number' AND a.revision::text=x->>'revision'
     AND a.status='active' AND x->>'status'='active' AND a.content_hash=x->>'sha256'
     AND a.owner_id::text=x->>'owner_id' AND a.visibility=x->>'visibility'
     AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o
       JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
       WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id
        AND o.status='parsed' AND o.content_hash=x->>'original_sha256'
        AND o.revision::text=x->>'original_revision' AND sec.epoch::text=x->>'security_epoch'
        AND sec.source_state='active' AND sec.disposition='active')))
  THEN RAISE EXCEPTION 'Publication actual source version or safety changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF v.authority_snapshot->'scope' IS DISTINCT FROM plan->'scope'
  OR v.authority_snapshot->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR v.authority_snapshot->>'operation' IS DISTINCT FROM v.operation
  OR v.authority_snapshot->>'purpose' IS DISTINCT FROM v.purpose
  OR v.authority_snapshot->'authorized' IS DISTINCT FROM 'true'::jsonb
  OR v.authority_snapshot->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR NOT(v.authority_snapshot->'roles' @> '["manufacturing"]'::jsonb)
  OR NOT public.capture_authority_time_current(v.authority_snapshot,v.created_at)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.authority_snapshot->'fact_refs'))
 THEN RAISE EXCEPTION 'Publication named manufacturing authority missing' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.authority_snapshot->'fact_refs') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f
    JOIN public.professional_authority_current cur ON cur.tenant_id=f.tenant_id
     AND cur.category_id=f.category_id AND cur.product_id=f.product_id AND cur.project_id=f.project_id
     AND cur.subject_id=f.subject_id AND cur.kind=f.kind AND cur.series_id=f.series_id
     AND cur.fact_id=f.id AND cur.fact_revision=f.revision
    WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id
     AND f.project_id=v.project_id AND f.subject_id=v.actor_id AND f.id::text=ref->>'id'
     AND f.revision::text=ref->>'revision' AND cur.epoch::text=ref->>'epoch'
     AND f.fact_sha256=ref->>'fact_sha256' AND f.state=ref->>'state'
     AND f.role=ref->>'role' AND f.kind=ref->>'kind' AND f.series_id::text=ref->>'series_id'
     AND f.issuer_key=ref->>'issuer_key' AND f.issuer_version=ref->>'issuer_version'
     AND f.nature=ref->>'nature'
     AND f.operations=ref->'operations' AND f.purposes=ref->'purposes'
     AND f.valid_from=(ref->>'valid_from')::timestamptz
     AND f.valid_until=(ref->>'valid_until')::timestamptz)
  THEN RAISE EXCEPTION 'Publication actual professional Current or fact changed'
   USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=v.receipt_id
     AND a.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=v.receipt_id
     AND e.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id
    AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256')
 THEN RAISE EXCEPTION 'Publication common members must commit in one transaction'
  USING ERRCODE='23514'; END IF;
END
"""

PROOF = r"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation='npi.manufacturing_baseline.publish'; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation='npi.manufacturing_baseline.publish'; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN
   RAISE EXCEPTION 'Publication decision history is retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN
    RAISE EXCEPTION 'Publication decision starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false
   OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Publication decision only permits its original false to true'
    USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

TRANSITION = r"""
BEGIN
 IF NEW.operation='npi.manufacturing_baseline.publish' THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM public.manufacturing_baseline_publications v
    WHERE v.tenant_id=NEW.tenant_id AND v.shared_proof_id=NEW.id)<>1 THEN
   RAISE EXCEPTION 'Consumed publication decision requires one actual new publication'
    USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision=1 AND NEW.epoch=1 THEN RETURN NEW; END IF;
 ELSIF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['version_id','revision','epoch'])
    IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['version_id','revision','epoch'])
   AND NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1
   AND EXISTS(SELECT 1 FROM public.manufacturing_baseline_publications v
    WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id AND v.revision=NEW.revision
     AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision)
  THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION 'Publication Current only advances one exact successor and epoch'
  USING ERRCODE='23514';
END
"""

RECEIPT_GUARD = r"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation='npi.manufacturing_baseline.publish'
  OR OLD.subject_type='manufacturing_publication'; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation='npi.manufacturing_baseline.publish'
  OR NEW.subject_type='manufacturing_publication'; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Publication receipt is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

MEMBER_GUARD = r"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id
   AND r.id=NEW.receipt_id AND (r.operation='npi.manufacturing_baseline.publish'
    OR r.subject_type='manufacturing_publication')) INTO scoped;
 END IF;
 IF TG_OP<>'INSERT' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id
   AND r.id=OLD.receipt_id AND (r.operation='npi.manufacturing_baseline.publish'
    OR r.subject_type='manufacturing_publication')) INTO old_scoped;
 END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'
   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error'])
    IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error'])
  THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Publication original audit event or request is immutable'
   USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END
"""

MEMBER_TARGET = r"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW;
 ELSE SELECT * INTO r FROM public.action_receipts
  WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation='npi.manufacturing_baseline.publish' OR r.subject_type='manufacturing_publication' THEN
  PERFORM public.assert_manufacturing_publication_members(r.tenant_id,r.subject_id);
 END IF;
 RETURN NULL;
END
"""

FUNCTION_SQL = {
    "assert_manufacturing_publication_members(uuid,uuid)": _function(
        "assert_manufacturing_publication_members", "t uuid,target uuid", MEMBERS, returns="void"
    ),
    "assert_manufacturing_publication_atom(uuid,uuid)": _function(
        "assert_manufacturing_publication_atom", "t uuid,target uuid", ATOM, returns="void"
    ),
    "protect_manufacturing_publication_proof()": _function(
        "protect_manufacturing_publication_proof", "", PROOF
    ),
    "require_manufacturing_publication_transition()": _function(
        "require_manufacturing_publication_transition", "", TRANSITION
    ),
    "protect_manufacturing_publication_current()": _function(
        "protect_manufacturing_publication_current", "", CURRENT_GUARD
    ),
    "protect_manufacturing_publication_receipt()": _function(
        "protect_manufacturing_publication_receipt", "", RECEIPT_GUARD
    ),
    "protect_manufacturing_publication_member()": _function(
        "protect_manufacturing_publication_member", "", MEMBER_GUARD
    ),
    "require_manufacturing_publication_member()": _function(
        "require_manufacturing_publication_member", "", MEMBER_TARGET
    ),
    "require_manufacturing_publication_atom()": _function(
        "require_manufacturing_publication_atom",
        "",
        "BEGIN PERFORM public.assert_manufacturing_publication_atom(NEW.tenant_id,NEW.id); "
        "RETURN NULL; END",
    ),
    "require_manufacturing_publication_document()": _function(
        "require_manufacturing_publication_document",
        "",
        """BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.manufacturing_baseline_publications v
  JOIN public.manufacturing_publication_documents d ON d.tenant_id=v.tenant_id
   AND d.publication_id=v.id AND d.xmin=v.xmin
  WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.publication_id AND d.id=NEW.id) THEN
  RAISE EXCEPTION 'Fixed publication links must be inserted with their publication'
   USING ERRCODE='23514'; END IF;
 PERFORM public.assert_manufacturing_publication_members(NEW.tenant_id,NEW.publication_id);
 RETURN NULL; END""",
    ),
    "reject_manufacturing_publication_mutation()": _function(
        "reject_manufacturing_publication_mutation",
        "",
        "BEGIN RAISE EXCEPTION 'Publication fixed records are append only' USING ERRCODE='23514'; END",
    ),
}


def policy_sql():
    ledger = TABLES[0].name
    # Parent SELECTs deliberately execute under caller RLS. In particular the
    # publication inherits the baseline's private/category/audience readers.
    visible = (
        "public.category_access(tenant_id,category_id) "
        f"AND EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id={ledger}.tenant_id "
        f"AND p.category_id={ledger}.category_id AND p.id={ledger}.product_id) "
        f"AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={ledger}.tenant_id "
        f"AND p.category_id={ledger}.category_id AND p.product_id={ledger}.product_id "
        f"AND p.id={ledger}.project_id) "
        "AND EXISTS(SELECT 1 FROM public.manufacturing_preparation_versions b "
        f"WHERE b.tenant_id={ledger}.tenant_id AND b.category_id={ledger}.category_id "
        f"AND b.product_id={ledger}.product_id AND b.project_id={ledger}.project_id "
        f"AND b.id={ledger}.baseline_id AND b.revision={ledger}.baseline_revision "
        f"AND b.owner_id={ledger}.owner_id AND b.visibility={ledger}.visibility) "
        f"AND public.direct_source_set_visible(tenant_id,category_id,product_id,{ledger}.required_source_read_set) "
        f"AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements({ledger}.body->'documents') doc "
        "WHERE NOT EXISTS(SELECT 1 FROM public.manufacturing_preparation_versions d "
        f"WHERE d.tenant_id={ledger}.tenant_id AND d.category_id={ledger}.category_id "
        f"AND d.product_id={ledger}.product_id AND d.project_id={ledger}.project_id "
        "AND d.id::text=doc->>'id' AND d.revision::text=doc->>'revision'))"
    )
    human = (
        "public.category_access(tenant_id,category_id,true) "
        "AND public.scope_actor()=public.scope_requester() "
        "AND EXISTS(SELECT 1 FROM public.principals a "
        "WHERE a.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
        "AND a.id=public.scope_actor() AND a.kind='human' AND a.active)"
    )
    statements = []
    for table in TABLES:
        name = table.name
        if name == ledger:
            read = visible
        else:
            identity = "version_id" if name == TABLES[1].name else "publication_id"
            revision = "revision" if name == TABLES[1].name else "publication_revision"
            read = (
                "public.category_access(tenant_id,category_id) "
                f"AND EXISTS(SELECT 1 FROM public.{ledger} v WHERE v.tenant_id={name}.tenant_id "
                f"AND v.category_id={name}.category_id AND v.product_id={name}.product_id "
                f"AND v.project_id={name}.project_id AND v.id={name}.{identity} "
                f"AND v.revision={name}.{revision})"
            )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner '
                "USING (true) WITH CHECK (true)",
                f'CREATE POLICY publication_read ON public."{name}" FOR SELECT TO pdos_next_app USING ({read})',
                f'CREATE POLICY publication_insert ON public."{name}" FOR INSERT TO pdos_next_app '
                f"WITH CHECK ({human} AND {read})",
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == TABLES[1].name:
            statements.extend(
                (
                    f'CREATE POLICY publication_advance ON public."{name}" FOR UPDATE TO pdos_next_app '
                    f"USING ({human} AND {read}) WITH CHECK ({human} AND {read})",
                    f'GRANT UPDATE(version_id,revision,epoch) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER publication_category BEFORE INSERT ON public.{table.name} "
                "FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER publication_category_immutable BEFORE UPDATE ON public.{table.name} "
                "FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} "
                "FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} "
                "FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    for table in (TABLES[0], TABLES[2]):
        statements.append(
            f"CREATE TRIGGER publication_immutable BEFORE UPDATE OR DELETE ON public.{table.name} "
            "FOR EACH ROW EXECUTE FUNCTION public.reject_manufacturing_publication_mutation()"
        )
    statements.extend(
        (
            "CREATE TRIGGER publication_current_guard BEFORE INSERT OR UPDATE OR DELETE "
            "ON public.manufacturing_publication_currents FOR EACH ROW "
            "EXECUTE FUNCTION public.protect_manufacturing_publication_current()",
            "CREATE CONSTRAINT TRIGGER publication_atom AFTER INSERT ON public.manufacturing_baseline_publications "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_manufacturing_publication_atom()",
            "CREATE CONSTRAINT TRIGGER publication_document_atom AFTER INSERT ON public.manufacturing_publication_documents "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_manufacturing_publication_document()",
            "CREATE TRIGGER publication_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations "
            "FOR EACH ROW EXECUTE FUNCTION public.protect_manufacturing_publication_proof()",
            "CREATE CONSTRAINT TRIGGER publication_proof_target AFTER UPDATE ON public.confirmations "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_manufacturing_publication_transition()",
            "CREATE TRIGGER publication_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts "
            "FOR EACH ROW EXECUTE FUNCTION public.protect_manufacturing_publication_receipt()",
        )
    )
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER publication_member_atom AFTER INSERT ON public.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_manufacturing_publication_member()"
        )
        if table != "action_receipts":
            statements.append(
                f"CREATE TRIGGER publication_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table} "
                "FOR EACH ROW EXECUTE FUNCTION public.protect_manufacturing_publication_member()"
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
    return (
        "LOCK TABLE public.manufacturing_baseline_publications,public.manufacturing_publication_currents,"
        "public.manufacturing_publication_documents,public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        """DO $publication$ BEGIN
 IF EXISTS(SELECT 1 FROM public.manufacturing_baseline_publications)
  OR EXISTS(SELECT 1 FROM public.manufacturing_publication_currents)
  OR EXISTS(SELECT 1 FROM public.manufacturing_publication_documents)
  OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation='npi.manufacturing_baseline.publish')
  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='npi.manufacturing_baseline.publish'
    OR subject_type='manufacturing_publication') THEN
  RAISE EXCEPTION 'Publication business history is retained; downgrade refused' USING ERRCODE='23514';
 END IF;
END; $publication$""",
        "DROP TRIGGER publication_proof_guard ON public.confirmations",
        "DROP TRIGGER publication_proof_target ON public.confirmations",
        "DROP TRIGGER publication_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER publication_member_atom ON public.{table}"
            for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER publication_member_guard ON public.{table}"
            for table in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(FUNCTION_SQL)),
    )


def install(connection):
    """Execute in the caller's migration transaction and selected ordinary role."""
    for statement in install_sql():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})


def uninstall(connection):
    """Reject retained business history before removing this exact new family."""
    for statement in uninstall_sql():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
