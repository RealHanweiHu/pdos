"""SQL proposal for the host-only policy owner; no connection or installer.

The ordinary migration owner freezes these statements. New writes bind actual
professional facts, source metadata and the common atomic group. Saved reads
retain their original signature without rescanning private request-key rows.
"""

# ruff: noqa: E501 -- Keep PostgreSQL predicates readable.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .policy_models import ReleasePolicyCurrent, ReleasePolicyFact

TABLES = (ReleasePolicyFact.__table__, ReleasePolicyCurrent.__table__)


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
        f"AS $release_policy$\n{body.rstrip()};\n$release_policy$"
    )


MEMBERS = r"""
DECLARE v public.release_policy_facts; r public.action_receipts;
BEGIN
 SELECT * INTO STRICT v FROM public.release_policy_facts WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 IF ROW(r.category_id,r.product_id,r.command_id,r.actor_id,r.requester_id,r.operation,r.subject_type,
    r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.actor_id,v.requester_id,'release.policy.import'::varchar,
    'release_policy_fact'::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.confirmation_id IS NOT NULL OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status',v.status)
  OR r.created_at<v.created_at
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation='release.policy.import'
    AND x.subject_type='release_policy_fact' AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id
    AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id
    AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type='release.policy_imported'
    AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1
    AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)
  OR v.input_snapshot->>'original_key_sha256' IS NULL
  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id
    AND k.receipt_id=r.id AND k.actor_id=v.actor_id AND k.digest=v.request_digest
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Release policy original common group mismatch' USING ERRCODE='23514'; END IF;
END
"""

