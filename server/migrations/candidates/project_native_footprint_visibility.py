"""Unnumbered RLS delta; only extend the existing restrictive Run audience input.

ALTER POLICY keeps its name, roles, command, permissiveness and other policies.
The existing audience helper deliberately ignores expected_revision (P32).
"""

POLICY = "kernel_source_audience"
PREVIOUS_EXPRESSION = "kernel_read_set_visible(tenant_id, category_id, read_sources)"
UP_SQL = """ALTER POLICY kernel_source_audience ON public.agent_runs
USING (public.kernel_read_set_visible(tenant_id,category_id,
 read_sources||coalesce(versions#>'{project_current_context,source_proof}','[]'::jsonb)))"""
DOWN_SQL = """ALTER POLICY kernel_source_audience ON public.agent_runs
USING (public.kernel_read_set_visible(tenant_id,category_id,read_sources))"""
