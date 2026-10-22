"""Field DDL and independent transaction declarations; never opens a database.

Retained source ACLs remain ordinary-caller checks. An old report's withdrawn
source does not prevent recording a newly evidenced containment fact.
"""

# ruff: noqa: E501 -- complete PostgreSQL predicates remain readable.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next import models as registered_models  # noqa: F401 -- parent metadata

from .models import (
    CURRENT,
    FEEDBACK,
    RESPONSE,
    FieldFeedbackCurrent,
    FieldFeedbackVersion,
    FieldResponseRecord,
)

TABLES = tuple(
    model.__table__ for model in (FieldFeedbackVersion, FieldFeedbackCurrent, FieldResponseRecord)
)
FACTS = (FEEDBACK, RESPONSE)
OPS = "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link')"
T1 = "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link')"
SUBJECTS = "('field_feedback','field_response')"
CONTENT_ACL = (
    "public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis)"
)
RESULT_ACL = (
    "public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis)"
)
RECEIPT_SIGNATURE = "field_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)"


def table_sql():
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(i) for i in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def _scope_read(name):
    return (
        "public.category_access(tenant_id,category_id) "
        "AND (visibility='category' OR owner_id=public.scope_requester()) "
        f"AND ({name}.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products p "
        f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.id={name}.product_id)) "
        f"AND ({name}.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p "
        f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
        f"AND p.product_id={name}.product_id AND p.id={name}.project_id))"
    )


