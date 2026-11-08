"""Export audit rows (D56; C16 记审计): one append-only row per delivered export.

PLACEHOLDER NUMBER: s0_0861 was allocated by the coordinating session; rebase onto
the real head when integrating (down_revision and this file's name both move).

Only the named human reader acting for themself inserts a row (scope_actor =
scope_requester, principal kind human, current read access to the category);
the AI writer identity never satisfies the policy. Rows are readable by their
exporter and by active human tenant administrators. No UPDATE or DELETE.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM table (pdos_next.domain.exports.models).
TABLE_SQL = (
    "\nCREATE TABLE export_audits (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactor_id UUID NOT NULL, \n\tcategory_id UUID, \n\tproduct_id UUID, \n\tproject_id UUID, \n\tview VARCHAR(32) NOT NULL, \n\tscope JSONB NOT NULL, \n\trow_count INTEGER NOT NULL, \n\tai_row_count INTEGER NOT NULL, \n\tai_cell_count INTEGER NOT NULL, \n\tcontains_ai BOOLEAN NOT NULL, \n\tsheet_rows JSONB NOT NULL, \n\tfile_format VARCHAR(16) NOT NULL, \n\tfilename VARCHAR(200) NOT NULL, \n\tcontent_sha256 VARCHAR(64) NOT NULL, \n\tbyte_size INTEGER NOT NULL, \n\tmarker_version VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n\tFOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), \n\tCONSTRAINT export_audit_shape CHECK (view IN ('project','my_work','bom_diff','test_summary') AND file_format='xlsx' AND row_count>=0 AND ai_row_count>=0 AND ai_cell_count>=0 AND ai_row_count<=row_count AND byte_size>0 AND contains_ai=(ai_row_count>0 OR ai_cell_count>0) AND content_sha256 ~ '^[0-9a-f]{64}$' AND ((view='my_work' AND category_id IS NULL AND product_id IS NULL AND project_id IS NULL) OR (view<>'my_work' AND category_id IS NOT NULL AND product_id IS NOT NULL)))\n)\n\n",
    'CREATE INDEX ix_export_audits_actor_recent ON export_audits (tenant_id, actor_id, created_at)',
    'CREATE INDEX ix_export_audits_tenant_id ON export_audits (tenant_id)',
)

_TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
_INSERT = f"""{_TENANT}
 AND actor_id=public.scope_actor() AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=export_audits.tenant_id
   AND p.id=export_audits.actor_id AND p.kind='human' AND p.active)
 AND (category_id IS NULL OR public.category_access(tenant_id,category_id))
 AND (product_id IS NULL OR EXISTS(SELECT 1 FROM public.products x
   WHERE x.tenant_id=export_audits.tenant_id AND x.id=export_audits.product_id
    AND x.category_id=export_audits.category_id))"""
_READ = f"""{_TENANT} AND public.scope_actor()=public.scope_requester() AND (
 actor_id=public.scope_requester()
 OR EXISTS(SELECT 1 FROM public.tenant_administrators a JOIN public.principals p
   ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
   WHERE a.tenant_id=export_audits.tenant_id AND a.principal_id=public.scope_actor()
    AND a.active AND p.active AND p.kind='human'))"""
_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

SECURITY_SQL = (
    "ALTER TABLE public.export_audits ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.export_audits FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner_internal ON public.export_audits TO pdos_next_owner USING(true) WITH CHECK(true)",
    f"REVOKE ALL ON public.export_audits FROM {_REVOKED}",
    "CREATE TRIGGER export_audits_append_only BEFORE UPDATE OR DELETE ON public.export_audits "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    f"CREATE POLICY export_audit_append ON public.export_audits FOR INSERT TO pdos_next_app WITH CHECK({_INSERT})",
    f"CREATE POLICY export_audit_read ON public.export_audits FOR SELECT TO pdos_next_app USING({_READ})",
    "GRANT SELECT,INSERT ON public.export_audits TO pdos_next_app",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    "ALTER TABLE public.export_audits NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.export_audits) THEN
     RAISE EXCEPTION 'Export audit history requires s0_0861'; END IF; END $$""",
    "DROP TABLE public.export_audits",
)
