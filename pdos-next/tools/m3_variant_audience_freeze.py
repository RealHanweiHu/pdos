# ruff: noqa: E501
"""Freeze the bounded variant audience lock against the actual 0738 catalog; no DB."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".local/m3-derivation-0738-catalog.json"
catalog = json.loads(CATALOG.read_text())
old = next(
    row for row in catalog["functions"] if row["proname"] == "protect_object_audience_target"
)
assert old["owner"] == "pdos_next_owner"
assert old["acl"] == "{pdos_next_owner=X/pdos_next_owner}"

helper = """CREATE FUNCTION public.m3_lock_variant_audience_target(t uuid,c uuid,sid uuid,expected_owner uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE model_id uuid; actual_owner uuid;
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true OR scope_actor() IS DISTINCT FROM scope_requester()
  OR NOT EXISTS(SELECT 1 FROM principals person WHERE person.tenant_id=t AND person.id=scope_actor()
   AND person.active AND person.kind='human') THEN RETURN false; END IF;
 SELECT variant.product_id,variant.owner_id INTO model_id,actual_owner FROM product_variants variant
  WHERE variant.tenant_id=t AND variant.category_id=c AND variant.id=sid;
 IF NOT FOUND OR actual_owner IS DISTINCT FROM expected_owner OR
  ((actual_owner=scope_requester() AND category_access(t,c,true))
    OR m3_result_access(t,c,'product_variants',sid)) IS DISTINCT FROM true THEN RETURN false; END IF;
 -- Preserve the original Product-before-target lock order and its audience boundary.
 PERFORM 1 FROM products model WHERE model.tenant_id=t AND model.category_id=c AND model.id=model_id
  AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility) FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM product_variants variant
  WHERE variant.tenant_id=t AND variant.category_id=c AND variant.id=sid
   AND variant.product_id=model_id AND variant.owner_id=expected_owner
   AND ((variant.owner_id=scope_requester() AND category_access(t,c,true))
    OR m3_result_access(t,c,'product_variants',variant.id)) FOR UPDATE;
 RETURN FOUND;
END $$"""
needle = " model_col=CASE WHEN typ='products'"
assert old["sql"].count(needle) == 1
branch = """ IF typ='product_variants' THEN
  IF m3_lock_variant_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
"""
updated = old["sql"].replace(needle, branch + needle, 1)
signature = "public.m3_lock_variant_audience_target(uuid,uuid,uuid,uuid)"
up = (
    helper,
    f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app",
    updated,
)
down = (old["sql"], f"DROP FUNCTION {signature}")
path = ROOT / "server/migrations/schema_s0_0739.py"
path.write_text(
    '# ruff: noqa: E501\n'
    '"""Bounded ordinary-owner variant audience locking; frozen from actual 0738."""\n\n'
    f"SCHEMA_SQL = {up!r}\n\nDOWNGRADE_SQL = {down!r}\n"
)
print(f"{len(up)} UP / {len(down)} DOWN")
print(f"schema SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}")
print(f"catalog SHA256 {hashlib.sha256(CATALOG.read_bytes()).hexdigest()}")