ATOM = r"""
DECLARE v public.release_policy_facts; cur public.release_policy_currents; a public.artifact_versions;
 ref jsonb; basis jsonb; auth jsonb; position text[]; line text; vx xid; cx xid; rx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.release_policy_facts WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.release_policy_facts WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT cur FROM public.release_policy_currents WHERE tenant_id=t AND product_id=v.product_id
  AND project_id=v.project_id AND purpose_sha256=v.purpose_sha256;
 SELECT xmin INTO cx FROM public.release_policy_currents WHERE tenant_id=t AND id=cur.id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_release_policy_members(t,target);
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.actor_id<>v.requester_id OR v.writer_id<>v.actor_id OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.actor_id AND p.kind='human' AND p.active)
  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id
    AND p.product_id=v.product_id AND p.id=v.project_id AND p.owner_id=v.owner_id)
  OR vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,cur.fact_id,cur.revision,cur.epoch)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,v.id,v.revision,v.epoch)
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)
   IS DISTINCT FROM ARRAY['original_key_sha256','payload']
  OR v.input_snapshot->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text
  OR v.input_snapshot->'payload'->'source' IS DISTINCT FROM v.source
  OR (v.revision=1 AND v.input_snapshot->'payload'->'expected_previous' IS DISTINCT FROM 'null'::jsonb)
  OR (v.revision>1 AND v.input_snapshot->'payload'->'expected_previous'
   IS DISTINCT FROM jsonb_build_object('id',v.previous_id,'revision',v.previous_revision))
  OR v.material->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
  OR v.material->>'category_id' IS DISTINCT FROM v.category_id::text
  OR v.material->>'publisher_id' IS DISTINCT FROM v.actor_id::text
  OR v.material->>'owner_id' IS DISTINCT FROM v.owner_id::text
  OR v.material->>'visibility' IS DISTINCT FROM v.visibility
  OR v.material->>'purpose' IS DISTINCT FROM v.purpose
  OR v.material->>'policy_version' IS DISTINCT FROM v.policy_version
  OR v.material->>'nature' IS DISTINCT FROM v.nature
  OR v.material->>'status' IS DISTINCT FROM v.status
  OR (v.material->>'valid_from')::timestamptz IS DISTINCT FROM v.valid_from
  OR (v.material->>'valid_until')::timestamptz IS DISTINCT FROM v.valid_until
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.required_source_read_set)
  OR NOT(v.sources @> jsonb_build_array(v.source))
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id
    AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx
    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Release policy requires actual named scope and one transaction' USING ERRCODE='23514'; END IF;
 position=regexp_match(v.source->>'position','^line:([1-9][0-9]*);quote_sha256:([a-f0-9]{64})$');
 IF v.source->>'kind' IS DISTINCT FROM 'artifact' OR position IS NULL
  OR jsonb_typeof(v.source->'revision') IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'Release policy requires an exact original artifact line' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT a FROM public.artifact_versions WHERE tenant_id=t AND category_id=v.category_id
  AND id::text=v.source->>'id' AND revision::text=v.source->>'revision' AND status='active';
 line=(regexp_split_to_array(a.content,E'\r\n|[\n\r\013\014\034-\036\u0085\u2028\u2029]'))[position[1]::integer];
 IF line IS NULL OR encode(sha256(convert_to(line,'UTF8')),'hex')<>position[2] OR line::jsonb IS DISTINCT FROM v.material THEN
  RAISE EXCEPTION 'Release policy original material changed' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM jsonb_object_keys(v.source_basis))<>jsonb_array_length(v.required_source_read_set)
  OR (SELECT count(DISTINCT x->>'artifact_id') FROM jsonb_array_elements(v.required_source_read_set) x)
   <>jsonb_array_length(v.required_source_read_set) THEN
  RAISE EXCEPTION 'Release policy complete source basis required' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP
  basis=v.source_basis->(ref->>'artifact_id');
  IF basis IS NULL OR jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'
   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions art WHERE art.tenant_id=t AND art.category_id=v.category_id
    AND art.id::text=ref->>'artifact_id' AND art.revision::text=ref->>'expected_revision' AND art.status='active'
    AND art.revision::text=basis->>'revision' AND art.content_hash=basis->>'sha256'
    AND art.owner_id::text=basis->>'owner_id' AND art.visibility=basis->>'visibility'
    AND (v.visibility='private' OR art.visibility<>'private')
    AND (art.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o
     JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
     WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=art.original_id AND o.status='parsed'
      AND o.id::text=basis->>'original_id' AND o.revision::text=basis->>'original_revision'
      AND o.content_hash=basis->>'original_sha256' AND o.owner_id::text=basis->>'original_owner_id'
      AND o.visibility=basis->>'original_visibility' AND sec.epoch::text=basis->>'security_epoch'
      AND sec.source_state='active' AND sec.disposition='active' AND (v.visibility='private' OR o.visibility<>'private')))) THEN
   RAISE EXCEPTION 'Release policy direct source version security or audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) src WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(v.required_source_read_set) rd
   WHERE rd->>'artifact_id'=src->>'id' AND rd->'expected_revision'=src->'revision')) THEN
  RAISE EXCEPTION 'Release policy sources must be in the actual read set' USING ERRCODE='23514'; END IF;
 auth=v.authority_snapshot;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'required_source_read_set') rd
   WHERE NOT (v.required_source_read_set @> jsonb_build_array(rd))) THEN
  RAISE EXCEPTION 'Release policy must retain actual publisher sources' USING ERRCODE='23514'; END IF;
 IF auth->'scope' IS DISTINCT FROM v.material->'scope' OR auth->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR auth->>'operation' IS DISTINCT FROM 'release.policy.import' OR auth->>'purpose' IS DISTINCT FROM v.purpose
  OR auth->'authorized' IS DISTINCT FROM 'true'::jsonb OR auth->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR auth->'synthetic' IS DISTINCT FROM to_jsonb(v.nature='synthetic')
  OR NOT public.capture_authority_time_current(auth,v.created_at)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') r WHERE r IN ('engineering','manufacturing','quality'))
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'fact_refs')) THEN
  RAISE EXCEPTION 'Release policy requires actual publisher authority' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(auth->'fact_refs') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f JOIN public.professional_authority_current p
    ON p.tenant_id=f.tenant_id AND p.category_id=f.category_id AND p.product_id=f.product_id AND p.project_id=f.project_id
    AND p.subject_id=f.subject_id AND p.kind=f.kind AND p.series_id=f.series_id AND p.fact_id=f.id AND p.fact_revision=f.revision
   WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id AND f.project_id=v.project_id
    AND f.subject_id=v.actor_id AND f.id::text=ref->>'id' AND f.revision::text=ref->>'revision'
    AND p.epoch::text=ref->>'epoch' AND f.fact_sha256=ref->>'fact_sha256'
    AND f.series_id::text=ref->>'series_id' AND f.kind=ref->>'kind' AND f.role=ref->>'role'
    AND f.state=ref->>'state' AND f.nature=ref->>'nature' AND f.issuer_key=ref->>'issuer_key'
    AND f.issuer_version=ref->>'issuer_version' AND f.operations=ref->'operations' AND f.purposes=ref->'purposes'
    AND f.valid_from IS NOT DISTINCT FROM (ref->>'valid_from')::timestamptz
    AND f.valid_until IS NOT DISTINCT FROM (ref->>'valid_until')::timestamptz) THEN
   RAISE EXCEPTION 'Release policy professional fact or Current changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') AS roles(role_name)
   WHERE role_name IN ('engineering','manufacturing','quality') AND NOT EXISTS(
    SELECT kind FROM unnest(ARRAY['duty','qualification']) kind WHERE NOT EXISTS(
     SELECT 1 FROM jsonb_array_elements(auth->'fact_refs') f WHERE f->>'kind'=kind AND f->>'role'=role_name
      AND f->>'state'='active' AND (f->'operations') @> '["release.policy.import"]'::jsonb
      AND (f->'purposes') @> jsonb_build_array(v.purpose)
      AND (f->>'valid_from')::timestamptz<=v.created_at AND v.created_at<(f->>'valid_until')::timestamptz))) THEN
  RAISE EXCEPTION 'Release policy needs an actual applicable duty and qualification' USING ERRCODE='23514'; END IF;
END
"""

CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision=1 AND NEW.epoch=1 AND NEW.fact_id=NEW.series_id THEN RETURN NEW; END IF;
 ELSIF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['fact_id','revision','epoch']) IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['fact_id','revision','epoch'])
   AND NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1
   AND EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=NEW.tenant_id
    AND f.category_id=NEW.category_id AND f.product_id=NEW.product_id AND f.project_id=NEW.project_id
    AND f.purpose_sha256=NEW.purpose_sha256 AND f.series_id=NEW.series_id AND f.owner_id=NEW.owner_id
    AND f.visibility=NEW.visibility AND f.id=NEW.fact_id AND f.revision=NEW.revision AND f.epoch=NEW.epoch
    AND f.previous_id=OLD.fact_id AND f.previous_revision=OLD.revision) THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION 'Release policy Current advances one exact successor' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.release_policy_currents; cx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.release_policy_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.release_policy_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 IF NOT EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=cur.tenant_id
   AND f.category_id=cur.category_id AND f.product_id=cur.product_id AND f.project_id=cur.project_id
   AND f.series_id=cur.series_id AND f.purpose_sha256=cur.purpose_sha256 AND f.owner_id=cur.owner_id
   AND f.visibility=cur.visibility AND f.id=cur.fact_id AND f.revision=cur.revision AND f.epoch=cur.epoch AND f.xmin=cx) THEN
  RAISE EXCEPTION 'Release policy Current requires its same-transaction fact' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = r"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation='release.policy.import' OR OLD.subject_type='release_policy_fact'; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation='release.policy.import' OR NEW.subject_type='release_policy_fact'; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release policy receipt is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_GUARD = r"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
   AND (r.operation='release.policy.import' OR r.subject_type='release_policy_fact')) INTO scoped;
 END IF;
 IF TG_OP<>'INSERT' THEN
  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id
   AND (r.operation='release.policy.import' OR r.subject_type='release_policy_fact')) INTO old_scoped;
 END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'
   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Release policy original common member is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = r"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW;
 ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation='release.policy.import' OR r.subject_type='release_policy_fact' THEN
  IF r.operation IS DISTINCT FROM 'release.policy.import' OR r.subject_type IS DISTINCT FROM 'release_policy_fact' THEN
   RAISE EXCEPTION 'Release policy common subject mismatch' USING ERRCODE='23514'; END IF;
  PERFORM public.assert_release_policy_members(r.tenant_id,r.subject_id);
 END IF;
 RETURN NULL;
