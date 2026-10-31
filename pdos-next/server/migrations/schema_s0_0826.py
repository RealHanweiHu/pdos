"""Frozen derived enterprise projection schema, local only and rebuildable."""
# ruff: noqa: E501 -- frozen SQL predicates remain intact.

SCHEMA_SQL = [
    "\n"
    "CREATE TABLE enterprise_search_chunks (\n"
    "\tcategory_id UUID NOT NULL, \n"
    "\tsource_type VARCHAR(32) NOT NULL, \n"
    "\tsource_id UUID NOT NULL, \n"
    "\tsource_revision INTEGER NOT NULL, \n"
    "\tproduct_id UUID, \n"
    "\tproject_id UUID, \n"
    "\tproposal_id UUID, \n"
    "\tcontent_hash VARCHAR(64) NOT NULL, \n"
    "\tchunk_hash VARCHAR(64) NOT NULL, \n"
    "\twork_key VARCHAR(64) NOT NULL, \n"
    "\tordinal INTEGER NOT NULL, \n"
    "\tnature VARCHAR(16) NOT NULL, \n"
    "\ttext TEXT NOT NULL, \n"
    "\tlocator JSONB NOT NULL, \n"
    "\tterms TSVECTOR NOT NULL, \n"
    "\tterm_counts JSONB NOT NULL, \n"
    "\ttitle_counts JSONB NOT NULL, \n"
    "\ttoken_count INTEGER NOT NULL, \n"
    "\tcodes TEXT[] NOT NULL, \n"
    "\tcode_families TEXT[] NOT NULL, \n"
    "\tparser_version VARCHAR(160) NOT NULL, \n"
    "\tchunker_version VARCHAR(160) NOT NULL, \n"
    "\ttokenizer_version VARCHAR(160) NOT NULL, \n"
    "\tcode_rule_version VARCHAR(160) NOT NULL, \n"
    "\tid UUID NOT NULL, \n"
    "\ttenant_id UUID NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tUNIQUE (tenant_id, source_type, source_id, work_key, ordinal), \n"
    "\tCHECK (source_revision>0 AND ordinal>=0 AND token_count>=0), \n"
    "\tCHECK (nature IN ('structured','untrusted')), \n"
    "\tCHECK (char_length(text) BETWEEN 1 AND 20000), \n"
    "\tCHECK (content_hash ~ '^[a-f0-9]{64}$' AND chunk_hash ~ '^[a-f0-9]{64}$')\n"
    ")\n"
    "\n",
    "CREATE INDEX ix_enterprise_chunks_codes ON enterprise_search_chunks USING gin (codes)",
    "CREATE INDEX ix_enterprise_chunks_families ON enterprise_search_chunks USING gin "
    "(code_families)",
    "CREATE INDEX ix_enterprise_chunks_scope ON enterprise_search_chunks (tenant_id, category_id, "
    "source_type, source_id)",
    "CREATE INDEX ix_enterprise_chunks_terms ON enterprise_search_chunks USING gin (terms)",
    "CREATE INDEX ix_enterprise_search_chunks_tenant_id ON enterprise_search_chunks (tenant_id)",
    "ALTER TABLE public.enterprise_search_chunks ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.enterprise_search_chunks FORCE ROW LEVEL SECURITY",
    "CREATE POLICY enterprise_scope ON public.enterprise_search_chunks USING "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND "
    "category_access(tenant_id,category_id)) WITH CHECK "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND "
    "category_access(tenant_id,category_id))",
    "REVOKE ALL ON public.enterprise_search_chunks FROM "
    "PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT,UPDATE,DELETE ON public.enterprise_search_chunks TO pdos_next_app",
    "\n"
    "CREATE TABLE enterprise_search_sources (\n"
    "\tcategory_id UUID NOT NULL, \n"
    "\tsource_type VARCHAR(32) NOT NULL, \n"
    "\tsource_id UUID NOT NULL, \n"
    "\toriginal_id UUID, \n"
    "\tsource_revision INTEGER NOT NULL, \n"
    "\tcontent_hash VARCHAR(64), \n"
    "\twork_key VARCHAR(64), \n"
    "\tchunk_count INTEGER NOT NULL, \n"
    "\tstatus VARCHAR(32) NOT NULL, \n"
    "\tlast_error VARCHAR(80), \n"
    "\tevent_id UUID, \n"
    "\tchecked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tid UUID NOT NULL, \n"
    "\ttenant_id UUID NOT NULL, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tUNIQUE (tenant_id, source_type, source_id), \n"
    "\tCHECK (source_revision>0 AND chunk_count>=0), \n"
    "\tCHECK (status IN ('ready','unavailable','failed','rebuild_required'))\n"
    ")\n"
    "\n",
    "CREATE INDEX ix_enterprise_search_sources_tenant_id ON enterprise_search_sources (tenant_id)",
    "ALTER TABLE public.enterprise_search_sources ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.enterprise_search_sources FORCE ROW LEVEL SECURITY",
    "CREATE POLICY enterprise_scope ON public.enterprise_search_sources USING "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND "
    "category_access(tenant_id,category_id)) WITH CHECK "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND "
    "category_access(tenant_id,category_id))",
    "REVOKE ALL ON public.enterprise_search_sources FROM "
    "PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT,UPDATE,DELETE ON public.enterprise_search_sources TO pdos_next_app",
    "\n"
    "CREATE TABLE enterprise_search_corpus (\n"
    "\ttenant_id UUID NOT NULL, \n"
    "\tchunk_count INTEGER NOT NULL, \n"
    "\ttoken_count INTEGER NOT NULL, \n"
    "\tPRIMARY KEY (tenant_id), \n"
    "\tCHECK (chunk_count>=0 AND token_count>=0)\n"
    ")\n"
    "\n",
    "ALTER TABLE public.enterprise_search_corpus ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.enterprise_search_corpus FORCE ROW LEVEL SECURITY",
    "CREATE POLICY enterprise_scope ON public.enterprise_search_corpus USING "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)",
    "REVOKE ALL ON public.enterprise_search_corpus FROM "
    "PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT,UPDATE,DELETE ON public.enterprise_search_corpus TO pdos_next_app",
    "\n"
    "CREATE TABLE enterprise_search_terms (\n"
    "\ttenant_id UUID NOT NULL, \n"
    "\tterm TEXT NOT NULL, \n"
    "\tdocument_count INTEGER NOT NULL, \n"
    "\tPRIMARY KEY (tenant_id, term), \n"
    "\tCHECK (document_count>=0)\n"
    ")\n"
    "\n",
    "ALTER TABLE public.enterprise_search_terms ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.enterprise_search_terms FORCE ROW LEVEL SECURITY",
    "CREATE POLICY enterprise_scope ON public.enterprise_search_terms USING "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK "
    "(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)",
    "REVOKE ALL ON public.enterprise_search_terms FROM "
    "PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT,UPDATE,DELETE ON public.enterprise_search_terms TO pdos_next_app",
]

DOWNGRADE_SQL = [
    "DROP TABLE public.enterprise_search_terms",
    "DROP TABLE public.enterprise_search_corpus",
    "DROP TABLE public.enterprise_search_sources",
    "DROP TABLE public.enterprise_search_chunks",
]
