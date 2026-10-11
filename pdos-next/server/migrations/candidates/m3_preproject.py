"""M3 early G0 DDL candidate, intentionally outside Alembic's active revision directory.

Install only on the independently marked M3 fixture. B7/B8 integration must freeze this
material into an immutable Alembic revision allocated from the then-current real head.
"""

# ruff: noqa: E501 -- reviewable SQL statements preserve their exact candidate text

import json

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from migrations.versions.s0_0010_audience_fence import OWNERS as AUDIENCE_OWNERS
from migrations.versions.s0_0010_audience_fence import SQL as AUDIENCE_SQL
from pdos_next.domain.preproject.category_models import TABLES as CATEGORY_TABLES
from pdos_next.domain.preproject.models import TABLES

DELTA = """
-- The current common T2 confirmation policy permits no deadline. B7 must
-- incorporate this ORM/schema alignment when it freezes the actual heads.
ALTER TABLE confirmations ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE definition_revisions
 ADD COLUMN sealed boolean NOT NULL DEFAULT false,
 ADD COLUMN source_proposal_id uuid,
 ADD COLUMN source_submission_id uuid,
 ADD COLUMN source_proposal_revision integer,
 ADD COLUMN g0_decision_id uuid;
ALTER TABLE definition_specs
 ADD COLUMN parameter_id uuid,
 ADD COLUMN parameter_version integer,
 ADD COLUMN item_status text NOT NULL DEFAULT 'unknown',
 ADD COLUMN condition_note text,
 ADD COLUMN modality text,
 ADD COLUMN exceptions jsonb NOT NULL DEFAULT '[]',
 ADD COLUMN applicable_variants jsonb NOT NULL DEFAULT '[]',
 ADD COLUMN source_refs jsonb NOT NULL DEFAULT '[]',
 ADD COLUMN origin text NOT NULL DEFAULT 'human',
 ADD COLUMN writer_id uuid,
 ADD COLUMN run_id uuid,
 ADD COLUMN confirmed_by uuid,
 ADD COLUMN receipt_id uuid;
ALTER TABLE projects ADD COLUMN trigger_type text, ADD COLUMN trigger_id uuid,
 ADD COLUMN g0_decision_id uuid;
ALTER TABLE definition_revisions ADD CONSTRAINT m3_definition_decision_fk
 FOREIGN KEY(tenant_id,category_id,g0_decision_id)
 REFERENCES proposal_decisions(tenant_id,category_id,id);
ALTER TABLE projects ADD CONSTRAINT m3_project_decision_fk
 FOREIGN KEY(tenant_id,category_id,g0_decision_id)
 REFERENCES proposal_decisions(tenant_id,category_id,id);
ALTER TABLE definition_specs ADD CONSTRAINT m3_spec_status
 CHECK(item_status IN ('ai_draft','confirmed','expert_pending','unknown'));
ALTER TABLE definition_specs ADD CONSTRAINT m3_spec_origin
 CHECK(origin IN ('human','ai_draft','imported') AND (origin<>'ai_draft' OR run_id IS NOT NULL));
DO $$ DECLARE x record; BEGIN
 FOR x IN SELECT conname,pg_get_constraintdef(oid) AS body FROM pg_constraint
 WHERE conrelid='definition_specs'::regclass AND contype='c' LOOP
  IF x.body LIKE '%value_type%' THEN
   EXECUTE format('ALTER TABLE definition_specs DROP CONSTRAINT %I',x.conname);
  END IF;
 END LOOP;
END $$;
ALTER TABLE definition_specs ADD CONSTRAINT m3_spec_value_type
 CHECK(value_type IN ('number','range','text','boolean','enum'));
ALTER TABLE definition_specs ADD CONSTRAINT m3_spec_known_shape CHECK(
 availability<>'known' OR
 (value_type='number' AND value IS NOT NULL AND lower IS NULL AND upper IS NULL AND text IS NULL) OR
 (value_type='range' AND lower IS NOT NULL AND upper IS NOT NULL AND value IS NULL AND text IS NULL) OR
 (value_type IN ('text','boolean','enum') AND text IS NOT NULL AND value IS NULL
  AND lower IS NULL AND upper IS NULL));
ALTER TABLE definition_specs ALTER COLUMN key TYPE text, ALTER COLUMN parameter TYPE text,
 ALTER COLUMN unit TYPE text;
ALTER TABLE products ALTER COLUMN name TYPE text;
ALTER TABLE projects ALTER COLUMN name TYPE text;
ALTER TABLE definition_revisions ALTER COLUMN title TYPE text;
ALTER TABLE products ADD COLUMN target_price numeric(38,12),
 ADD COLUMN target_price_currency text, ADD COLUMN target_price_basis text,
 ADD COLUMN target_price_includes_tax boolean, ADD COLUMN target_price_as_of date;
ALTER TABLE products ADD CONSTRAINT m3_target_price_basis
 CHECK(target_price_basis IS NULL OR target_price_basis IN ('retail','promo','unknown'));
"""