def policy_sql():
    statements = []
    for table in TABLES:
        name = table.name
        read = _scope_read(name)
        if name in FACTS:
            read += f" AND {CONTENT_ACL} AND {RESULT_ACL}"
        if name == CURRENT:
            read += (
                f" AND EXISTS(SELECT 1 FROM public.{FEEDBACK} fixed WHERE fixed.tenant_id={name}.tenant_id "
                f"AND fixed.category_id={name}.category_id AND fixed.feedback_id={name}.feedback_id "
                f"AND fixed.id={name}.version_id AND fixed.revision={name}.revision "
                f"AND ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM "
                f"ROW({name}.product_id,{name}.project_id,{name}.owner_id,{name}.visibility))"
            )
        if name == RESPONSE:
            # The historical parent, not its Current, owns read authority. This
            # never reads Receipt, avoiding a Receipt -> response -> Receipt loop.
            read += (
                f" AND EXISTS(SELECT 1 FROM public.{FEEDBACK} parent WHERE parent.tenant_id={name}.tenant_id "
                f"AND parent.category_id={name}.category_id AND parent.feedback_id={name}.feedback_id "
                f"AND parent.id={name}.feedback_version_id AND parent.revision={name}.feedback_revision "
                f"AND ROW(parent.product_id,parent.project_id) IS NOT DISTINCT FROM ROW({name}.product_id,{name}.project_id))"
            )
        write = "public.category_access(tenant_id,category_id,true)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY field_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY field_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {_scope_read(name)})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == CURRENT:
            statements.extend(
                (
                    f'CREATE POLICY field_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {_scope_read(name)})',
                    f'GRANT UPDATE(version_id,revision,product_id,project_id) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;
 ELSIF TG_OP='UPDATE'
  AND (to_jsonb(NEW)-ARRAY['version_id','revision','product_id','project_id']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['version_id','revision','product_id','project_id'])
  AND NEW.revision=OLD.revision+1 AND (OLD.product_id IS NULL OR NEW.product_id=OLD.product_id)
  AND EXISTS(SELECT 1 FROM public.field_feedback_versions v WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id
   AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision
   AND v.operation='field.feedback.locate' AND v.product_id=NEW.product_id AND v.project_id IS NOT DISTINCT FROM NEW.project_id)
 THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Field Current requires an exact single-step location CAS' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.field_feedback_currents; fixed public.field_feedback_versions; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO STRICT fixed FROM public.field_feedback_versions WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 IF vx IS DISTINCT FROM cx OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)
  IS DISTINCT FROM ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.feedback_id,fixed.id,fixed.revision) THEN
  RAISE EXCEPTION 'Field Current requires its exact same-transaction version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

SELECT_FACT = r"""
 IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;
 ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.field_response_records x WHERE x.tenant_id=t AND x.id=target;
 ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;
"""

MEMBERS_ATOM = r"""
DECLARE v record; r public.action_receipts; proof public.confirmations; expected jsonb; event_name text;
BEGIN
__SELECT__
 expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE WHEN kind='field_response' THEN 'recorded' WHEN v.body->'location' IS NOT NULL AND v.body->'location'<>'null'::jsonb THEN 'located' ELSE 'unknown' END,
  'feedback_id',v.feedback_id,'project_id',v.project_id);
 event_name=CASE v.operation WHEN 'field.feedback.create' THEN 'field.feedback_created' WHEN 'field.feedback.locate' THEN 'field.feedback_located'
  WHEN 'field.feedback.action.record' THEN 'field.feedback_action_recorded' WHEN 'field.feedback.followup.link' THEN 'field.feedback_followup_linked' END;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 IF ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.result IS DISTINCT FROM expected OR r.created_at<v.created_at OR event_name IS NULL
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND x.operation=v.operation AND x.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND x.type=event_name AND x.subject_id=v.id AND x.subject_revision=v.revision AND x.schema_version=1 AND x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND x.created_at>=v.created_at)
  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR (v.command->'envelope') ? 'idempotency_key' OR (v.command->'envelope'->'payload') ? 'confirmation_token'
  OR (v.command->'envelope'->'payload') ? 'approval_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Field original receipt audit event or request key mismatch' USING ERRCODE='23514'; END IF;
 IF v.operation<>'field.feedback.create' THEN
  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF proof.consumed IS DISTINCT FROM true OR ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE WHEN v.product_id IS NULL THEN 'category' ELSE 'product' END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)
   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at OR proof.expires_at IS NULL
   OR v.created_at>=proof.expires_at OR r.created_at>=proof.expires_at OR v.actor_id<>v.requester_id
   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN
   RAISE EXCEPTION 'Field T1 requires its actual consumed human confirmation' USING ERRCODE='23514'; END IF;
 END IF;
END
""".replace("__SELECT__", SELECT_FACT)

COMMON_ATOM = r"""
DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb; active_sources jsonb;
BEGIN
__SELECT__
 vx=v.tx;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_field_members(t,target,kind);
 envelope=v.command->'envelope';
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND h.active)
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' AND h.active)
  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM v.command_id::text
  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS DISTINCT FROM v.product_id::text
  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'
  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation
  OR v.command->'review'->'sources' IS DISTINCT FROM envelope->'payload'->'sources'
  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis OR v.body IS DISTINCT FROM v.command->'review'->'after'
  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))
  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id AND p.id=v.product_id AND p.revision::text=envelope->>'expected_revision'))
  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))
  OR NOT coalesce((envelope->'source_read_set') @> (v.reads),false) OR NOT coalesce((v.reads) @> (envelope->'source_read_set'),false)
  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)
  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)
  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)
  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Field requires actual scope actor sources and one common transaction' USING ERRCODE='23514'; END IF;
 IF v.confirmation_id IS NOT NULL THEN
  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 consumption shares its new fact transaction' USING ERRCODE='23514'; END IF;
 END IF;
 IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Field requires actual direct-source metadata' USING ERRCODE='23514'; END IF;
 FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
   AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'
   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash'
   AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products source_product
    WHERE source_product.tenant_id=t AND source_product.category_id=v.category_id AND source_product.id=a.product_id AND source_product.visibility='category'))))
   AND (a.original_id IS NULL OR v.visibility='private' OR EXISTS(SELECT 1 FROM public.uploaded_originals o
    WHERE o.tenant_id=t AND o.id=a.original_id AND o.visibility='category'))) THEN
   RAISE EXCEPTION 'Field historical source hash or actual audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 active_sources=CASE WHEN kind='field_feedback' THEN v.sources ELSE envelope->'payload'->'sources' END;
 IF v.operation='field.feedback.followup.link' THEN
  active_sources=active_sources||coalesce((SELECT jsonb_agg(content.value) FROM jsonb_array_elements(v.source_basis->'result_receipts') result,
   LATERAL jsonb_array_elements(result->'direct_content_refs') content),'[]'::jsonb);
 END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(active_sources) LOOP
  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE value->>'id'=ref->>'id';
  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND rd->'expected_revision'=ref->'revision')
   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'
    AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.revision::text=basis->>'revision'
    AND a.content_hash=basis->>'hash' AND a.status=basis->>'status' AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'
    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(SELECT 1 FROM public.action_receipts r
      WHERE r.tenant_id=t AND r.subject_id=a.id AND r.subject_revision=a.revision AND r.subject_type='artifact' AND r.operation='evidence.artifact.register'
       AND r.id::text=basis->'registration'->>'receipt_id' AND r.actor_id::text=basis->'registration'->>'actor_id'
       AND r.requester_id::text=basis->'registration'->>'requester_id' AND r.run_id::text IS NOT DISTINCT FROM basis->'registration'->>'run_id'))
     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 FROM public.uploaded_originals o
      JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE o.tenant_id=t AND o.category_id=v.category_id
       AND o.id=a.original_id AND o.id::text=basis->'original'->>'id' AND o.status='parsed' AND sec.epoch::text=basis->'original'->>'epoch'
       AND sec.source_state='active' AND sec.disposition='active' AND sec.source_state=basis->'original'->>'source_state'
       AND sec.disposition=basis->'original'->>'disposition')))) THEN
   RAISE EXCEPTION 'Field newly adopted direct source metadata changed' USING ERRCODE='23514'; END IF;
 END LOOP;
END
""".replace("__SELECT__", SELECT_FACT)

FEEDBACK_ATOM = r"""
DECLARE v public.field_feedback_versions; prior public.field_feedback_versions; cur public.field_feedback_currents;
 payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;
 PERFORM public.assert_field_common(t,target,'field_feedback');
 SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND category_id=v.category_id AND feedback_id=v.feedback_id;
 SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=t AND id=cur.id;
 payload=v.command->'envelope'->'payload';
 IF vx IS DISTINCT FROM cx OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)
  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field feedback binds actual owner and same-transaction Current' USING ERRCODE='23514'; END IF;
 IF v.operation='field.feedback.create' THEN
  expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',
   'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);
  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources' OR v.project_id IS NOT NULL
   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb THEN
   RAISE EXCEPTION 'Field intake records only its actual declared source report, with unknown location' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT prior FROM public.field_feedback_versions WHERE tenant_id=t AND id=v.previous_id;
  location=v.body->'location';
  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS DISTINCT FROM ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)
   OR (prior.product_id IS NOT NULL AND prior.product_id IS DISTINCT FROM v.product_id)
   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT FROM jsonb_build_object('id',v.feedback_id,'revision',prior.revision)
   OR v.command->'review'->'before' IS DISTINCT FROM prior.body
   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM (prior.body-ARRAY['revision','location'])
   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)
   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR location->>'state' IS DISTINCT FROM 'known'
   OR location->>'product_id' IS DISTINCT FROM v.product_id::text OR location->>'project_id' IS DISTINCT FROM v.project_id::text
   OR location->'engineering_configuration' IS DISTINCT FROM payload->'engineering_configuration'
   OR location->'manufacturing_configuration' IS DISTINCT FROM payload->'manufacturing_configuration'
   OR location->'batch' IS DISTINCT FROM payload->'batch'
   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb AND payload->>'project_id' IS DISTINCT FROM v.project_id::text)
   OR NOT coalesce((v.sources) @> (prior.sources),false) OR NOT coalesce((v.sources) @> (payload->'sources'),false)
   OR NOT coalesce((v.sources) @> (location->'sources'),false)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) source WHERE NOT((prior.sources) @> (jsonb_build_array(source))
    OR (payload->'sources') @> (jsonb_build_array(source)) OR (location->'sources') @> (jsonb_build_array(source)))) THEN
   RAISE EXCEPTION 'Field location preserves report, privacy and exact predecessor; known product cannot silently change' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations engineering WHERE engineering.tenant_id=t AND engineering.category_id=v.category_id
   AND engineering.product_id=v.product_id AND engineering.id::text=location->'engineering_configuration'->>'id'
   AND engineering.revision::text=location->'engineering_configuration'->>'revision'
   AND coalesce((v.reads) @> (engineering.required_source_read_set),false)
   AND (v.visibility='private' OR engineering.visibility='category')
   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM public.project_product_links link WHERE link.tenant_id=t AND link.category_id=v.category_id
    AND link.product_id=v.product_id AND link.project_id=v.project_id AND link.definition_id=engineering.definition_id AND link.definition_revision=engineering.definition_revision))) THEN
   RAISE EXCEPTION 'Field location requires an actual engineering configuration in the selected project' USING ERRCODE='23514'; END IF;
  IF coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM public.process_revisions manufacturing
   WHERE manufacturing.tenant_id=t AND manufacturing.category_id=v.category_id AND manufacturing.product_id=v.product_id
    AND manufacturing.id::text=location->'manufacturing_configuration'->>'id' AND manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'
    AND manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'
    AND coalesce((v.reads) @> (manufacturing.required_source_read_set),false) AND (v.visibility='private' OR manufacturing.visibility='category')) THEN
   RAISE EXCEPTION 'Field manufacturing configuration must match actual engineering configuration' USING ERRCODE='23514'; END IF;
  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM public.build_lots lot
   JOIN public.actual_configurations actual ON actual.tenant_id=lot.tenant_id AND actual.product_id=lot.product_id AND actual.id=lot.actual_configuration_id
   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND lot.product_id=v.product_id AND lot.project_id=v.project_id
    AND lot.id::text=location->'batch'->>'id' AND lot.revision::text=location->'batch'->>'revision'
    AND actual.revision=lot.actual_configuration_revision
    AND actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'
    AND actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'
    AND actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'
    AND actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'
    AND (payload->>'project_id' IS NULL OR payload->>'project_id'=lot.project_id::text)
    AND coalesce((v.reads) @> (lot.required_source_read_set),false) AND coalesce((v.reads) @> (actual.required_source_read_set),false)
    AND (v.visibility='private' OR (lot.visibility='category' AND actual.visibility='category'))) THEN
   RAISE EXCEPTION 'Field batch requires exact native lot and actual physical configuration' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

RESPONSE_ATOM = r"""
DECLARE v public.field_response_records; parent public.field_feedback_versions; cur public.field_feedback_currents;
 payload jsonb; expected jsonb; selected_result jsonb; native_receipt public.action_receipts;
BEGIN
 SELECT * INTO STRICT v FROM public.field_response_records WHERE tenant_id=t AND id=target;
 PERFORM public.assert_field_common(t,target,'field_response');
 SELECT * INTO STRICT parent FROM public.field_feedback_versions WHERE tenant_id=t AND category_id=v.category_id AND id=v.feedback_version_id;
 SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND category_id=v.category_id AND feedback_id=v.feedback_id;
 payload=v.command->'envelope'->'payload';
 expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,
  'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));
 IF ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)
  IS DISTINCT FROM ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)
  OR cur.version_id<>parent.id OR cur.revision<>parent.revision
  OR v.owner_id<>v.requester_id OR (parent.visibility='private' AND v.visibility<>'private')
  OR payload->>'visibility' IS DISTINCT FROM v.visibility
  OR payload->'feedback' IS DISTINCT FROM jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)
  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources'
  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM (payload->>'occurred_at')::timestamptz
  OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb
  OR (v.operation='field.feedback.action.record' AND (payload->>'action_kind' IS DISTINCT FROM v.response_kind OR v.body->'result_receipts'<>'[]'::jsonb))
  OR NOT coalesce((v.source_basis->'artifacts') @> (parent.source_basis->'artifacts'),false) THEN
  RAISE EXCEPTION 'Field response binds exact current parent and new actual facts without advancing its report' USING ERRCODE='23514'; END IF;
 IF v.operation='field.feedback.followup.link' THEN
  IF v.project_id IS NULL OR jsonb_array_length(payload->'result_receipts')=0
   OR jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') AS fixed_result(value) WHERE fixed_result.value->>'product_id' IS DISTINCT FROM v.product_id::text
    OR fixed_result.value->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(payload->'result_receipts') requested WHERE requested->'receipt_id'=fixed_result.value->'receipt_id')) THEN
   RAISE EXCEPTION 'Field follow-up references only finite fixed native results in its actual project' USING ERRCODE='23514'; END IF;
  FOR selected_result IN SELECT value FROM jsonb_array_elements(v.source_basis->'result_receipts') LOOP
   SELECT * INTO STRICT native_receipt FROM public.action_receipts r WHERE r.tenant_id=t AND r.category_id=v.category_id
    AND r.id::text=selected_result->>'receipt_id' AND r.product_id=v.product_id AND r.operation=selected_result->>'operation'
    AND r.subject_type=selected_result->>'subject_type' AND r.subject_id::text=selected_result->>'subject_id'
    AND r.subject_revision::text=selected_result->>'subject_revision' AND r.request_digest=selected_result->>'receipt_request_digest'
    AND r.visibility=selected_result->>'receipt_visibility';
   IF (v.visibility='category' AND (native_receipt.visibility<>'category' OR selected_result->>'visibility'<>'category'
     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.id=v.product_id AND p.visibility='category')
     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.id=v.project_id AND p.visibility='category')))
    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.category_id=v.category_id AND a.receipt_id=native_receipt.id
     AND a.actor_id=native_receipt.actor_id AND a.operation=native_receipt.operation)
    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.category_id=v.category_id AND e.receipt_id=native_receipt.id
     AND e.subject_id=native_receipt.subject_id AND e.subject_revision=native_receipt.subject_revision AND e.actor_id=native_receipt.actor_id
     AND e.schema_version=1 AND e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) THEN
    RAISE EXCEPTION 'Field follow-up requires actual native receipt audit event and audience' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
