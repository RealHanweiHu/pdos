# ruff: noqa: E501 -- frozen PostgreSQL definitions preserve their original SQL text
"""Allow category source parents for model consumers; retain invoker RLS."""

from alembic import op

revision = "s0_0418"
down_revision = "s0_0417"
branch_labels = None
depends_on = None
FUNCTION = "CREATE OR REPLACE FUNCTION public.upstream_row_visible(t uuid, c uuid, p uuid, typ text, sid uuid)\n RETURNS boolean\n LANGUAGE plpgsql\n STABLE\n SET search_path TO 'public', 'pg_temp'\nAS $function$\nDECLARE visible boolean;\nBEGIN\n IF NOT typ=ANY(ARRAY['uploaded_originals','artifact_versions','definition_revisions',\n  'product_variants','projects','plan_proposals','bom_revisions','engineering_configurations'])\n THEN RETURN false; END IF;\n EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I\n  WHERE tenant_id=$1 AND category_id=$2 AND (product_id IS NOT DISTINCT FROM $3 OR ($5 AND product_id IS NULL)) AND id=$4)',typ)\n INTO visible USING t,c,p,sid,typ=ANY(ARRAY['uploaded_originals','artifact_versions']);\n RETURN visible;\nEND $function$\n"
PREVIOUS_FUNCTION = "CREATE OR REPLACE FUNCTION public.upstream_row_visible(t uuid, c uuid, p uuid, typ text, sid uuid)\n RETURNS boolean\n LANGUAGE plpgsql\n STABLE\n SET search_path TO 'public', 'pg_temp'\nAS $function$\nDECLARE visible boolean;\nBEGIN\n IF NOT typ=ANY(ARRAY['uploaded_originals','artifact_versions','definition_revisions',\n  'product_variants','projects','plan_proposals','bom_revisions','engineering_configurations'])\n THEN RETURN false; END IF;\n EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I\n  WHERE tenant_id=$1 AND category_id=$2 AND product_id IS NOT DISTINCT FROM $3 AND id=$4)',typ)\n INTO visible USING t,c,p,sid;\n RETURN visible;\nEND $function$\n"


def upgrade():
    op.execute(FUNCTION)


def downgrade():
    op.execute(PREVIOUS_FUNCTION)
