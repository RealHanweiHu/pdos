"""Independent embedding profiles, derived vectors and indexing accounting (P30)."""

EXTENSION_SQL = (
    (
        '-- Root allocates revision/down_revision only after verifying the actu'
        'al head.\nDO $$ BEGIN\n IF NOT EXISTS(SELECT 1 FROM pg_available_extensi'
        "ons WHERE name='vector') THEN\n   RAISE EXCEPTION 'pgvector must be ava"
        "ilable on this PostgreSQL host';\n END IF;\nEND $$;\nCREATE EXTENSION IF "
        'NOT EXISTS vector;\nDO $$ BEGIN\n IF (SELECT string_to_array(extversion,'
        "'.')::int[] FROM pg_extension WHERE extname='vector')\n    < ARRAY[0,8,"
        "6] THEN\n   RAISE EXCEPTION 'Verified pgvector 0.8.6 or newer required "
        "for this draft';\n END IF;\nEND $$;\n\n"
    ),
)

SCHEMA_SQL = (
    (
        'CREATE TABLE enterprise_embedding_profile_heads (\n\ttenant_id UUID NOT '
        'NULL, \n\tprofile_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tenabl'
        'ed BOOLEAN NOT NULL, \n\tPRIMARY KEY (tenant_id, profile_id)\n);\n\nALTER T'
        'ABLE public.enterprise_embedding_profile_heads ENABLE ROW LEVEL SECURI'
        'TY;\n\nALTER TABLE public.enterprise_embedding_profile_heads FORCE ROW L'
        'EVEL SECURITY;\n\nREVOKE ALL ON public.enterprise_embedding_profile_head'
        's FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE PO'
        'LICY embedding_read ON public.enterprise_embedding_profile_heads FOR S'
        'ELECT TO pdos_next_app,pdos_next_owner USING (tenant_id=NULLIF(current'
        "_setting('pdos.tenant_id',true),'')::uuid AND kernel_model_configurati"
        'on_access(tenant_id));\n\nCREATE POLICY embedding_insert ON public.enter'
        'prise_embedding_profile_heads FOR INSERT TO pdos_next_app,pdos_next_ow'
        "ner WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true"
        "),'')::uuid AND kernel_model_configuration_access(tenant_id) AND kerne"
        'l_admin_authorized());\n\nCREATE POLICY embedding_update ON public.enter'
        'prise_embedding_profile_heads FOR UPDATE TO pdos_next_app,pdos_next_ow'
        "ner USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')"
        '::uuid AND kernel_model_configuration_access(tenant_id) AND kernel_adm'
        "in_authorized()) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.te"
        "nant_id',true),'')::uuid AND kernel_model_configuration_access(tenant_"
        'id) AND kernel_admin_authorized());\n\nGRANT SELECT,INSERT,UPDATE ON pub'
        'lic.enterprise_embedding_profile_heads TO pdos_next_app;\n\nCREATE TABLE'
        ' enterprise_embedding_profiles (\n\tprofile_id UUID NOT NULL, \n\trevision'
        ' INTEGER NOT NULL, \n\tbudget_revision INTEGER NOT NULL, \n\tmetadata_json'
        ' JSONB NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tbinding_digest VARCHAR('
        '64) NOT NULL, \n\tsecret_json JSONB, \n\tcreated_by UUID NOT NULL, \n\tid UU'
        'ID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TI'
        'ME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, profile_id,'
        ' revision), \n\tUNIQUE (tenant_id, budget_revision), \n\tUNIQUE (tenant_id'
        ', id), \n\tFOREIGN KEY(tenant_id, profile_id) REFERENCES enterprise_embe'
        'dding_profile_heads (tenant_id, profile_id), \n\tFOREIGN KEY(tenant_id, '
        'created_by) REFERENCES principals (tenant_id, id), \n\tCHECK (revision>0'
        ' AND budget_revision>0)\n);\n\nCREATE INDEX ix_enterprise_embedding_profi'
        'les_tenant_id ON enterprise_embedding_profiles (tenant_id);\n\nALTER TAB'
        'LE public.enterprise_embedding_profiles ENABLE ROW LEVEL SECURITY;\n\nAL'
        'TER TABLE public.enterprise_embedding_profiles FORCE ROW LEVEL SECURIT'
        'Y;\n\nREVOKE ALL ON public.enterprise_embedding_profiles FROM PUBLIC,pdo'
        's_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE POLICY embedding_re'
        'ad ON public.enterprise_embedding_profiles FOR SELECT TO pdos_next_app'
        ",pdos_next_owner USING (tenant_id=NULLIF(current_setting('pdos.tenant_"
        "id',true),'')::uuid AND kernel_model_configuration_access(tenant_id));"
        '\n\nCREATE POLICY embedding_insert ON public.enterprise_embedding_profil'
        'es FOR INSERT TO pdos_next_app,pdos_next_owner WITH CHECK (tenant_id=N'
        "ULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND kernel_mode"
        'l_configuration_access(tenant_id) AND kernel_admin_authorized() AND cr'
        'eated_by=scope_actor());\n\nGRANT SELECT,INSERT ON public.enterprise_emb'
        'edding_profiles TO pdos_next_app;\n\nCREATE TABLE enterprise_embedding_b'
        'udgets (\n\ttenant_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tlimi'
        't_micro_usd BIGINT NOT NULL, \n\theld_micro_usd BIGINT NOT NULL, \n\tspent'
        '_micro_usd BIGINT NOT NULL, \n\tPRIMARY KEY (tenant_id), \n\tCHECK (revisi'
        'on>=0 AND limit_micro_usd>=0 AND held_micro_usd>=0 AND spent_micro_usd'
        '>=0)\n);\n\nALTER TABLE public.enterprise_embedding_budgets ENABLE ROW LE'
        'VEL SECURITY;\n\nALTER TABLE public.enterprise_embedding_budgets FORCE R'
        'OW LEVEL SECURITY;\n\nREVOKE ALL ON public.enterprise_embedding_budgets '
        'FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE POLI'
        'CY embedding_scope ON public.enterprise_embedding_budgets TO pdos_next'
        "_app,pdos_next_owner USING (tenant_id=NULLIF(current_setting('pdos.ten"
        "ant_id',true),'')::uuid AND kernel_model_configuration_access(tenant_i"
        "d)) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true"
        "),'')::uuid AND kernel_model_configuration_access(tenant_id));\n\nGRANT "
        'SELECT,INSERT,UPDATE ON public.enterprise_embedding_budgets TO pdos_ne'
        'xt_app;\n\nCREATE TABLE enterprise_embedding_batches (\n\tprofile_version_'
        'id UUID NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tmanifest JSONB NOT NU'
        'LL, \n\twork_key VARCHAR(64) NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\ta'
        'ttempts INTEGER NOT NULL, \n\tlast_error VARCHAR(80), \n\tid UUID NOT NULL'
        ', \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT'
        ' NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, work_key), \n\tUNIQUE (t'
        'enant_id, id), \n\tFOREIGN KEY(tenant_id, profile_version_id) REFERENCES'
        " enterprise_embedding_profiles (tenant_id, id), \n\tCHECK (state IN ('qu"
        "eued','running','ready','retryable','unavailable')), \n\tCHECK (attempts"
        ' BETWEEN 0 AND 3)\n);\n\nCREATE INDEX ix_enterprise_embedding_batches_ten'
        'ant_id ON enterprise_embedding_batches (tenant_id);\n\nALTER TABLE publi'
        'c.enterprise_embedding_batches ENABLE ROW LEVEL SECURITY;\n\nALTER TABLE'
        ' public.enterprise_embedding_batches FORCE ROW LEVEL SECURITY;\n\nREVOKE'
        ' ALL ON public.enterprise_embedding_batches FROM PUBLIC,pdos_agent,pdo'
        's_next_auth,pdos_next_dispatch;\n\nCREATE POLICY embedding_scope ON publ'
        'ic.enterprise_embedding_batches TO pdos_next_app,pdos_next_owner USING'
        " (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AN"
        'D kernel_model_configuration_access(tenant_id) AND category_access(ten'
        "ant_id,category_id)) WITH CHECK (tenant_id=NULLIF(current_setting('pdo"
        "s.tenant_id',true),'')::uuid AND kernel_model_configuration_access(ten"
        'ant_id) AND category_access(tenant_id,category_id));\n\nGRANT SELECT,INS'
        'ERT,UPDATE ON public.enterprise_embedding_batches TO pdos_next_app;\n\nC'
        'REATE TABLE enterprise_embedding_calls (\n\tbatch_id UUID NOT NULL, \n\tca'
        'tegory_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tattempt INTEGE'
        'R NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tprofile_digest VARCHAR(64)'
        ' NOT NULL, \n\tinput_digest VARCHAR(64) NOT NULL, \n\tsource_count INTEGER'
        ' NOT NULL, \n\tcharacter_count INTEGER NOT NULL, \n\tdata_categories JSONB'
        ' NOT NULL, \n\tegress JSONB NOT NULL, \n\tpricing JSONB NOT NULL, \n\treserv'
        'ed_tokens BIGINT NOT NULL, \n\treserved_micro_usd BIGINT NOT NULL, \n\tcha'
        'rged_micro_usd BIGINT NOT NULL, \n\tinput_tokens BIGINT, \n\tprovider_requ'
        'est_id VARCHAR(200), \n\tevidence_ref VARCHAR(500), \n\tid UUID NOT NULL, '
        '\n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT N'
        'ULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, batch_id, attempt), \n\tUN'
        'IQUE (tenant_id, id), \n\tFOREIGN KEY(tenant_id, batch_id) REFERENCES en'
        "terprise_embedding_batches (tenant_id, id), \n\tCHECK (state IN ('starte"
        "d','completed','unknown','unknown_usage','reconciled')), \n\tCHECK (atte"
        'mpt BETWEEN 1 AND 3 AND revision>0 AND source_count>=0 AND character_c'
        'ount>=0 AND reserved_tokens>=0 AND reserved_micro_usd>=0 AND charged_m'
        'icro_usd>=0 AND (input_tokens IS NULL OR input_tokens>=0))\n);\n\nCREATE '
        'INDEX ix_enterprise_embedding_calls_tenant_id ON enterprise_embedding_'
        'calls (tenant_id);\n\nALTER TABLE public.enterprise_embedding_calls ENAB'
        'LE ROW LEVEL SECURITY;\n\nALTER TABLE public.enterprise_embedding_calls '
        'FORCE ROW LEVEL SECURITY;\n\nREVOKE ALL ON public.enterprise_embedding_c'
        'alls FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE'
        ' POLICY embedding_scope ON public.enterprise_embedding_calls TO pdos_n'
        "ext_app,pdos_next_owner USING (tenant_id=NULLIF(current_setting('pdos."
        "tenant_id',true),'')::uuid AND kernel_model_configuration_access(tenan"
        't_id) AND category_access(tenant_id,category_id)) WITH CHECK (tenant_i'
        "d=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND kernel_m"
        'odel_configuration_access(tenant_id) AND category_access(tenant_id,cat'
        'egory_id));\n\nGRANT SELECT,INSERT,UPDATE ON public.enterprise_embedding'
        '_calls TO pdos_next_app;\n\nCREATE TABLE enterprise_chunk_embeddings (\n\t'
        'tenant_id UUID NOT NULL, \n\tchunk_id UUID NOT NULL, \n\tprofile_version_i'
        'd UUID NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tchunk_hash VARCHAR(64)'
        ' NOT NULL, \n\tdimensions INTEGER NOT NULL, \n\tvector vector NOT NULL, \n\t'
        'norm FLOAT NOT NULL, \n\tPRIMARY KEY (tenant_id, chunk_id, profile_versi'
        'on_id), \n\tFOREIGN KEY(tenant_id, profile_version_id) REFERENCES enterp'
        'rise_embedding_profiles (tenant_id, id), \n\tCHECK (dimensions BETWEEN 1'
        ' AND 2000 AND vector_dims(vector)=dimensions AND norm=1), \n\tFOREIGN KE'
        'Y(chunk_id) REFERENCES enterprise_search_chunks (id) ON DELETE CASCADE'
        '\n);\n\nALTER TABLE public.enterprise_chunk_embeddings ENABLE ROW LEVEL S'
        'ECURITY;\n\nALTER TABLE public.enterprise_chunk_embeddings FORCE ROW LEV'
        'EL SECURITY;\n\nREVOKE ALL ON public.enterprise_chunk_embeddings FROM PU'
        'BLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE POLICY embe'
        'dding_scope ON public.enterprise_chunk_embeddings TO pdos_next_app,pdo'
        "s_next_owner USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',"
        "true),'')::uuid AND kernel_model_configuration_access(tenant_id) AND c"
        'ategory_access(tenant_id,category_id)) WITH CHECK (tenant_id=NULLIF(cu'
        "rrent_setting('pdos.tenant_id',true),'')::uuid AND kernel_model_config"
        'uration_access(tenant_id) AND category_access(tenant_id,category_id));'
        '\n\nGRANT SELECT,INSERT,UPDATE,DELETE ON public.enterprise_chunk_embeddi'
        'ngs TO pdos_next_app;\n\n-- Unnumbered draft. Root must allocate the act'
        'ual next head and verify pgvector.\n-- Reuse the existing non-login, no'
        'n-bypass derived-maintenance role. It\n-- receives DELETE + metadata co'
        'lumns only, never a grant to read vector values.\nGRANT SELECT(tenant_i'
        'd,profile_version_id),DELETE ON public.enterprise_chunk_embeddings\n TO'
        ' pdos_enterprise_index_maintainer;\nCREATE POLICY embedding_retirement_'
        'metadata ON public.enterprise_chunk_embeddings\n FOR SELECT TO pdos_ent'
        "erprise_index_maintainer\n USING (tenant_id=NULLIF(current_setting('pdo"
        "s.tenant_id',true),'')::uuid);\nCREATE POLICY embedding_retirement_dele"
        'te ON public.enterprise_chunk_embeddings\n FOR DELETE TO pdos_enterpris'
        "e_index_maintainer\n USING (tenant_id=NULLIF(current_setting('pdos.tena"
        "nt_id',true),'')::uuid);\nCREATE FUNCTION public.enterprise_embedding_r"
        'etire(t uuid, versions uuid[]) RETURNS void\nLANGUAGE plpgsql SECURITY '
        'DEFINER SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN\n IF t IS'
        " NULL OR t IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',tr"
        "ue),'')::uuid\n    OR versions IS NULL OR array_position(versions,NULL)"
        " IS NOT NULL\n THEN RAISE EXCEPTION 'Exact confirmed profile retirement"
        " required'; END IF;\n DELETE FROM public.enterprise_chunk_embeddings WH"
        'ERE tenant_id=t\n   AND profile_version_id=ANY(versions);\nEND $$;\nREVOK'
        'E ALL ON FUNCTION public.enterprise_embedding_retire(uuid,uuid[])\n FRO'
        'M PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;\nG'
        'RANT EXECUTE ON FUNCTION public.enterprise_embedding_retire(uuid,uuid['
        ']) TO pdos_next_owner;\n-- After upgrade.sql, apply transfer.sql with t'
        'he existing privileged migration shell.\n\nCREATE FUNCTION public.enterp'
        'rise_embedding_profile_atom() RETURNS trigger\nLANGUAGE plpgsql SECURIT'
        'Y DEFINER SET search_path=pg_catalog,public AS $$ BEGIN\n IF NOT EXISTS'
        '(SELECT 1 FROM public.action_receipts r\n   JOIN public.confirmations c'
        ' ON c.tenant_id=r.tenant_id AND c.category_id=r.category_id\n   JOIN pu'
        'blic.audit_entries a ON a.tenant_id=r.tenant_id AND a.receipt_id=r.id\n'
        '   JOIN public.outbox_events o ON o.tenant_id=r.tenant_id AND o.receip'
        't_id=r.id\n   WHERE r.tenant_id=NEW.tenant_id AND r.subject_id=NEW.id\n '
        "   AND r.subject_revision=NEW.revision AND r.operation='embedding.prof"
        "ile.save'\n    AND r.subject_type='embedding_profile' AND r.actor_id=NE"
        'W.created_by\n    AND r.requester_id=NEW.created_by AND r.run_id IS NUL'
        'L AND r.agent_run_id IS NULL\n    AND r.product_id IS NULL AND r.visibi'
        "lity='private'\n    AND c.operation=r.operation AND c.actor_id=NEW.crea"
        "ted_by AND c.consumed\n    AND c.subject_type='category' AND c.subject_"
        'id=r.category_id\n    AND c.created_at<=r.created_at AND r.created_at<c'
        ".expires_at\n    AND c.snapshot->>'binding_digest'=NEW.binding_digest\n "
        "   AND c.snapshot->'metadata'=NEW.metadata_json\n    AND (c.snapshot->>"
        "'next_revision')::integer=NEW.revision\n    AND (c.snapshot->>'next_bud"
        "get_revision')::integer=NEW.budget_revision\n    AND (c.snapshot->>'ena"
        "bled')::boolean=NEW.enabled\n    AND a.category_id=r.category_id AND a."
        'actor_id=r.actor_id AND a.operation=r.operation\n    AND o.category_id='
        "r.category_id AND o.actor_id=r.actor_id\n    AND o.type='embedding.prof"
        "ile_saved' AND o.subject_id=NEW.id\n    AND o.subject_revision=NEW.revi"
        "sion)\n THEN RAISE EXCEPTION 'Confirmed independent embedding profile r"
        "eceipt atom required'; END IF;\n IF NOT EXISTS(SELECT 1 FROM public.ent"
        'erprise_embedding_profile_heads h\n    WHERE h.tenant_id=NEW.tenant_id '
        'AND h.profile_id=NEW.profile_id\n      AND h.revision=NEW.revision AND '
        "h.enabled=NEW.enabled)\n THEN RAISE EXCEPTION 'Exact embedding profile "
        "head required'; END IF;\n IF NOT EXISTS(SELECT 1 FROM public.enterprise"
        '_embedding_budgets b\n    WHERE b.tenant_id=NEW.tenant_id AND b.revisio'
        "n=NEW.budget_revision)\n THEN RAISE EXCEPTION 'Exact indexing budget re"
        "vision required'; END IF;\n IF NOT NEW.enabled THEN\n   PERFORM public.e"
        'nterprise_embedding_retire(NEW.tenant_id, ARRAY(\n     SELECT p.id FROM'
        ' public.enterprise_embedding_profiles p\n      WHERE p.tenant_id=NEW.te'
        'nant_id AND p.profile_id=NEW.profile_id));\n END IF;\n RETURN NEW;\nEND $'
        '$;\nCREATE CONSTRAINT TRIGGER embedding_profile_atom AFTER INSERT ON en'
        'terprise_embedding_profiles\n DEFERRABLE INITIALLY DEFERRED FOR EACH RO'
        'W\n EXECUTE FUNCTION enterprise_embedding_profile_atom();\nCREATE TRIGGE'
        'R embedding_profile_immutable BEFORE UPDATE OR DELETE ON enterprise_em'
        'bedding_profiles\n FOR EACH ROW EXECUTE FUNCTION kernel_append_only();\n'
        '\nCREATE FUNCTION public.enterprise_embedding_head_guard() RETURNS trig'
        'ger\nLANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN\n IF'
        " TG_OP='INSERT' THEN\n   IF NEW.revision<>0 OR NEW.enabled THEN RAISE E"
        "XCEPTION 'Empty profile head required'; END IF;\n ELSE\n   IF NEW.tenant"
        '_id IS DISTINCT FROM OLD.tenant_id OR NEW.profile_id IS DISTINCT FROM '
        'OLD.profile_id\n      OR NEW.revision<>OLD.revision+1 OR NOT EXISTS(\n  '
        '      SELECT 1 FROM enterprise_embedding_profiles p WHERE p.tenant_id='
        'NEW.tenant_id\n          AND p.profile_id=NEW.profile_id AND p.revision'
        "=NEW.revision AND p.enabled=NEW.enabled)\n   THEN RAISE EXCEPTION 'Reta"
        "ined monotonic embedding version required'; END IF;\n END IF;\n RETURN N"
        'EW;\nEND $$;\nCREATE CONSTRAINT TRIGGER embedding_head_guard AFTER INSER'
        'T OR UPDATE\n ON enterprise_embedding_profile_heads DEFERRABLE INITIALL'
        'Y DEFERRED FOR EACH ROW\n EXECUTE FUNCTION enterprise_embedding_head_gu'
        'ard();\n\nCREATE FUNCTION public.enterprise_embedding_budget_guard() RET'
        'URNS trigger\nLANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ '
        "BEGIN\n IF TG_OP='INSERT' THEN\n   IF NEW.revision<>0 OR NEW.limit_micro"
        '_usd<>0 OR NEW.held_micro_usd<>0 OR NEW.spent_micro_usd<>0\n   THEN RAI'
        "SE EXCEPTION 'Empty indexing budget required'; END IF;\n ELSIF NEW.tena"
        "nt_id IS DISTINCT FROM OLD.tenant_id THEN\n   RAISE EXCEPTION 'Immutabl"
        "e indexing budget tenant required';\n ELSIF NEW.revision IS DISTINCT FR"
        'OM OLD.revision OR NEW.limit_micro_usd IS DISTINCT FROM OLD.limit_micr'
        'o_usd THEN\n   IF NEW.revision<>OLD.revision+1 OR NOT kernel_admin_auth'
        'orized() OR NOT EXISTS(\n     SELECT 1 FROM action_receipts r JOIN conf'
        'irmations c\n       ON c.tenant_id=r.tenant_id AND c.category_id=r.cate'
        'gory_id\n     JOIN enterprise_embedding_profiles p ON p.tenant_id=r.ten'
        'ant_id AND p.id=r.subject_id\n     WHERE r.tenant_id=NEW.tenant_id AND '
        "r.operation='embedding.profile.save'\n       AND p.budget_revision=NEW."
        'revision AND p.revision=r.subject_revision\n       AND r.requester_id=s'
        'cope_requester() AND r.actor_id=scope_actor()\n       AND r.run_id IS N'
        'ULL AND r.agent_run_id IS NULL\n       AND c.operation=r.operation AND '
        "c.actor_id=r.actor_id AND c.consumed\n       AND (c.snapshot->>'index_b"
        "udget_micro_usd')::bigint=NEW.limit_micro_usd\n       AND (c.snapshot->"
        ">'next_budget_revision')::integer=NEW.revision\n       AND c.created_at"
        '<=r.created_at AND r.created_at<c.expires_at)\n   THEN RAISE EXCEPTION '
        "'Confirmed indexing budget CAS required'; END IF;\n END IF;\n RETURN NEW"
        ';\nEND $$;\nCREATE CONSTRAINT TRIGGER embedding_budget_guard AFTER INSER'
        'T OR UPDATE\n ON enterprise_embedding_budgets DEFERRABLE INITIALLY DEFE'
        'RRED FOR EACH ROW\n EXECUTE FUNCTION enterprise_embedding_budget_guard('
        ');\n\nCREATE FUNCTION public.enterprise_embedding_vector_guard() RETURNS'
        ' trigger\nLANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGI'
        'N\n IF NOT EXISTS(SELECT 1 FROM enterprise_search_chunks c\n    WHERE c.'
        'id=NEW.chunk_id AND c.tenant_id=NEW.tenant_id AND c.category_id=NEW.ca'
        'tegory_id\n      AND c.chunk_hash=NEW.chunk_hash)\n OR NOT EXISTS(SELECT'
        ' 1 FROM enterprise_embedding_profiles p\n    JOIN enterprise_embedding_'
        'profile_heads h ON h.tenant_id=p.tenant_id\n      AND h.profile_id=p.pr'
        'ofile_id AND h.revision=p.revision AND h.enabled\n    WHERE p.id=NEW.pr'
        'ofile_version_id AND p.tenant_id=NEW.tenant_id AND p.enabled\n      AND'
        " (p.metadata_json->>'dimensions')::integer=NEW.dimensions)\n OR abs(vec"
        "tor_norm(NEW.vector)-1)>0.0001\n THEN RAISE EXCEPTION 'Current scoped c"
        "hunk and normalized independent profile space required'; END IF;\n RETU"
        'RN NEW;\nEND $$;\nCREATE TRIGGER embedding_vector_guard BEFORE INSERT OR'
        ' UPDATE ON enterprise_chunk_embeddings\n FOR EACH ROW EXECUTE FUNCTION '
        'enterprise_embedding_vector_guard();\n\nCREATE FUNCTION public.enterpris'
        'e_embedding_reconcile_atom() RETURNS trigger\nLANGUAGE plpgsql SECURITY'
        " DEFINER SET search_path=pg_catalog,public AS $$ BEGIN\n IF NEW.state='"
        "reconciled' AND OLD.state IS DISTINCT FROM 'reconciled' THEN\n   IF OLD"
        ".state NOT IN ('unknown','unknown_usage') OR NEW.revision<>OLD.revisio"
        'n+1\n   OR NOT EXISTS(SELECT 1 FROM action_receipts r JOIN confirmation'
        's c\n     ON c.tenant_id=r.tenant_id AND c.category_id=r.category_id\n  '
        '   JOIN audit_entries a ON a.tenant_id=r.tenant_id AND a.receipt_id=r.'
        'id\n     JOIN outbox_events o ON o.tenant_id=r.tenant_id AND o.receipt_'
        'id=r.id\n     WHERE r.tenant_id=NEW.tenant_id AND r.subject_id=NEW.id\n '
        "      AND r.subject_revision=NEW.revision AND r.operation='embedding.c"
        "all.reconcile'\n       AND r.subject_type='embedding_call' AND r.catego"
        'ry_id=NEW.category_id\n       AND r.actor_id=r.requester_id AND r.run_i'
        'd IS NULL AND r.agent_run_id IS NULL\n       AND c.operation=r.operatio'
        'n AND c.actor_id=r.actor_id AND c.consumed\n       AND c.created_at<=r.'
        "created_at AND r.created_at<c.expires_at\n       AND c.snapshot->>'call"
        "_id'=NEW.id::text\n       AND (c.snapshot->>'actual_micro_usd')::bigint"
        "=NEW.charged_micro_usd\n       AND (c.snapshot->>'input_tokens')::bigin"
        "t=NEW.input_tokens\n       AND c.snapshot->>'evidence_ref'=NEW.evidence"
        "_ref\n       AND a.operation=r.operation AND o.type='embedding.call_rec"
        "onciled')\n   THEN RAISE EXCEPTION 'Confirmed original embedding cost r"
        "econciliation required'; END IF;\n ELSIF OLD.state<>'started' THEN\n   R"
        "AISE EXCEPTION 'Settled embedding accounting is immutable';\n END IF;\n "
        'RETURN NEW;\nEND $$;\nCREATE CONSTRAINT TRIGGER embedding_reconcile_atom'
        ' AFTER UPDATE ON enterprise_embedding_calls\n DEFERRABLE INITIALLY DEFE'
        'RRED FOR EACH ROW\n EXECUTE FUNCTION enterprise_embedding_reconcile_ato'
        'm();\nREVOKE ALL ON FUNCTION enterprise_embedding_profile_atom(),enterp'
        'rise_embedding_head_guard(),\n enterprise_embedding_budget_guard(),ente'
        'rprise_embedding_vector_guard(),\n enterprise_embedding_reconcile_atom('
        ') FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\n\nCREATE I'
        'NDEX ix_enterprise_embedding_hnsw_2\n ON enterprise_chunk_embeddings US'
        'ING hnsw ((vector::vector(2)) vector_cosine_ops)\n WHERE dimensions=2;\n'
        '\nCREATE INDEX ix_enterprise_embedding_hnsw_384\n ON enterprise_chunk_em'
        'beddings USING hnsw ((vector::vector(384)) vector_cosine_ops)\n WHERE d'
        'imensions=384;\n\nCREATE INDEX ix_enterprise_embedding_hnsw_768\n ON ente'
        'rprise_chunk_embeddings USING hnsw ((vector::vector(768)) vector_cosin'
        'e_ops)\n WHERE dimensions=768;\n\nCREATE INDEX ix_enterprise_embedding_hn'
        'sw_1024\n ON enterprise_chunk_embeddings USING hnsw ((vector::vector(10'
        '24)) vector_cosine_ops)\n WHERE dimensions=1024;\n\nCREATE INDEX ix_enter'
        'prise_embedding_hnsw_1536\n ON enterprise_chunk_embeddings USING hnsw ('
        '(vector::vector(1536)) vector_cosine_ops)\n WHERE dimensions=1536;\n\nCRE'
        'ATE INDEX ix_enterprise_embedding_hnsw_2000\n ON enterprise_chunk_embed'
        'dings USING hnsw ((vector::vector(2000)) vector_cosine_ops)\n WHERE dim'
        'ensions=2000;\n'
    ),
)

