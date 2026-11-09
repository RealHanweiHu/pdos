"""Evidence root lookups reject a missing source as a check violation, like every guard (D285).

s0_0733's m3_evidence_root used SELECT ... INTO STRICT, so a claim, link or share whose
root is outside the category (or gone) failed with P0002 "query returned no rows"
instead of the guards' 23514. The rejection itself is unchanged; only its class is.

Placeholder number written on s0_0861 (11-08); renumber to the actual head at integration.
"""

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0864"
down_revision = "s0_0863"
branch_labels = depends_on = None

SIGNATURE = "m3_evidence_root(uuid,uuid,text,uuid,integer)"
PREVIOUS = (
    "CREATE OR REPLACE FUNCTION public.m3_evidence_root(t uuid, c uuid, kind text, sid uuid, "
    "ver integer)\n"
    " RETURNS jsonb\n"
    " LANGUAGE plpgsql\n"
    " STABLE SECURITY DEFINER\n"
    " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
    "AS $function$\n"
    "DECLARE a artifact_versions; w public_web_snapshots; k claims; private boolean; body "
    "text;\n"
    "BEGIN\n"
    " IF kind='claim' THEN\n"
    "  SELECT * INTO STRICT k FROM claims WHERE tenant_id=t AND category_id=c AND id=sid;\n"
    "  IF k.status<>'active' OR k.revision<>ver THEN RAISE EXCEPTION 'claim source stale' "
    "USING ERRCODE='23514'; END IF;\n"
    "  RETURN "
    "m3_evidence_root(t,c,k.source_kind,coalesce(k.artifact_id,k.snapshot_id),k.source_revision)\n"
    "   "
    "||jsonb_build_object('claim_private',k.privacy='private','proposal_id',k.proposal_id);\n"
    " ELSIF kind IN ('artifact','original') THEN\n"
    "  SELECT * INTO STRICT a FROM artifact_versions WHERE tenant_id=t AND category_id=c AND "
    "id=sid;\n"
    "  IF a.status<>'active' OR a.revision<>ver THEN RAISE EXCEPTION 'artifact source stale' "
    "USING ERRCODE='23514'; END IF;\n"
    "  private=a.visibility<>'category' OR EXISTS(SELECT 1 FROM products p WHERE "
    "p.tenant_id=t AND p.id=a.product_id AND p.visibility<>'category')\n"
    "   OR EXISTS(SELECT 1 FROM uploaded_originals o WHERE o.tenant_id=t AND "
    "o.id=a.original_id AND o.visibility<>'category');\n"
    "  RETURN "
    "jsonb_build_object('type','original','id',a.id,'version',a.revision,'private',private,'body',a.content,'product_id',a.product_id);\n"
    " ELSIF kind='snapshot' THEN\n"
    "  SELECT * INTO STRICT w FROM public_web_snapshots WHERE tenant_id=t AND category_id=c "
    "AND id=sid;\n"
    "  IF ver<>1 OR w.status NOT IN ('ok','partial') THEN RAISE EXCEPTION 'snapshot source "
    "stale' USING ERRCODE='23514'; END IF;\n"
    "  RETURN "
    "jsonb_build_object('type','snapshot','id',w.id,'version',1,'private',w.visibility<>'category','body',w.markdown,'product_id',NULL);\n"
    " END IF;\n"
    " RAISE EXCEPTION 'unknown evidence source' USING ERRCODE='23514';\n"
    "END $function$\n"
)

CURRENT = (
    "CREATE OR REPLACE FUNCTION public.m3_evidence_root(t uuid, c uuid, kind text, sid uuid, "
    "ver integer)\n"
    " RETURNS jsonb\n"
    " LANGUAGE plpgsql\n"
    " STABLE SECURITY DEFINER\n"
    " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
    "AS $function$\n"
    "DECLARE a artifact_versions; w public_web_snapshots; k claims; private boolean; body "
    "text;\n"
    "BEGIN\n"
    " IF kind='claim' THEN\n"
    "  SELECT * INTO k FROM claims WHERE tenant_id=t AND category_id=c AND id=sid;\n"
    "  IF NOT FOUND THEN RAISE EXCEPTION 'claim source unavailable' USING ERRCODE='23514'; "
    "END IF;\n"
    "  IF k.status<>'active' OR k.revision<>ver THEN RAISE EXCEPTION 'claim source stale' "
    "USING ERRCODE='23514'; END IF;\n"
    "  RETURN "
    "m3_evidence_root(t,c,k.source_kind,coalesce(k.artifact_id,k.snapshot_id),k.source_revision)\n"
    "   "
    "||jsonb_build_object('claim_private',k.privacy='private','proposal_id',k.proposal_id);\n"
    " ELSIF kind IN ('artifact','original') THEN\n"
    "  SELECT * INTO a FROM artifact_versions WHERE tenant_id=t AND category_id=c AND "
    "id=sid;\n"
    "  IF NOT FOUND THEN RAISE EXCEPTION 'artifact source unavailable' USING ERRCODE='23514'; "
    "END IF;\n"
    "  IF a.status<>'active' OR a.revision<>ver THEN RAISE EXCEPTION 'artifact source stale' "
    "USING ERRCODE='23514'; END IF;\n"
    "  private=a.visibility<>'category' OR EXISTS(SELECT 1 FROM products p WHERE "
    "p.tenant_id=t AND p.id=a.product_id AND p.visibility<>'category')\n"
    "   OR EXISTS(SELECT 1 FROM uploaded_originals o WHERE o.tenant_id=t AND "
    "o.id=a.original_id AND o.visibility<>'category');\n"
    "  RETURN "
    "jsonb_build_object('type','original','id',a.id,'version',a.revision,'private',private,'body',a.content,'product_id',a.product_id);\n"
    " ELSIF kind='snapshot' THEN\n"
    "  SELECT * INTO w FROM public_web_snapshots WHERE tenant_id=t AND category_id=c AND "
    "id=sid;\n"
    "  IF NOT FOUND THEN RAISE EXCEPTION 'snapshot source unavailable' USING ERRCODE='23514'; "
    "END IF;\n"
    "  IF ver<>1 OR w.status NOT IN ('ok','partial') THEN RAISE EXCEPTION 'snapshot source "
    "stale' USING ERRCODE='23514'; END IF;\n"
    "  RETURN "
    "jsonb_build_object('type','snapshot','id',w.id,'version',1,'private',w.visibility<>'category','body',w.markdown,'product_id',NULL);\n"
    " END IF;\n"
    " RAISE EXCEPTION 'unknown evidence source' USING ERRCODE='23514';\n"
    "END $function$\n"
)


def _replace(expected, replacement):
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, {SIGNATURE: expected})
    connection.exec_driver_sql(replacement, execution_options={"no_parameters": True})
    require_functions(connection, {SIGNATURE: replacement})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _replace(PREVIOUS, CURRENT)


def downgrade():
    _replace(CURRENT, PREVIOUS)
