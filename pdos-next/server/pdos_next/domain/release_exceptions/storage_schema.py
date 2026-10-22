"""Uninstalled SQL declarations for named, bounded release exceptions.

The migration host freezes and installs these statements. Only a new approval
checks package/policy Current; retained history and withdrawal never re-approve
the old package. Shared lifecycle/subject registration belongs to that host.
"""

# ruff: noqa: E501 -- Keep PostgreSQL predicates readable.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import ReleaseExceptionCurrent, ReleaseExceptionDecision

TABLES = (ReleaseExceptionDecision.__table__, ReleaseExceptionCurrent.__table__)
OPERATIONS = "('release.exception.decide','release.exception.withdraw')"
SUBJECT = "release_exception"


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
        f"AS $release_exception$\n{body.rstrip()};\n$release_exception$"
    )


# Original-key aliases validate retained members, not today's package/policy or
# the old signer's current qualifications. Public reads do not scan these rows.
MEMBERS = r"""
DECLARE v public.release_exception_decisions; r public.action_receipts; c public.confirmations; event_name text;
BEGIN
 SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 event_name=CASE WHEN v.action='approved' THEN 'release.exception_decided' ELSE 'release.exception_withdrawn' END;
 IF ROW(c.category_id,c.product_id,c.actor_id,c.subject_type,c.subject_id,c.operation,c.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,'product'::varchar,v.product_id,v.operation,v.shared_proof_revision)
  OR c.consumed IS DISTINCT FROM true OR c.token_hash IS DISTINCT FROM v.token_sha256
  OR c.payload_digest IS DISTINCT FROM v.material_sha256 OR c.snapshot IS DISTINCT FROM v.input_snapshot->'review'
  OR c.expires_at IS DISTINCT FROM v.proof_expires_at
  OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at
   AND (c.expires_at IS NULL OR v.created_at<c.expires_at))
  OR ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,
   r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.shared_proof_id,v.actor_id,v.requester_id,v.operation,
    'release_exception'::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status',v.action)
  OR r.created_at<v.created_at OR (c.expires_at IS NOT NULL AND r.created_at>=c.expires_at)
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation
    AND x.subject_type='release_exception' AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id
    AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id
    AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name
    AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1
    AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)
  OR v.input_snapshot->>'original_key_sha256' IS NULL
  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR (v.input_snapshot->'command') ? 'idempotency_key'
  OR (v.input_snapshot->'command'->'payload') ? 'approval_token'
  OR (v.input_snapshot->'semantic') ? 'approval_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id
    AND k.receipt_id=r.id AND k.actor_id=v.actor_id AND k.digest=v.request_digest
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Release exception original common group mismatch' USING ERRCODE='23514'; END IF;
END
"""

