# ruff: noqa: E501
"""Freeze recursive definition audience/privacy and revision metadata locks; no DB."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".local/m3-derivation-0739-catalog.json"
CAT = json.loads(CATALOG.read_text())
UP, DOWN = [], []


def prior(name):
    return next(row["sql"] for row in CAT["functions"] if row["proname"] == name)


def function(sql, signature, *, public=False):
    name = signature.split("(")[0]
    old = next((row["sql"] for row in CAT["functions"] if row["proname"] == name), None)
    UP.append(sql)
    DOWN.insert(0, old or f"DROP FUNCTION {signature}")
    if old is None:
        UP.append(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch"
        )
        if public:
            UP.append(f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app")


function(
    r"""
CREATE FUNCTION m3_definition_source_state(t uuid,c uuid,did uuid,ver integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE refs jsonb; ref jsonb; sid uuid; source_ver integer; readable boolean; is_private boolean;
 private_root boolean=false;
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true THEN RETURN NULL; END IF;
 refs=m3_baseline_reference_graph(t,c,did,ver);
 IF refs IS NULL THEN RETURN NULL; END IF;
 FOR ref IN SELECT item FROM jsonb_array_elements(refs) item LOOP
  sid=(ref->>'id')::uuid; source_ver=(ref->>'version')::integer;
  readable=false; is_private=true;
  IF ref->>'type'='definition' THEN
   SELECT source_object_audience(t,c,'definition_revisions',definition.id,definition.owner_id,definition.visibility)
    AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility),
    definition.visibility<>'category' OR model.visibility<>'category'
   INTO readable,is_private FROM definition_revisions definition JOIN products model
    ON model.tenant_id=definition.tenant_id AND model.category_id=definition.category_id AND model.id=definition.product_id
    WHERE definition.tenant_id=t AND definition.category_id=c AND definition.id=sid AND definition.revision=source_ver;
  ELSIF ref->>'type' IN ('artifact','original') THEN
   -- Historical definition bodies retain their permission boundary even when a
   -- source is withdrawn. Active/version/quote eligibility remains a G0 check.
   SELECT m3_evidence_source_reader(t,c,'artifact',artifact.id)
    AND (original.product_id IS NULL OR source_object_audience(t,c,'products',original_model.id,original_model.owner_id,original_model.visibility)),
    artifact.visibility<>'category' OR coalesce(model.visibility<>'category',false)
     OR coalesce(original.visibility<>'category',false) OR coalesce(original_model.visibility<>'category',false)
   INTO readable,is_private FROM artifact_versions artifact
    LEFT JOIN products model ON model.tenant_id=t AND model.category_id=c AND model.id=artifact.product_id
    LEFT JOIN uploaded_originals original ON original.tenant_id=t AND original.category_id=c AND original.id=artifact.original_id
    LEFT JOIN products original_model ON original_model.tenant_id=t AND original_model.category_id=c AND original_model.id=original.product_id
    WHERE artifact.tenant_id=t AND artifact.category_id=c AND artifact.id=sid;
  ELSIF ref->>'type'='snapshot' THEN
   SELECT m3_evidence_source_reader(t,c,'snapshot',snapshot.id),snapshot.visibility<>'category'
   INTO readable,is_private FROM public_web_snapshots snapshot
    WHERE snapshot.tenant_id=t AND snapshot.category_id=c AND snapshot.id=sid AND source_ver=1;
  ELSIF ref->>'type'='claim' THEN
   SELECT m3_claim_reader(t,c,claim.id)
    AND (claim.product_id IS NULL OR source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility))
    AND (claim.revision=source_ver OR (claim.status<>'active' AND claim.revision=source_ver+1)),
    claim.privacy='private' OR claim.visibility<>'category' OR coalesce(run.private_context,false)
     OR coalesce(model.visibility<>'category',false)
   INTO readable,is_private FROM claims claim
    LEFT JOIN agent_runs run ON run.tenant_id=t AND run.category_id=c AND run.id=claim.run_id
    LEFT JOIN products model ON model.tenant_id=t AND model.category_id=c AND model.id=claim.product_id
    WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id=sid;
  ELSIF ref->>'type'='knowledge' THEN
   SELECT true,false INTO readable,is_private FROM category_knowledge_entries knowledge
    WHERE knowledge.tenant_id=t AND knowledge.category_id=c AND knowledge.id=sid AND knowledge.version=source_ver;
  ELSIF ref->>'type'='parameter' THEN
   SELECT true,false INTO readable,is_private FROM parameter_versions parameter
    WHERE parameter.tenant_id=t AND parameter.category_id=c AND parameter.parameter_id=sid AND parameter.version=source_ver;
  ELSIF ref->>'type'='human' THEN
   SELECT true,false INTO readable,is_private FROM principals person
    WHERE person.tenant_id=t AND person.id=sid AND person.kind='human';
  END IF;
  IF readable IS DISTINCT FROM true THEN RETURN NULL; END IF;
  private_root=private_root OR coalesce(is_private,true);
 END LOOP;
 RETURN jsonb_build_object('private',private_root);
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR numeric_value_out_of_range THEN RETURN NULL;
END $$
""",
    "m3_definition_source_state(uuid,uuid,uuid,integer)",
)

function(
    """
