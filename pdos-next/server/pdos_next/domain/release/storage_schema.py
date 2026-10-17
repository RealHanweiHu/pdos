"""Uninstalled release storage contract, owned by the caller's migration.

Only write-time atoms inspect the original private RequestKey. Historic reads
use the saved immutable signature and ordinary RLS; no full material reproof is
introduced here. Installation neither supplies policy nor grants qualification.
"""

# ruff: noqa: E501 -- Keep PostgreSQL predicates readable.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import ReleaseDecision, ReleasePackage, ReleasePackageCurrent

TABLES = (
    ReleasePackage.__table__,
    ReleasePackageCurrent.__table__,
    ReleaseDecision.__table__,
)
OPERATIONS = (
    "('release.package.assemble','release.engineering.approve','release.manufacturing.approve')"
)
T2 = "('release.engineering.approve','release.manufacturing.approve')"
SUBJECTS = "('release_package','release_decision')"


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
        f"AS $release$\n{body.rstrip()};\n$release$"
    )


# The immutable common group is checked when inserted and when common adds a
# replay alias. Original Current/ACL/professional state need not stay live.
MEMBERS = r"""
DECLARE v record; r public.action_receipts; c public.confirmations;
 event_name text; expected_status text; proof uuid;
BEGIN
 IF kind='release_package' THEN
  SELECT * INTO STRICT v FROM public.release_packages WHERE tenant_id=t AND id=target;
  event_name='release.package_assembled'; expected_status='assembled'; proof=NULL;
 ELSIF kind='release_decision' THEN
  SELECT * INTO STRICT v FROM public.release_decisions WHERE tenant_id=t AND id=target;
  event_name=CASE v.discipline WHEN 'engineering' THEN 'release.engineering_approved' ELSE 'release.manufacturing_approved' END;
  expected_status='approved'; proof=v.shared_proof_id;
  SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=proof;
  IF ROW(c.category_id,c.product_id,c.actor_id,c.subject_type,c.subject_id,c.operation,c.revision)
    IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,'product'::varchar,v.product_id,v.operation,v.shared_proof_revision)
   OR c.consumed IS DISTINCT FROM true OR c.token_hash IS DISTINCT FROM v.token_sha256
   OR c.payload_digest IS DISTINCT FROM v.material_sha256
   OR c.snapshot IS DISTINCT FROM v.input_snapshot->'review'
   OR c.expires_at IS DISTINCT FROM v.proof_expires_at
   OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at
    AND (c.expires_at IS NULL OR v.created_at<c.expires_at)) THEN
   RAISE EXCEPTION 'Release decision requires its original consumed T2 proof' USING ERRCODE='23514';
  END IF;
 ELSE RAISE EXCEPTION 'Unknown release subject' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 IF ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,
   r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,proof,v.actor_id,v.requester_id,v.operation,
   kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status)
  OR r.created_at<v.created_at
  OR (kind='release_decision' AND (r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
    OR (c.expires_at IS NOT NULL AND r.created_at>=c.expires_at)))
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation
   AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
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
  RAISE EXCEPTION 'Release original receipt audit event or request mismatch' USING ERRCODE='23514';
 END IF;
END
"""

