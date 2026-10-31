"""Unnumbered G base proposal. Administratively executed; never a runtime entry."""

BASE_SQL = (
    (
        '-- UNNUMBERED REVIEW DRAFT. Do not apply until root reviews actual head and role grant'
        's.\n-- No business source SELECT, broad RLS disable, runtime role membership or creden'
        'tials.\nCREATE ROLE pdos_next_dingtalk_maintenance NOLOGIN NOSUPERUSER NOCREATEDB NOCR'
        'EATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;'
    ),
    (
        'CREATE TABLE dingtalk_applications (\n\tadministrator_id UUID NOT NULL, \n\tservice_pr'
        'incipal_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcorp_id VARCHAR(160) NOT '
        'NULL, \n\tclient_id VARCHAR(160) NOT NULL, \n\trobot_code VARCHAR(160) NOT NULL, \n\ts'
        'ecret_arn TEXT NOT NULL, \n\tsecret_version VARCHAR(160) NOT NULL, \n\tactive BOOLEAN '
        'NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP '
        'WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE '
        '(tenant_id), \n\tFOREIGN KEY(tenant_id, administrator_id) REFERENCES principals (tenan'
        't_id, id), \n\tFOREIGN KEY(tenant_id, service_principal_id) REFERENCES principals (ten'
        'ant_id, id), \n\tCHECK (revision>0 AND length(corp_id)>0 AND length(secret_version)>0)'
        ', \n\tUNIQUE (corp_id)\n)\n\n;'
    ),
    (
        'CREATE INDEX ix_dingtalk_applications_tenant_id ON dingtalk_applications (tenant_id);'
    ),
    (
        'ALTER TABLE public.dingtalk_applications ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_applications FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_applications FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_'
        'next_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_applications TO pdos_next_app;'
    ),
    (
        'CREATE TABLE dingtalk_binding_nonces (\n\tapplication_id UUID NOT NULL, \n\towner_id U'
        'UID NOT NULL, \n\tapp_revision INTEGER NOT NULL, \n\tstate_sha256 VARCHAR(64) NOT NULL'
        ', \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tconsumed_at TIMESTAMP WITH TIM'
        'E ZONE, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WI'
        'TH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (s'
        'tate_sha256), \n\tFOREIGN KEY(tenant_id, application_id) REFERENCES dingtalk_applicati'
        'ons (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenan'
        't_id, id), \n\tCHECK (app_revision>0 AND length(state_sha256)=64)\n)\n\n;'
    ),
    (
        'CREATE INDEX ix_dingtalk_binding_nonces_tenant_id ON dingtalk_binding_nonces (tenant_i'
        'd);'
    ),
    (
        'ALTER TABLE public.dingtalk_binding_nonces ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_binding_nonces FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_binding_nonces FROM PUBLIC,pdos_agent,pdos_next_auth,pdo'
        's_next_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_binding_nonces TO pdos_next_app;'
    ),
    (
        'CREATE TABLE dingtalk_account_bindings (\n\tapplication_id UUID NOT NULL, \n\towner_id'
        ' UUID NOT NULL, \n\texternal_user_id VARCHAR(200) NOT NULL, \n\tverified_nonce_id UUID'
        ' NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tepoch INTEGER NOT NULL, \n\tverified_at TI'
        'MESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_by UUID, \n\trevoke_key UUID, \n\trevoke_'
        'reason TEXT, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTA'
        'MP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tFORE'
        'IGN KEY(tenant_id, application_id) REFERENCES dingtalk_applications (tenant_id, id), '
        '\n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIG'
        'N KEY(tenant_id, revoked_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(te'
        'nant_id, verified_nonce_id) REFERENCES dingtalk_binding_nonces (tenant_id, id), \n\tUN'
        'IQUE (tenant_id, verified_nonce_id), \n\tCHECK (epoch>0 AND length(external_user_id)>0'
        '), \n\tCHECK ((active AND revoked_by IS NULL AND revoke_key IS NULL) OR (NOT active AN'
        'D revoked_by IS NOT NULL AND revoke_key IS NOT NULL))\n)\n\n;'
    ),
    (
        'CREATE UNIQUE INDEX dingtalk_one_active_account ON dingtalk_account_bindings (tenant_i'
        'd, owner_id) WHERE active IS true;'
    ),
    (
        'CREATE UNIQUE INDEX dingtalk_one_active_external ON dingtalk_account_bindings (applica'
        'tion_id, external_user_id) WHERE active IS true;'
    ),
    (
        'CREATE INDEX ix_dingtalk_account_bindings_tenant_id ON dingtalk_account_bindings (tena'
        'nt_id);'
    ),
    (
        'ALTER TABLE public.dingtalk_account_bindings ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_account_bindings FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_account_bindings FROM PUBLIC,pdos_agent,pdos_next_auth,p'
        'dos_next_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_account_bindings TO pdos_next_app;'
    ),
    (
        'CREATE TABLE dingtalk_messages (\n\tapplication_id UUID NOT NULL, \n\tbinding_id UUID '
        'NOT NULL, \n\tbinding_epoch INTEGER NOT NULL, \n\towner_id UUID NOT NULL, \n\texternal'
        '_message_id VARCHAR(200) NOT NULL, \n\tenvelope_sha256 VARCHAR(64) NOT NULL, \n\tconve'
        'rsation_kind VARCHAR(16) NOT NULL, \n\tconversation_id VARCHAR(200) NOT NULL, \n\trun_'
        'id UUID NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\terror_code VARCHAR(80), \n\tleas'
        'e_id UUID, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tworkflow_id VARCHAR(240), \n'
        '\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZO'
        'NE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (application'
        '_id, external_message_id), \n\tUNIQUE (tenant_id, run_id), \n\tFOREIGN KEY(tenant_id, '
        'application_id) REFERENCES dingtalk_applications (tenant_id, id), \n\tFOREIGN KEY(tena'
        'nt_id, binding_id) REFERENCES dingtalk_account_bindings (tenant_id, id), \n\tFOREIGN K'
        'EY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_'
        'id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tCHECK (binding_epoch>0 AND leng'
        "th(envelope_sha256)=64), \n\tCHECK (conversation_kind IN ('direct','group')), \n\tCHEC"
        "K (state IN ('pending','admitted','completed','cancelled','unknown','blocked'))\n)\n\n"
        ';'
    ),
    (
        'CREATE INDEX ix_dingtalk_messages_tenant_id ON dingtalk_messages (tenant_id);'
    ),
    (
        'ALTER TABLE public.dingtalk_messages ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_messages FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_messages FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next'
        '_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_messages TO pdos_next_app;'
    ),
    (
        'CREATE TABLE dingtalk_share_consents (\n\tmessage_id UUID NOT NULL, \n\towner_id UUID '
        'NOT NULL, \n\trequest_key UUID NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\t'
        'include_citations BOOLEAN NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\terror_code VAR'
        'CHAR(80), \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP '
        'WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE '
        '(tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, message_id) REFERENCES '
        'dingtalk_messages (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES pri'
        "ncipals (tenant_id, id), \n\tCHECK (length(payload_sha256)=64), \n\tCHECK (state IN ('"
        "confirmed','dispatched','blocked','delivered','unknown','cancelled'))\n)\n\n;"
    ),
    (
        'CREATE INDEX ix_dingtalk_share_consents_tenant_id ON dingtalk_share_consents (tenant_i'
        'd);'
    ),
    (
        'ALTER TABLE public.dingtalk_share_consents ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_share_consents FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_share_consents FROM PUBLIC,pdos_agent,pdos_next_auth,pdo'
        's_next_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_share_consents TO pdos_next_app;'
    ),
    (
        'CREATE TABLE dingtalk_deliveries (\n\tmessage_id UUID NOT NULL, \n\towner_id UUID NOT '
        'NULL, \n\tconsent_id UUID, \n\trequest_key UUID NOT NULL, \n\tphase VARCHAR(24) NOT NU'
        'LL, \n\tpayload JSONB NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\tcontent_k'
        'ind VARCHAR(24) NOT NULL, \n\tsource_dependencies JSONB NOT NULL, \n\tstate VARCHAR(24'
        ') NOT NULL, \n\tp26 JSONB, \n\tprovider_receipt JSONB, \n\terror_code VARCHAR(80), \n'
        '\tattempts INTEGER NOT NULL, \n\tattempt_id UUID, \n\tsend_started_at TIMESTAMP WITH T'
        'IME ZONE, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP '
        'WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE '
        '(tenant_id, request_key), \n\tFOREIGN KEY(tenant_id, message_id) REFERENCES dingtalk_m'
        'essages (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (t'
        'enant_id, id), \n\tFOREIGN KEY(tenant_id, consent_id) REFERENCES dingtalk_share_consen'
        "ts (tenant_id, id), \n\tCHECK (phase IN ('received','answer','group_notice','share')),"
        " \n\tCHECK (state IN ('planned','sending','delivered','unknown','blocked','cancelled')"
        '), \n\tCHECK (attempts>=0 AND length(payload_sha256)=64), \n\tCHECK (content_kind IN ('
        "'control','answer','local_link')), \n\tCHECK (CASE WHEN jsonb_typeof(source_dependenci"
        "es)='array' THEN (content_kind='answer')=(jsonb_array_length(source_dependencies)>0) E"
        "LSE false END), \n\tCHECK ((phase='share' AND consent_id IS NOT NULL) OR (phase<>'shar"
        "e' AND consent_id IS NULL)), \n\tCHECK (state NOT IN ('sending','delivered','unknown')"
        ' OR p26 IS NOT NULL)\n)\n\n;'
    ),
    (
        'CREATE INDEX ix_dingtalk_deliveries_tenant_id ON dingtalk_deliveries (tenant_id);'
    ),
    (
        'ALTER TABLE public.dingtalk_deliveries ENABLE ROW LEVEL SECURITY;'
    ),
    (
        'ALTER TABLE public.dingtalk_deliveries FORCE ROW LEVEL SECURITY;'
    ),
    (
        'REVOKE ALL ON public.dingtalk_deliveries FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_ne'
        'xt_dispatch;'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.dingtalk_deliveries TO pdos_next_app;'
    ),
    (
        '-- NOLOGIN role reads only exact channel metadata. Delivery payload and business\n-- g'
        'oal/result/text/source refs are deliberately absent from its SELECT grants.\nGRANT USA'
        'GE,CREATE ON SCHEMA public TO pdos_next_dingtalk_maintenance;'
    ),
    (
        '-- Existing PUBLIC kernel RLS expressions may invoke these ordinary predicates.\nGRANT'
        ' EXECUTE ON FUNCTION public.scope_actor(),public.scope_requester(),\n public.category_'
        'access(uuid,uuid,boolean) TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT SELECT ON public.dingtalk_applications,public.dingtalk_account_bindings,\n publi'
        'c.dingtalk_binding_nonces,public.dingtalk_messages,public.dingtalk_share_consents\n TO'
        ' pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT SELECT (id,tenant_id,message_id,owner_id,consent_id,request_key,phase,state,erro'
        'r_code,content_kind,source_dependencies)\n ON public.dingtalk_deliveries TO pdos_next_'
        'dingtalk_maintenance;'
    ),
    (
        'GRANT UPDATE (state,error_code) ON public.dingtalk_deliveries TO pdos_next_dingtalk_ma'
        'intenance;'
    ),
    (
        'GRANT UPDATE (state) ON public.dingtalk_messages TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT SELECT (id,tenant_id,requester_id,writer_id,category_id,state,cancel_epoch,rever'
        'ted_at)\n ON public.agent_runs TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT UPDATE (state,error_code,cancel_epoch) ON public.agent_runs TO pdos_next_dingtal'
        'k_maintenance;'
    ),
    (
        'GRANT SELECT (id,tenant_id,run_id,state) ON public.agent_tool_calls TO pdos_next_dingt'
        'alk_maintenance;'
    ),
    (
        'GRANT SELECT (tenant_id,run_id,sequence) ON public.agent_run_events TO pdos_next_dingt'
        'alk_maintenance;'
    ),
    (
        'GRANT INSERT ON public.agent_run_events TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT SELECT (id,tenant_id,active,kind) ON public.principals TO pdos_next_dingtalk_mai'
        'ntenance;'
    ),
    (
        'GRANT SELECT (tenant_id,principal_id,active) ON public.tenant_administrators TO pdos_n'
        'ext_dingtalk_maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.kernel_release_call(uuid,uuid,text,boolean,integer,te'
        'xt)\n TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'CREATE POLICY dingtalk_cancel_metadata ON public.agent_runs\n TO pdos_next_dingtalk_ma'
        "intenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WI"
        "TH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);"
    ),
    (
        'CREATE POLICY dingtalk_cancel_event_metadata ON public.agent_run_events\n TO pdos_next'
        "_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'"
        "')::uuid)\n WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::u"
        'uid);'
    ),
    (
        'CREATE POLICY dingtalk_cancel_call_metadata ON public.agent_tool_calls\n FOR SELECT TO'
        " pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_i"
        "d',true),'')::uuid);"
    ),
    (
        'CREATE POLICY dingtalk_principal_metadata ON public.principals\n FOR SELECT TO pdos_ne'
        "xt_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true)"
        ",'')::uuid);"
    ),
    (
        'CREATE POLICY dingtalk_administrator_metadata ON public.tenant_administrators\n FOR SE'
        "LECT TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.t"
        "enant_id',true),'')::uuid);"
    ),
    (
        'CREATE FUNCTION public.dingtalk_admin(t uuid) RETURNS boolean\n LANGUAGE sql STABLE SE'
        'CURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\n SELECT t=NULLIF(curre'
        "nt_setting('pdos.tenant_id',true),'')::uuid AND public.scope_actor()=public.scope_requ"
        'ester()\n AND EXISTS(SELECT 1 FROM public.principals p JOIN public.tenant_administrato'
        'rs a\n ON a.tenant_id=p.tenant_id AND a.principal_id=p.id\n WHERE p.tenant_id=t AND p.'
        "id=public.scope_actor() AND p.active AND p.kind='human' AND a.active)\n$$;"
    ),
    (
        'CREATE FUNCTION public.dingtalk_service(t uuid,app uuid) RETURNS boolean\n LANGUAGE sq'
        'l STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\n SELECT t=N'
        "ULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND public.scope_actor()=public"
        '.scope_requester()\n AND EXISTS(SELECT 1 FROM public.dingtalk_applications a JOIN publ'
        'ic.principals p\n ON p.tenant_id=a.tenant_id AND p.id=a.service_principal_id\n WHERE a'
        ".tenant_id=t AND a.id=app AND p.id=public.scope_actor() AND p.active AND p.kind='agent"
        "')\n$$;"
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_applications TO pdos_next'
        "_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'"
        "')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uui"
        'd);'
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_applications FOR SELECT TO pdos_next_ap'
        "p USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (true))"
        ';'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_applications FOR INSERT TO pdos_next_'
        "app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND "
        '(dingtalk_admin(tenant_id)));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_applications FOR UPDATE TO pdos_next_'
        "app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (ding"
        "talk_admin(tenant_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',"
        "true),'')::uuid AND (dingtalk_admin(tenant_id)));"
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_binding_nonces TO pdos_ne'
        "xt_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true)"
        ",'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::u"
        'uid);'
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_binding_nonces FOR SELECT TO pdos_next_'
        "app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owne"
        'r_id=scope_requester() AND scope_actor()=scope_requester()));'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_binding_nonces FOR INSERT TO pdos_nex'
        "t_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AN"
        'D (owner_id=scope_requester() AND scope_actor()=scope_requester()));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_binding_nonces FOR UPDATE TO pdos_nex'
        "t_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (ow"
        'ner_id=scope_requester() AND scope_actor()=scope_requester())) WITH CHECK (tenant_id=N'
        "ULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester()"
        ' AND scope_actor()=scope_requester()));'
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_account_bindings TO pdos_'
        "next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',tru"
        "e),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),''):"
        ':uuid);'
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_account_bindings FOR SELECT TO pdos_nex'
        "t_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (ow"
        'ner_id=scope_requester() OR dingtalk_admin(tenant_id) OR dingtalk_service(tenant_id,ap'
        'plication_id)));'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_account_bindings FOR INSERT TO pdos_n'
        "ext_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid "
        'AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_admi'
        'n(tenant_id)));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_account_bindings FOR UPDATE TO pdos_n'
        "ext_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ("
        '(owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_admin(ten'
        "ant_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uui"
        'd AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_ad'
        'min(tenant_id)));'
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_messages TO pdos_next_din'
        "gtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::"
        "uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);"
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_messages FOR SELECT TO pdos_next_app US'
        "ING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=s"
        'cope_requester() OR dingtalk_admin(tenant_id) OR dingtalk_service(tenant_id,applicatio'
        'n_id)));'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_messages FOR INSERT TO pdos_next_app '
        "WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((ow"
        'ner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_service(tena'
        'nt_id,application_id)));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_messages FOR UPDATE TO pdos_next_app '
        "USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_i"
        'd=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_service(tenant_id'
        ",application_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true)"
        ",'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR di"
        'ngtalk_service(tenant_id,application_id)));'
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_share_consents TO pdos_ne'
        "xt_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true)"
        ",'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::u"
        'uid);'
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_share_consents FOR SELECT TO pdos_next_'
        "app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owne"
        'r_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tena'
        'nt_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id AN'
        'D dingtalk_service(m.tenant_id,m.application_id))));'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_share_consents FOR INSERT TO pdos_nex'
        "t_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AN"
        'D (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE'
        ' m.tenant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.messag'
        'e_id AND dingtalk_service(m.tenant_id,m.application_id))));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_share_consents FOR UPDATE TO pdos_nex'
        "t_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (ow"
        'ner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.te'
        'nant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id '
        'AND dingtalk_service(m.tenant_id,m.application_id)))) WITH CHECK (tenant_id=NULLIF(cur'
        "rent_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXIST"
        'S(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_share_consents.t'
        'enant_id AND m.id=dingtalk_share_consents.message_id AND dingtalk_service(m.tenant_id,'
        'm.application_id))));'
    ),
    (
        'CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_deliveries TO pdos_next_d'
        "ingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')"
        "::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)"
        ';'
    ),
    (
        'CREATE POLICY dingtalk_read ON public.dingtalk_deliveries FOR SELECT TO pdos_next_app '
        "USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id"
        '=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_i'
        'd=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk_s'
        'ervice(m.tenant_id,m.application_id))));'
    ),
    (
        'CREATE POLICY dingtalk_insert ON public.dingtalk_deliveries FOR INSERT TO pdos_next_ap'
        "p WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (o"
        'wner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.t'
        'enant_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND din'
        'gtalk_service(m.tenant_id,m.application_id))));'
    ),
    (
        'CREATE POLICY dingtalk_update ON public.dingtalk_deliveries FOR UPDATE TO pdos_next_ap'
        "p USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_"
        'id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant'
        '_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk'
        '_service(m.tenant_id,m.application_id)))) WITH CHECK (tenant_id=NULLIF(current_setting'
        "('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 F"
        'ROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_deliveries.tenant_id AND m.i'
        'd=dingtalk_deliveries.message_id AND dingtalk_service(m.tenant_id,m.application_id))))'
        ';'
    ),
    (
        'CREATE FUNCTION public.dingtalk_callback_application(app uuid)\n RETURNS TABLE(tenant_'
        'id uuid, service_principal_id uuid)\n LANGUAGE plpgsql SECURITY DEFINER SET search_pat'
        'h=pg_catalog,public,pg_temp AS $$\nDECLARE app_tenant uuid; service_id uuid; previous_'
        "tenant text; previous_app text;\nBEGIN\n previous_tenant=current_setting('pdos.tenant_"
        "id',true);\n previous_app=current_setting('pdos.dingtalk_application',true);\n PERFORM"
        " set_config('pdos.dingtalk_application',app::text,true);\n SELECT a.tenant_id,a.servic"
        'e_principal_id INTO app_tenant,service_id\n FROM public.dingtalk_applications a WHERE '
        "a.id=app AND a.active;\n PERFORM set_config('pdos.tenant_id',COALESCE(app_tenant::text"
        ",''),true);\n IF EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=app_tenant"
        "\n AND p.id=service_id AND p.active AND p.kind='agent') THEN\n  RETURN QUERY SELECT ap"
        "p_tenant,service_id;\n END IF;\n PERFORM set_config('pdos.tenant_id',COALESCE(previous"
        "_tenant,''),true);\n PERFORM set_config('pdos.dingtalk_application',COALESCE(previous_"
        "app,''),true);\nEND $$;"
    ),
    (
        '-- Auth has no tenant scope before signature verification. Only this exact\n-- UUID lo'
        'cator uses a separate role-specific policy; no app KMS ref is returned.\nCREATE POLICY'
        ' dingtalk_callback_locator ON public.dingtalk_applications FOR SELECT\n TO pdos_next_d'
        "ingtalk_maintenance USING (id=NULLIF(current_setting('pdos.dingtalk_application',true)"
        ",'')::uuid);"
    ),
    (
        'CREATE FUNCTION public.dingtalk_message_service(t uuid,mid uuid) RETURNS uuid\n LANGUA'
        'GE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\n SELEC'
        'T a.service_principal_id FROM public.dingtalk_messages m\n JOIN public.dingtalk_applic'
        'ations a ON a.tenant_id=m.tenant_id AND a.id=m.application_id\n WHERE t=NULLIF(current'
        "_setting('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND m.id=mid\n$$;"
    ),
    (
        'CREATE FUNCTION public.dingtalk_pending_references(t uuid, maximum integer)\n RETURNS '
        'TABLE(message_id uuid,run_id uuid,owner_id uuid,consent_id uuid)\n LANGUAGE sql STABLE'
        ' SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\n SELECT m.id,m.run_'
        'id,m.owner_id,NULL::uuid FROM public.dingtalk_messages m\n WHERE t=NULLIF(current_sett'
        "ing('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND m.state='pending'\n UNION A"
        'LL\n SELECT m.id,m.run_id,m.owner_id,c.id FROM public.dingtalk_share_consents c\n JOIN'
        ' public.dingtalk_messages m ON m.tenant_id=c.tenant_id AND m.id=c.message_id\n WHERE t'
        "=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND c.state"
        "='confirmed' AND NOT EXISTS(\n  SELECT 1 FROM public.dingtalk_deliveries d WHERE d.ten"
        'ant_id=t AND d.consent_id=c.id)\n LIMIT GREATEST(0,LEAST(maximum,100))\n$$;'
    ),
    (
        'CREATE FUNCTION public.dingtalk_cancel_lost_run(t uuid,mid uuid) RETURNS uuid\n LANGUA'
        'GE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\nDECLARE m'
        ' record; b record; a record; r record; call_id uuid; old_actor text; old_requester tex'
        "t;\nBEGIN\n IF t IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::u"
        'uid THEN RETURN NULL; END IF;\n SELECT id,tenant_id,application_id,binding_id,binding_'
        'epoch,owner_id,run_id INTO m\n FROM public.dingtalk_messages WHERE tenant_id=t AND id='
        'mid FOR UPDATE;\n IF NOT FOUND THEN RETURN NULL; END IF;\n SELECT active,epoch,owner_i'
        'd,application_id INTO b FROM public.dingtalk_account_bindings\n WHERE tenant_id=t AND '
        'id=m.binding_id;\n SELECT active,service_principal_id INTO a FROM public.dingtalk_appl'
        'ications WHERE tenant_id=t AND id=m.application_id;\n IF a.active AND b.active AND b.e'
        'poch=m.binding_epoch AND b.owner_id=m.owner_id\n AND b.application_id=m.application_id'
        ' AND EXISTS(SELECT 1 FROM public.principals writer\n WHERE writer.tenant_id=t AND writ'
        "er.id=a.service_principal_id AND writer.active AND writer.kind='agent')\n AND EXISTS(S"
        'ELECT 1 FROM public.principals p\n WHERE p.tenant_id=t AND p.id=m.owner_id AND p.activ'
        "e AND p.kind='human') THEN RETURN NULL; END IF;\n SELECT id,tenant_id,requester_id,wri"
        'ter_id,category_id,state,cancel_epoch,reverted_at INTO r\n FROM public.agent_runs WHER'
        'E tenant_id=t AND id=m.run_id FOR UPDATE;\n IF NOT FOUND OR r.requester_id IS DISTINCT'
        " FROM m.owner_id OR r.category_id IS NOT NULL THEN\n  RAISE EXCEPTION 'channel run bin"
        "ding mismatch' USING ERRCODE='23514'; END IF;\n UPDATE public.dingtalk_messages SET st"
        "ate='cancelled' WHERE tenant_id=t AND id=mid;\n UPDATE public.dingtalk_deliveries SET "
        "state='cancelled',error_code='CANCELLED_RUN'\n WHERE tenant_id=t AND message_id=mid AN"
        "D state='planned';\n IF r.reverted_at IS NOT NULL OR r.state IN ('completed','partial'"
        ",'failed','cancelled') THEN RETURN r.id; END IF;\n old_actor=current_setting('pdos.act"
        "or_id',true); old_requester=current_setting('pdos.requester_id',true);\n -- Native tec"
        'hnical release checks this exact persisted writer/requester and\n -- charges any unkno'
        "wn reservation; no Human command or business source READ.\n PERFORM set_config('pdos.a"
        "ctor_id',r.writer_id::text,true);\n PERFORM set_config('pdos.requester_id',r.requester"
        '_id::text,true);\n FOR call_id IN SELECT id FROM public.agent_tool_calls WHERE tenant_'
        "id=t AND run_id=r.id AND state='started' LOOP\n  PERFORM public.kernel_release_call(r."
        "id,call_id,'CANCELLED_RUN',true,0,NULL);\n END LOOP;\n PERFORM set_config('pdos.actor_"
        "id',COALESCE(old_actor,''),true);\n PERFORM set_config('pdos.requester_id',COALESCE(ol"
        "d_requester,''),true);\n UPDATE public.agent_runs SET state='cancelled',error_code='CA"
        "NCELLED_RUN',cancel_epoch=cancel_epoch+1\n WHERE tenant_id=t AND id=r.id;\n INSERT INT"
        'O public.agent_run_events(id,tenant_id,created_at,run_id,sequence,body)\n SELECT gen_r'
        'andom_uuid(),t,clock_timestamp(),r.id,COALESCE(max(sequence),0)+1,\n  \'{"type":"run_s'
        'tate","status":"cancelled","error_code":"CANCELLED_RUN"}\'::jsonb\n FROM public.agent_'
        'run_events WHERE tenant_id=t AND run_id=r.id;\n RETURN r.id;\nEND $$;'
    ),
    (
        'ALTER FUNCTION public.dingtalk_admin(uuid) OWNER TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_admin(uuid) TO pdos_next_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_admin(uuid) FROM PUBLIC,pdos_agent,pdos_next_ap'
        'p,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_admin(uuid) TO pdos_next_app;'
    ),
    (
        'ALTER FUNCTION public.dingtalk_service(uuid,uuid) OWNER TO pdos_next_dingtalk_maintena'
        'nce;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_service(uuid,uuid) TO pdos_next_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_service(uuid,uuid) FROM PUBLIC,pdos_agent,pdos_'
        'next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_service(uuid,uuid) TO pdos_next_app;'
    ),
    (
        'ALTER FUNCTION public.dingtalk_callback_application(uuid) OWNER TO pdos_next_dingtalk_'
        'maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_callback_application(uuid) TO pdos_next_owne'
        'r;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_callback_application(uuid) FROM PUBLIC,pdos_age'
        'nt,pdos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_callback_application(uuid) TO pdos_next_auth'
        ';'
    ),
    (
        'ALTER FUNCTION public.dingtalk_message_service(uuid,uuid) OWNER TO pdos_next_dingtalk_'
        'maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_message_service(uuid,uuid) TO pdos_next_owne'
        'r;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_message_service(uuid,uuid) FROM PUBLIC,pdos_age'
        'nt,pdos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_message_service(uuid,uuid) TO pdos_next_auth'
        ',pdos_next_dispatch;'
    ),
    (
        'ALTER FUNCTION public.dingtalk_pending_references(uuid,integer) OWNER TO pdos_next_din'
        'gtalk_maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_pending_references(uuid,integer) TO pdos_nex'
        't_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_pending_references(uuid,integer) FROM PUBLIC,pd'
        'os_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_pending_references(uuid,integer) TO pdos_nex'
        't_dispatch;'
    ),
    (
        'ALTER FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) OWNER TO pdos_next_dingtalk_'
        'maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) TO pdos_next_owne'
        'r;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) FROM PUBLIC,pdos_age'
        'nt,pdos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) TO pdos_next_disp'
        'atch;'
    ),
    (
        '-- Immutable verified binding/Run edges. These controls never inspect source text.\nCR'
        'EATE FUNCTION public.dingtalk_control_guard() RETURNS trigger\n LANGUAGE plpgsql SECUR'
        'ITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\nDECLARE a record; n recor'
        'd; b record; m record; r record;\nBEGIN\n IF NEW.tenant_id IS DISTINCT FROM NULLIF(cur'
        "rent_setting('pdos.tenant_id',true),'')::uuid\n THEN RAISE EXCEPTION 'channel tenant m"
        "ismatch' USING ERRCODE='23514'; END IF;\n IF TG_TABLE_NAME='dingtalk_applications' THE"
        'N\n  IF NOT public.dingtalk_admin(NEW.tenant_id) OR NOT EXISTS(SELECT 1 FROM public.pr'
        'incipals p\n   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.service_principal_id AND p'
        ".kind='agent' AND p.active)\n  THEN RAISE EXCEPTION 'named administrator and existing "
        "agent required' USING ERRCODE='23514'; END IF;\n  IF TG_OP='UPDATE' AND (NEW.id<>OLD.i"
        'd OR NEW.tenant_id<>OLD.tenant_id OR NEW.created_at<>OLD.created_at\n   OR NEW.service'
        '_principal_id<>OLD.service_principal_id OR NEW.revision<>OLD.revision+1)\n  THEN RAISE'
        " EXCEPTION 'application identity immutable' USING ERRCODE='23514'; END IF;\n ELSIF TG_"
        "TABLE_NAME='dingtalk_binding_nonces' THEN\n  IF NEW.owner_id IS DISTINCT FROM public.s"
        'cope_actor() OR public.scope_actor()<>public.scope_requester()\n   OR NOT EXISTS(SELEC'
        'T 1 FROM public.principals p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.owner_id AND'
        " p.kind='human' AND p.active)\n  THEN RAISE EXCEPTION 'nonce must belong to actual hum"
        "an' USING ERRCODE='23514'; END IF;\n  IF TG_OP='INSERT' THEN\n   SELECT revision,activ"
        'e INTO a FROM public.dingtalk_applications WHERE tenant_id=NEW.tenant_id AND id=NEW.ap'
        'plication_id;\n   IF a.active IS DISTINCT FROM true OR a.revision IS DISTINCT FROM NEW'
        '.app_revision\n    OR NEW.consumed_at IS NOT NULL OR NEW.expires_at>NEW.created_at+int'
        "erval '5 minutes'\n    OR NEW.expires_at<=clock_timestamp() THEN\n    RAISE EXCEPTION "
        "'nonce must use current app and short expiry' USING ERRCODE='23514'; END IF;\n  END IF"
        ";\n  IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'consumed_at'<>to_jsonb(OLD)-'consumed_at'\n"
        '   OR OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL OR NEW.expires_at<=NEW.co'
        "nsumed_at)\n  THEN RAISE EXCEPTION 'nonce may only be consumed once' USING ERRCODE='23"
        "514'; END IF;\n ELSIF TG_TABLE_NAME='dingtalk_account_bindings' THEN\n  IF TG_OP='INSE"
        "RT' THEN\n   SELECT application_id,owner_id,app_revision,state_sha256,expires_at,consu"
        'med_at INTO n\n    FROM public.dingtalk_binding_nonces WHERE tenant_id=NEW.tenant_id A'
        'ND id=NEW.verified_nonce_id;\n   SELECT id,revision,active INTO a FROM public.dingtalk'
        '_applications WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;\n   IF n.applic'
        'ation_id IS DISTINCT FROM NEW.application_id OR n.owner_id IS DISTINCT FROM NEW.owner_'
        'id\n    OR n.consumed_at IS NULL OR n.expires_at<=clock_timestamp() OR n.app_revision '
        'IS DISTINCT FROM a.revision\n    OR a.active IS DISTINCT FROM true OR NEW.owner_id IS '
        'DISTINCT FROM public.scope_actor()\n    OR public.scope_actor()<>public.scope_requeste'
        "r() OR NOT NEW.active OR NEW.epoch<>1\n   THEN RAISE EXCEPTION 'verified self nonce re"
        "quired' USING ERRCODE='23514'; END IF;\n  ELSIF to_jsonb(NEW)-ARRAY['active','epoch','"
        "revoked_by','revoke_key','revoke_reason']\n   <>to_jsonb(OLD)-ARRAY['active','epoch','"
        "revoked_by','revoke_key','revoke_reason']\n   OR NOT OLD.active OR NEW.active OR NEW.e"
        'poch<>OLD.epoch+1\n   OR NEW.revoked_by IS DISTINCT FROM public.scope_actor()\n   OR N'
        'OT(NEW.owner_id=public.scope_actor() OR public.dingtalk_admin(NEW.tenant_id)) THEN\n  '
        " RAISE EXCEPTION 'binding only supports named revoke' USING ERRCODE='23514';\n  END IF"
        ";\n ELSIF TG_TABLE_NAME='dingtalk_messages' THEN\n  IF TG_OP='INSERT' THEN\n   SELECT "
        'active,epoch,owner_id,application_id INTO b FROM public.dingtalk_account_bindings\n   '
        ' WHERE tenant_id=NEW.tenant_id AND id=NEW.binding_id;\n   SELECT service_principal_id,'
        'active INTO a FROM public.dingtalk_applications\n    WHERE tenant_id=NEW.tenant_id AND'
        ' id=NEW.application_id;\n   SELECT requester_id,writer_id,category_id,state INTO r FRO'
        'M public.agent_runs\n    WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;\n   IF b.act'
        'ive IS DISTINCT FROM true OR a.active IS DISTINCT FROM true\n    OR b.epoch IS DISTINC'
        'T FROM NEW.binding_epoch OR b.owner_id IS DISTINCT FROM NEW.owner_id\n    OR b.applica'
        'tion_id IS DISTINCT FROM NEW.application_id OR r.requester_id IS DISTINCT FROM NEW.own'
        'er_id\n    OR r.writer_id IS DISTINCT FROM a.service_principal_id OR r.category_id IS '
        "NOT NULL OR r.state<>'queued'\n    OR EXISTS(SELECT 1 FROM public.agent_tool_calls c W"
        'HERE c.tenant_id=NEW.tenant_id AND c.run_id=NEW.run_id)\n    OR NEW.owner_id IS DISTIN'
        'CT FROM public.scope_actor() OR public.scope_actor()<>public.scope_requester()\n   THE'
        "N RAISE EXCEPTION 'message requires fresh actual bound personal run' USING ERRCODE='23"
        "514'; END IF;\n  ELSIF session_user<>'pdos_next_dispatch' AND NOT public.dingtalk_serv"
        "ice(NEW.tenant_id,NEW.application_id) THEN\n   RAISE EXCEPTION 'actual channel dispatc"
        "her required' USING ERRCODE='23514';\n  ELSIF to_jsonb(NEW)-ARRAY['state','error_code'"
        ",'lease_id','lease_until','workflow_id']\n   <>to_jsonb(OLD)-ARRAY['state','error_code"
        "','lease_id','lease_until','workflow_id'] THEN\n   RAISE EXCEPTION 'channel run identi"
        "ty immutable' USING ERRCODE='23514';\n  END IF;\n ELSIF TG_TABLE_NAME='dingtalk_share_"
        "consents' THEN\n  SELECT owner_id,conversation_kind,application_id INTO m FROM public."
        "dingtalk_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.message_id;\n  IF TG_OP='UP"
        "DATE' THEN\n   IF session_user<>'pdos_next_dispatch' AND NOT public.dingtalk_service(N"
        "EW.tenant_id,m.application_id) THEN\n    RAISE EXCEPTION 'only actual channel dispatch"
        "er may update delivery state' USING ERRCODE='23514'; END IF;\n   IF to_jsonb(NEW)-ARRA"
        "Y['state','error_code']<>to_jsonb(OLD)-ARRAY['state','error_code'] THEN\n    RAISE EXC"
        "EPTION 'share consent identity immutable' USING ERRCODE='23514'; END IF;\n   RETURN NE"
        "W;\n  END IF;\n  IF m.owner_id IS DISTINCT FROM NEW.owner_id OR m.conversation_kind<>'"
        "group'\n   OR NEW.owner_id IS DISTINCT FROM public.scope_actor() OR public.scope_actor"
        "()<>public.scope_requester()\n  THEN RAISE EXCEPTION 'explicit own group confirmation "
        "required' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME='dingtalk_deliveries' T"
        'HEN\n  SELECT owner_id,application_id INTO m FROM public.dingtalk_messages WHERE tenan'
        "t_id=NEW.tenant_id AND id=NEW.message_id;\n  IF session_user<>'pdos_next_dispatch' AND"
        ' NOT public.dingtalk_service(NEW.tenant_id,m.application_id)\n   THEN RAISE EXCEPTION '
        "'actual service delivery required' USING ERRCODE='23514'; END IF;\n  IF NEW.owner_id I"
        "S DISTINCT FROM m.owner_id THEN RAISE EXCEPTION 'delivery owner mismatch' USING ERRCOD"
        "E='23514'; END IF;\n  IF NEW.content_kind NOT IN ('control','answer','local_link') OR "
        "jsonb_typeof(NEW.source_dependencies) IS DISTINCT FROM 'array'\n   OR ((NEW.content_ki"
        "nd='answer') IS DISTINCT FROM (jsonb_array_length(NEW.source_dependencies)>0))\n  THEN"
        " RAISE EXCEPTION 'outbound copy requires fixed source identities' USING ERRCODE='23514"
        "'; END IF;\n  -- source_dependencies/content_kind join payload in the immutable compar"
        'ison below.\n  -- Full typed Artifact closure is the shared F/root retention guard, ne'
        "ver a permission grant.\n\n  IF TG_OP='UPDATE' AND to_jsonb(NEW)-ARRAY['state','p26','"
        "provider_receipt','error_code','attempts','attempt_id','send_started_at']\n   <>to_jso"
        "nb(OLD)-ARRAY['state','p26','provider_receipt','error_code','attempts','attempt_id','s"
        "end_started_at']\n   THEN RAISE EXCEPTION 'delivery payload and consent immutable' USI"
        "NG ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND $$;"
    ),
    (
        'ALTER FUNCTION public.dingtalk_control_guard() OWNER TO pdos_next_dingtalk_maintenance'
        ';'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_control_guard() TO pdos_next_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_control_guard() FROM PUBLIC,pdos_agent,pdos_nex'
        't_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_application'
        's FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_binding_non'
        'ces FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_account_bin'
        'dings FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_messages FO'
        'R EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_share_conse'
        'nts FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_deliveries '
        'FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'GRANT UPDATE (state,error_code) ON public.dingtalk_share_consents TO pdos_next_dingtal'
        'k_maintenance;'
    ),
    (
        'CREATE FUNCTION public.dingtalk_mark_dispatched(t uuid,mid uuid,cid uuid) RETURNS void'
        '\n LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\n'
        "BEGIN\n IF t IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::uuid"
        "\n THEN RAISE EXCEPTION 'channel dispatch tenant mismatch' USING ERRCODE='23514'; END "
        "IF;\n IF cid IS NULL THEN\n  UPDATE public.dingtalk_messages SET state='admitted' WHER"
        "E tenant_id=t AND id=mid AND state='pending';\n ELSE\n  UPDATE public.dingtalk_share_c"
        "onsents SET state='dispatched'\n   WHERE tenant_id=t AND id=cid AND message_id=mid AND"
        " state='confirmed';\n END IF;\nEND $$;"
    ),
    (
        'ALTER FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) OWNER TO pdos_next_ding'
        'talk_maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) TO pdos_next'
        '_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid)\n FROM PUBLIC,p'
        'dos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) TO pdos_next'
        '_dispatch;'
    ),
    (
        'CREATE FUNCTION public.dingtalk_run_identity_guard() RETURNS trigger\n LANGUAGE plpgsq'
        'l SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\nBEGIN\n IF EXISTS('
        'SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=NEW.tenant_id AND m.run_id='
        'NEW.id)\n AND (NEW.versions->\'dingtalk\' IS DISTINCT FROM \'{"version":1}\'::jsonb OR'
        " NEW.category_id IS NOT NULL)\n THEN RAISE EXCEPTION 'channel run marker immutable' US"
        "ING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;"
    ),
    (
        'ALTER FUNCTION public.dingtalk_run_identity_guard() OWNER TO pdos_next_dingtalk_mainte'
        'nance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_run_identity_guard() TO pdos_next_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_run_identity_guard()\n FROM PUBLIC,pdos_agent,p'
        'dos_next_app,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'CREATE TRIGGER dingtalk_run_identity BEFORE UPDATE ON public.agent_runs FOR EACH ROW\n'
        " WHEN (OLD.versions ? 'dingtalk' OR NEW.versions ? 'dingtalk')\n EXECUTE FUNCTION publ"
        'ic.dingtalk_run_identity_guard();'
    ),
    (
        'REVOKE CREATE ON SCHEMA public FROM pdos_next_dingtalk_maintenance;'
    ),
)