CREATE FUNCTION m3_definition_roots_visible(t uuid,c uuid,did uuid,ver integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m3_definition_source_state(t,c,did,ver) IS NOT NULL
$$
""",
    "m3_definition_roots_visible(uuid,uuid,uuid,integer)",
    public=True,
)
function(
    """
CREATE FUNCTION m3_definition_root_private(t uuid,c uuid,did uuid,ver integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 -- Unknown and unreadable roots return the same NULL, never hidden privacy.
 SELECT (m3_definition_source_state(t,c,did,ver)->>'private')::boolean
$$
""",
    "m3_definition_root_private(uuid,uuid,uuid,integer)",
    public=True,
)

old = prior("definition_sources_visible")
needle = "\n$function$"
assert old.count(needle) == 1
function(
    old.replace(
        needle,
        "\n AND EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c\n  AND definition.product_id=p AND definition.id=d AND m3_definition_roots_visible(t,c,d,definition.revision))"
        + needle,
    ),
    "definition_sources_visible(uuid,uuid,uuid,uuid)",
)
# Keep existing Artifact scope/audience checks; add deep checks to the shared
# helper used by Definition and canonical VariantRevision read policies.
UP.append(
    "CREATE POLICY m3_definition_deep_read ON definition_specs AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (definition_sources_visible(tenant_id,category_id,product_id,definition_id))"
)
DOWN.insert(0, "DROP POLICY m3_definition_deep_read ON definition_specs")
old = prior("m3_evidence_proposal_roots")
needle = (
    "WHEN typ='definition' THEN CASE WHEN d.visibility='category' THEN 'shared' ELSE 'private' END"
)
assert old.count(needle) == 1
function(
    old.replace(
        needle,
        "WHEN typ='definition' THEN CASE WHEN m3_definition_root_private(t,c,n.sid,n.ver) IS FALSE THEN 'shared' ELSE 'private' END",
    ),
    "m3_evidence_proposal_roots(uuid,uuid,uuid)",
)

function(
    """
CREATE FUNCTION m3_lock_variant_revision_audience_target(t uuid,c uuid,sid uuid,expected_owner uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE variant_id_value uuid; model_id uuid; actual_owner uuid;
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true OR scope_actor() IS DISTINCT FROM scope_requester()
  OR NOT EXISTS(SELECT 1 FROM principals person WHERE person.tenant_id=t AND person.id=scope_actor()
   AND person.active AND person.kind='human') THEN RETURN false; END IF;
 SELECT revision.variant_id,revision.product_id,revision.owner_id
  INTO variant_id_value,model_id,actual_owner FROM variant_revisions revision
  JOIN product_variants variant ON variant.tenant_id=t AND variant.category_id=c
   AND variant.id=revision.variant_id AND variant.product_id=revision.product_id
  WHERE revision.tenant_id=t AND revision.category_id=c AND revision.id=sid;
 IF NOT FOUND OR actual_owner IS DISTINCT FROM expected_owner OR
  ((actual_owner=scope_requester() AND category_access(t,c,true))
   OR m3_result_access(t,c,'variant_revisions',sid)) IS DISTINCT FROM true THEN RETURN false; END IF;
 PERFORM 1 FROM products model WHERE model.tenant_id=t AND model.category_id=c AND model.id=model_id
  AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility) FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM product_variants variant WHERE variant.tenant_id=t AND variant.category_id=c AND variant.id=variant_id_value
  AND variant.product_id=model_id AND (source_object_audience(t,c,'product_variants',variant.id,variant.owner_id,variant.visibility)
   OR m3_result_access(t,c,'product_variants',variant.id)) FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM variant_revisions revision WHERE revision.tenant_id=t AND revision.category_id=c AND revision.id=sid
  AND revision.variant_id=variant_id_value AND revision.product_id=model_id AND revision.owner_id=expected_owner
  AND ((revision.owner_id=scope_requester() AND category_access(t,c,true)) OR m3_result_access(t,c,'variant_revisions',sid)) FOR UPDATE;
 RETURN FOUND;
END $$
""",
    "m3_lock_variant_revision_audience_target(uuid,uuid,uuid,uuid)",
    public=True,
)
old = prior("protect_object_audience_target")
needle = " IF typ='product_variants' THEN"
assert old.count(needle) == 1
function(
    old.replace(
        needle,
        """ IF typ='variant_revisions' THEN
  IF m3_lock_variant_revision_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
"""
        + needle,
    ),
    "protect_object_audience_target()",
)

old = prior("m3_g0_derivation_assert")
needle = " IF proposal.target_kind='new_variant' THEN\n"
assert old.count(needle) == 1
proof = """  IF (SELECT count(*) FROM product_variants actual_variant
   JOIN variant_revisions actual_version ON actual_version.tenant_id=actual_variant.tenant_id
    AND actual_version.category_id=actual_variant.category_id AND actual_version.variant_id=actual_variant.id
   WHERE actual_variant.tenant_id=t AND actual_variant.category_id=c AND actual_variant.id=decision.created_variant_id
    AND actual_variant.product_id=model.id AND actual_variant.g0_decision_id=decision.id AND actual_variant.xmin=rx
    AND actual_version.product_id=model.id AND actual_version.definition_id=definition.id
    AND actual_version.revision=1 AND actual_version.xmin=rx
    AND actual_version.parent_definition_id=proposal.baseline_definition_id
    AND actual_version.parent_revision=proposal.baseline_definition_revision
    AND actual_version.effective_definition=jsonb_build_object('definition_id',definition.id,'definition_revision',definition.revision))<>1 THEN
   RAISE EXCEPTION 'G0 variant canonical definition mismatch' USING ERRCODE='23514'; END IF;
"""
updated = old.replace(needle, needle + proof)
needle = "AND (proposal.effective_visibility='private' OR (baseline.visibility='category' AND parent.visibility='category'))"
assert updated.count(needle) == 1
updated = updated.replace(
    needle,
    "AND (proposal.effective_visibility='private' OR (baseline.visibility='category' AND parent.visibility='category' AND m3_definition_root_private(t,c,baseline.id,proposal.baseline_definition_revision) IS FALSE))",
)
function(updated, "m3_g0_derivation_assert(uuid,uuid,uuid)")

path = ROOT / "server/migrations/schema_s0_0740.py"
path.write_text(
    '# ruff: noqa: E501\n"""Deep fixed-definition source privacy and bounded revision audience locks."""\n\n'
    + f"SCHEMA_SQL = {tuple(UP)!r}\n\nDOWNGRADE_SQL = {tuple(DOWN)!r}\n"
)
print(f"{len(UP)} UP / {len(DOWN)} DOWN")
print("schema SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
print("catalog SHA256", hashlib.sha256(CATALOG.read_bytes()).hexdigest())