COMMON = r"""
DECLARE v record; r public.action_receipts; vx xid; rx xid; command jsonb; semantic jsonb; review jsonb; ref jsonb;
BEGIN
 IF kind='release_package' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.release_packages x WHERE x.tenant_id=t AND x.id=target;
 ELSIF kind='release_decision' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.release_decisions x WHERE x.tenant_id=t AND x.id=target;
 ELSE RAISE EXCEPTION 'Unknown release subject' USING ERRCODE='23514'; END IF;
 vx=v.tx;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_release_members(t,target,kind);
 command=v.input_snapshot->'command'; semantic=v.input_snapshot->'semantic'; review=v.input_snapshot->'review';
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.writer_id<>v.actor_id OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.actor_id AND p.active)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.requester_id AND p.kind='human' AND p.active)
  OR (v.actor_id<>v.requester_id AND r.run_id IS NULL AND r.agent_run_id IS NULL)
  OR (v.visibility='private' AND v.owner_id<>v.requester_id)
  OR vx IS DISTINCT FROM rx
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)
    IS DISTINCT FROM ARRAY['command','original_key_sha256','review','semantic']
  OR command->>'operation' IS DISTINCT FROM v.operation
  OR command->>'command_id' IS DISTINCT FROM v.command_id::text
  OR command->>'category_id' IS DISTINCT FROM v.category_id::text
  OR command->>'product_id' IS DISTINCT FROM v.product_id::text
  OR command->'payload' IS DISTINCT FROM semantic
  OR NOT COALESCE((command->'source_read_set') @> v.required_source_read_set,false)
  OR NOT COALESCE(v.required_source_read_set @> (command->'source_read_set'),false)
  OR jsonb_array_length(command->'source_read_set')<>jsonb_array_length(v.required_source_read_set)
  OR review->>'operation' IS DISTINCT FROM v.operation
  OR review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR review->'read_basis' IS DISTINCT FROM v.source_basis
  OR v.body->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
  OR v.body->>'category_id' IS DISTINCT FROM v.category_id::text
  OR v.material_snapshot->'scope' IS DISTINCT FROM v.body->'scope'
  OR v.material_snapshot->>'category_id' IS DISTINCT FROM v.category_id::text
  OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id
   AND p.id=v.product_id AND p.revision::text=command->>'expected_revision')
  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id
   AND p.product_id=v.product_id AND p.id=v.project_id)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.required_source_read_set)
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id
   AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx
   AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Release requires actual scope and one common transaction' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(v.material_snapshot->'required_source_read_set') x
   WHERE NOT v.required_source_read_set @> jsonb_build_array(x))
  OR (SELECT count(DISTINCT x->>'artifact_id') FROM jsonb_array_elements(v.required_source_read_set) x)
   <>jsonb_array_length(v.required_source_read_set) THEN
  RAISE EXCEPTION 'Release must retain the actual material read set' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP
  IF jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'
   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
    AND a.id::text=ref->>'artifact_id' AND a.revision::text=ref->>'expected_revision' AND a.status='active'
    AND (v.visibility='private' OR a.visibility<>'private')
    AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o
     JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
     WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.status='parsed'
      AND sec.source_state='active' AND sec.disposition='active'
      AND (v.visibility='private' OR o.visibility<>'private')))) THEN
   RAISE EXCEPTION 'Release direct original version security or audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
END
"""

PACKAGE = r"""
DECLARE v public.release_packages; cur public.release_package_currents; command jsonb; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.release_packages WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.release_packages WHERE tenant_id=t AND id=target;
 PERFORM public.assert_release_common(t,target,'release_package');
 command=v.input_snapshot->'command';
 SELECT * INTO STRICT cur FROM public.release_package_currents WHERE tenant_id=t
  AND category_id=v.category_id AND product_id=v.product_id AND project_id=v.project_id AND series_id=v.series_id;
 SELECT xmin INTO cx FROM public.release_package_currents WHERE tenant_id=t AND id=cur.id;
 IF cur.version_id<>v.id OR cur.revision<>v.revision OR cur.epoch<>v.revision OR cx IS DISTINCT FROM vx
  OR v.body IS DISTINCT FROM v.input_snapshot->'review'->'after'
  OR v.body->'declaration' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR v.body->>'owner_id' IS DISTINCT FROM v.owner_id::text
  OR v.body->>'product_revision' IS DISTINCT FROM command->>'expected_revision'
  OR v.body->'sources' IS DISTINCT FROM v.sources
  OR v.body->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
  OR v.body->'objects' IS DISTINCT FROM v.material_snapshot->'objects'
  OR v.body->'policy' IS DISTINCT FROM v.material_snapshot->'policy'
  OR v.body->'checks' IS DISTINCT FROM v.material_snapshot->'checks'
  OR v.body->'exceptions' IS DISTINCT FROM v.material_snapshot->'exceptions'
  OR v.body->'declaration'->>'purpose' IS DISTINCT FROM v.purpose
  OR v.body->'declaration'->>'visibility' IS DISTINCT FROM v.visibility
  OR v.body->'declaration'->>'project_id' IS DISTINCT FROM v.project_id::text
  OR v.material_snapshot->>'purpose' IS DISTINCT FROM v.purpose
  OR v.body->'declaration'->'subject_config' IS DISTINCT FROM v.material_snapshot->'subject_config'
  OR v.body->'declaration'->'release_scope' IS DISTINCT FROM v.material_snapshot->'release_scope'
  OR (v.revision=1 AND (v.input_snapshot->'semantic'->'previous'<>'null'::jsonb
    OR v.input_snapshot->'review'->'before'<>'null'::jsonb))
  OR (v.revision>1 AND (v.input_snapshot->'semantic'->'previous'
    IS DISTINCT FROM jsonb_build_object('id',v.previous_id,'revision',v.previous_revision)
    OR v.input_snapshot->'review'->'before'->'version'->>'id' IS DISTINCT FROM v.previous_id::text
    OR v.input_snapshot->'review'->'before'->'version'->>'revision' IS DISTINCT FROM v.previous_revision::text)) THEN
  RAISE EXCEPTION 'Release package must fix its actual material and Current atom' USING ERRCODE='23514';
 END IF;
END
"""

