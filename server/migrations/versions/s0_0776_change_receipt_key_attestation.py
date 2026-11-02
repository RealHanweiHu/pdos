"""Attest a readable Change receipt's key without exposing another actor's key."""

from alembic import op

revision = "s0_0776"
down_revision = "s0_0775"
branch_labels = None
depends_on = None

# Same category, direct audience and product audience predicates as the current
# action_receipts/products SELECT policies. A later audience-policy change must
# update this read-only proof together. RequestKey's own-actor RLS stays intact.
FUNCTION = """
CREATE FUNCTION public.change_receipt_key_bound(t uuid, p uuid, receipt uuid)
RETURNS boolean LANGUAGE sql STABLE STRICT SECURITY DEFINER
SET search_path=pg_catalog,public AS $function$
 SELECT EXISTS (
  SELECT 1 FROM public.action_receipts r
  WHERE r.tenant_id=t AND r.product_id=p AND r.id=receipt
    AND public.category_access(r.tenant_id,r.category_id)
    AND (r.visibility='category' OR r.requester_id=public.scope_requester() OR EXISTS (
      SELECT 1 FROM public.object_audiences a
      WHERE a.tenant_id=r.tenant_id AND a.category_id=r.category_id
        AND a.object_type='action_receipts' AND a.subject_id=r.id
        AND a.owner_id=r.requester_id AND a.principal_id=public.scope_requester()))
    AND EXISTS (
      SELECT 1 FROM public.products model
      WHERE model.tenant_id=r.tenant_id AND model.category_id=r.category_id AND model.id=p
        AND ((public.category_access(model.tenant_id,model.category_id)
          AND (model.visibility='category' OR model.owner_id=public.scope_requester()
            OR EXISTS (SELECT 1 FROM public.object_audiences a
              WHERE a.tenant_id=model.tenant_id AND a.category_id=model.category_id
                AND a.object_type='products' AND a.subject_id=model.id
                AND a.owner_id=model.owner_id AND a.principal_id=public.scope_requester())))
          OR public.m3_result_access(model.tenant_id,model.category_id,'products',model.id)))
    AND EXISTS (
      SELECT 1 FROM public.request_keys k
      WHERE k.tenant_id=r.tenant_id AND k.category_id=r.category_id
        AND k.actor_id=r.actor_id AND k.receipt_id=r.id AND k.digest=r.request_digest)
 )
$function$;
"""


def upgrade():
    op.execute(FUNCTION)
    op.execute(
        "REVOKE ALL ON FUNCTION public.change_receipt_key_bound(uuid,uuid,uuid) "
        "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.change_receipt_key_bound(uuid,uuid,uuid) TO pdos_next_app"
    )


def downgrade():
    op.execute("DROP FUNCTION public.change_receipt_key_bound(uuid,uuid,uuid)")