SECURITY = """
CREATE OR REPLACE FUNCTION direct_source_set_visible(t uuid,c uuid,p uuid,refs jsonb)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (
  SELECT 1 FROM jsonb_array_elements(refs) r
  LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid
   AND a.tenant_id=t AND a.category_id=c AND (a.product_id IS NULL OR a.product_id=p)
  LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c
  LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c
   AND o.product_id IS NOT DISTINCT FROM a.product_id
  WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL
   OR NOT source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)))
   OR NOT source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)
   OR (a.original_id IS NOT NULL AND (o.id IS NULL
    OR NOT source_object_audience(t,c,'uploaded_originals',o.id,o.owner_id,o.visibility)))
 )
$$;
CREATE FUNCTION m3_proposal_reader(t uuid,c uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM proposals x WHERE x.tenant_id=t
 AND x.category_id=c AND x.id=p AND (x.effective_visibility='category'
 OR x.owner_id=scope_requester() OR EXISTS(SELECT 1 FROM proposal_submissions sub
 WHERE sub.tenant_id=t AND sub.proposal_id=p AND sub.reviewer_id=scope_requester())
 OR (x.effective_visibility='audience' AND EXISTS(SELECT 1 FROM object_audiences a
 WHERE a.tenant_id=t AND a.category_id=c AND a.object_type='proposals'
 AND a.subject_id=p AND a.principal_id=scope_requester()))))
$$;
CREATE FUNCTION m3_reviewer(t uuid,c uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT scope_actor()=scope_requester() AND category_access(t,c) AND EXISTS(
 SELECT 1 FROM proposals x JOIN proposal_submissions sub ON sub.id=x.current_submission_id
 AND sub.tenant_id=x.tenant_id AND sub.proposal_id=x.id
 JOIN grants g ON g.tenant_id=x.tenant_id AND g.category_id=x.category_id
 AND g.principal_id=sub.reviewer_id
 JOIN principals person ON person.tenant_id=g.tenant_id AND person.id=g.principal_id
 WHERE x.tenant_id=t AND x.category_id=c AND x.id=p AND x.status='in_review'
 AND x.owner_id<>sub.reviewer_id AND sub.reviewer_id=scope_requester()
 AND g.product_manager AND (g.expires_at IS NULL OR g.expires_at>now())
 AND person.active AND person.kind='human')
$$;
CREATE FUNCTION m3_owner(t uuid,c uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c,true) AND EXISTS(SELECT 1 FROM proposals x
 WHERE x.tenant_id=t AND x.category_id=c AND x.id=p AND x.owner_id=scope_requester())
$$;
CREATE FUNCTION m3_writer(t uuid,c uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c,true) AND m3_proposal_reader(t,c,p) AND EXISTS(
 SELECT 1 FROM proposals x WHERE x.tenant_id=t AND x.category_id=c AND x.id=p
 AND x.status IN ('draft','returned'))
$$;
CREATE FUNCTION m3_audience_member(t uuid,c uuid,p uuid,person_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1
 FROM proposals x JOIN grants g ON g.tenant_id=x.tenant_id AND g.category_id=x.category_id
 JOIN principals person ON person.tenant_id=g.tenant_id AND person.id=g.principal_id
 WHERE x.tenant_id=t AND x.category_id=c AND x.id=p AND person.id=person_id
 AND m3_proposal_reader(t,c,p)
 AND person.active AND (g.expires_at IS NULL OR g.expires_at>now())
 AND (x.effective_visibility='category' OR x.owner_id=person.id
 OR EXISTS(SELECT 1 FROM proposal_submissions sub WHERE sub.tenant_id=t
  AND sub.proposal_id=p AND sub.reviewer_id=person.id)
 OR (x.effective_visibility='audience' AND EXISTS(SELECT 1 FROM object_audiences a
  WHERE a.tenant_id=t AND a.category_id=c AND a.object_type='proposals'
  AND a.subject_id=p AND a.principal_id=person.id))))
$$;
CREATE FUNCTION m3_decision_actor(t uuid,c uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT scope_actor()=scope_requester() AND category_access(t,c) AND EXISTS(
 SELECT 1 FROM proposals x JOIN proposal_decisions d ON d.submission_id=x.current_submission_id
 AND d.tenant_id=x.tenant_id AND d.proposal_id=x.id WHERE x.tenant_id=t AND x.category_id=c
 AND x.id=p AND d.decided_by=scope_requester() AND x.status=d.outcome)
$$;
CREATE FUNCTION m3_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'M3 immutable version'; END $$;
CREATE FUNCTION m3_proposal_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
 BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'M3 proposal identity immutable'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.owner_id<>scope_requester() OR NEW.visibility<>'private'
   OR NEW.effective_visibility<>'private' OR NEW.status<>'draft' THEN
   RAISE EXCEPTION 'M3 proposal starts private and draft'; END IF;
 ELSE
  IF ROW(NEW.id,NEW.tenant_id,NEW.category_id,NEW.owner_id,NEW.entry_kind,NEW.target_kind)
   IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.category_id,OLD.owner_id,OLD.entry_kind,OLD.target_kind)
   OR NOT (NEW.revision=OLD.revision+1 OR (NEW.revision=OLD.revision
    AND (to_jsonb(NEW)-ARRAY['private_source_count','effective_visibility'])=
        (to_jsonb(OLD)-ARRAY['private_source_count','effective_visibility'])))
   THEN RAISE EXCEPTION 'M3 identity or revision'; END IF;
  IF OLD.owner_id<>scope_requester() AND NOT (
   OLD.status IN ('draft','returned') AND NEW.status=OLD.status
   AND m3_writer(OLD.tenant_id,OLD.category_id,OLD.id)) AND (
   NOT m3_reviewer(OLD.tenant_id,OLD.category_id,OLD.id)
   OR NEW.status NOT IN ('approved','returned','rejected')
   OR NEW.title IS DISTINCT FROM OLD.title OR NEW.brief IS DISTINCT FROM OLD.brief
   OR NEW.source_refs IS DISTINCT FROM OLD.source_refs
   OR NEW.visibility IS DISTINCT FROM OLD.visibility
   OR NEW.effective_visibility IS DISTINCT FROM OLD.effective_visibility
   OR NEW.customer_identities IS DISTINCT FROM OLD.customer_identities
   OR NEW.context_refs IS DISTINCT FROM OLD.context_refs
   OR NEW.current_submission_id IS DISTINCT FROM OLD.current_submission_id
   OR NOT EXISTS(SELECT 1 FROM proposal_decisions d WHERE d.tenant_id=OLD.tenant_id
    AND d.submission_id=OLD.current_submission_id AND d.decided_by=scope_requester()
    AND d.outcome=NEW.status)) THEN RAISE EXCEPTION 'M3 named decision required'; END IF;
 END IF;
 RETURN NEW; END $$;
CREATE FUNCTION m3_sealed_definition_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE parent_id uuid; parent_tenant uuid; locked boolean;
 BEGIN
 IF TG_TABLE_NAME='definition_revisions' THEN
  IF OLD.sealed THEN RAISE EXCEPTION 'M3 G0 definition sealed'; END IF;
 ELSE
  parent_id:=CASE WHEN TG_OP='DELETE' THEN OLD.definition_id ELSE NEW.definition_id END;
  parent_tenant:=CASE WHEN TG_OP='DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
  SELECT sealed INTO locked FROM definition_revisions d WHERE d.tenant_id=parent_tenant
   AND d.id=parent_id FOR UPDATE;
  IF locked OR (TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM definition_revisions d
   WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.definition_id AND d.sealed))
   THEN RAISE EXCEPTION 'M3 G0 spec sealed'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END $$;
CREATE TRIGGER m3_proposal_guard BEFORE INSERT OR UPDATE OR DELETE ON proposals
 FOR EACH ROW EXECUTE FUNCTION m3_proposal_guard();
CREATE TRIGGER m3_sealed_definition BEFORE UPDATE OR DELETE ON definition_revisions
 FOR EACH ROW EXECUTE FUNCTION m3_sealed_definition_guard();
CREATE TRIGGER m3_sealed_spec BEFORE INSERT OR UPDATE OR DELETE ON definition_specs
 FOR EACH ROW EXECUTE FUNCTION m3_sealed_definition_guard();
CREATE TRIGGER m3_sealed_source BEFORE INSERT OR UPDATE OR DELETE ON definition_sources
 FOR EACH ROW EXECUTE FUNCTION m3_sealed_definition_guard();
CREATE POLICY m3_confirmation ON confirmations FOR INSERT TO pdos_next_app
 WITH CHECK(operation='proposal.g0.decide' AND actor_id=scope_actor()
 AND subject_type='proposal' AND m3_reviewer(tenant_id,category_id,subject_id));
CREATE POLICY m3_confirmation_consume ON confirmations FOR UPDATE TO pdos_next_app
 USING(operation='proposal.g0.decide' AND actor_id=scope_actor()
 AND m3_reviewer(tenant_id,category_id,subject_id))
 WITH CHECK(operation='proposal.g0.decide' AND actor_id=scope_actor()
 AND m3_proposal_reader(tenant_id,category_id,subject_id));
CREATE POLICY m3_receipt ON action_receipts FOR INSERT TO pdos_next_app
 WITH CHECK(operation='proposal.g0.decide' AND actor_id=scope_actor()
 AND subject_type='proposal' AND m3_proposal_reader(tenant_id,category_id,subject_id));
CREATE POLICY m3_audit ON audit_entries FOR INSERT TO pdos_next_app WITH CHECK(
 actor_id=scope_actor() AND EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id=audit_entries.tenant_id
 AND r.id=audit_entries.receipt_id AND r.operation='proposal.g0.decide' AND r.actor_id=scope_actor()));
CREATE POLICY m3_outbox ON outbox_events FOR INSERT TO pdos_next_app WITH CHECK(
 actor_id=scope_actor() AND EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id=outbox_events.tenant_id
 AND r.id=outbox_events.receipt_id AND r.operation='proposal.g0.decide' AND r.actor_id=scope_actor()));
CREATE POLICY m3_request_key ON request_keys FOR INSERT TO pdos_next_app WITH CHECK(
 actor_id=scope_actor() AND EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id=request_keys.tenant_id
 AND r.id=request_keys.receipt_id AND r.operation='proposal.g0.decide' AND r.actor_id=scope_actor()));
CREATE FUNCTION m3_result_access(t uuid,c uuid,typ text,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM proposal_decisions d WHERE d.tenant_id=t AND d.category_id=c
 AND d.outcome='approved' AND d.decided_by=scope_actor() AND scope_actor()=scope_requester()
 AND m3_reviewer(t,c,d.proposal_id) AND sid=CASE typ
 WHEN 'products' THEN d.created_product_id WHEN 'definition_revisions' THEN d.created_definition_id
 WHEN 'projects' THEN d.created_project_id END)
$$;
CREATE FUNCTION m3_review_source_access(t uuid,c uuid,typ text,sid uuid,owner uuid,person uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT scope_actor()=scope_requester() AND category_access(t,c,true) AND EXISTS(
 SELECT 1 FROM proposals p JOIN proposal_submissions sub
 ON sub.tenant_id=p.tenant_id AND sub.proposal_id=p.id
 JOIN proposal_sources ps ON ps.proposal_id=p.id AND ps.tenant_id=p.tenant_id
 JOIN artifact_versions a ON a.id=ps.source_id AND a.tenant_id=ps.tenant_id
 LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=a.tenant_id
 WHERE p.tenant_id=t AND p.category_id=c AND p.owner_id=scope_requester()
 AND ps.source_type='original' AND person=sub.reviewer_id
 AND source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)
 AND ((typ='artifact_versions' AND sid=a.id AND owner=a.owner_id)
 OR (typ='uploaded_originals' AND sid=o.id AND owner=o.owner_id)))
$$;
CREATE OR REPLACE FUNCTION protect_fixed_definition() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
 BEGIN
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='definition_revisions'
 AND (to_jsonb(OLD)->>'sealed')='false' AND (to_jsonb(NEW)->>'sealed')='true'
 AND (to_jsonb(NEW)-ARRAY['sealed','source_proposal_id','source_submission_id','source_proposal_revision','g0_decision_id'])
   =(to_jsonb(OLD)-ARRAY['sealed','source_proposal_id','source_submission_id','source_proposal_revision','g0_decision_id'])
 AND m3_result_access(NEW.tenant_id,NEW.category_id,'definition_revisions',NEW.id)
 THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'definition snapshots are immutable'; END $$;
CREATE FUNCTION m3_open_item_initial() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN IF NEW.status<>(CASE WHEN NEW.kind='task' THEN 'assigned' ELSE 'open' END)
 THEN RAISE EXCEPTION 'M3 initial assignment state'; END IF; RETURN NEW; END $$;
CREATE TRIGGER m3_open_item_initial BEFORE INSERT ON project_open_items
 FOR EACH ROW EXECUTE FUNCTION m3_open_item_initial();
"""