TRANSFER_TABLES_SQL = (
    (
        'ALTER TABLE public.dingtalk_applications OWNER TO pdos_next_owner;'
    ),
    (
        'ALTER TABLE public.dingtalk_binding_nonces OWNER TO pdos_next_owner;'
    ),
    (
        'ALTER TABLE public.dingtalk_account_bindings OWNER TO pdos_next_owner;'
    ),
    (
        'ALTER TABLE public.dingtalk_messages OWNER TO pdos_next_owner;'
    ),
    (
        'ALTER TABLE public.dingtalk_share_consents OWNER TO pdos_next_owner;'
    ),
    (
        'ALTER TABLE public.dingtalk_deliveries OWNER TO pdos_next_owner;'
    ),
)

EMPTY_HISTORY_SQL = (
    (
        'LOCK TABLE public.dingtalk_account_bindings,public.dingtalk_applications,public.dingta'
        'lk_binding_nonces,public.dingtalk_deliveries,public.dingtalk_messages,public.dingtalk_'
        'share_consents IN ACCESS EXCLUSIVE MODE;'
    ),
    (
        'DO $$ BEGIN\n IF EXISTS(SELECT 1 FROM public.dingtalk_applications) OR EXISTS(SELECT 1'
        ' FROM public.dingtalk_binding_nonces) OR EXISTS(SELECT 1 FROM public.dingtalk_account_'
        'bindings) OR EXISTS(SELECT 1 FROM public.dingtalk_messages) OR EXISTS(SELECT 1 FROM pu'
        'blic.dingtalk_share_consents) OR EXISTS(SELECT 1 FROM public.dingtalk_deliveries) THEN'
        "\n  RAISE EXCEPTION 'G history must be retained; nonempty channel tables cannot be dow"
        "ngraded';\n END IF;\nEND $$;"
    ),
)