DECISION_ATOM = r"""
DECLARE v public.release_decisions; p public.release_packages; c public.confirmations;
 vx xid; cx xid; authority jsonb; ref jsonb; review jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.release_decisions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.release_decisions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT p FROM public.release_packages WHERE tenant_id=t AND id=v.package_id;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 PERFORM public.assert_release_common(t,target,'release_decision');
 authority=v.authority_snapshot; review=v.input_snapshot->'review';
 IF v.actor_id<>v.requester_id OR vx IS DISTINCT FROM cx
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND a.kind='human' AND a.active)
  OR NOT EXISTS(SELECT 1 FROM public.release_package_currents cur WHERE cur.tenant_id=t
    AND cur.category_id=v.category_id AND cur.product_id=v.product_id AND cur.project_id=v.project_id
    AND cur.series_id=p.series_id AND cur.version_id=p.id AND cur.revision=p.revision)
  OR v.shared_proof_revision::text IS DISTINCT FROM v.input_snapshot->'command'->>'expected_revision'
  OR v.body->>'operation' IS DISTINCT FROM v.operation OR v.body->>'discipline' IS DISTINCT FROM v.discipline
  OR v.body->'package' IS DISTINCT FROM jsonb_build_object('id',p.id,'revision',p.revision)
  OR v.body->>'package_sha256' IS DISTINCT FROM p.body->>'body_sha256'
  OR (v.body||jsonb_build_object('prepared_at',null)) IS DISTINCT FROM review->'after'
  OR v.body->'input_snapshot' IS DISTINCT FROM v.input_snapshot->'semantic'
  OR v.body->'signers' IS DISTINCT FROM jsonb_build_array(v.actor_id)
  OR v.body->>'purpose' IS DISTINCT FROM v.purpose
  OR v.body->'customer_acceptance' IS DISTINCT FROM 'null'::jsonb
  OR v.body->'external_received' IS DISTINCT FROM 'false'::jsonb
  OR v.body->'external_effective' IS DISTINCT FROM 'false'::jsonb
  OR v.body->'assessment'->>'discipline' IS DISTINCT FROM v.discipline
  OR NOT COALESCE(v.body->'assessment'->>'state' IN ('READY','READY_WITH_CONDITIONS'),false)
  OR v.body->'assessment'->'blocked' IS DISTINCT FROM '[]'::jsonb
  OR v.body->'assessment'->'unknown' IS DISTINCT FROM '[]'::jsonb
  OR (v.body->>'expiry' IS NOT NULL AND v.created_at>=(v.body->>'expiry')::timestamptz)
  OR review->'authority' IS DISTINCT FROM authority
  OR authority->'scope' IS DISTINCT FROM v.body->'scope'
  OR authority->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR authority->>'operation' IS DISTINCT FROM v.operation
  OR authority->>'purpose' IS DISTINCT FROM v.purpose
  OR authority->'authorized' IS DISTINCT FROM 'true'::jsonb
  OR authority->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR NOT(authority->'roles' @> jsonb_build_array(v.discipline))
  OR NOT public.capture_authority_time_current(authority,v.created_at)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(authority->'fact_refs')) THEN
  RAISE EXCEPTION 'Release decision requires the exact package and independent named authority' USING ERRCODE='23514';
 END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(authority->'fact_refs') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_current cur WHERE cur.tenant_id=t
   AND cur.category_id=v.category_id AND cur.product_id=v.product_id AND cur.project_id=v.project_id
   AND cur.subject_id=v.actor_id AND cur.fact_id::text=ref->>'id' AND cur.fact_revision::text=ref->>'revision'
   AND cur.series_id::text=ref->>'series_id' AND cur.kind=ref->>'kind' AND cur.epoch::text=ref->>'epoch') THEN
   RAISE EXCEPTION 'Release named authority Current changed' USING ERRCODE='23514'; END IF;
 END LOOP;
END
"""

CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision=1 AND NEW.epoch=1 AND NEW.version_id=NEW.series_id THEN RETURN NEW; END IF;
 ELSIF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['version_id','revision','epoch']) IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['version_id','revision','epoch'])
   AND NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1
   AND EXISTS(SELECT 1 FROM public.release_packages v WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id
    AND v.category_id=NEW.category_id AND v.product_id=NEW.product_id AND v.project_id=NEW.project_id
    AND v.series_id=NEW.series_id AND v.owner_id=NEW.owner_id AND v.visibility=NEW.visibility
    AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision) THEN RETURN NEW;
  END IF;
 END IF;
 RAISE EXCEPTION 'Release Current advances one exact package and epoch' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.release_package_currents; cx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.release_package_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.release_package_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 IF NOT EXISTS(SELECT 1 FROM public.release_packages p WHERE p.tenant_id=cur.tenant_id
  AND p.category_id=cur.category_id AND p.product_id=cur.product_id AND p.project_id=cur.project_id
  AND p.series_id=cur.series_id AND p.owner_id=cur.owner_id AND p.visibility=cur.visibility
  AND p.id=cur.version_id AND p.revision=cur.revision AND p.xmin=cx) THEN
  RAISE EXCEPTION 'Release Current requires its package in the same transaction' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END
"""

PROOF = f"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN {T2}; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN {T2}; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Release proof history is retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Release proof starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Release proof permits only original false to true' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

TRANSITION = f"""
BEGIN
 IF NEW.operation IN {T2} THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM public.release_decisions v WHERE v.tenant_id=NEW.tenant_id
    AND v.shared_proof_id=NEW.id AND v.operation=NEW.operation)<>1 THEN
   RAISE EXCEPTION 'Consumed release proof requires one actual named decision' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {OPERATIONS} OR OLD.subject_type IN {SUBJECTS}; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {OPERATIONS} OR NEW.subject_type IN {SUBJECTS}; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release receipt is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
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
   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Release original audit event or request is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = f"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW;
 ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation IN {OPERATIONS} OR r.subject_type IN {SUBJECTS} THEN
  PERFORM public.assert_release_members(r.tenant_id,r.subject_id,r.subject_type::text);
 END IF;
 RETURN NULL;
