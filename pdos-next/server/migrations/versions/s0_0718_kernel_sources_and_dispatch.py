"""B7 protect actual Run sources and recover queued reference-only dispatch."""

# ruff: noqa: E501 -- exact reviewed PostgreSQL definitions

import hashlib

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0718 import SUMMARY_AFTER, SUMMARY_BEFORE, SUMMARY_HASH

revision = "s0_0718"
down_revision = "s0_0717"
branch_labels = None
depends_on = None

SQL = """
CREATE FUNCTION kernel_lifecycle_links(table_name text,payload jsonb) RETURNS uuid[]
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public AS $$
DECLARE refs uuid[];
BEGIN
 IF table_name<>'agent_runs' THEN RETURN public.lifecycle_payload_links(payload); END IF;
 SELECT COALESCE(array_agg((r->>'artifact_id')::uuid),'{}') INTO refs
 FROM jsonb_array_elements(payload->'read_sources') r;
 RETURN refs;
END $$;
REVOKE ALL ON FUNCTION kernel_lifecycle_links(text,jsonb) FROM PUBLIC,pdos_agent;

CREATE FUNCTION kernel_source_reference_gate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions; links uuid[]='{}';
BEGIN
 IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;
 IF TG_OP='UPDATE' THEN
  prior=OLD;
  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources) IS DISTINCT FROM
     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources)
  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;
 IF r.category_id IS NULL THEN
  IF jsonb_array_length(r.read_sources)<>0
  THEN RAISE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 PERFORM 1 FROM public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF;
 IF r.product_id IS NOT NULL THEN
  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenant_id
   AND category_id=r.category_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NOT public.kernel_read_set_visible(r.tenant_id,r.category_id,r.read_sources)
 THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(r.read_sources) LOOP
  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id
   AND category_id=r.category_id AND id=(ref->>'artifact_id')::uuid
   AND revision=(ref->>'expected_revision')::integer AND status='active'
   AND (product_id IS NULL OR product_id=r.product_id)
   AND product_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;
  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;
  links=array_append(links,a.id);
  IF a.original_id IS NOT NULL THEN links=array_append(links,a.original_id); END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM public.lifecycle_objects o
  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_id AND o.id=ANY(links)
   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL
    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))
 THEN RAISE EXCEPTION 'Pending original prohibits Run source binding'
  USING ERRCODE='23514',CONSTRAINT='category_source_reference_fence'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION kernel_source_reference_gate() FROM PUBLIC,pdos_agent;
CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON agent_runs
 FOR EACH ROW EXECUTE FUNCTION kernel_source_reference_gate();

CREATE FUNCTION kernel_source_reference_clock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE r agent_runs;
BEGIN
 IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;
 IF r.category_id IS NOT NULL AND jsonb_array_length(r.read_sources)>0 THEN
  UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1
   WHERE tenant_id=r.tenant_id AND id=r.category_id;
  IF r.product_id IS NOT NULL THEN
   UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1
    WHERE tenant_id=r.tenant_id AND id=r.product_id;
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
REVOKE ALL ON FUNCTION kernel_source_reference_clock() FROM PUBLIC,pdos_agent;
CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR DELETE ON agent_runs
 FOR EACH ROW EXECUTE FUNCTION kernel_source_reference_clock();

CREATE FUNCTION kernel_pending_runs(t uuid,page_limit integer DEFAULT 100)
RETURNS TABLE(tenant_id uuid,category_id uuid,requester_id uuid,run_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT r.tenant_id,r.category_id,r.requester_id,r.id FROM public.agent_runs r
 WHERE r.tenant_id=t AND t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
  AND r.state='queued' AND r.reverted_at IS NULL
 ORDER BY r.created_at,r.id LIMIT LEAST(GREATEST(page_limit,1),200)
$$;
REVOKE ALL ON FUNCTION kernel_pending_runs(uuid,integer) FROM PUBLIC,pdos_next_app,pdos_agent;
GRANT EXECUTE ON FUNCTION kernel_pending_runs(uuid,integer) TO pdos_next_dispatch;
"""


def upgrade():
    actual = (
        op.get_bind()
        .execute(
            text(
                "SELECT pg_get_functiondef('lifecycle_reference_summary(uuid,uuid,uuid,uuid[])'::regprocedure)"
            )
        )
        .scalar_one()
    )
    if hashlib.sha256(actual.encode()).hexdigest() != SUMMARY_HASH:
        raise RuntimeError("Unreviewed B7 lifecycle summary")
    op.execute(SQL)
    op.execute(SUMMARY_AFTER)


def downgrade():
    if (
        op.get_bind()
        .execute(
            text("SELECT EXISTS(SELECT 1 FROM agent_runs WHERE jsonb_array_length(read_sources)>0)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Retained Run sources prevent removal of their lifecycle guard")
    op.execute(SUMMARY_BEFORE)
    op.execute("DROP TRIGGER lifecycle_reference ON agent_runs")
    op.execute("DROP TRIGGER category_lifecycle_clock ON agent_runs")
    for signature in (
        "kernel_pending_runs(uuid,integer)",
        "kernel_source_reference_clock()",
        "kernel_source_reference_gate()",
        "kernel_lifecycle_links(text,jsonb)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
