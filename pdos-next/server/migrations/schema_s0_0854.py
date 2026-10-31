"""Admit the v2 server project projection under the same fixed source guard."""

from migrations.schema_s0_0850 import NATIVE_FUNCTIONS as FOOTPRINT_FUNCTIONS

SIGNATURE = "kernel_source_reference_gate()"
PREVIOUS_GATE = FOOTPRINT_FUNCTIONS[SIGNATURE]
PREVIOUS_KIND = (
    "r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'"
)
NATIVE_KIND = (
    "(r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'"
    "\n   AND r.versions#>>'{project_current_context,kind}'"
    " IS DISTINCT FROM 'project-current-facts/v2')"
)
if PREVIOUS_GATE.count(PREVIOUS_KIND) != 1:
    raise RuntimeError("0854 requires the reviewed single project context kind guard")
NATIVE_GATE = PREVIOUS_GATE.replace(PREVIOUS_KIND, NATIVE_KIND, 1)

PREVIOUS_FUNCTIONS = {SIGNATURE: PREVIOUS_GATE}
NATIVE_FUNCTIONS = {SIGNATURE: NATIVE_GATE}

LOCK_SQL = "LOCK TABLE public.agent_runs IN SHARE ROW EXCLUSIVE MODE"
RETAINED_V2_SQL = """DO $project_context_v2_history$
BEGIN
 IF EXISTS(SELECT 1 FROM public.agent_runs r
  WHERE r.versions#>>'{project_current_context,kind}'='project-current-facts/v2'
   AND jsonb_array_length(coalesce(
    r.versions#>'{project_current_context,source_proof}','[]'::jsonb))>0) THEN
  RAISE EXCEPTION 'Retained v2 native project source history prohibits downgrade'
   USING ERRCODE='23514',CONSTRAINT='native_project_context_v2_history_retained';
 END IF;
END $project_context_v2_history$;
"""

UP_SQL = (LOCK_SQL, NATIVE_GATE)
# The old guard checks kind only when native sources are nonempty. Empty-source
# v2 Runs remain valid under it and must not impose a new downgrade restriction.
DOWN_SQL = (LOCK_SQL, RETAINED_V2_SQL, PREVIOUS_GATE)