END
"""

FUNCTION_SQL = {
    "assert_release_members(uuid,uuid,text)": _function(
        "assert_release_members", "t uuid,target uuid,kind text", MEMBERS, returns="void"
    ),
    "assert_release_common(uuid,uuid,text)": _function(
        "assert_release_common", "t uuid,target uuid,kind text", COMMON, returns="void"
    ),
    "assert_release_package(uuid,uuid)": _function(
        "assert_release_package", "t uuid,target uuid", PACKAGE, returns="void"
    ),
    "assert_release_decision(uuid,uuid)": _function(
        "assert_release_decision", "t uuid,target uuid", DECISION_ATOM, returns="void"
    ),
    "protect_release_current()": _function("protect_release_current", "", CURRENT_GUARD),
    "require_release_current()": _function("require_release_current", "", CURRENT_ATOM),
    "protect_release_proof()": _function("protect_release_proof", "", PROOF),
    "require_release_transition()": _function("require_release_transition", "", TRANSITION),
    "protect_release_receipt()": _function("protect_release_receipt", "", RECEIPT_GUARD),
    "protect_release_member()": _function("protect_release_member", "", MEMBER_GUARD),
    "require_release_member()": _function("require_release_member", "", MEMBER_TARGET),
    "require_release_package()": _function(
        "require_release_package",
        "",
        "BEGIN PERFORM public.assert_release_package(NEW.tenant_id,NEW.id); RETURN NULL; END",
    ),
    "require_release_decision()": _function(
        "require_release_decision",
        "",
        "BEGIN PERFORM public.assert_release_decision(NEW.tenant_id,NEW.id); RETURN NULL; END",
    ),
    "reject_release_mutation()": _function(
        "reject_release_mutation",
        "",
        "BEGIN RAISE EXCEPTION 'Release package and named decision history is immutable' USING ERRCODE='23514'; END",
    ),
}


def function_sql():
    return tuple(FUNCTION_SQL.values())


def policy_sql():
    statements = []
    for table in TABLES:
        name = table.name
        if table is TABLES[0]:
            read = (
                "public.category_access(tenant_id,category_id) "
                f"AND ({name}.visibility='category' OR {name}.owner_id=public.scope_requester() "
                "OR EXISTS(SELECT 1 FROM public.object_audiences a "
                f"WHERE a.tenant_id={name}.tenant_id AND a.category_id={name}.category_id "
                f"AND a.object_type='{name}' AND a.subject_id={name}.id "
                f"AND a.owner_id={name}.owner_id AND a.principal_id=public.scope_requester())) "
                f"AND EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.id={name}.product_id) "
                f"AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.id={name}.project_id) "
                f"AND public.direct_source_set_visible(tenant_id,category_id,product_id,{name}.required_source_read_set)"
            )
        else:
            identity = "version_id" if table is TABLES[1] else "package_id"
            revision = "revision" if table is TABLES[1] else "package_revision"
            read = (
                "public.category_access(tenant_id,category_id) "
                f"AND EXISTS(SELECT 1 FROM public.release_packages p WHERE p.tenant_id={name}.tenant_id "
                f"AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.project_id={name}.project_id "
                f"AND p.id={name}.{identity} AND p.revision={name}.{revision})"
            )
            if table is TABLES[2]:
                read += f" AND public.direct_source_set_visible(tenant_id,category_id,product_id,{name}.required_source_read_set)"
        write = "public.category_access(tenant_id,category_id,true)"
        if table is TABLES[2]:
            write += (
                " AND public.scope_actor()=public.scope_requester() "
                "AND EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
                "AND a.id=public.scope_actor() AND a.kind='human' AND a.active)"
            )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING (true) WITH CHECK (true)',
                f'CREATE POLICY release_read ON public."{name}" FOR SELECT TO pdos_next_app USING ({read})',
                f'CREATE POLICY release_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK ({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table is TABLES[1]:
            statements.extend(
                (
                    f'CREATE POLICY release_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING ({write} AND {read}) WITH CHECK ({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,epoch) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER release_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER release_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    for table in (TABLES[0], TABLES[2]):
        statements.append(
            f"CREATE TRIGGER release_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.reject_release_mutation()"
        )
    statements.extend(
        (
            "CREATE TRIGGER release_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.release_package_currents FOR EACH ROW EXECUTE FUNCTION public.protect_release_current()",
            "CREATE CONSTRAINT TRIGGER release_current_atom AFTER INSERT OR UPDATE ON public.release_package_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_current()",
            "CREATE CONSTRAINT TRIGGER release_package_atom AFTER INSERT ON public.release_packages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_package()",
            "CREATE CONSTRAINT TRIGGER release_decision_atom AFTER INSERT ON public.release_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_decision()",
            "CREATE TRIGGER release_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_release_proof()",
            "CREATE CONSTRAINT TRIGGER release_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_transition()",
            "CREATE TRIGGER release_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_release_receipt()",
        )
    )
    for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER release_member_atom AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_member()"
        )
        if name != "action_receipts":
            statements.append(
                f"CREATE TRIGGER release_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.protect_release_member()"
            )
    return tuple(statements)


def upgrade_sql():
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in FUNCTION_SQL
        ),
        *policy_sql(),
        *trigger_sql(),
    )


def downgrade_sql():
    return (
        "LOCK TABLE public.release_packages,public.release_package_currents,public.release_decisions,public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        f"""DO $release$ BEGIN
 IF EXISTS(SELECT 1 FROM public.release_packages) OR EXISTS(SELECT 1 FROM public.release_package_currents)
  OR EXISTS(SELECT 1 FROM public.release_decisions) OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {T2})
  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPERATIONS} OR subject_type IN {SUBJECTS}) THEN
  RAISE EXCEPTION 'Release business history is retained; downgrade refused' USING ERRCODE='23514'; END IF;
END; $release$""",
        "DROP TRIGGER release_proof_guard ON public.confirmations",
        "DROP TRIGGER release_proof_target ON public.confirmations",
        "DROP TRIGGER release_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER release_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER release_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(FUNCTION_SQL)),
    )


install_sql = upgrade_sql
uninstall_sql = downgrade_sql
