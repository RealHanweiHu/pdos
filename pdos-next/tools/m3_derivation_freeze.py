# ruff: noqa: E501, E402
"""Freeze 0738 derivation scope and G0 atoms against the actual 0737 catalog; no DB."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from pdos_next.models import Base
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex

CAT = json.loads((ROOT / ".local/m3-derivation-0737-catalog.json").read_text())
UP, DOWN, FUNCTIONS = [], [], []
DIALECT = postgresql.dialect()


def change(up, down):
    UP.append(up)
    DOWN.insert(0, down)


def function(sql, signature):
    name = signature.split("(")[0]
    old = next((row["sql"] for row in CAT["functions"] if row["proname"] == name), None)
    change(sql, old or f"DROP FUNCTION {signature}")
    FUNCTIONS.append((signature, old is None))


def prior(name):
    return next(row["sql"] for row in CAT["functions"] if row["proname"] == name)


def trigger(name, table, fn, *, operations="INSERT", deferred=True):
    sql = f"CREATE {'CONSTRAINT ' if deferred else ''}TRIGGER {name} {'AFTER' if deferred else 'BEFORE'} {operations} ON {table} "
    if deferred:
        sql += "DEFERRABLE INITIALLY DEFERRED "
    change(sql + f"FOR EACH ROW EXECUTE FUNCTION {fn}()", f"DROP TRIGGER {name} ON {table}")


TABLES = (
    "products",
    "definition_revisions",
    "product_variants",
    "variant_revisions",
    "project_product_links",
    "proposal_decisions",
)
new_columns = {}
for table_name in TABLES:
    table = Base.metadata.tables[table_name]
    old = {row["column_name"] for row in CAT["columns"] if row["table_name"] == table_name}
    new_columns[table_name] = {column.name for column in table.columns} - old
    for column in table.columns:
        if column.name in new_columns[table_name]:
            change(
                f"ALTER TABLE {table_name} ADD COLUMN "
                + str(CreateColumn(column).compile(dialect=DIALECT)),
                f"ALTER TABLE {table_name} DROP COLUMN {column.name}",
            )

assert (
    next(
        row["data_type"]
        for row in CAT["columns"]
        if row["table_name"] == "product_variants" and row["column_name"] == "name"
    )
    == "character varying"
)
assert str(Base.metadata.tables["product_variants"].c.name.type.compile(dialect=DIALECT)) == "TEXT"
change(
    "ALTER TABLE product_variants ALTER COLUMN name TYPE text",
    "ALTER TABLE product_variants ALTER COLUMN name TYPE character varying(160)",
)

for table_name, name in (
    ("definition_revisions", "definition_revisions_status_check"),
    ("definition_revisions", "definition_revisions_tenant_id_product_id_revision_key"),
    ("project_product_links", "project_product_links_tenant_id_project_id_key"),
):
    old = next(
        row["sql"]
        for row in CAT["constraints"]
        if row["table_name"] == table_name and row["conname"] == name
    )
    if name == "definition_revisions_status_check":
        old = "CHECK (status = 'draft')"
    change(
        f"ALTER TABLE {table_name} DROP CONSTRAINT {name}",
        f"ALTER TABLE {table_name} ADD CONSTRAINT {name} {old}",
    )
for table_name in TABLES:
    table = Base.metadata.tables[table_name]
    old_names = {row["conname"] for row in CAT["constraints"] if row["table_name"] == table_name}
    for constraint in sorted(table.constraints, key=lambda item: str(item.name)):
        if (
            constraint.name
            and constraint.name not in old_names
            and (
                set(column.name for column in constraint.columns) & new_columns[table_name]
                or str(constraint.name).startswith("m3_")
            )
        ):
            change(
                str(AddConstraint(constraint).compile(dialect=DIALECT)),
                f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint.name}",
            )
    old_indexes = {row["indexname"] for row in CAT["indexes"] if row["tablename"] == table_name}
    for index in sorted(table.indexes, key=lambda item: item.name):
        if index.name not in old_indexes:
            change(str(CreateIndex(index).compile(dialect=DIALECT)), f"DROP INDEX {index.name}")

function(
    r"""
CREATE FUNCTION m3_published_baseline(t uuid,c uuid,pid uuid,did uuid,ver integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM definition_revisions baseline JOIN action_receipts receipt
  ON receipt.tenant_id=baseline.tenant_id AND receipt.id=baseline.publication_receipt_id
  JOIN principals signer ON signer.tenant_id=receipt.tenant_id AND signer.id=receipt.actor_id
  WHERE baseline.tenant_id=t AND baseline.category_id=c AND baseline.product_id=pid AND baseline.id=did
   AND baseline.revision=ver AND baseline.status='published' AND baseline.sealed
   AND receipt.operation='product.definition.publish' AND receipt.subject_type='definition_revision'
   AND receipt.subject_id=baseline.id AND receipt.subject_revision=baseline.revision AND receipt.product_id=pid AND receipt.category_id=c
   AND receipt.actor_id=receipt.requester_id AND receipt.run_id IS NULL AND receipt.agent_run_id IS NULL AND signer.kind='human')
