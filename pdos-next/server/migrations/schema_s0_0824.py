"""Private append-only work products from actual agent runs."""
# ruff: noqa: E501

TABLE_SQL = """CREATE TABLE public.agent_work_products (
 session_id UUID NOT NULL,
 run_id UUID NOT NULL,
 root_id UUID NOT NULL,
 supersedes_id UUID,
 owner_id UUID NOT NULL,
 category_id UUID,
 kind VARCHAR(16) NOT NULL,
 title VARCHAR(200) NOT NULL,
 body TEXT NOT NULL,
 revision INTEGER NOT NULL,
 origin VARCHAR(16) NOT NULL,
 request_key UUID NOT NULL,
 request_sha256 VARCHAR(64) NOT NULL,
 id UUID NOT NULL,
 tenant_id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id),
 UNIQUE (tenant_id, id),
 UNIQUE (tenant_id, root_id, revision),
 UNIQUE (tenant_id, owner_id, request_key),
 FOREIGN KEY (tenant_id, session_id) REFERENCES public.agent_sessions (tenant_id, id),
 FOREIGN KEY (tenant_id, run_id) REFERENCES public.agent_runs (tenant_id, id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES public.principals (tenant_id, id),
 FOREIGN KEY (tenant_id, category_id) REFERENCES public.categories (tenant_id, id),
 FOREIGN KEY (tenant_id, root_id) REFERENCES public.agent_work_products (tenant_id, id),
 FOREIGN KEY (tenant_id, supersedes_id) REFERENCES public.agent_work_products (tenant_id, id),
 CONSTRAINT work_product_kind CHECK (kind IN ('document','table')),
 CONSTRAINT work_product_origin CHECK (origin IN ('ai_draft','human')),
 CONSTRAINT work_product_revision CHECK (revision > 0),
 CONSTRAINT work_product_title CHECK (char_length(btrim(title)) BETWEEN 1 AND 200),
 CONSTRAINT work_product_body CHECK (char_length(btrim(body)) BETWEEN 1 AND 200000),
 CONSTRAINT work_product_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
 CONSTRAINT work_product_not_self_parent CHECK (supersedes_id IS DISTINCT FROM id)
)"""

INDEX_SQL = "CREATE INDEX ix_agent_work_products_tenant_id ON public.agent_work_products (tenant_id)"

SCOPE_SQL = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester() AND scope_actor()=scope_requester()
 AND EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=agent_work_products.tenant_id
   AND a.id=scope_actor() AND a.active)
 AND EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=agent_work_products.tenant_id
   AND a.id=scope_requester() AND a.active)
 AND EXISTS(SELECT 1 FROM agent_sessions s WHERE s.tenant_id=agent_work_products.tenant_id
   AND s.id=agent_work_products.session_id AND s.owner_id=agent_work_products.owner_id
   AND (s.category_id IS NULL OR category_access(s.tenant_id,s.category_id)))
 AND EXISTS(SELECT 1 FROM agent_runs r WHERE r.tenant_id=agent_work_products.tenant_id
   AND r.id=agent_work_products.run_id)"""

POLICY_SQL = f"""CREATE POLICY work_product_scope ON public.agent_work_products
 USING ({SCOPE_SQL}) WITH CHECK ({SCOPE_SQL})"""
TRIGGER_SQL = """CREATE TRIGGER work_product_append BEFORE UPDATE OR DELETE
 ON public.agent_work_products FOR EACH ROW EXECUTE FUNCTION kernel_append_only()"""
HISTORY_GUARD_SQL = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.agent_work_products) THEN
  RAISE EXCEPTION 'Work product history requires s0_0824';
 END IF;
END $$"""

SCHEMA_SQL = [
    TABLE_SQL,
    INDEX_SQL,
    "ALTER TABLE public.agent_work_products ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.agent_work_products FORCE ROW LEVEL SECURITY",
    POLICY_SQL,
    "REVOKE ALL ON public.agent_work_products FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.agent_work_products TO pdos_next_app",
    TRIGGER_SQL,
]
DOWNGRADE_SQL = [
    "ALTER TABLE public.agent_work_products NO FORCE ROW LEVEL SECURITY",
    HISTORY_GUARD_SQL,
    "ALTER TABLE public.agent_work_products FORCE ROW LEVEL SECURITY",
    "DROP TRIGGER IF EXISTS work_product_append ON public.agent_work_products",
    "DROP TABLE IF EXISTS public.agent_work_products",
]