WRITE_ATOM = r"""
DECLARE v public.release_exception_decisions; command jsonb; review jsonb; ref jsonb; basis jsonb; vx xid; rx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 PERFORM public.assert_release_exception_members(t,target);
 command=v.input_snapshot->'command'; review=v.input_snapshot->'review';
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.actor_id<>v.requester_id OR v.writer_id<>v.actor_id OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.actor_id AND p.kind='human' AND p.active)
  OR vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)
    IS DISTINCT FROM ARRAY['command','original_key_sha256','review','semantic']
  OR command->>'operation' IS DISTINCT FROM v.operation OR command->>'command_id' IS DISTINCT FROM v.command_id::text
  OR command->>'category_id' IS DISTINCT FROM v.category_id::text OR command->>'product_id' IS DISTINCT FROM v.product_id::text
  OR command->'payload' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR v.body->'declaration' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR NOT COALESCE((command->'source_read_set') @> v.required_source_read_set,false)
  OR NOT COALESCE(v.required_source_read_set @> (command->'source_read_set'),false)
  OR jsonb_array_length(command->'source_read_set')<>jsonb_array_length(v.required_source_read_set)
  OR v.shared_proof_revision::text IS DISTINCT FROM command->>'expected_revision'
  OR review->>'operation' IS DISTINCT FROM v.operation
  OR review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR review->'read_basis' IS DISTINCT FROM v.source_basis
  OR (v.body||jsonb_build_object('prepared_at',null)) IS DISTINCT FROM review->'after'
  OR v.body->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
  OR v.body->>'category_id' IS DISTINCT FROM v.category_id::text
  OR v.body->>'owner_id' IS DISTINCT FROM v.owner_id::text OR v.body->>'visibility' IS DISTINCT FROM v.visibility
  OR v.body->>'operation' IS DISTINCT FROM v.operation OR v.body->>'action' IS DISTINCT FROM v.action
  OR v.body->>'discipline' IS DISTINCT FROM v.discipline OR v.body->>'purpose' IS DISTINCT FROM v.purpose
  OR v.body->'basis_package' IS DISTINCT FROM jsonb_build_object('id',v.basis_package_id,'revision',v.basis_package_revision)
  OR v.body->'policy_fact' IS DISTINCT FROM jsonb_build_object('id',v.policy_fact_id,'revision',v.policy_fact_revision)
  OR (v.body->>'expiry')::timestamptz IS DISTINCT FROM v.expiry
  OR v.body->'sources' IS DISTINCT FROM v.sources OR v.body->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR v.body->'signers' IS DISTINCT FROM jsonb_build_array(v.actor_id)
  OR v.body->>'state' IS DISTINCT FROM 'READY' OR v.body->'unknown' IS DISTINCT FROM '[]'::jsonb
  OR v.body->'blocked' IS DISTINCT FROM '[]'::jsonb
  OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id
    AND p.id=v.product_id AND p.revision::text=command->>'expected_revision')
  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id
    AND p.product_id=v.product_id AND p.id=v.project_id)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.required_source_read_set)
  OR (SELECT count(DISTINCT x->>'artifact_id') FROM jsonb_array_elements(v.required_source_read_set) x)
    <>jsonb_array_length(v.required_source_read_set)
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id
    AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Release exception requires actual named scope and one common transaction' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(v.source_basis->'artifact_sources') IS DISTINCT FROM 'object'
  OR (SELECT count(*) FROM jsonb_object_keys(v.source_basis->'artifact_sources'))<>jsonb_array_length(v.required_source_read_set) THEN
  RAISE EXCEPTION 'Release exception complete direct source basis required' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP
  basis=v.source_basis->'artifact_sources'->(ref->>'artifact_id');
  IF basis IS NULL OR jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'
   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
    AND a.id::text=ref->>'artifact_id' AND a.revision::text=ref->>'expected_revision' AND a.status='active'
    AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'sha256'
    AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'
    AND (v.visibility='private' OR a.visibility<>'private')
    AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o
     JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
     WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.status='parsed'
      AND o.id::text=basis->>'original_id' AND o.revision::text=basis->>'original_revision'
      AND o.content_hash=basis->>'original_sha256' AND o.owner_id::text=basis->>'original_owner_id'
      AND o.visibility=basis->>'original_visibility' AND sec.epoch::text=basis->>'security_epoch'
      AND sec.source_state='active' AND sec.disposition='active' AND (v.visibility='private' OR o.visibility<>'private')))) THEN
   RAISE EXCEPTION 'Release exception direct source version security or audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) src WHERE src->>'kind'='artifact' AND NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(v.required_source_read_set) rd
   WHERE rd->>'artifact_id'=src->>'id' AND rd->'expected_revision'=src->'revision')) THEN
  RAISE EXCEPTION 'Release exception source omitted from direct read set' USING ERRCODE='23514'; END IF;
END
"""