END
"""

RECEIPT_GUARD = r"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN __OPS__ OR OLD.subject_type IN __SUBJECTS__; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN __OPS__ OR NEW.subject_type IN __SUBJECTS__; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Field receipt history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
""".replace("__OPS__", OPS).replace("__SUBJECTS__", SUBJECTS)

MEMBER_GUARD = r"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN __OPS__ OR r.subject_type IN __SUBJECTS__)) INTO scoped; END IF;
 IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN __OPS__ OR r.subject_type IN __SUBJECTS__)) INTO old_scoped; END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Field original audit event or request key is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
""".replace("__OPS__", OPS).replace("__SUBJECTS__", SUBJECTS)

MEMBER_TARGET = r"""
DECLARE receipt public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * INTO receipt FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF receipt.operation IN __OPS__ OR receipt.subject_type IN __SUBJECTS__ THEN
  PERFORM public.assert_field_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); END IF;
 RETURN NULL;
END
""".replace("__OPS__", OPS).replace("__SUBJECTS__", SUBJECTS)

CONFIRMATION_GUARD = r"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN __T1__; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN __T1__; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Field confirmation history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Field T1 starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Field confirmation consumes only its original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
""".replace("__T1__", T1)

CONFIRMATION_TARGET = r"""
BEGIN
 IF NEW.operation IN __T1__ THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM (SELECT confirmation_id FROM public.field_feedback_versions v WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation
    UNION ALL SELECT confirmation_id FROM public.field_response_records v WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation) refs)<>1 THEN
   RAISE EXCEPTION 'Consumed Field T1 proof requires exactly one new fact' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
""".replace("__T1__", T1)

