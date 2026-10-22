# ruff: noqa: E501
"""Freeze the statement-snapshot insert window and final G0 source proof; no DB."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".local/m3-derivation-0740-catalog.json"
catalog = json.loads(CATALOG.read_text())


def prior(name):
    return next(row["sql"] for row in catalog["functions"] if row["proname"] == name)


old_reader = prior("definition_sources_visible")
needle = """ AND EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
  AND definition.product_id=p AND definition.id=d AND m3_definition_roots_visible(t,c,d,definition.revision))"""
assert old_reader.count(needle) == 1
new_reader = old_reader.replace(
    needle,
    """ -- INSERT RETURNING can evaluate STABLE read policies before this statement's
 -- new header is visible. Preserve its prior source policy for that window;
 -- every stored header still requires the full actual recursive audience graph.
 AND (NOT EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d)
  OR EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d AND m3_definition_roots_visible(t,c,d,definition.revision)))""",
)
old_atom = prior("m3_g0_derivation_assert")
needle = "END $function$"
assert old_atom.count(needle) == 1
new_atom = old_atom.replace(
    needle,
    """ -- The deferred atom sees the complete persisted canonical graph, after the
 -- INSERT RETURNING statement-snapshot window has closed.
 IF definition_sources_visible(t,c,model.id,definition.id) IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'G0 canonical definition sources are not currently readable' USING ERRCODE='23514'; END IF;
END $function$""",
)
up = (new_reader, new_atom)
down = (old_atom, old_reader)
path = ROOT / "server/migrations/schema_s0_0741.py"
path.write_text(
    '# ruff: noqa: E501\n"""Definition insert snapshot window with deferred complete source proof."""\n\n'
    + f"SCHEMA_SQL = {up!r}\n\nDOWNGRADE_SQL = {down!r}\n"
)
print(f"{len(up)} UP / {len(down)} DOWN")
print("schema SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
print("catalog SHA256", hashlib.sha256(CATALOG.read_bytes()).hexdigest())