EMPTY_HISTORY_SQL = (
    (
        'DO $$ BEGIN\n IF EXISTS(SELECT 1 FROM enterprise_embedding_calls)\n OR E'
        'XISTS(SELECT 1 FROM enterprise_embedding_profiles) THEN\n   RAISE EXCEP'
        "TION 'Retain profile/cost/egress history; export and explicitly resolv"
        "e before downgrade';\n END IF;\nEND $$;\n\n"
    ),
)

DOWNGRADE_SQL = (
    (
        'DROP FUNCTION public.enterprise_embedding_retire(uuid,uuid[]);\n\nDROP T'
        'ABLE public.enterprise_chunk_embeddings;\n\nDROP TABLE public.enterprise'
        '_embedding_calls;\n\nDROP TABLE public.enterprise_embedding_batches;\n\nDR'
        'OP TABLE public.enterprise_embedding_budgets;\n\nDROP TABLE public.enter'
        'prise_embedding_profiles;\n\nDROP TABLE public.enterprise_embedding_prof'
        'ile_heads;\n\nDROP FUNCTION public.enterprise_embedding_profile_atom();\n'
        '\nDROP FUNCTION public.enterprise_embedding_head_guard();\n\nDROP FUNCTIO'
        'N public.enterprise_embedding_budget_guard();\n\nDROP FUNCTION public.en'
        'terprise_embedding_vector_guard();\n\nDROP FUNCTION public.enterprise_em'
        'bedding_reconcile_atom();\n\n-- Existing shared vector extension is deli'
        'berately retained.\n'
    ),
)

TRANSFER_SQL = (
    (
        '-- Same post-owner transfer pattern as s0_0832 / s0_0834; no runtime m'
        'embership.\nGRANT CREATE ON SCHEMA public TO pdos_enterprise_index_main'
        'tainer;\nALTER FUNCTION public.enterprise_embedding_retire(uuid,uuid[])'
        ' OWNER TO pdos_enterprise_index_maintainer;\nREVOKE CREATE ON SCHEMA pu'
        'blic FROM pdos_enterprise_index_maintainer;\n'
    ),
)

RESTORE_SQL = (
    (
        '-- Privileged shell only, before empty-data ordinary-owner downgrade.s'
        'ql.\nALTER FUNCTION public.enterprise_embedding_retire(uuid,uuid[]) OWN'
        'ER TO pdos_next_owner;\n'
    ),
)

