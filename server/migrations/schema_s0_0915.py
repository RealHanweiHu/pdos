"""D274: a personal Run's pinned sources link it into each source category's lifecycle graph.

A personal Run (P91) has no category of its own, so the category scan over
``agent_runs`` never saw it, and purge or retention planning missed its references.
Like a DingTalk personal answer, it now joins category c's graph with only the
sources whose category receipt (``versions.personal_sources``) names c. Category
Runs are unchanged, and as with them the Run joins the full graph only, not the
root lookup by identities.
"""

from migrations.schema_s0_0852 import NATIVE_FUNCTIONS as _AT_S0_0852

SIGNATURE = "m3_lifecycle_nodes(uuid,uuid,uuid[])"
# The exact predecessor: written by s0_0852 and unchanged through s0_0869.
PREVIOUS = _AT_S0_0852[SIGNATURE]

_ANCHOR = "\n\n -- Read exactly the retained metadata, never Delivery.payload."
_PERSONAL_RUNS = """

 -- P91 personal Runs have no category; each pinned source keeps its category
 -- receipt, and only this category's subset links the Run here (D274).
 IF identities IS NULL THEN
  FOR payload IN
   SELECT jsonb_build_object('id',r.id,'read_sources',(SELECT jsonb_agg(source)
    FROM jsonb_array_elements(r.versions->'personal_sources') source
    WHERE source->>'category_id'=c::text))
   FROM public.agent_runs r
   WHERE r.tenant_id=t AND r.category_id IS NULL
    AND jsonb_typeof(r.versions->'personal_sources')='array'
    AND EXISTS(SELECT 1 FROM jsonb_array_elements(r.versions->'personal_sources') source
     WHERE source->>'category_id'=c::text)
  LOOP
   table_name='agent_runs'; node_id=(payload->>'id')::uuid;
   links=public.kernel_lifecycle_links(table_name,payload);
   RETURN NEXT;
  END LOOP;
 END IF;"""
if PREVIOUS.count(_ANCHOR) != 1:
    raise RuntimeError("s0_0852 lifecycle graph anchor changed")
CURRENT = PREVIOUS.replace(_ANCHOR, _PERSONAL_RUNS + _ANCHOR)

PREVIOUS_FUNCTIONS = {SIGNATURE: PREVIOUS}
PERSONAL_FUNCTIONS = {SIGNATURE: CURRENT}
UP_SQL = (CURRENT,)
DOWN_SQL = (PREVIOUS,)