END
"""

FUNCTION_SQL = {
    "assert_release_policy_members(uuid,uuid)": _function(
        "assert_release_policy_members", "t uuid,target uuid", MEMBERS, returns="void"
    ),
    "assert_release_policy_atom(uuid,uuid)": _function(
        "assert_release_policy_atom", "t uuid,target uuid", ATOM, returns="void"
    ),
    "protect_release_policy_current()": _function(
        "protect_release_policy_current", "", CURRENT_GUARD
    ),
    "require_release_policy_current()": _function(
        "require_release_policy_current", "", CURRENT_ATOM
    ),
    "protect_release_policy_receipt()": _function(
        "protect_release_policy_receipt", "", RECEIPT_GUARD
    ),
    "protect_release_policy_member()": _function("protect_release_policy_member", "", MEMBER_GUARD),
    "require_release_policy_member()": _function(
        "require_release_policy_member", "", MEMBER_TARGET
    ),
    "require_release_policy_atom()": _function(
        "require_release_policy_atom",
        "",
        "BEGIN PERFORM public.assert_release_policy_atom(NEW.tenant_id,NEW.id); RETURN NULL; END",
    ),
    "reject_release_policy_mutation()": _function(
        "reject_release_policy_mutation",
        "",
        "BEGIN RAISE EXCEPTION 'Release policy history is immutable' USING ERRCODE='23514'; END",
    ),
}


def function_sql():
    return tuple(FUNCTION_SQL.values())


def policy_sql():
    statements = []
    human = (
        "public.category_access(tenant_id,category_id,true) AND public.scope_actor()=public.scope_requester() "
        "AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
        "AND p.id=public.scope_actor() AND p.kind='human' AND p.active)"
    )
    for table in TABLES:
        name = table.name
        if table is TABLES[0]:
            read = (
                "public.category_access(tenant_id,category_id) "
                f"AND ({name}.visibility='category' OR {name}.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM public.object_audiences a "
                f"WHERE a.tenant_id={name}.tenant_id AND a.category_id={name}.category_id AND a.object_type='{name}' "
                f"AND a.subject_id={name}.id AND a.owner_id={name}.owner_id AND a.principal_id=public.scope_requester())) "
                f"AND EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.id={name}.product_id) "
                f"AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.id={name}.project_id) "
                f"AND public.direct_source_set_visible(tenant_id,category_id,product_id,{name}.required_source_read_set)"
            )
        else:
            read = (
                "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.release_policy_facts f "
                f"WHERE f.tenant_id={name}.tenant_id AND f.category_id={name}.category_id AND f.product_id={name}.product_id "
                f"AND f.project_id={name}.project_id AND f.id={name}.fact_id AND f.revision={name}.revision AND f.epoch={name}.epoch)"
            )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING (true) WITH CHECK (true)',
                f'CREATE POLICY release_policy_read ON public."{name}" FOR SELECT TO pdos_next_app USING ({read})',
                f'CREATE POLICY release_policy_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK ({human} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table is TABLES[1]:
            statements.extend(
                (
                    f'CREATE POLICY release_policy_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING ({human} AND {read}) WITH CHECK ({human} AND {read})',
                    f'GRANT UPDATE(fact_id,revision,epoch) ON public."{name}" TO pdos_next_app',
                )
            )
    receipt = (
        "operation='release.policy.import' AND subject_type='release_policy_fact' AND confirmation_id IS NULL "
        "AND run_id IS NULL AND agent_run_id IS NULL AND actor_id=public.scope_actor() AND requester_id=public.scope_requester() "
        "AND actor_id=requester_id AND public.category_access(tenant_id,category_id,true) "
        "AND EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=action_receipts.tenant_id "
        "AND f.category_id=action_receipts.category_id AND f.product_id=action_receipts.product_id "
        "AND f.id=action_receipts.subject_id AND f.revision=action_receipts.subject_revision "
        "AND f.receipt_id=action_receipts.id AND f.actor_id=action_receipts.actor_id)"
    )
    statements.append(
        f"CREATE POLICY release_policy_receipt_insert ON public.action_receipts FOR INSERT TO pdos_next_app WITH CHECK ({receipt})"
    )
    for name in ("audit_entries", "outbox_events", "request_keys"):
        member = (
            f"EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id={name}.tenant_id AND r.category_id={name}.category_id "
            f"AND r.id={name}.receipt_id AND r.operation='release.policy.import' AND r.subject_type='release_policy_fact' "
            f"AND r.actor_id=public.scope_actor() AND r.requester_id=public.scope_requester() AND r.actor_id={name}.actor_id) "
            "AND public.category_access(tenant_id,category_id,true)"
        )
        if name == "audit_entries":
            member += " AND operation='release.policy.import'"
        elif name == "outbox_events":
            member += " AND type='release.policy_imported'"
        else:
            member += " AND actor_id=public.scope_actor()"
        statements.append(
            f"CREATE POLICY release_policy_member_insert ON public.{name} FOR INSERT TO pdos_next_app WITH CHECK ({member})"
        )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER release_policy_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER release_policy_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    statements.extend(
        (
            "CREATE TRIGGER release_policy_immutable BEFORE UPDATE OR DELETE ON public.release_policy_facts FOR EACH ROW EXECUTE FUNCTION public.reject_release_policy_mutation()",
            "CREATE TRIGGER release_policy_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.release_policy_currents FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_current()",
            "CREATE CONSTRAINT TRIGGER release_policy_atom AFTER INSERT ON public.release_policy_facts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_policy_atom()",
            "CREATE CONSTRAINT TRIGGER release_policy_current_atom AFTER INSERT OR UPDATE ON public.release_policy_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_policy_current()",
            "CREATE TRIGGER release_policy_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_receipt()",
        )
    )
    for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER release_policy_member_atom AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_policy_member()"
        )
        if name != "action_receipts":
            statements.append(
                f"CREATE TRIGGER release_policy_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_member()"
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
        "LOCK TABLE public.release_policy_facts,public.release_policy_currents,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        """DO $release_policy$ BEGIN
 IF EXISTS(SELECT 1 FROM public.release_policy_facts) OR EXISTS(SELECT 1 FROM public.release_policy_currents)
  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='release.policy.import' OR subject_type='release_policy_fact') THEN
  RAISE EXCEPTION 'Release policy business history retained; downgrade refused' USING ERRCODE='23514'; END IF;
END; $release_policy$""",
        "DROP POLICY release_policy_receipt_insert ON public.action_receipts",
        *(
            f"DROP POLICY release_policy_member_insert ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        "DROP TRIGGER release_policy_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER release_policy_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER release_policy_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(FUNCTION_SQL)),
    )