FUNCTIONS = ""

# Extend the existing single audience identity/locking guard, keeping its owner
# catalogue and implementation. Category proposals have only an optional baseline.
SECURITY += (
    AUDIENCE_SQL.split("CREATE TRIGGER", 1)[0]
    .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace("__OWNERS__", json.dumps({**AUDIENCE_OWNERS, "proposals": "owner_id"}))
    .replace(
        "model_col=CASE WHEN typ='products' THEN 'id' ELSE 'product_id' END;",
        "model_col=CASE WHEN typ='products' THEN 'id' "
        "WHEN typ='proposals' THEN 'baseline_product_id' ELSE 'product_id' END;",
    )
)

ATOMIC_GUARDS = """
CREATE FUNCTION m3_atom_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; p proposals; sub proposal_submissions; d proposal_decisions; frozen jsonb;
BEGIN
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 SELECT * INTO STRICT p FROM proposals WHERE tenant_id=NEW.tenant_id AND id=NEW.proposal_id;
 IF r.category_id<>NEW.category_id OR r.subject_type<>'proposal' OR r.subject_id<>NEW.proposal_id
  OR r.actor_id<>scope_actor() OR r.requester_id<>scope_requester() OR r.run_id IS NOT NULL
  OR (r.agent_run_id IS NOT NULL AND r.operation<>'proposal.item.patch')
  THEN RAISE EXCEPTION 'M3 common receipt binding'; END IF;
 IF TG_TABLE_NAME='proposal_submissions' THEN
  IF r.operation<>'proposal.g0.submit' OR r.actor_id<>NEW.owner_id
   OR NEW.owner_id<>p.owner_id OR NEW.owner_id=NEW.reviewer_id THEN
   RAISE EXCEPTION 'M3 independent submission atom'; END IF;
 ELSIF TG_TABLE_NAME='proposal_decisions' THEN
  SELECT * INTO STRICT sub FROM proposal_submissions WHERE tenant_id=NEW.tenant_id AND id=NEW.submission_id;
  IF r.operation<>'proposal.g0.decide' OR r.actor_id<>NEW.decided_by
   OR p.status<>NEW.outcome OR p.current_submission_id<>NEW.submission_id
   OR p.owner_id<>NEW.owner_id OR NEW.review_digest<>sub.document_digest
   OR NEW.decided_by<>sub.reviewer_id THEN RAISE EXCEPTION 'M3 named decision atom'; END IF;
  IF NEW.outcome='approved' AND (
   NOT EXISTS(SELECT 1 FROM definition_revisions def WHERE def.tenant_id=NEW.tenant_id
    AND def.id=NEW.created_definition_id AND def.product_id=NEW.created_product_id
    AND def.sealed AND def.revision=1 AND def.g0_decision_id=NEW.id)
   OR NOT EXISTS(SELECT 1 FROM projects project WHERE project.tenant_id=NEW.tenant_id
    AND project.id=NEW.created_project_id AND project.product_id=NEW.created_product_id
    AND project.g0_decision_id=NEW.id AND project.owner_id=NEW.project_owner_id)
   OR NOT EXISTS(SELECT 1 FROM project_product_links link WHERE link.tenant_id=NEW.tenant_id
    AND link.project_id=NEW.created_project_id AND link.product_id=NEW.created_product_id
    AND link.definition_id=NEW.created_definition_id AND link.definition_revision=1)
   OR (SELECT count(*) FROM project_open_items oi WHERE oi.tenant_id=NEW.tenant_id
    AND oi.g0_decision_id=NEW.id)<>jsonb_array_length(NEW.dispositions)) THEN
   RAISE EXCEPTION 'M3 G0 results must commit together'; END IF;
 ELSIF TG_TABLE_NAME='proposal_item_versions' THEN
  IF r.operation='proposal.g0.decide' THEN
   SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND receipt_id=r.id;
   SELECT item INTO STRICT frozen FROM proposal_submissions ps,
    LATERAL jsonb_array_elements(ps.frozen_document->'items') item
    WHERE ps.tenant_id=NEW.tenant_id AND ps.id=d.submission_id AND item->>'item_id'=NEW.item_id::text;
   IF d.outcome<>'approved' OR NEW.kind<>'question' OR NEW.removed
    OR NEW.version<>(frozen->>'version')::int+1
    OR NEW.content IS DISTINCT FROM ((frozen->'content')||'{"status":"carried"}'::jsonb)
    OR NEW.origin IS DISTINCT FROM frozen->>'origin'
    OR NEW.source_refs IS DISTINCT FROM frozen->'source_refs'
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(d.dispositions) disp
     WHERE disp->>'subject_type'='question' AND disp->>'subject_id'=NEW.item_id::text)
    THEN RAISE EXCEPTION 'M3 only decided questions may be carried'; END IF;
  END IF;
  IF r.operation NOT IN ('proposal.create','proposal.item.patch','proposal.question.create','proposal.g0.decide')
   OR NOT coalesce((
    (NEW.origin='human' AND NEW.writer_id=r.actor_id AND NEW.run_id IS NULL
     AND NEW.confirmed_by IS NULL AND NEW.prepared_candidate_id IS NULL AND r.agent_run_id IS NULL)
    OR (NEW.origin='ai_draft' AND NEW.writer_id=r.actor_id AND NEW.run_id=r.agent_run_id
     AND NEW.confirmed_by IS NULL AND NEW.prepared_candidate_id IS NULL
     AND EXISTS(SELECT 1 FROM agent_runs ar WHERE ar.tenant_id=NEW.tenant_id AND ar.id=NEW.run_id
      AND ar.category_id=NEW.category_id AND ar.requester_id=r.requester_id AND ar.writer_id=r.actor_id
      AND ar.proposal_id=NEW.proposal_id AND ar.reverted_at IS NULL AND ar.state<>'cancelled')
     AND EXISTS(SELECT 1 FROM agent_tool_calls ac WHERE ac.tenant_id=NEW.tenant_id
      AND ac.run_id=NEW.run_id AND ac.receipt_id=r.id AND ac.state='completed'
      AND ac.execution_binding->>'operation'=r.operation)
     AND NOT EXISTS(SELECT 1 FROM proposal_item_versions prior WHERE prior.tenant_id=NEW.tenant_id
      AND prior.item_id=NEW.item_id AND prior.version=NEW.version-1
      AND (prior.origin='human' OR prior.confirmed_by IS NOT NULL)))
    OR (NEW.origin='ai_draft' AND r.agent_run_id IS NULL AND NEW.confirmed_by=r.actor_id
     AND EXISTS(SELECT 1 FROM proposal_prepared_candidates pc WHERE pc.tenant_id=NEW.tenant_id
      AND pc.id=NEW.prepared_candidate_id AND pc.category_id=NEW.category_id
      AND pc.requester_id=r.requester_id AND pc.writer_id=NEW.writer_id AND pc.run_id=NEW.run_id
      AND pc.operation=r.operation))
    OR (r.operation='proposal.g0.decide' AND NEW.origin='ai_draft'
     AND NEW.origin=frozen->>'origin' AND NEW.writer_id=(frozen->>'writer_id')::uuid
     AND NEW.run_id=(frozen->>'run_id')::uuid AND NEW.confirmed_by=r.actor_id
     AND NEW.prepared_candidate_id IS NULL)),false)
  THEN RAISE EXCEPTION 'M3 version provenance'; END IF;
 ELSIF TG_TABLE_NAME='proposal_revisions' THEN
  IF NEW.actor_id<>r.actor_id OR NEW.run_id IS DISTINCT FROM r.agent_run_id
   OR NEW.revision<>r.subject_revision THEN
   RAISE EXCEPTION 'M3 document receipt revision'; END IF;
 END IF;
 RETURN NULL;
END $$;
"""