RECEIPT_VISIBLE = r"""
BEGIN
 IF kind NOT IN ('field_feedback','field_response') THEN RETURN true; END IF;
 IF NOT public.category_access(t,c) THEN RETURN false; END IF;
 IF kind='field_feedback' THEN RETURN EXISTS(SELECT 1 FROM public.field_feedback_versions f WHERE f.tenant_id=t AND f.category_id=c
  AND f.product_id IS NOT DISTINCT FROM p AND f.id=target AND f.revision=rev AND f.receipt_id=receipt AND f.actor_id=actor
  AND f.operation IN ('field.feedback.create','field.feedback.locate'));
 ELSIF kind='field_response' THEN RETURN EXISTS(SELECT 1 FROM public.field_response_records f WHERE f.tenant_id=t AND f.category_id=c
  AND f.product_id IS NOT DISTINCT FROM p AND f.id=target AND f.revision=rev AND f.receipt_id=receipt AND f.actor_id=actor
  AND f.operation IN ('field.feedback.action.record','field.feedback.followup.link')); END IF;
 RETURN false;
END
"""


def functions():
    return (
        (
            "reject_field_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Field facts are immutable' USING ERRCODE='23514'; END",
            "trigger",
        ),
        ("protect_field_current", "", CURRENT_GUARD, "trigger"),
        ("require_field_current", "", CURRENT_ATOM, "trigger"),
        ("assert_field_members", "t uuid,target uuid,kind text", MEMBERS_ATOM, "void"),
        ("assert_field_common", "t uuid,target uuid,kind text", COMMON_ATOM, "void"),
        ("assert_field_feedback", "t uuid,target uuid", FEEDBACK_ATOM, "void"),
        ("assert_field_response", "t uuid,target uuid", RESPONSE_ATOM, "void"),
        (
            "require_field_feedback",
            "",
            "BEGIN PERFORM public.assert_field_feedback(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
        (
            "require_field_response",
            "",
            "BEGIN PERFORM public.assert_field_response(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
        ("protect_field_receipt", "", RECEIPT_GUARD, "trigger"),
        ("protect_field_member", "", MEMBER_GUARD, "trigger"),
        ("require_field_member", "", MEMBER_TARGET, "trigger"),
        ("protect_field_confirmation", "", CONFIRMATION_GUARD, "trigger"),
        ("require_field_confirmation", "", CONFIRMATION_TARGET, "trigger"),
    )


def _function(name, args, body, returns):
    return (
        f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n"
        f"{body.rstrip()};\n$field$"
    )


def function_sql():
    return tuple(_function(*value) for value in functions())


def signatures():
    return tuple(
        name + "(" + ",".join(part.split()[-1] for part in args.split(",") if part) + ")"
        for name, args, _body, _returns in functions()
    )


def receipt_visibility_sql():
    """Install separately before adding this finite helper to core RLS policies."""
    return (
        "CREATE FUNCTION public.field_receipt_visible(t uuid,c uuid,p uuid,kind text,target uuid,rev integer,receipt uuid,actor uuid) RETURNS boolean\n"
        "LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $field_receipt$\n"
        + RECEIPT_VISIBLE.rstrip()
        + ";\n$field_receipt$",
        f"REVOKE ALL ON FUNCTION public.{RECEIPT_SIGNATURE} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        f"GRANT EXECUTE ON FUNCTION public.{RECEIPT_SIGNATURE} TO pdos_next_app",
    )


def trigger_sql():
    statements = []
    for table, stem in ((FEEDBACK, "field_feedback"), (RESPONSE, "field_response")):
        statements.extend(
            (
                f"CREATE TRIGGER {stem}_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_field_mutation()",
                f"CREATE CONSTRAINT TRIGGER {stem}_atom AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}()",
            )
        )
    statements.extend(
        (
            f"CREATE TRIGGER field_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENT} FOR EACH ROW EXECUTE FUNCTION public.protect_field_current()",
            f"CREATE CONSTRAINT TRIGGER field_current_atom AFTER INSERT OR UPDATE ON public.{CURRENT} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_current()",
        )
    )
    return tuple(statements)


def common_trigger_sql():
    values = [
        "CREATE TRIGGER protect_field_receipt BEFORE UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_field_receipt()",
        "CREATE TRIGGER protect_field_confirmation BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_field_confirmation()",
        "CREATE CONSTRAINT TRIGGER require_field_confirmation AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_confirmation()",
    ]
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        if table != "action_receipts":
            values.append(
                f"CREATE TRIGGER protect_field_member BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.protect_field_member()"
            )
        values.append(
            f"CREATE CONSTRAINT TRIGGER require_field_member AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_member()"
        )
    return tuple(values)


def drop_cycle_sql():
    return ()


def upgrade_sql():
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in signatures()
        ),
        *receipt_visibility_sql(),
        *policy_sql(),
        *trigger_sql(),
        *common_trigger_sql(),
    )


