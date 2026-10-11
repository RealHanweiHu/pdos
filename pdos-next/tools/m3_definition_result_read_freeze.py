# ruff: noqa: E501
"""Freeze the pending G0 result's self-audience window from actual 0741; no DB."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".local/m3-derivation-0741-catalog.json"
catalog = json.loads(CATALOG.read_text())
old = next(
    row["sql"] for row in catalog["functions"] if row["proname"] == "m3_definition_source_state"
)
needle = "SELECT source_object_audience(t,c,'definition_revisions',definition.id,definition.owner_id,definition.visibility)\n    AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility),"
assert old.count(needle) == 1
new = old.replace(
    needle,
    """SELECT (source_object_audience(t,c,'definition_revisions',definition.id,definition.owner_id,definition.visibility)
    OR (definition.id=did AND definition.xmin::text::bigint=txid_current()%4294967296
     AND m3_result_access(t,c,'definition_revisions',definition.id)))
    AND source_object_audience(t,c,'products',model.id,model.owner_id,model.visibility),""",
)
# The exception is only the exact new result header. Every nested fixed parent
# and source retains its actual audience, and privacy still comes from the rows.
path = ROOT / "server/migrations/schema_s0_0742.py"
path.write_text(
    '# ruff: noqa: E501\n"""Same-transaction G0 definition self-audience window; parents remain guarded."""\n\n'
    + f"SCHEMA_SQL = {(new,)!r}\n\nDOWNGRADE_SQL = {(old,)!r}\n"
)
print("1 UP / 1 DOWN")
print("schema SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
print("catalog SHA256", hashlib.sha256(CATALOG.read_bytes()).hexdigest())