$$;
""",
    "m3_published_baseline(uuid,uuid,uuid,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_baseline_reference_graph(t uuid,c uuid,did uuid,ver integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE queue jsonb=jsonb_build_array(jsonb_build_object('ref',jsonb_build_object('type','definition','id',did,'version',ver),'path','[]'::jsonb));
 refs jsonb='[]'; cursor_index integer=0; node jsonb; ref jsonb; path jsonb; token text; children jsonb;
BEGIN
 WHILE cursor_index<jsonb_array_length(queue) LOOP
  node=queue->cursor_index; cursor_index=cursor_index+1; ref=node->'ref'; path=node->'path';
  token=(ref->>'type')||':'||(ref->>'id')||':'||(ref->>'version');
  IF token IS NULL OR path ? token THEN RETURN NULL; END IF;
  refs=refs||jsonb_build_array(ref); path=path||jsonb_build_array(token); children='[]';
  IF ref->>'type'='definition' THEN
   SELECT coalesce(jsonb_agg(source),'[]') INTO children FROM (
    SELECT jsonb_build_object('type','artifact','id',s.artifact_id,'version',s.source_revision,'line',s.line,'quote',s.quote) source
     FROM definition_sources s WHERE s.tenant_id=t AND s.category_id=c AND s.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT item FROM definition_specs spec CROSS JOIN LATERAL jsonb_array_elements(spec.source_refs) item
     WHERE spec.tenant_id=t AND spec.category_id=c AND spec.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT jsonb_build_object('type','definition','id',d.derived_from_definition_id,'version',d.derived_from_definition_revision)
     FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid AND d.derived_from_definition_id IS NOT NULL
    UNION ALL SELECT jsonb_build_object('type','definition','id',parent.id,'version',parent.revision)
     FROM definition_revisions d JOIN definition_revisions parent ON parent.tenant_id=d.tenant_id AND parent.category_id=d.category_id AND parent.id=d.parent_definition_id
     WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid
   ) edges;
  ELSIF ref->>'type'='knowledge' THEN
   SELECT coalesce(jsonb_agg(item),'[]') INTO children FROM category_knowledge_entries knowledge
    CROSS JOIN LATERAL jsonb_array_elements(knowledge.source_refs) item
    WHERE knowledge.tenant_id=t AND knowledge.category_id=c AND knowledge.id=(ref->>'id')::uuid;
  ELSIF ref->>'type'='claim' THEN
   SELECT coalesce(jsonb_agg(jsonb_build_object('type',claim.source_kind,'id',coalesce(claim.artifact_id,claim.snapshot_id),
    'version',claim.source_revision,'line',claim.line,'quote',claim.quote)),'[]') INTO children
    FROM claims claim WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id=(ref->>'id')::uuid;
  END IF;
  SELECT queue||coalesce(jsonb_agg(jsonb_build_object('ref',child,'path',path)),'[]') INTO queue FROM jsonb_array_elements(children) child;
 END LOOP;
 RETURN (SELECT coalesce(jsonb_agg(DISTINCT item ORDER BY item),'[]') FROM jsonb_array_elements(refs) item);
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN RETURN NULL;
END $$;
""",
    "m3_baseline_reference_graph(uuid,uuid,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_published_baseline_valid(t uuid,c uuid,pid uuid,did uuid,ver integer) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE refs jsonb; ref jsonb; sid uuid; source_ver integer; valid boolean; body text;
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true OR m3_published_baseline(t,c,pid,did,ver) IS DISTINCT FROM true THEN RETURN false; END IF;
 refs=m3_baseline_reference_graph(t,c,did,ver);
 IF refs IS NULL THEN RETURN false; END IF;
 -- Claims are locked once in UUID order, before their source roots. All reads
 -- remain actual scope/audience checks below; no body leaves this function.
 PERFORM 1 FROM claims claim WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id IN
  (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type'='claim') ORDER BY claim.id FOR SHARE;
 PERFORM 1 FROM artifact_versions artifact WHERE artifact.tenant_id=t AND artifact.category_id=c AND artifact.id IN
  (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type' IN ('artifact','original')) ORDER BY artifact.id FOR SHARE;
 PERFORM 1 FROM public_web_snapshots snapshot WHERE snapshot.tenant_id=t AND snapshot.category_id=c AND snapshot.id IN
  (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type'='snapshot') ORDER BY snapshot.id FOR SHARE;
 PERFORM 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c AND definition.id IN
  (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type'='definition') ORDER BY definition.id FOR SHARE;
 PERFORM 1 FROM products model WHERE model.tenant_id=t AND model.category_id=c AND model.id IN
  (SELECT definition.product_id FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.id IN
   (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type'='definition')
   UNION SELECT artifact.product_id FROM artifact_versions artifact WHERE artifact.tenant_id=t AND artifact.id IN
   (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type' IN ('artifact','original'))) ORDER BY model.id FOR SHARE;
 PERFORM 1 FROM uploaded_originals original WHERE original.tenant_id=t AND original.category_id=c AND original.id IN
  (SELECT artifact.original_id FROM artifact_versions artifact WHERE artifact.tenant_id=t AND artifact.id IN
   (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type' IN ('artifact','original'))) ORDER BY original.id FOR SHARE;
 PERFORM 1 FROM original_security security WHERE security.tenant_id=t AND security.category_id=c AND security.original_id IN
  (SELECT artifact.original_id FROM artifact_versions artifact WHERE artifact.tenant_id=t AND artifact.id IN
   (SELECT (item->>'id')::uuid FROM jsonb_array_elements(refs) item WHERE item->>'type' IN ('artifact','original'))) ORDER BY security.id FOR SHARE;
 IF refs IS DISTINCT FROM m3_baseline_reference_graph(t,c,did,ver) THEN RETURN false; END IF;
 FOR ref IN SELECT item FROM jsonb_array_elements(refs) item LOOP
  sid=(ref->>'id')::uuid; source_ver=(ref->>'version')::integer; valid=false; body=NULL;
  IF ref->>'type'='definition' THEN
   SELECT EXISTS(SELECT 1 FROM definition_revisions definition JOIN products model
    ON model.tenant_id=definition.tenant_id AND model.category_id=definition.category_id AND model.id=definition.product_id
    WHERE definition.tenant_id=t AND definition.category_id=c AND definition.id=sid AND definition.revision=source_ver
     AND (definition.status<>'published' OR m3_published_baseline(t,c,model.id,definition.id,definition.revision))
     AND source_object_audience(t,c,'definition_revisions',definition.id,definition.owner_id,definition.visibility)
     AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility)) INTO valid;
  ELSIF ref->>'type' IN ('artifact','original') THEN
   SELECT artifact.content INTO body FROM artifact_versions artifact WHERE artifact.tenant_id=t AND artifact.category_id=c
    AND artifact.id=sid AND artifact.revision=source_ver AND artifact.status='active' AND m3_evidence_source_reader(t,c,'artifact',sid)
    AND (artifact.original_id IS NULL OR EXISTS(SELECT 1 FROM original_security security WHERE security.tenant_id=t
     AND security.category_id=c AND security.original_id=artifact.original_id AND security.source_state='active' AND security.disposition='active'));
   valid=FOUND;
  ELSIF ref->>'type'='snapshot' THEN
   SELECT snapshot.markdown INTO body FROM public_web_snapshots snapshot WHERE snapshot.tenant_id=t AND snapshot.category_id=c
    AND snapshot.id=sid AND source_ver=1 AND snapshot.status IN ('ok','partial') AND m3_evidence_source_reader(t,c,'snapshot',sid);
   valid=FOUND;
  ELSIF ref->>'type'='claim' THEN
   SELECT EXISTS(SELECT 1 FROM claims claim WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id=sid
    AND claim.revision=source_ver AND claim.status='active' AND m3_claim_reader(t,c,sid)
    AND (ref->>'line' IS NULL OR (ref->>'line')::integer=claim.line)
    AND (ref->>'quote' IS NULL OR position(ref->>'quote' IN claim.quote)>0)) INTO valid;
  ELSIF ref->>'type'='knowledge' THEN
   SELECT EXISTS(SELECT 1 FROM category_knowledge_entries knowledge WHERE knowledge.tenant_id=t AND knowledge.category_id=c
    AND knowledge.id=sid AND knowledge.version=source_ver AND knowledge.action<>'withdraw') INTO valid;
  ELSIF ref->>'type'='parameter' THEN
   SELECT EXISTS(SELECT 1 FROM parameter_versions parameter WHERE parameter.tenant_id=t AND parameter.category_id=c
    AND parameter.parameter_id=sid AND parameter.version=source_ver) INTO valid;
  ELSIF ref->>'type'='human' THEN
   SELECT EXISTS(SELECT 1 FROM principals person WHERE person.tenant_id=t AND person.id=sid AND person.active AND person.kind='human'
    AND nullif(ref->>'statement','') IS NOT NULL) INTO valid;
  END IF;
  IF valid IS DISTINCT FROM true THEN RETURN false; END IF;
  IF body IS NOT NULL AND (ref->>'line' IS NOT NULL OR ref->>'quote' IS NOT NULL) THEN
   IF ref->>'line' IS NULL OR ref->>'quote' IS NULL OR (ref->>'line')::integer<1
    OR position(ref->>'quote' IN split_part(replace(body,E'\r\n',E'\n'),E'\n',(ref->>'line')::integer))=0 THEN RETURN false; END IF;
  END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR numeric_value_out_of_range THEN RETURN false;
END $$;
""",
    "m3_published_baseline_valid(uuid,uuid,uuid,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_lock_published_baseline(t uuid,c uuid,pid uuid,did uuid,ver integer)
RETURNS TABLE(id uuid,revision integer,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF m3_published_baseline_valid(t,c,pid,did,ver) IS DISTINCT FROM true THEN RETURN; END IF;
 RETURN QUERY SELECT baseline.id,baseline.revision,baseline.status::text FROM definition_revisions baseline
  JOIN products model ON model.tenant_id=baseline.tenant_id AND model.category_id=baseline.category_id AND model.id=baseline.product_id
  WHERE baseline.tenant_id=t AND baseline.category_id=c AND baseline.product_id=pid AND baseline.id=did
   AND m3_published_baseline(t,c,pid,did,ver)
   AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility)
   AND source_object_audience(t,c,'definition_revisions',baseline.id,baseline.owner_id,baseline.visibility)
  FOR SHARE OF baseline,model;
END $$;
""",
    "m3_lock_published_baseline(uuid,uuid,uuid,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_derived_baseline_visible(t uuid,c uuid,did uuid,ver integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT CASE WHEN did IS NULL THEN ver IS NULL ELSE category_access(t,c) AND EXISTS(
  SELECT 1 FROM definition_revisions baseline JOIN products model
   ON model.tenant_id=baseline.tenant_id AND model.category_id=baseline.category_id AND model.id=baseline.product_id
   WHERE baseline.tenant_id=t AND baseline.category_id=c AND baseline.id=did AND baseline.revision=ver
    AND m3_published_baseline(t,c,model.id,baseline.id,ver)
    AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility)
    AND source_object_audience(t,c,'definition_revisions',baseline.id,baseline.owner_id,baseline.visibility)
    AND definition_sources_visible(t,c,model.id,baseline.id)) END
$$;
""",
    "m3_derived_baseline_visible(uuid,uuid,uuid,integer)",
)
change(
    "CREATE POLICY m3_derived_source_read ON definition_revisions AS RESTRICTIVE FOR SELECT TO pdos_next_app "
    "USING (m3_derived_baseline_visible(tenant_id,category_id,derived_from_definition_id,derived_from_definition_revision))",
    "DROP POLICY m3_derived_source_read ON definition_revisions",
)

function(
    r"""
CREATE FUNCTION m3_variant_definition_visible(t uuid,c uuid,pid uuid,vid uuid,did uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM definition_revisions canonical
  WHERE canonical.tenant_id=t AND canonical.category_id=c AND canonical.product_id=pid AND canonical.variant_id=vid AND canonical.id=did
   AND source_object_audience(t,c,'definition_revisions',canonical.id,canonical.owner_id,canonical.visibility)
   AND definition_sources_visible(t,c,pid,canonical.id)
   AND m3_derived_baseline_visible(t,c,canonical.derived_from_definition_id,canonical.derived_from_definition_revision))
$$;
""",
    "m3_variant_definition_visible(uuid,uuid,uuid,uuid,uuid)",
)
policy = next(
    row
    for row in CAT["policies"]
    if row["tablename"] == "variant_revisions" and row["policyname"] == "direct_source_audience"
)
change(
    "ALTER POLICY direct_source_audience ON variant_revisions USING (CASE WHEN definition_id IS NULL THEN ("
    + policy["qual"]
    + ") "
    "ELSE m3_variant_definition_visible(tenant_id,category_id,product_id,variant_id,definition_id) END)",
    "ALTER POLICY direct_source_audience ON variant_revisions USING (" + policy["qual"] + ")",
)

function(
    r"""
CREATE FUNCTION m3_definition_publication_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP<>'INSERT' AND OLD.status='published' THEN
  RAISE EXCEPTION 'published definition is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF current_user<>'pdos_next_owner' AND (NEW.status<>'draft' OR NEW.publication_receipt_id IS NOT NULL
  OR (TG_OP='UPDATE' AND NEW.status IS DISTINCT FROM OLD.status)) THEN
  RAISE EXCEPTION 'definition publication requires unavailable named publication authority' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""",
    "m3_definition_publication_guard()",
)
trigger(
    "a_definition_publication",
    "definition_revisions",
    "m3_definition_publication_guard",
    operations="INSERT OR UPDATE OR DELETE",
    deferred=False,
)

function(
    r"""
CREATE FUNCTION m3_definition_publication_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.operation='product.definition.publish' AND current_user<>'pdos_next_owner' THEN
  RAISE EXCEPTION 'definition publication receipt requires unavailable named publication authority' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""",
    "m3_definition_publication_receipt_guard()",
)
trigger(
    "a_definition_publication_receipt",
    "action_receipts",
    "m3_definition_publication_receipt_guard",
    deferred=False,
)

function(
    r"""
CREATE FUNCTION m3_published_definition_child_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE target_tenant uuid; target_id uuid; fixed_status text;
BEGIN
 target_tenant=CASE WHEN TG_OP='DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
 target_id=CASE WHEN TG_OP='DELETE' THEN OLD.definition_id ELSE NEW.definition_id END;
 SELECT parent.status INTO fixed_status FROM definition_revisions parent
  WHERE parent.tenant_id=target_tenant AND parent.id=target_id FOR UPDATE;
 IF fixed_status='published' OR (TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM definition_revisions previous
  WHERE previous.tenant_id=OLD.tenant_id AND previous.id=OLD.definition_id AND previous.status='published')) THEN
  RAISE EXCEPTION 'published definition children are immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
""",
    "m3_published_definition_child_guard()",
)
for table in ("definition_specs", "definition_sources"):
    trigger(
        "a_published_definition_child",
        table,
        "m3_published_definition_child_guard",
        operations="INSERT OR UPDATE OR DELETE",
        deferred=False,
    )

function(
    r"""
CREATE FUNCTION m3_proposal_baseline_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF (NEW.entry_kind='derivative' OR NEW.target_kind='new_variant') AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(NEW.source_refs) source
   WHERE source->>'type'='definition' AND source->>'id'=NEW.baseline_definition_id::text
    AND (source->>'version')::integer=NEW.baseline_definition_revision) THEN
  RAISE EXCEPTION 'proposal fixed baseline requires its source reference' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF ROW(NEW.baseline_product_id,NEW.baseline_definition_id,NEW.baseline_definition_revision)
   IS DISTINCT FROM ROW(OLD.baseline_product_id,OLD.baseline_definition_id,OLD.baseline_definition_revision) THEN
   RAISE EXCEPTION 'proposal derivation baseline is fixed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.entry_kind='derivative' OR NEW.target_kind='new_variant' THEN
  IF m3_published_baseline_valid(NEW.tenant_id,NEW.category_id,NEW.baseline_product_id,NEW.baseline_definition_id,NEW.baseline_definition_revision) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'proposal baseline must be actual readable fixed publication' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM definition_revisions baseline JOIN products model
   ON model.tenant_id=baseline.tenant_id AND model.category_id=baseline.category_id AND model.id=baseline.product_id
   WHERE baseline.tenant_id=NEW.tenant_id AND baseline.category_id=NEW.category_id AND baseline.id=NEW.baseline_definition_id
    AND source_object_audience(NEW.tenant_id,NEW.category_id,'definition_revisions',baseline.id,baseline.owner_id,baseline.visibility)
    AND source_object_audience(NEW.tenant_id,NEW.category_id,'products',model.id,model.owner_id,model.visibility)
   FOR SHARE OF baseline,model;
  IF NOT FOUND THEN RAISE EXCEPTION 'proposal baseline must be actual readable fixed publication' USING ERRCODE='23514'; END IF;
 ELSIF NEW.baseline_product_id IS NOT NULL OR NEW.baseline_definition_id IS NOT NULL OR NEW.baseline_definition_revision IS NOT NULL THEN
  RAISE EXCEPTION 'new product has no derivation baseline' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
""",
    "m3_proposal_baseline_guard()",
)
trigger(
    "m3_proposal_baseline",
    "proposals",
    "m3_proposal_baseline_guard",
    operations="INSERT OR UPDATE",
    deferred=False,
)

old = prior("protect_fixed_definition")
marker = " BEGIN\n"
assert marker in old
function(
    old.replace(
        marker,
        """ BEGIN
 IF TG_TABLE_NAME='definition_revisions' AND TG_OP='UPDATE' AND current_user='pdos_next_owner'
  AND OLD.status='draft' AND NOT OLD.sealed AND NEW.status='published' AND NEW.sealed
  AND (to_jsonb(NEW)-ARRAY['status','sealed','publication_receipt_id']) IS NOT DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','sealed','publication_receipt_id']) THEN RETURN NEW; END IF;
""",
        1,
    ),
    "protect_fixed_definition()",
)

# Result authorization is confined to the actual pending named decision. An
# existing baseline Product is never an output of a new-Variant decision.
function(
    r"""
CREATE OR REPLACE FUNCTION m3_result_access(t uuid,c uuid,typ text,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM proposal_decisions decision
  JOIN proposals proposal ON proposal.tenant_id=decision.tenant_id AND proposal.category_id=decision.category_id AND proposal.id=decision.proposal_id
  WHERE decision.tenant_id=t AND decision.category_id=c AND decision.outcome='approved'
   AND decision.decided_by=scope_actor() AND scope_actor()=scope_requester() AND m3_reviewer(t,c,decision.proposal_id)
   AND decision.xmin::text::bigint=txid_current()%4294967296
   AND sid=CASE typ WHEN 'products' THEN CASE WHEN proposal.target_kind='new_product' THEN decision.created_product_id END
    WHEN 'definition_revisions' THEN decision.created_definition_id WHEN 'projects' THEN decision.created_project_id
    WHEN 'variant_revisions' THEN (SELECT version.id FROM variant_revisions version WHERE version.tenant_id=t AND version.category_id=c
      AND version.variant_id=decision.created_variant_id AND version.definition_id=decision.created_definition_id AND version.revision=1)
    WHEN 'product_variants' THEN CASE WHEN proposal.target_kind='new_variant' THEN decision.created_variant_id END END)
$$;
""",
    "m3_result_access(uuid,uuid,text,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_g0_result_reader(t uuid,c uuid,typ text,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM proposal_decisions decision
  WHERE decision.tenant_id=t AND decision.category_id=c AND decision.outcome='approved'
   AND CASE typ
    WHEN 'projects' THEN EXISTS(SELECT 1 FROM projects result WHERE result.tenant_id=t AND result.category_id=c
     AND result.id=sid AND result.id=decision.created_project_id AND result.g0_decision_id=decision.id
     AND source_object_audience(t,c,typ,result.id,result.owner_id,result.visibility))
    WHEN 'product_variants' THEN EXISTS(SELECT 1 FROM product_variants result WHERE result.tenant_id=t AND result.category_id=c
     AND result.id=sid AND result.id=decision.created_variant_id AND result.product_id=decision.created_product_id AND result.g0_decision_id=decision.id
     AND source_object_audience(t,c,typ,result.id,result.owner_id,result.visibility))
    ELSE false END)
$$;
""",
    "m3_g0_result_reader(uuid,uuid,text,uuid)",
)

# Result headers/tasks retain their explicitly approved audience. Only SELECT
# receives this alternative; existing product write predicates are unchanged.
for table in ("projects", "product_variants"):
    policy = next(
        row
        for row in CAT["policies"]
        if row["tablename"] == table and row["policyname"] == "model_audience"
    )
    roles = policy["roles"].strip("{}").replace('"', "")
    qual, check = policy["qual"], policy["with_check"]
    change(
        f"DROP POLICY model_audience ON {table}",
        f"CREATE POLICY model_audience ON {table} AS RESTRICTIVE FOR ALL TO {roles} USING ({qual}) WITH CHECK ({check})",
    )
    for operation in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        name = "m3_model_" + operation.lower()
        predicate = qual
        if operation == "SELECT":
            predicate += f" OR (current_user='pdos_next_app' AND m3_g0_result_reader(tenant_id,category_id,'{table}',id))"
        statement = f"CREATE POLICY {name} ON {table} AS RESTRICTIVE FOR {operation} TO {roles}"
        if operation != "INSERT":
            statement += f" USING ({predicate})"
        if operation in ("INSERT", "UPDATE"):
            statement += f" WITH CHECK ({check})"
        change(statement, f"DROP POLICY {name} ON {table}")
policy = next(
    row
    for row in CAT["policies"]
    if row["tablename"] == "projects" and row["policyname"] == "upstream_audience"
)
change(
    "ALTER POLICY upstream_audience ON projects USING (("
    + policy["qual"]
    + ") OR m3_g0_result_reader(tenant_id,category_id,'projects',id))",
    "ALTER POLICY upstream_audience ON projects USING (" + policy["qual"] + ")",
)

for table, identity in (("product_variants", "id"), ("variant_revisions", "variant_id")):
    predicate = f"m3_result_access(tenant_id,category_id,'product_variants',{identity})"
    for command in ("INSERT", "SELECT"):
        name = "m3_variant_result_" + command.lower()
        clause = "WITH CHECK" if command == "INSERT" else "USING"
        change(
            f"CREATE POLICY {name} ON {table} FOR {command} TO pdos_next_app {clause} ({predicate})",
            f"DROP POLICY {name} ON {table}",
        )

function(
    r"""
CREATE FUNCTION m3_derivation_product_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.parent_product_id IS DISTINCT FROM OLD.parent_product_id THEN
  RAISE EXCEPTION 'derived product parent is fixed' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM proposal_decisions decision JOIN proposals proposal ON proposal.tenant_id=decision.tenant_id AND proposal.id=decision.proposal_id
  WHERE decision.tenant_id=NEW.tenant_id AND decision.category_id=NEW.category_id AND decision.created_product_id=NEW.id
   AND decision.outcome='approved' AND decision.created_variant_id IS NOT NULL AND proposal.target_kind='new_variant'
   AND proposal.baseline_product_id=NEW.id AND decision.decided_by=scope_actor() AND decision.xmin::text::bigint=txid_current()%4294967296)
  AND (to_jsonb(NEW)-'lifecycle_epoch') IS DISTINCT FROM (to_jsonb(OLD)-'lifecycle_epoch') THEN
  RAISE EXCEPTION 'variant G0 cannot modify baseline product' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""",
    "m3_derivation_product_guard()",
)
trigger(
    "m3_derivation_product",
    "products",
    "m3_derivation_product_guard",
    operations="UPDATE",
    deferred=False,
)

function(
    r"""
CREATE FUNCTION m3_g0_derivation_assert(t uuid,c uuid,did uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE decision proposal_decisions; proposal proposals; submission proposal_submissions; definition definition_revisions;
 model products; variant product_variants; variant_version variant_revisions; project projects; receipt action_receipts;
 rx xid; spec_item jsonb; expected_spec definition_specs; actual_spec definition_specs; spec_count bigint;
 expected_claims jsonb; frozen_claims jsonb; baseline_claim jsonb;
BEGIN
 SELECT * INTO STRICT decision FROM proposal_decisions WHERE tenant_id=t AND category_id=c AND id=did;
 IF decision.outcome<>'approved' THEN RETURN; END IF;
 SELECT * INTO STRICT proposal FROM proposals WHERE tenant_id=t AND category_id=c AND id=decision.proposal_id;
 SELECT * INTO STRICT submission FROM proposal_submissions WHERE tenant_id=t AND category_id=c AND id=decision.submission_id;
 SELECT * INTO STRICT receipt FROM action_receipts WHERE tenant_id=t AND category_id=c AND id=decision.receipt_id;
 SELECT * INTO STRICT definition FROM definition_revisions WHERE tenant_id=t AND category_id=c AND id=decision.created_definition_id;
 SELECT * INTO STRICT model FROM products WHERE tenant_id=t AND category_id=c AND id=decision.created_product_id FOR UPDATE;
 SELECT * INTO STRICT project FROM projects WHERE tenant_id=t AND category_id=c AND id=decision.created_project_id;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=t AND id=receipt.id;
 IF receipt.operation IS DISTINCT FROM 'proposal.g0.decide' OR receipt.subject_type IS DISTINCT FROM 'proposal'
  OR receipt.subject_id IS DISTINCT FROM proposal.id OR receipt.actor_id IS DISTINCT FROM decision.decided_by
  OR receipt.subject_revision IS DISTINCT FROM proposal.revision
  OR receipt.requester_id IS DISTINCT FROM decision.decided_by OR receipt.actor_id IS DISTINCT FROM scope_actor()
  OR scope_actor() IS DISTINCT FROM scope_requester() OR category_access(t,c) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM grants grant_row JOIN principals signer ON signer.tenant_id=grant_row.tenant_id AND signer.id=grant_row.principal_id
   WHERE grant_row.tenant_id=t AND grant_row.category_id=c AND grant_row.principal_id=decision.decided_by
    AND grant_row.product_manager AND (grant_row.expires_at IS NULL OR grant_row.expires_at>statement_timestamp())
    AND signer.active AND signer.kind='human')
  OR receipt.agent_run_id IS NOT NULL OR receipt.run_id IS NOT NULL OR receipt.product_id IS NOT NULL
  OR submission.proposal_id IS DISTINCT FROM proposal.id OR submission.reviewer_id IS DISTINCT FROM decision.decided_by
  OR proposal.current_submission_id IS DISTINCT FROM submission.id OR decision.review_digest IS DISTINCT FROM submission.document_digest
  OR definition.product_id IS DISTINCT FROM model.id OR definition.g0_decision_id IS DISTINCT FROM decision.id
  OR definition.variant_id IS DISTINCT FROM decision.created_variant_id OR definition.revision<>1 OR NOT definition.sealed OR definition.status<>'draft'
  OR definition.source_proposal_id IS DISTINCT FROM proposal.id OR definition.source_submission_id IS DISTINCT FROM submission.id
  OR definition.source_proposal_revision IS DISTINCT FROM submission.revision OR definition.owner_id IS DISTINCT FROM proposal.owner_id
  OR definition.visibility IS DISTINCT FROM proposal.effective_visibility
  OR project.product_id IS DISTINCT FROM model.id OR project.g0_decision_id IS DISTINCT FROM decision.id OR project.owner_id IS DISTINCT FROM decision.project_owner_id
  OR project.visibility IS DISTINCT FROM proposal.effective_visibility
  OR rx::text::bigint IS DISTINCT FROM txid_current()%4294967296
  OR rx IS DISTINCT FROM (SELECT xmin FROM proposal_decisions WHERE tenant_id=t AND id=decision.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM proposals WHERE tenant_id=t AND id=proposal.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM definition_revisions WHERE tenant_id=t AND id=definition.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM projects WHERE tenant_id=t AND id=project.id)
  OR receipt.result->>'decision_id' IS DISTINCT FROM decision.id::text OR receipt.result->>'product_id' IS DISTINCT FROM model.id::text
  OR receipt.result->>'definition_id' IS DISTINCT FROM definition.id::text OR receipt.result->>'project_id' IS DISTINCT FROM project.id::text
  OR NOT EXISTS(SELECT 1 FROM project_product_links link WHERE link.tenant_id=t AND link.category_id=c AND link.project_id=project.id
   AND link.product_id=model.id AND link.definition_id=definition.id AND link.definition_revision=definition.revision
   AND link.variant_id IS NOT DISTINCT FROM definition.variant_id AND link.xmin=rx) THEN
  RAISE EXCEPTION 'G0 derivation outputs require exact same transaction named receipt' USING ERRCODE='23514'; END IF;
 IF proposal.entry_kind='derivative' OR proposal.target_kind='new_variant' THEN
  IF m3_published_baseline_valid(t,c,proposal.baseline_product_id,proposal.baseline_definition_id,proposal.baseline_definition_revision) IS DISTINCT FROM true
   OR definition.derived_from_definition_id IS DISTINCT FROM proposal.baseline_definition_id
   OR definition.derived_from_definition_revision IS DISTINCT FROM proposal.baseline_definition_revision
   OR submission.frozen_document->>'baseline_product_id' IS DISTINCT FROM proposal.baseline_product_id::text
   OR submission.frozen_document->>'baseline_definition_id' IS DISTINCT FROM proposal.baseline_definition_id::text
   OR (submission.frozen_document->>'baseline_definition_revision')::integer IS DISTINCT FROM proposal.baseline_definition_revision
   OR NOT EXISTS(SELECT 1 FROM definition_revisions baseline JOIN products parent ON parent.tenant_id=baseline.tenant_id AND parent.id=baseline.product_id
    WHERE baseline.tenant_id=t AND baseline.category_id=c AND baseline.id=proposal.baseline_definition_id
     AND source_object_audience(t,c,'definition_revisions',baseline.id,baseline.owner_id,baseline.visibility)
     AND source_object_audience(t,c,'products',parent.id,parent.owner_id,parent.visibility)
     AND (proposal.effective_visibility='private' OR (baseline.visibility='category' AND parent.visibility='category'))) THEN
   RAISE EXCEPTION 'G0 derivation baseline must be actual readable fixed publication' USING ERRCODE='23514'; END IF;
  -- The dependency set comes from persisted source edges, not a caller's
  -- declaration. The frozen document and actual signed consumption must both
  -- contain the complete recursive Claim closure of the fixed parent.
  SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_object('id',(ref->>'id')::uuid,'version',(ref->>'version')::integer)
   ORDER BY jsonb_build_object('id',(ref->>'id')::uuid,'version',(ref->>'version')::integer)),'[]') INTO expected_claims
   FROM jsonb_array_elements(m3_baseline_reference_graph(t,c,proposal.baseline_definition_id,proposal.baseline_definition_revision)) ref
   WHERE ref->>'type'='claim';
  IF jsonb_typeof(coalesce(submission.frozen_document->'baseline_claim_refs','[]')) IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'G0 baseline claim closure differs from fixed publication' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(submission.frozen_document->'baseline_claim_refs','[]')) ref
   WHERE ref->>'type' IS DISTINCT FROM 'claim' OR ref->>'id' IS NULL OR ref->>'version' IS NULL) THEN
   RAISE EXCEPTION 'G0 baseline claim closure differs from fixed publication' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_object('id',(ref->>'id')::uuid,'version',(ref->>'version')::integer)
   ORDER BY jsonb_build_object('id',(ref->>'id')::uuid,'version',(ref->>'version')::integer)),'[]') INTO frozen_claims
   FROM jsonb_array_elements(coalesce(submission.frozen_document->'baseline_claim_refs','[]')) ref;
  IF frozen_claims IS DISTINCT FROM expected_claims THEN
   RAISE EXCEPTION 'G0 baseline claim closure differs from fixed publication' USING ERRCODE='23514'; END IF;
  FOR baseline_claim IN SELECT ref FROM jsonb_array_elements(expected_claims) ref LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(submission.frozen_document->'source_refs','[]')) ref
    WHERE ref->>'type'='claim' AND (ref->>'id')::uuid=(baseline_claim->>'id')::uuid
     AND (ref->>'version')::integer=(baseline_claim->>'version')::integer)
    OR (SELECT count(*) FROM claim_consumptions consumption
     WHERE consumption.tenant_id=t AND consumption.category_id=c AND consumption.product_id=model.id
      AND consumption.claim_id=(baseline_claim->>'id')::uuid AND consumption.claim_version=(baseline_claim->>'version')::integer
      AND consumption.decision_id=decision.id AND consumption.definition_id=definition.id
      AND consumption.receipt_id=receipt.id AND consumption.consumer_id=decision.id AND consumption.xmin=rx)<>1 THEN
    RAISE EXCEPTION 'G0 baseline claim consumption must commit with decision' USING ERRCODE='23514'; END IF;
  END LOOP;
 ELSE
  IF definition.derived_from_definition_id IS NOT NULL OR definition.derived_from_definition_revision IS NOT NULL
   OR proposal.baseline_product_id IS NOT NULL OR proposal.baseline_definition_id IS NOT NULL OR proposal.baseline_definition_revision IS NOT NULL THEN
   RAISE EXCEPTION 'new product has no derivation baseline' USING ERRCODE='23514'; END IF;
 END IF;
 IF proposal.target_kind='new_variant' THEN
  SELECT * INTO variant FROM product_variants WHERE tenant_id=t AND category_id=c AND id=decision.created_variant_id;
  SELECT * INTO variant_version FROM variant_revisions WHERE tenant_id=t AND category_id=c AND variant_id=variant.id AND revision=1;
  IF variant.id IS NULL OR variant_version.id IS NULL OR model.id IS DISTINCT FROM proposal.baseline_product_id OR variant.product_id IS DISTINCT FROM model.id
   OR variant.g0_decision_id IS DISTINCT FROM decision.id OR variant.owner_id IS DISTINCT FROM proposal.owner_id
   OR variant.visibility IS DISTINCT FROM proposal.effective_visibility OR variant_version.visibility IS DISTINCT FROM proposal.effective_visibility
   OR variant_version.definition_id IS DISTINCT FROM definition.id OR variant_version.product_id IS DISTINCT FROM model.id
   OR variant_version.owner_id IS DISTINCT FROM proposal.owner_id OR variant_version.parent_definition_id IS DISTINCT FROM proposal.baseline_definition_id
   OR variant_version.parent_revision IS DISTINCT FROM proposal.baseline_definition_revision
   OR variant_version.previous_revision_id IS NOT NULL
   OR variant_version.sources IS DISTINCT FROM jsonb_build_array(jsonb_build_object('type','definition','id',proposal.baseline_definition_id,'version',proposal.baseline_definition_revision))
   OR variant_version.effective_definition IS DISTINCT FROM jsonb_build_object('definition_id',definition.id,'definition_revision',definition.revision)
   OR rx IS DISTINCT FROM (SELECT xmin FROM product_variants WHERE tenant_id=t AND id=variant.id)
   OR rx IS DISTINCT FROM (SELECT xmin FROM variant_revisions WHERE tenant_id=t AND id=variant_version.id)
   OR receipt.result->>'variant_id' IS DISTINCT FROM variant.id::text THEN
   RAISE EXCEPTION 'G0 variant canonical definition mismatch' USING ERRCODE='23514'; END IF;
 ELSIF proposal.target_kind='new_product' THEN
  IF decision.created_variant_id IS NOT NULL OR definition.variant_id IS NOT NULL
   OR rx IS DISTINCT FROM (SELECT xmin FROM products WHERE tenant_id=t AND id=model.id) OR model.visibility IS DISTINCT FROM proposal.effective_visibility
   OR model.parent_product_id IS DISTINCT FROM (CASE WHEN proposal.entry_kind='derivative' THEN proposal.baseline_product_id ELSE NULL END)
   OR (proposal.baseline_product_id IS NOT NULL AND model.id=proposal.baseline_product_id) THEN
   RAISE EXCEPTION 'G0 new product identity or derivation mismatch' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'unknown G0 target scope' USING ERRCODE='23514'; END IF;
 -- Canonical specification facts are exactly the fixed submitted items,
 -- including human-value and AI provenance fields; JSON numeric strings are
 -- coerced through the actual row type before comparison.
 SELECT count(*) INTO spec_count FROM jsonb_array_elements(submission.frozen_document->'items') item WHERE item->>'kind'='spec';
 IF spec_count<>(SELECT count(*) FROM definition_specs spec WHERE spec.tenant_id=t AND spec.definition_id=definition.id) THEN
  RAISE EXCEPTION 'G0 canonical specification set differs from submission' USING ERRCODE='23514'; END IF;
 FOR spec_item IN SELECT item FROM jsonb_array_elements(submission.frozen_document->'items') item WHERE item->>'kind'='spec' LOOP
  SELECT * INTO STRICT actual_spec FROM definition_specs WHERE tenant_id=t AND category_id=c AND definition_id=definition.id AND key=spec_item->'content'->>'key';
  SELECT * INTO expected_spec FROM jsonb_populate_record(NULL::definition_specs,(spec_item->'content')||jsonb_build_object(
   'text',spec_item->'content'->'text_value','method',spec_item->'content'->'verification_method','state','proposed',
   'test_conditions',coalesce(spec_item->'content'->'test_conditions','[]'::jsonb),
   'reason',coalesce(spec_item->'content'->>'reason',''),'source_refs',spec_item->'source_refs','origin',spec_item->>'origin',
   'writer_id',spec_item->'writer_id','run_id',spec_item->'run_id','confirmed_by',spec_item->'confirmed_by','receipt_id',receipt.id));
  IF (to_jsonb(actual_spec)-ARRAY['id','tenant_id','category_id','product_id','definition_id','created_at']) IS DISTINCT FROM
     (to_jsonb(expected_spec)-ARRAY['id','tenant_id','category_id','product_id','definition_id','created_at']) THEN
   RAISE EXCEPTION 'G0 canonical specification differs from frozen human value or provenance' USING ERRCODE='23514'; END IF;
 END LOOP;
END $$;
""",
    "m3_g0_derivation_assert(uuid,uuid,uuid)",
)

old = prior("m3_atom_guard")
marker = "  IF NEW.outcome='approved' AND ("
assert marker in old
old = old.replace(
    marker,
    "  IF NEW.outcome='approved' THEN PERFORM m3_g0_derivation_assert(NEW.tenant_id,NEW.category_id,NEW.id); END IF;\n"
    + marker,
    1,
)
function(old, "m3_atom_guard()")

function(
    r"""
CREATE FUNCTION m3_derivation_scope_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE payload jsonb; canonical definition_revisions; parent definition_revisions; decision_id uuid; linked_variant product_variants;
BEGIN
 payload=to_jsonb(NEW);
 IF TG_TABLE_NAME='definition_revisions' THEN
  SELECT * INTO STRICT canonical FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
  IF canonical.visibility='category' AND NOT EXISTS(SELECT 1 FROM products model WHERE model.tenant_id=canonical.tenant_id
   AND model.category_id=canonical.category_id AND model.id=canonical.product_id AND model.visibility='category') THEN
   RAISE EXCEPTION 'private model cannot create shared definition' USING ERRCODE='23514'; END IF;
  IF canonical.parent_definition_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM definition_revisions previous
   WHERE previous.tenant_id=canonical.tenant_id AND previous.category_id=canonical.category_id AND previous.id=canonical.parent_definition_id
    AND previous.product_id=canonical.product_id AND previous.variant_id IS NOT DISTINCT FROM canonical.variant_id) THEN
   RAISE EXCEPTION 'definition continuation parent scope mismatch' USING ERRCODE='23514'; END IF;
  IF canonical.status='published' AND NOT m3_published_baseline(canonical.tenant_id,canonical.category_id,canonical.product_id,canonical.id,canonical.revision) THEN
   RAISE EXCEPTION 'published definition receipt mismatch' USING ERRCODE='23514'; END IF;
  IF canonical.derived_from_definition_id IS NOT NULL THEN
   SELECT * INTO STRICT parent FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=canonical.derived_from_definition_id;
   IF NOT m3_published_baseline(parent.tenant_id,parent.category_id,parent.product_id,parent.id,canonical.derived_from_definition_revision)
    OR canonical.g0_decision_id IS NULL THEN RAISE EXCEPTION 'definition derivation baseline mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF canonical.variant_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM product_variants variant WHERE variant.tenant_id=NEW.tenant_id
   AND variant.category_id=NEW.category_id AND variant.id=canonical.variant_id AND variant.product_id=canonical.product_id
   AND variant.g0_decision_id=canonical.g0_decision_id) THEN RAISE EXCEPTION 'definition variant scope mismatch' USING ERRCODE='23514'; END IF;
  decision_id=canonical.g0_decision_id;
 ELSIF TG_TABLE_NAME='product_variants' THEN decision_id=NEW.g0_decision_id;
 ELSIF TG_TABLE_NAME='variant_revisions' THEN
  IF NEW.definition_id IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO STRICT canonical FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  IF canonical.variant_id IS DISTINCT FROM NEW.variant_id OR canonical.product_id IS DISTINCT FROM NEW.product_id
   OR canonical.revision IS DISTINCT FROM NEW.revision OR canonical.g0_decision_id IS NULL
   OR NEW.effective_definition IS DISTINCT FROM jsonb_build_object('definition_id',canonical.id,'definition_revision',canonical.revision) THEN
   RAISE EXCEPTION 'variant snapshot must reference canonical definition' USING ERRCODE='23514'; END IF;
  decision_id=canonical.g0_decision_id;
 ELSIF TG_TABLE_NAME='project_product_links' THEN
  SELECT * INTO STRICT canonical FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  IF canonical.product_id IS DISTINCT FROM NEW.product_id OR canonical.variant_id IS DISTINCT FROM NEW.variant_id
   OR canonical.revision IS DISTINCT FROM NEW.definition_revision THEN
   RAISE EXCEPTION 'project definition variant scope mismatch' USING ERRCODE='23514'; END IF;
  decision_id=canonical.g0_decision_id;
 ELSIF TG_TABLE_NAME='products' THEN
  IF NEW.parent_product_id IS NULL THEN RETURN NULL; END IF;
  SELECT actual.id INTO STRICT decision_id FROM proposal_decisions actual WHERE actual.tenant_id=NEW.tenant_id AND actual.category_id=NEW.category_id
   AND actual.created_product_id=NEW.id AND actual.created_variant_id IS NULL AND actual.outcome='approved';
 END IF;
 IF decision_id IS NOT NULL THEN PERFORM m3_g0_derivation_assert(NEW.tenant_id,NEW.category_id,decision_id); END IF;
 RETURN NULL;
END $$;
""",
    "m3_derivation_scope_atom()",
)
for table in (
    "definition_revisions",
    "product_variants",
    "variant_revisions",
    "project_product_links",
    "products",
):
    trigger(
        "m3_derivation_scope",
        table,
        "m3_derivation_scope_atom",
        operations="INSERT OR UPDATE" if table == "definition_revisions" else "INSERT",
    )

# Only actual new-Variant G0 output rows may account against an existing model
# under the ordinary owner. The invoker lifecycle gate keeps every other path.
VARIANT_OUTPUT_MATCH = """decision.tenant_id=(payload->>'tenant_id')::uuid AND decision.category_id=(payload->>'category_id')::uuid
 AND decision.created_product_id=(payload->>'product_id')::uuid AND decision.created_variant_id IS NOT NULL
 AND decision.outcome='approved' AND decision.decided_by=scope_actor() AND scope_actor()=scope_requester()
 AND decision.xmin::text::bigint=txid_current()%4294967296 AND proposal.target_kind='new_variant'
 AND proposal.baseline_product_id=decision.created_product_id AND category_access(decision.tenant_id,decision.category_id)
 AND EXISTS(SELECT 1 FROM proposal_submissions signed_submission WHERE signed_submission.tenant_id=decision.tenant_id
  AND signed_submission.category_id=decision.category_id AND signed_submission.id=decision.submission_id
  AND signed_submission.proposal_id=proposal.id AND signed_submission.reviewer_id=decision.decided_by
  AND signed_submission.owner_id<>decision.decided_by AND proposal.current_submission_id=signed_submission.id)
 AND CASE TG_TABLE_NAME
  WHEN 'product_variants' THEN (payload->>'id')::uuid=decision.created_variant_id AND (payload->>'g0_decision_id')::uuid=decision.id
  WHEN 'definition_revisions' THEN (payload->>'id')::uuid=decision.created_definition_id
  WHEN 'definition_specs' THEN (payload->>'definition_id')::uuid=decision.created_definition_id
  WHEN 'definition_sources' THEN (payload->>'definition_id')::uuid=decision.created_definition_id
  WHEN 'variant_revisions' THEN (payload->>'variant_id')::uuid=decision.created_variant_id AND (payload->>'definition_id')::uuid=decision.created_definition_id
  WHEN 'projects' THEN (payload->>'id')::uuid=decision.created_project_id
  WHEN 'project_product_links' THEN (payload->>'project_id')::uuid=decision.created_project_id AND (payload->>'definition_id')::uuid=decision.created_definition_id
  WHEN 'plan_revisions' THEN (payload->>'project_id')::uuid=decision.created_project_id
  WHEN 'project_tasks' THEN (payload->>'project_id')::uuid=decision.created_project_id
  WHEN 'project_work_packages' THEN (payload->>'project_id')::uuid=decision.created_project_id
  WHEN 'task_dependencies' THEN (payload->>'project_id')::uuid=decision.created_project_id
  ELSE false END"""
old = prior("lifecycle_reference_gate")
marker = "        p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;"
assert marker in old
route = (
    """        IF TG_OP IN ('INSERT','UPDATE') AND EXISTS(SELECT 1 FROM proposal_decisions decision
          JOIN proposals proposal ON proposal.tenant_id=decision.tenant_id AND proposal.id=decision.proposal_id
          WHERE """
    + VARIANT_OUTPUT_MATCH
    + """) THEN RETURN NEW; END IF;
"""
)
function(old.replace(marker, route + marker, 1), "lifecycle_reference_gate()")

function(
    r"""
CREATE FUNCTION m3_variant_lifecycle_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE payload jsonb; matched_decision proposal_decisions; receipt action_receipts; rx xid; row_xid xid;
BEGIN
 payload=to_jsonb(NEW);
 SELECT decision.* INTO matched_decision FROM proposal_decisions decision JOIN proposals proposal
  ON proposal.tenant_id=decision.tenant_id AND proposal.id=decision.proposal_id WHERE
"""
    + VARIANT_OUTPUT_MATCH
    + r""";
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO STRICT receipt FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=matched_decision.receipt_id;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=receipt.id;
 EXECUTE format('SELECT xmin FROM public.%I WHERE tenant_id=$1 AND id=$2',TG_TABLE_NAME) INTO row_xid USING NEW.tenant_id,NEW.id;
 IF rx IS DISTINCT FROM row_xid THEN RAISE EXCEPTION 'variant G0 reference must be part of its receipt transaction' USING ERRCODE='23514'; END IF;
 PERFORM m3_g0_derivation_assert(NEW.tenant_id,NEW.category_id,matched_decision.id);
 PERFORM 1 FROM products WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.product_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'variant lifecycle product unavailable' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM lifecycle_objects lifecycle WHERE lifecycle.tenant_id=NEW.tenant_id AND lifecycle.product_id=NEW.product_id
  AND ((lifecycle.state->'value'->>'pending_intent_id') IS NOT NULL OR lifecycle.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))
  AND position(lifecycle.id::text IN payload::text)>0) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;
 UPDATE products SET lifecycle_epoch=lifecycle_epoch+1 WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.product_id;
 RETURN NULL;
END $$;
""",
    "m3_variant_lifecycle_atom()",
)
for table in (
    "product_variants",
    "variant_revisions",
    "definition_revisions",
    "definition_specs",
    "definition_sources",
    "projects",
    "project_product_links",
    "plan_revisions",
    "project_tasks",
    "project_work_packages",
    "task_dependencies",
):
    trigger(
        "m3_variant_lifecycle", table, "m3_variant_lifecycle_atom", operations="INSERT OR UPDATE"
    )

old = prior("m3_evidence_consumption_lifecycle_atom")
needle = "  OR rx IS DISTINCT FROM (SELECT xmin FROM products WHERE tenant_id=NEW.tenant_id AND id=subject_product.id) THEN"
assert needle in old
old = old.replace(
    needle,
    "  OR (decision.created_variant_id IS NULL AND rx IS DISTINCT FROM (SELECT xmin FROM products WHERE tenant_id=NEW.tenant_id AND id=subject_product.id)) THEN",
    1,
)
needle = " payload=to_jsonb(NEW);"
assert needle in old
old = old.replace(
    needle,
    " IF decision.created_variant_id IS NOT NULL THEN PERFORM m3_g0_derivation_assert(NEW.tenant_id,NEW.category_id,decision.id); END IF;\n"
    + needle,
    1,
)
function(old, "m3_evidence_consumption_lifecycle_atom()")

for signature, is_new in FUNCTIONS:
    if is_new:
        UP.append(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
        )
UP.append(
    "GRANT EXECUTE ON FUNCTION m3_lock_published_baseline(uuid,uuid,uuid,uuid,integer) TO pdos_next_app"
)
UP.append(
    "GRANT EXECUTE ON FUNCTION m3_derived_baseline_visible(uuid,uuid,uuid,integer) TO pdos_next_app"
)

UP.append("GRANT EXECUTE ON FUNCTION m3_g0_result_reader(uuid,uuid,text,uuid) TO pdos_next_app")
UP.append(
    "GRANT EXECUTE ON FUNCTION m3_variant_definition_visible(uuid,uuid,uuid,uuid,uuid) TO pdos_next_app"
)

REFUSE = """LOCK TABLE products,definition_revisions,product_variants,variant_revisions,project_product_links,proposal_decisions IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM products WHERE parent_product_id IS NOT NULL)
  OR EXISTS(SELECT 1 FROM definition_revisions WHERE variant_id IS NOT NULL OR publication_receipt_id IS NOT NULL OR derived_from_definition_id IS NOT NULL OR derived_from_definition_revision IS NOT NULL OR status<>'draft')
  OR EXISTS(SELECT 1 FROM product_variants WHERE g0_decision_id IS NOT NULL OR length(name)>160)
  OR EXISTS(SELECT 1 FROM variant_revisions WHERE definition_id IS NOT NULL)
  OR EXISTS(SELECT 1 FROM project_product_links WHERE variant_id IS NOT NULL)
  OR EXISTS(SELECT 1 FROM proposal_decisions WHERE created_variant_id IS NOT NULL) THEN
  RAISE EXCEPTION 'derivation downgrade refuses persisted facts' USING ERRCODE='23514'; END IF;
END $$;"""
output = ROOT / "server/migrations/schema_s0_0738.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Fixed published derivation baselines and canonical G0 model/variant scopes."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr((REFUSE, *DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN) + 1} downgrade statements into {output.name}")