BASE_DOWN_SQL = (
    (
        '-- Exact UNNUMBERED draft rollback; preserves all pre-existing roles/policies/FORCE RL'
        'S.\nDROP TRIGGER dingtalk_run_identity ON public.agent_runs;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_deliveries;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_deliveries;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_deliveries;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_deliveries;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_deliveries;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_share_consents;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_share_consents;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_share_consents;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_share_consents;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_share_consents;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_messages;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_messages;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_messages;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_messages;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_messages;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_account_bindings;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_account_bindings;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_account_bindings;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_account_bindings;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_account_bindings;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_binding_nonces;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_binding_nonces;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_binding_nonces;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_binding_nonces;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_binding_nonces;'
    ),
    (
        'DROP TRIGGER dingtalk_control ON public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_read ON public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_insert ON public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_update ON public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_maintenance_tenant ON public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_callback_locator ON public.dingtalk_applications;'
    ),
    (
        'DROP FUNCTION public.dingtalk_run_identity_guard();'
    ),
    (
        'DROP FUNCTION public.dingtalk_control_guard();'
    ),
    (
        'DROP FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid);'
    ),
    (
        'DROP FUNCTION public.dingtalk_pending_references(uuid,integer);'
    ),
    (
        'DROP FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid);'
    ),
    (
        'DROP FUNCTION public.dingtalk_message_service(uuid,uuid);'
    ),
    (
        'DROP FUNCTION public.dingtalk_callback_application(uuid);'
    ),
    (
        'DROP FUNCTION public.dingtalk_service(uuid,uuid);'
    ),
    (
        'DROP FUNCTION public.dingtalk_admin(uuid);'
    ),
    (
        'DROP TABLE public.dingtalk_deliveries;'
    ),
    (
        'DROP TABLE public.dingtalk_share_consents;'
    ),
    (
        'DROP TABLE public.dingtalk_messages;'
    ),
    (
        'DROP TABLE public.dingtalk_account_bindings;'
    ),
    (
        'DROP TABLE public.dingtalk_binding_nonces;'
    ),
    (
        'DROP TABLE public.dingtalk_applications;'
    ),
    (
        'DROP POLICY dingtalk_cancel_metadata ON public.agent_runs;'
    ),
    (
        'REVOKE ALL ON public.agent_runs FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'DROP POLICY dingtalk_cancel_call_metadata ON public.agent_tool_calls;'
    ),
    (
        'REVOKE ALL ON public.agent_tool_calls FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'DROP POLICY dingtalk_cancel_event_metadata ON public.agent_run_events;'
    ),
    (
        'REVOKE ALL ON public.agent_run_events FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'DROP POLICY dingtalk_principal_metadata ON public.principals;'
    ),
    (
        'REVOKE ALL ON public.principals FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'DROP POLICY dingtalk_administrator_metadata ON public.tenant_administrators;'
    ),
    (
        'REVOKE ALL ON public.tenant_administrators FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'REVOKE EXECUTE ON FUNCTION public.kernel_release_call(uuid,uuid,text,boolean,integer,t'
        'ext) FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'REVOKE ALL ON SCHEMA public FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'REVOKE EXECUTE ON FUNCTION public.scope_actor(),public.scope_requester(),\n public.cat'
        'egory_access(uuid,uuid,boolean) FROM pdos_next_dingtalk_maintenance;'
    ),
    (
        'REVOKE SELECT(id,tenant_id,requester_id,writer_id,category_id,state,cancel_epoch,rever'
        'ted_at),\n UPDATE(state,error_code,cancel_epoch) ON public.agent_runs FROM pdos_next_d'
        'ingtalk_maintenance;'
    ),
    (
        'REVOKE SELECT(id,tenant_id,run_id,state) ON public.agent_tool_calls FROM pdos_next_din'
        'gtalk_maintenance;'
    ),
    (
        'REVOKE SELECT(tenant_id,run_id,sequence) ON public.agent_run_events FROM pdos_next_din'
        'gtalk_maintenance;'
    ),
    (
        'REVOKE SELECT(id,tenant_id,active,kind) ON public.principals FROM pdos_next_dingtalk_m'
        'aintenance;'
    ),
    (
        'REVOKE SELECT(tenant_id,principal_id,active) ON public.tenant_administrators FROM pdos'
        '_next_dingtalk_maintenance;'
    ),
    (
        'DROP ROLE pdos_next_dingtalk_maintenance;'
    ),
)