AUTHORITY = r"""
DECLARE v public.release_exception_decisions; auth jsonb; ref jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 auth=v.authority_snapshot;
 IF v.input_snapshot->'review'->'authority' IS DISTINCT FROM auth
  OR auth->'scope' IS DISTINCT FROM v.body->'scope' OR auth->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR auth->>'operation' IS DISTINCT FROM v.operation OR auth->>'purpose' IS DISTINCT FROM v.purpose
  OR auth->'authorized' IS DISTINCT FROM 'true'::jsonb OR auth->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR NOT public.capture_authority_time_current(auth,v.created_at)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'fact_refs')) THEN
  RAISE EXCEPTION 'Release exception requires actual current named professional authority' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(auth->'fact_refs') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f JOIN public.professional_authority_current cur
   ON cur.tenant_id=f.tenant_id AND cur.category_id=f.category_id AND cur.product_id=f.product_id AND cur.project_id=f.project_id
    AND cur.subject_id=f.subject_id AND cur.kind=f.kind AND cur.series_id=f.series_id AND cur.fact_id=f.id AND cur.fact_revision=f.revision
   WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id AND f.project_id=v.project_id
    AND f.subject_id=v.actor_id AND f.id::text=ref->>'id' AND f.revision::text=ref->>'revision'
    AND cur.epoch::text=ref->>'epoch' AND f.fact_sha256=ref->>'fact_sha256' AND f.state=ref->>'state'
    AND f.role=ref->>'role' AND f.kind=ref->>'kind' AND f.series_id::text=ref->>'series_id'
    AND f.issuer_key=ref->>'issuer_key' AND f.issuer_version=ref->>'issuer_version' AND f.nature=ref->>'nature'
    AND f.operations=ref->'operations' AND f.purposes=ref->'purposes'
    AND f.valid_from IS NOT DISTINCT FROM (ref->>'valid_from')::timestamptz
    AND f.valid_until IS NOT DISTINCT FROM (ref->>'valid_until')::timestamptz) THEN
   RAISE EXCEPTION 'Release exception professional fact or Current changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') AS roles(role_name)
   WHERE role_name IN ('engineering','manufacturing','quality') AND NOT EXISTS(
    SELECT kind FROM unnest(ARRAY['duty','qualification']) kind WHERE NOT EXISTS(
     SELECT 1 FROM jsonb_array_elements(auth->'fact_refs') f WHERE f->>'kind'=kind AND f->>'role'=role_name
      AND f->>'state'='active' AND (f->'operations') @> jsonb_build_array(v.operation)
      AND (f->'purposes') @> jsonb_build_array(v.purpose)
      AND (f->>'valid_from')::timestamptz<=v.created_at AND v.created_at<(f->>'valid_until')::timestamptz))) THEN
  RAISE EXCEPTION 'Release exception needs applicable duty and qualification' USING ERRCODE='23514'; END IF;
END
"""

# Matches the finite scope relation in rules.scope_covers, with no policy-version
# whitelist and no implicit unbounded value when a constrained value is absent.
SCOPE_COVERS = r"""
DECLARE key text; b jsonb; c jsonb;
BEGIN
 IF jsonb_typeof(bound) IS DISTINCT FROM 'object' OR jsonb_typeof(chosen) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['lots','lines','regions'] LOOP
  b=bound->key; c=chosen->key;
  IF c IS NULL OR c='null'::jsonb THEN
   IF b IS NOT NULL AND b<>'null'::jsonb THEN RETURN false; END IF;
  ELSIF jsonb_typeof(c) IS DISTINCT FROM 'array' THEN RETURN false;
  ELSIF c='[]'::jsonb THEN
   IF b IS DISTINCT FROM '[]'::jsonb THEN RETURN false; END IF;
  ELSIF jsonb_typeof(b) IS DISTINCT FROM 'array' OR NOT(b @> c) THEN RETURN false;
  END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['site','unit'] LOOP
  IF bound->key IS DISTINCT FROM chosen->key THEN RETURN false; END IF;
 END LOOP;
 IF chosen->>'quantity' IS NULL THEN RETURN bound->>'quantity' IS NULL; END IF;
 IF bound->>'quantity' IS NULL THEN RETURN false; END IF;
 RETURN (chosen->>'quantity')::numeric>0 AND (chosen->>'quantity')::numeric<=(bound->>'quantity')::numeric;
END
"""