def downgrade_sql():
    values = [
        "LOCK TABLE public.field_feedback_versions,public.field_feedback_currents,public.field_response_records,public.action_receipts,public.confirmations IN ACCESS EXCLUSIVE MODE",
        "DO $field$ BEGIN IF EXISTS(SELECT 1 FROM public.field_feedback_versions) OR EXISTS(SELECT 1 FROM public.field_feedback_currents) OR EXISTS(SELECT 1 FROM public.field_response_records) "
        f"OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPS} OR subject_type IN {SUBJECTS}) "
        f"OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {T1}) THEN RAISE EXCEPTION 'Field history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $field$",
        "DROP TRIGGER protect_field_receipt ON public.action_receipts",
        "DROP TRIGGER protect_field_confirmation ON public.confirmations",
        "DROP TRIGGER require_field_confirmation ON public.confirmations",
    ]
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        if table != "action_receipts":
            values.append(f"DROP TRIGGER protect_field_member ON public.{table}")
        values.append(f"DROP TRIGGER require_field_member ON public.{table}")
    values.extend(f"DROP TABLE public.{table}" for table in (RESPONSE, CURRENT, FEEDBACK))
    values.append(f"DROP FUNCTION public.{RECEIPT_SIGNATURE}")
    values.extend(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures()))
    return tuple(values)
