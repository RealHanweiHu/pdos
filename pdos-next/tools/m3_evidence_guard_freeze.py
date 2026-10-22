# ruff: noqa: E501
"""Freeze 0736 scoped evidence locking and audience deletion from actual 0735."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = json.loads((ROOT / ".local/m3-evidence-0735-catalog.json").read_text())
UP, DOWN = [], []

old = next(row["sql"] for row in CAT["functions"] if row["proname"] == "m3_evidence_link_atom")
# Record variables and table aliases share PL/pgSQL's name resolution. Keep
# the query aliases intact and give the two record variables unique names.
new = old.replace("ar agent_runs;", "actual_link_run agent_runs;").replace(
    "spec definition_specs;", "target_link_spec definition_specs;"
)
new = new.replace(
    "INTO STRICT spec FROM definition_specs", "INTO STRICT target_link_spec FROM definition_specs"
)
new = new.replace(
    "id=spec.definition_id FOR UPDATE", "id=target_link_spec.definition_id FOR UPDATE"
)
marker = " ELSIF NEW.origin='ai_draft' THEN"
assert old.count(marker) == 1
prefix, tail = new.split(marker)
tail = tail.replace(
    "INTO STRICT ar FROM agent_runs", "INTO STRICT actual_link_run FROM agent_runs"
).replace("ar.", "actual_link_run.")
new = prefix + marker + tail
assert new != old
UP.append(new)
DOWN.append(old)

# Audit every M3 PL/pgSQL function against the actual catalog, including the
# newly amended body, for record-variable/table-alias collisions.
for row in CAT["functions"]:
    if not row["proname"].startswith("m3_"):
        continue
    sql = new if row["proname"] == "m3_evidence_link_atom" else row["sql"]
    declarations = re.search(r"DECLARE(.*?)\bBEGIN\b", sql, re.S | re.I)
    if not declarations:
        continue
    variables = set(re.findall(r"(?:^|;)\s*(\w+)\s+[a-z]", declarations.group(1), re.I))
    aliases = set(re.findall(r"\b(?:FROM|JOIN)\s+[\w.]+\s+(?:AS\s+)?(\w+)", sql, re.I))
    assert not variables & aliases, (row["proname"], variables & aliases)

assert not any(row["proname"] == "m3_lock_claim_references" for row in CAT["functions"])
UP.extend(
    [
        r"""
CREATE FUNCTION m3_lock_claim_references(t uuid,c uuid,requested uuid[])
RETURNS TABLE(id uuid,revision integer,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true OR requested IS NULL OR array_position(requested,NULL) IS NOT NULL THEN
  RETURN; END IF;
 -- Exclusive locks serialize approval/Consumption with withdrawal. The caller
 -- gets only row identity and state; reading the body still goes through RLS.
 RETURN QUERY SELECT locked_claim.id,locked_claim.revision,locked_claim.status::text FROM claims locked_claim
  WHERE locked_claim.tenant_id=t AND locked_claim.category_id=c AND locked_claim.id=ANY(requested)
   AND m3_claim_reader(t,c,locked_claim.id)
  ORDER BY locked_claim.id FOR UPDATE OF locked_claim;
 -- Missing and unreadable IDs produce no rows; ordinary caller reads retain
 -- their existing 404 and withdrawn/version-conflict semantics.
END $$;
""",
        "REVOKE ALL ON FUNCTION m3_lock_claim_references(uuid,uuid,uuid[]) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        "GRANT EXECUTE ON FUNCTION m3_lock_claim_references(uuid,uuid,uuid[]) TO pdos_next_app",
    ]
)
DOWN.insert(0, "DROP FUNCTION m3_lock_claim_references(uuid,uuid,uuid[])")

assert not any(
    g["table_name"] == "object_audiences"
    and g["grantee"] == "pdos_next_app"
    and g["privilege_type"] == "DELETE"
    for g in CAT["grants"]
)
assert not any(
    p["tablename"] == "object_audiences" and p["policyname"] == "m3_share_delete_only"
    for p in CAT["policies"]
)
UP.extend(
    [
        "CREATE POLICY m3_share_delete_only ON object_audiences AS RESTRICTIVE FOR DELETE TO pdos_next_app USING (object_type='proposals' AND owner_id=scope_actor() AND m3_evidence_share_pending(tenant_id,category_id,subject_id,NULL))",
        "GRANT DELETE ON object_audiences TO pdos_next_app",
    ]
)
DOWN[:0] = [
    "REVOKE DELETE ON object_audiences FROM pdos_next_app",
    "DROP POLICY m3_share_delete_only ON object_audiences",
]

output = ROOT / "server/migrations/schema_s0_0736.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Unambiguous Link guards, bounded audience deletion and scoped Claim locks."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr(tuple(DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN)} downgrade statements into {output.name}")