DECISION_ATOM = r"""
DECLARE v public.release_exception_decisions; p public.release_packages; f public.release_policy_facts;
 prior public.release_exception_decisions; cur public.release_exception_currents; key text; check_value jsonb; policy_rule jsonb; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT p FROM public.release_packages WHERE tenant_id=t AND id=v.basis_package_id;
 SELECT * INTO STRICT f FROM public.release_policy_facts WHERE tenant_id=t AND id=v.policy_fact_id;
 SELECT * INTO STRICT cur FROM public.release_exception_currents WHERE tenant_id=t AND series_id=v.series_id;
 SELECT xmin INTO cx FROM public.release_exception_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_release_exception_write(t,target);
 PERFORM public.assert_release_exception_authority(t,target);
 IF vx IS DISTINCT FROM cx
  OR ROW(p.category_id,p.product_id,p.project_id,p.revision,p.owner_id,p.visibility)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.basis_package_revision,v.owner_id,v.visibility)
  OR ROW(f.category_id,f.product_id,f.project_id,f.revision,f.purpose)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.policy_fact_revision,v.purpose)
  OR v.body->>'policy_version' IS DISTINCT FROM f.policy_version
  OR v.body->'subject_config' IS DISTINCT FROM p.body->'declaration'->'subject_config'
  OR v.purpose IS DISTINCT FROM p.purpose
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,
    cur.basis_package_id,cur.basis_package_revision,cur.policy_fact_id,cur.policy_fact_revision,cur.discipline,cur.purpose,
    cur.decision_id,cur.decision_revision,cur.action,cur.epoch)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,
    v.basis_package_id,v.basis_package_revision,v.policy_fact_id,v.policy_fact_revision,v.discipline,v.purpose,
    v.id,v.revision,v.action,(CASE WHEN v.action='approved' THEN 1 ELSE 2 END)) THEN
  RAISE EXCEPTION 'Release exception fixed package policy or Current binding mismatch' USING ERRCODE='23514'; END IF;
 IF v.action='approved' THEN
  IF v.body->'previous' IS DISTINCT FROM 'null'::jsonb
   OR NOT EXISTS(SELECT 1 FROM public.release_package_currents c WHERE c.tenant_id=t AND c.category_id=v.category_id
    AND c.product_id=v.product_id AND c.project_id=v.project_id AND c.series_id=p.series_id AND c.version_id=p.id AND c.revision=p.revision)
   OR NOT EXISTS(SELECT 1 FROM public.release_policy_currents c WHERE c.tenant_id=t AND c.category_id=v.category_id
    AND c.product_id=v.product_id AND c.project_id=v.project_id AND c.purpose_sha256=f.purpose_sha256
    AND c.fact_id=f.id AND c.revision=f.revision AND c.epoch=f.epoch)
   OR f.status<>'active' OR (f.valid_from IS NOT NULL AND v.created_at<f.valid_from)
   OR (f.valid_until IS NOT NULL AND v.created_at>=f.valid_until)
   OR (v.expiry IS NOT NULL AND v.created_at>=v.expiry)
   OR f.material->'scope' IS DISTINCT FROM v.body->'scope'
   OR f.material->'subject_config' IS DISTINCT FROM v.body->'subject_config'
   OR p.body->'policy'->>'version' IS DISTINCT FROM f.policy_version
   OR NOT public.release_exception_scope_covers(p.body->'declaration'->'release_scope',v.body->'release_scope')
   OR NOT public.release_exception_scope_covers(f.material->'release_scope',v.body->'release_scope')
   OR v.body->'declaration'->'basis_package' IS DISTINCT FROM v.body->'basis_package'
   OR v.body->'declaration'->>'discipline' IS DISTINCT FROM v.discipline
   OR v.body->'declaration'->>'purpose' IS DISTINCT FROM v.purpose
   OR EXISTS(SELECT 1 FROM unnest(ARRAY['release_scope','check_keys','limits','risk_controls','expiry','reason']) name
    WHERE v.body->'declaration'->name IS DISTINCT FROM v.body->name)
   OR jsonb_typeof(v.body->'check_keys') IS DISTINCT FROM 'array' OR jsonb_array_length(v.body->'check_keys')=0
   OR jsonb_array_length(v.body->'check_keys')<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(v.body->'check_keys'))
   OR jsonb_array_length(v.body->'selected_checks')<>jsonb_array_length(v.body->'check_keys') THEN
   RAISE EXCEPTION 'New release exception requires actual current applicable package and policy' USING ERRCODE='23514'; END IF;
  FOR key IN SELECT value FROM jsonb_array_elements_text(v.body->'check_keys') LOOP
   SELECT value INTO STRICT check_value FROM jsonb_array_elements(p.body->'checks') WHERE value->>'key'=key;
   SELECT value INTO STRICT policy_rule FROM jsonb_array_elements(f.material->'rules') WHERE value->>'id'=key;
   IF NOT(v.body->'selected_checks' @> jsonb_build_array(check_value))
    OR check_value->'applicable' IS DISTINCT FROM 'true'::jsonb
    OR check_value->'non_waivable' IS DISTINCT FROM 'false'::jsonb
    OR check_value->>'discipline' NOT IN(v.discipline,'both') OR policy_rule->'waivable' IS DISTINCT FROM 'true'::jsonb
    OR policy_rule->>'discipline' NOT IN(v.discipline,'both')
    OR NOT(policy_rule->'allowed_purpose' @> jsonb_build_array(v.purpose))
    OR NOT public.release_exception_scope_covers(policy_rule->'scope',v.body->'release_scope')
    OR (check_value->'release_scope'<>'null'::jsonb AND NOT public.release_exception_scope_covers(check_value->'release_scope',v.body->'release_scope')) THEN
    RAISE EXCEPTION 'Release exception cannot alter a check or bypass a non-waivable rule' USING ERRCODE='23514'; END IF;
  END LOOP;
 ELSE
  SELECT * INTO STRICT prior FROM public.release_exception_decisions WHERE tenant_id=t AND id=v.previous_id;
  PERFORM public.assert_release_exception_members(t,prior.id);
  IF prior.action<>'approved' OR prior.revision<>v.previous_revision
   OR v.body->'previous' IS DISTINCT FROM jsonb_build_object('id',prior.id,'revision',prior.revision)
   OR v.body->'declaration'->'exception' IS DISTINCT FROM v.body->'previous'
   OR v.expiry IS DISTINCT FROM prior.expiry
   OR (v.body-ARRAY['operation','action','declaration','previous','sources','required_source_read_set','signers','prepared_at','reason','state','unknown','blocked'])
    IS DISTINCT FROM (prior.body-ARRAY['operation','action','declaration','previous','sources','required_source_read_set','signers','prepared_at','reason','state','unknown','blocked']) THEN
   RAISE EXCEPTION 'Withdrawal retains the original approved limits and binding' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.action='approved' AND NEW.epoch=1 AND NEW.decision_id=NEW.series_id AND NEW.decision_revision=1 THEN RETURN NEW; END IF;
 ELSIF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['decision_id','decision_revision','action','epoch'])
   IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['decision_id','decision_revision','action','epoch'])
   AND OLD.action='approved' AND OLD.epoch=1 AND NEW.action='withdrawn' AND NEW.epoch=OLD.epoch+1
   AND EXISTS(SELECT 1 FROM public.release_exception_decisions v WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.decision_id
    AND v.revision=NEW.decision_revision AND v.action='withdrawn' AND v.series_id=NEW.series_id
    AND v.previous_id=OLD.decision_id AND v.previous_revision=OLD.decision_revision) THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION 'Release exception Current permits one approved to withdrawn CAS' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.release_exception_currents; v public.release_exception_decisions; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.release_exception_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.release_exception_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=NEW.tenant_id AND id=cur.decision_id;
 SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=NEW.tenant_id AND id=cur.decision_id;
 IF cx IS DISTINCT FROM vx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,
    cur.basis_package_id,cur.basis_package_revision,cur.policy_fact_id,cur.policy_fact_revision,cur.discipline,cur.purpose,
    cur.decision_revision,cur.action,cur.epoch)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,
    v.basis_package_id,v.basis_package_revision,v.policy_fact_id,v.policy_fact_revision,v.discipline,v.purpose,
    v.revision,v.action,(CASE WHEN v.action='approved' THEN 1 ELSE 2 END)) THEN
  RAISE EXCEPTION 'Release exception Current requires its new immutable decision' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

PROOF = f"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN {OPERATIONS}; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN {OPERATIONS}; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Release exception proof history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Release exception proof starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Release exception proof permits only original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

TRANSITION = f"""
BEGIN
 IF NEW.operation IN {OPERATIONS} THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM public.release_exception_decisions d WHERE d.tenant_id=NEW.tenant_id
    AND d.shared_proof_id=NEW.id AND d.operation=NEW.operation)<>1 THEN
   RAISE EXCEPTION 'Consumed exception T2 requires one actual immutable decision' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {OPERATIONS} OR OLD.subject_type='release_exception'; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {OPERATIONS} OR NEW.subject_type='release_exception'; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release exception common receipt is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_GUARD = f"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
   AND (r.operation IN {OPERATIONS} OR r.subject_type='release_exception')) INTO scoped;
 END IF;
 IF TG_OP<>'INSERT' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id
   AND (r.operation IN {OPERATIONS} OR r.subject_type='release_exception')) INTO old_scoped;
 END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'
   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Release exception original audit event or key is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = f"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW;
 ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation IN {OPERATIONS} OR r.subject_type='release_exception' THEN
  IF r.subject_type IS DISTINCT FROM 'release_exception' THEN
   RAISE EXCEPTION 'Release exception common subject mismatch' USING ERRCODE='23514'; END IF;
  PERFORM public.assert_release_exception_members(r.tenant_id,r.subject_id);
 END IF;
 RETURN NULL;