def statements():
    result = []
    for table in (*TABLES, *CATEGORY_TABLES):
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name == "action_receipts":
                fk.deferrable, fk.initially = True, "DEFERRED"
        result.append(str(CreateTable(table).compile(dialect=postgresql.dialect())))
        result.extend(
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            for index in sorted(table.indexes, key=lambda x: x.name)
        )
    result += [DELTA, SECURITY, ATOMIC_GUARDS]
    result.append(
        "GRANT UPDATE(sealed,source_proposal_id,source_submission_id,source_proposal_revision,g0_decision_id) "
        "ON definition_revisions TO pdos_next_app;"
    )
    for table in TABLES:
        name = table.name
        if name == "proposal_prepared_candidates":
            read = "category_access(tenant_id,category_id) AND requester_id=scope_requester()"
            result.append(
                f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY;"
                f"CREATE POLICY owner_internal ON {name} TO pdos_next_owner USING(true) WITH CHECK(true);"
                f"CREATE POLICY m3_read ON {name} FOR SELECT TO pdos_next_app USING({read});"
                f"CREATE POLICY m3_insert ON {name} FOR INSERT TO pdos_next_app WITH CHECK({read} "
                "AND writer_id=scope_actor() AND EXISTS(SELECT 1 FROM agent_runs ar "
                "WHERE ar.id=proposal_prepared_candidates.run_id "
                "AND ar.tenant_id=proposal_prepared_candidates.tenant_id "
                "AND ar.category_id=proposal_prepared_candidates.category_id "
                "AND ar.requester_id=scope_requester() AND ar.writer_id=scope_actor() "
                "AND ar.product_id IS NULL AND ar.reverted_at IS NULL AND ar.state<>'cancelled'));"
                f"REVOKE ALL ON {name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;"
                f"GRANT SELECT,INSERT ON {name} TO pdos_next_app;"
                f"CREATE TRIGGER m3_append BEFORE UPDATE OR DELETE ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION m3_append_only();"
            )
            continue
        subject = (
            "id"
            if name == "proposals"
            else (
                "(SELECT proposal_id FROM proposal_decisions WHERE id=g0_decision_id)"
                if name == "project_open_items"
                else "proposal_id"
            )
        )
        read = f"m3_proposal_reader(tenant_id,category_id,{subject})"
        write = f"m3_owner(tenant_id,category_id,{subject})"
        if name in {
            "proposals",
            "proposal_items",
            "proposal_item_versions",
            "proposal_sources",
            "proposal_revisions",
        }:
            write += f" OR m3_writer(tenant_id,category_id,{subject})"
        if name in {
            "proposals",
            "proposal_decisions",
            "proposal_revisions",
            "proposal_items",
            "proposal_item_versions",
            "project_open_items",
        }:
            write += f" OR m3_reviewer(tenant_id,category_id,{subject})"
        if name == "proposal_revisions":
            write += f" OR m3_decision_actor(tenant_id,category_id,{subject})"
        if name == "proposals":
            write += (
                " OR (category_access(tenant_id,category_id,true) AND owner_id=scope_requester())"
            )
        if name == "project_open_items":
            read = (
                "category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM projects p "
                "WHERE p.tenant_id=project_open_items.tenant_id AND p.id=project_open_items.project_id)"
            )
        result.append(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY;"
            f"CREATE POLICY owner_internal ON {name} TO pdos_next_owner USING(true) WITH CHECK(true);"
            f"CREATE POLICY m3_read ON {name} FOR SELECT TO pdos_next_app USING({read});"
            f"CREATE POLICY m3_insert ON {name} FOR INSERT TO pdos_next_app WITH CHECK({write});"
            f"CREATE POLICY m3_update ON {name} FOR UPDATE TO pdos_next_app USING({write}) WITH CHECK({write});"
            f"REVOKE ALL ON {name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;"
            f"GRANT SELECT,INSERT,UPDATE ON {name} TO pdos_next_app;"
        )
        if name == "proposal_sources":
            result.append(
                f"GRANT DELETE ON {name} TO pdos_next_app;"
                f"CREATE POLICY m3_delete ON {name} FOR DELETE TO pdos_next_app USING({write});"
            )
        if name in {
            "proposal_item_versions",
            "proposal_revisions",
            "proposal_submissions",
            "proposal_decisions",
        }:
            result.append(
                f"CREATE TRIGGER m3_append BEFORE UPDATE OR DELETE ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION m3_append_only();"
            )
            result.append(
                f"CREATE CONSTRAINT TRIGGER m3_atom AFTER INSERT ON {name} "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION m3_atom_guard();"
            )
    for signature in (
        "m3_proposal_reader(uuid,uuid,uuid)",
        "m3_reviewer(uuid,uuid,uuid)",
        "m3_owner(uuid,uuid,uuid)",
        "m3_writer(uuid,uuid,uuid)",
        "m3_audience_member(uuid,uuid,uuid,uuid)",
        "m3_decision_actor(uuid,uuid,uuid)",
        "m3_result_access(uuid,uuid,text,uuid)",
        "m3_review_source_access(uuid,uuid,text,uuid,uuid,uuid)",
    ):
        result.append(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent;"
            f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app;"
        )
    for table in ("products", "definition_revisions", "projects"):
        access = f"m3_result_access(tenant_id,category_id,'{table}',id)"
        result.append(
            f"CREATE POLICY m3_result_read ON {table} FOR SELECT TO pdos_next_app USING({access});"
            f"CREATE POLICY m3_result_insert ON {table} FOR INSERT TO pdos_next_app WITH CHECK({access});"
            f"CREATE POLICY m3_result_update ON {table} FOR UPDATE TO pdos_next_app USING({access}) WITH CHECK({access});"
        )
    for table in ("definition_specs", "definition_sources", "project_product_links"):
        access = "m3_result_access(tenant_id,category_id,'definition_revisions',definition_id)"
        result.append(
            f"CREATE POLICY m3_result_insert ON {table} FOR INSERT TO pdos_next_app WITH CHECK({access});"
            f"CREATE POLICY m3_result_update ON {table} FOR UPDATE TO pdos_next_app USING({access}) WITH CHECK({access});"
        )
    result.append(
        "CREATE POLICY m3_result_audience ON object_audiences FOR INSERT TO pdos_next_app "
        "WITH CHECK(m3_result_access(tenant_id,category_id,object_type,subject_id));"
    )
    result.append(
        "CREATE POLICY m3_review_source ON object_audiences FOR INSERT TO pdos_next_app WITH CHECK("
        "m3_review_source_access(tenant_id,category_id,object_type,subject_id,owner_id,principal_id));"
    )
    for table in CATEGORY_TABLES:
        name = table.name
        read = "category_access(tenant_id,category_id)"
        if name == "product_target_segments":
            read += " AND EXISTS(SELECT 1 FROM products p WHERE p.id=product_target_segments.product_id AND p.tenant_id=product_target_segments.tenant_id)"
        result.append(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY;"
            f"CREATE POLICY owner_internal ON {name} TO pdos_next_owner USING(true) WITH CHECK(true);"
            f"CREATE POLICY m3_read ON {name} FOR SELECT TO pdos_next_app USING({read});"
            f"REVOKE ALL ON {name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;"
            f"GRANT SELECT ON {name} TO pdos_next_app;"
        )
        if name == "product_target_segments":
            result.append(
                f"GRANT INSERT ON {name} TO pdos_next_app;"
                f"CREATE POLICY m3_insert ON {name} FOR INSERT TO pdos_next_app WITH CHECK("
                "m3_result_access(tenant_id,category_id,'products',product_id));"
            )
        elif name == "category_knowledge_entries":
            result.append(
                f"CREATE TRIGGER m3_append BEFORE UPDATE OR DELETE ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION m3_append_only();"
            )
    result.append(
        "ALTER POLICY audience_assignment ON object_audiences "
        "WITH CHECK(owner_id=scope_requester() OR "
        "m3_result_access(tenant_id,category_id,object_type,subject_id) OR "
        "m3_review_source_access(tenant_id,category_id,object_type,subject_id,owner_id,principal_id));"
    )
    result.append(
        "ALTER POLICY upstream_audience ON projects USING("
        "m3_result_access(tenant_id,category_id,'projects',id) OR "
        "project_definition_visible(tenant_id,category_id,product_id,id));"
    )
    result.append(
        "CREATE POLICY m3_category_source_read ON definition_sources FOR SELECT TO pdos_next_app USING("
        "category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM definition_revisions d "
        "WHERE d.tenant_id=definition_sources.tenant_id AND d.id=definition_sources.definition_id "
        "AND d.product_id=definition_sources.product_id) AND EXISTS(SELECT 1 FROM artifact_versions a "
        "WHERE a.tenant_id=definition_sources.tenant_id AND a.category_id=definition_sources.category_id "
        "AND a.id=definition_sources.artifact_id "
        "AND (a.product_id IS NULL OR a.product_id=definition_sources.product_id)));"
    )
    for name in (
        "m3_atom_guard",
        "m3_append_only",
        "m3_proposal_guard",
        "m3_sealed_definition_guard",
        "m3_open_item_initial",
    ):
        result.append(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC,pdos_agent;")
    return result