END
"""

FUNCTIONS = (
    ("assert_release_exception_members", "t uuid,target uuid", MEMBERS, "void"),
    ("assert_release_exception_write", "t uuid,target uuid", WRITE_ATOM, "void"),
    ("assert_release_exception_authority", "t uuid,target uuid", AUTHORITY, "void"),
    ("release_exception_scope_covers", "bound jsonb,chosen jsonb", SCOPE_COVERS, "boolean"),
    ("assert_release_exception_decision", "t uuid,target uuid", DECISION_ATOM, "void"),
    ("protect_release_exception_current", "", CURRENT_GUARD, "trigger"),
    ("require_release_exception_current", "", CURRENT_ATOM, "trigger"),
    ("protect_release_exception_proof", "", PROOF, "trigger"),
    ("require_release_exception_transition", "", TRANSITION, "trigger"),
    ("protect_release_exception_receipt", "", RECEIPT_GUARD, "trigger"),
    ("protect_release_exception_member", "", MEMBER_GUARD, "trigger"),
    ("require_release_exception_member", "", MEMBER_TARGET, "trigger"),
    (
        "require_release_exception_decision",
        "",
        "BEGIN PERFORM public.assert_release_exception_decision(NEW.tenant_id,NEW.id); RETURN NULL; END",
        "trigger",
    ),
    (
        "reject_release_exception_mutation",
        "",
        "BEGIN RAISE EXCEPTION 'Release exception decisions are immutable' USING ERRCODE='23514'; END",
        "trigger",
    ),
)
FUNCTION_SIGNATURES = tuple(
    f"{name}({','.join(value.split()[-1] for value in arguments.split(',')) if arguments else ''})"
    for name, arguments, _, _ in FUNCTIONS
)


def function_sql():
    return tuple(
        _function(name, args, body, returns=result) for name, args, body, result in FUNCTIONS
    )


def policy_sql():
    statements = []
    human = (
        "public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h "
        "WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
        "AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"
    )
    write = f"{human} AND public.category_access(tenant_id,category_id,true)"
    for table in TABLES:
        name = table.name
        if table is TABLES[0]:
            read = (
                f"{human} AND public.category_access(tenant_id,category_id) "
                f"AND EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.id={name}.product_id) "
                f"AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.id={name}.project_id) "
                f"AND EXISTS(SELECT 1 FROM public.release_packages p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
                f"AND p.product_id={name}.product_id AND p.project_id={name}.project_id AND p.owner_id={name}.owner_id "
                f"AND p.visibility={name}.visibility AND p.id={name}.basis_package_id AND p.revision={name}.basis_package_revision) "
                f"AND EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id={name}.tenant_id AND f.id={name}.policy_fact_id AND f.revision={name}.policy_fact_revision) "
                f"AND public.direct_source_set_visible(tenant_id,category_id,product_id,{name}.required_source_read_set)"
            )
        else:
            read = (
                f"{human} AND public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.release_exception_decisions d "
                f"WHERE d.tenant_id={name}.tenant_id AND d.category_id={name}.category_id AND d.product_id={name}.product_id "
                f"AND d.project_id={name}.project_id AND d.series_id={name}.series_id AND d.owner_id={name}.owner_id "
                f"AND d.visibility={name}.visibility AND d.id={name}.decision_id AND d.revision={name}.decision_revision)"
            )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING (true) WITH CHECK (true)',
                f'CREATE POLICY release_exception_read ON public."{name}" FOR SELECT TO pdos_next_app USING ({read})',
                f'CREATE POLICY release_exception_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK ({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table is TABLES[1]:
            statements.extend(
                (
                    f'CREATE POLICY release_exception_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING ({write} AND {read}) WITH CHECK ({write} AND {read})',
                    f'GRANT UPDATE(decision_id,decision_revision,action,epoch) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER release_exception_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER release_exception_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    statements.extend(
        (
            "CREATE TRIGGER release_exception_immutable BEFORE UPDATE OR DELETE ON public.release_exception_decisions FOR EACH ROW EXECUTE FUNCTION public.reject_release_exception_mutation()",
            "CREATE CONSTRAINT TRIGGER release_exception_decision_atom AFTER INSERT ON public.release_exception_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_decision()",
            "CREATE TRIGGER release_exception_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.release_exception_currents FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_current()",
            "CREATE CONSTRAINT TRIGGER release_exception_current_atom AFTER INSERT OR UPDATE ON public.release_exception_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_current()",
            "CREATE TRIGGER release_exception_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_proof()",
            "CREATE CONSTRAINT TRIGGER release_exception_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_transition()",
            "CREATE TRIGGER release_exception_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_receipt()",
        )
    )
    for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER release_exception_member_atom AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_member()"
        )
        if name != "action_receipts":
            statements.append(
                f"CREATE TRIGGER release_exception_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_member()"
            )
    return tuple(statements)


def upgrade_sql():
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in FUNCTION_SIGNATURES
        ),
        *policy_sql(),
        *trigger_sql(),
    )


def downgrade_sql():
    return (
        "LOCK TABLE public.release_exception_decisions,public.release_exception_currents,public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        f"""DO $release_exception$ BEGIN
 IF EXISTS(SELECT 1 FROM public.release_exception_decisions) OR EXISTS(SELECT 1 FROM public.release_exception_currents)
  OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {OPERATIONS})
  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPERATIONS} OR subject_type='release_exception') THEN
  RAISE EXCEPTION 'Release exception business history retained; downgrade refused' USING ERRCODE='23514'; END IF;
END; $release_exception$""",
        "DROP TRIGGER release_exception_proof_guard ON public.confirmations",
        "DROP TRIGGER release_exception_proof_target ON public.confirmations",
        "DROP TRIGGER release_exception_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER release_exception_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER release_exception_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(FUNCTION_SIGNATURES)),
    )


install_sql = upgrade_sql
uninstall_sql = downgrade_sql
