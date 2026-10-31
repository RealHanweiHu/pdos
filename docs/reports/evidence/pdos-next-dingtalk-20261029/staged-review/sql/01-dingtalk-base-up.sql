-- UNNUMBERED REVIEW DRAFT. Do not apply until root reviews actual head and role grants.
-- No business source SELECT, broad RLS disable, runtime role membership or credentials.
CREATE ROLE pdos_next_dingtalk_maintenance NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;






CREATE TABLE dingtalk_applications (
	administrator_id UUID NOT NULL, 
	service_principal_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	corp_id VARCHAR(160) NOT NULL, 
	client_id VARCHAR(160) NOT NULL, 
	robot_code VARCHAR(160) NOT NULL, 
	secret_arn TEXT NOT NULL, 
	secret_version VARCHAR(160) NOT NULL, 
	active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (tenant_id), 
	FOREIGN KEY(tenant_id, administrator_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, service_principal_id) REFERENCES principals (tenant_id, id), 
	CHECK (revision>0 AND length(corp_id)>0 AND length(secret_version)>0), 
	UNIQUE (corp_id)
)

;

CREATE INDEX ix_dingtalk_applications_tenant_id ON dingtalk_applications (tenant_id);

ALTER TABLE public.dingtalk_applications ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_applications FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_applications FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_applications TO pdos_next_app;


CREATE TABLE dingtalk_binding_nonces (
	application_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	app_revision INTEGER NOT NULL, 
	state_sha256 VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (state_sha256), 
	FOREIGN KEY(tenant_id, application_id) REFERENCES dingtalk_applications (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (app_revision>0 AND length(state_sha256)=64)
)

;

CREATE INDEX ix_dingtalk_binding_nonces_tenant_id ON dingtalk_binding_nonces (tenant_id);

ALTER TABLE public.dingtalk_binding_nonces ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_binding_nonces FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_binding_nonces FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_binding_nonces TO pdos_next_app;


CREATE TABLE dingtalk_account_bindings (
	application_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	external_user_id VARCHAR(200) NOT NULL, 
	verified_nonce_id UUID NOT NULL, 
	active BOOLEAN NOT NULL, 
	epoch INTEGER NOT NULL, 
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_by UUID, 
	revoke_key UUID, 
	revoke_reason TEXT, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	FOREIGN KEY(tenant_id, application_id) REFERENCES dingtalk_applications (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, revoked_by) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, verified_nonce_id) REFERENCES dingtalk_binding_nonces (tenant_id, id), 
	UNIQUE (tenant_id, verified_nonce_id), 
	CHECK (epoch>0 AND length(external_user_id)>0), 
	CHECK ((active AND revoked_by IS NULL AND revoke_key IS NULL) OR (NOT active AND revoked_by IS NOT NULL AND revoke_key IS NOT NULL))
)

;

CREATE UNIQUE INDEX dingtalk_one_active_account ON dingtalk_account_bindings (tenant_id, owner_id) WHERE active IS true;

CREATE UNIQUE INDEX dingtalk_one_active_external ON dingtalk_account_bindings (application_id, external_user_id) WHERE active IS true;

CREATE INDEX ix_dingtalk_account_bindings_tenant_id ON dingtalk_account_bindings (tenant_id);

ALTER TABLE public.dingtalk_account_bindings ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_account_bindings FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_account_bindings FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_account_bindings TO pdos_next_app;


CREATE TABLE dingtalk_messages (
	application_id UUID NOT NULL, 
	binding_id UUID NOT NULL, 
	binding_epoch INTEGER NOT NULL, 
	owner_id UUID NOT NULL, 
	external_message_id VARCHAR(200) NOT NULL, 
	envelope_sha256 VARCHAR(64) NOT NULL, 
	conversation_kind VARCHAR(16) NOT NULL, 
	conversation_id VARCHAR(200) NOT NULL, 
	run_id UUID NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	error_code VARCHAR(80), 
	lease_id UUID, 
	lease_until TIMESTAMP WITH TIME ZONE, 
	workflow_id VARCHAR(240), 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (application_id, external_message_id), 
	UNIQUE (tenant_id, run_id), 
	FOREIGN KEY(tenant_id, application_id) REFERENCES dingtalk_applications (tenant_id, id), 
	FOREIGN KEY(tenant_id, binding_id) REFERENCES dingtalk_account_bindings (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), 
	CHECK (binding_epoch>0 AND length(envelope_sha256)=64), 
	CHECK (conversation_kind IN ('direct','group')), 
	CHECK (state IN ('pending','admitted','completed','cancelled','unknown','blocked'))
)

;

CREATE INDEX ix_dingtalk_messages_tenant_id ON dingtalk_messages (tenant_id);

ALTER TABLE public.dingtalk_messages ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_messages FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_messages FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_messages TO pdos_next_app;


CREATE TABLE dingtalk_share_consents (
	message_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	request_key UUID NOT NULL, 
	payload_sha256 VARCHAR(64) NOT NULL, 
	include_citations BOOLEAN NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	error_code VARCHAR(80), 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (tenant_id, owner_id, request_key), 
	FOREIGN KEY(tenant_id, message_id) REFERENCES dingtalk_messages (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (length(payload_sha256)=64), 
	CHECK (state IN ('confirmed','dispatched','blocked','delivered','unknown','cancelled'))
)

;

CREATE INDEX ix_dingtalk_share_consents_tenant_id ON dingtalk_share_consents (tenant_id);

ALTER TABLE public.dingtalk_share_consents ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_share_consents FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_share_consents FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_share_consents TO pdos_next_app;


CREATE TABLE dingtalk_deliveries (
	message_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	consent_id UUID, 
	request_key UUID NOT NULL, 
	phase VARCHAR(24) NOT NULL, 
	payload JSONB NOT NULL, 
	payload_sha256 VARCHAR(64) NOT NULL, 
	content_kind VARCHAR(24) NOT NULL, 
	source_dependencies JSONB NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	p26 JSONB, 
	provider_receipt JSONB, 
	error_code VARCHAR(80), 
	attempts INTEGER NOT NULL, 
	attempt_id UUID, 
	send_started_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (tenant_id, request_key), 
	FOREIGN KEY(tenant_id, message_id) REFERENCES dingtalk_messages (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, consent_id) REFERENCES dingtalk_share_consents (tenant_id, id), 
	CHECK (phase IN ('received','answer','group_notice','share')), 
	CHECK (state IN ('planned','sending','delivered','unknown','blocked','cancelled')), 
	CHECK (attempts>=0 AND length(payload_sha256)=64), 
	CHECK (content_kind IN ('control','answer','local_link')), 
	CHECK (CASE WHEN jsonb_typeof(source_dependencies)='array' THEN (content_kind='answer')=(jsonb_array_length(source_dependencies)>0) ELSE false END), 
	CHECK ((phase='share' AND consent_id IS NOT NULL) OR (phase<>'share' AND consent_id IS NULL)), 
	CHECK (state NOT IN ('sending','delivered','unknown') OR p26 IS NOT NULL)
)

;

CREATE INDEX ix_dingtalk_deliveries_tenant_id ON dingtalk_deliveries (tenant_id);

ALTER TABLE public.dingtalk_deliveries ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.dingtalk_deliveries FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.dingtalk_deliveries FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT SELECT,INSERT,UPDATE ON public.dingtalk_deliveries TO pdos_next_app;

-- NOLOGIN role reads only exact channel metadata. Delivery payload and business
-- goal/result/text/source refs are deliberately absent from its SELECT grants.
GRANT USAGE,CREATE ON SCHEMA public TO pdos_next_dingtalk_maintenance;
-- Existing PUBLIC kernel RLS expressions may invoke these ordinary predicates.
GRANT EXECUTE ON FUNCTION public.scope_actor(),public.scope_requester(),
 public.category_access(uuid,uuid,boolean) TO pdos_next_dingtalk_maintenance;
GRANT SELECT ON public.dingtalk_applications,public.dingtalk_account_bindings,
 public.dingtalk_binding_nonces,public.dingtalk_messages,public.dingtalk_share_consents
 TO pdos_next_dingtalk_maintenance;
GRANT SELECT (id,tenant_id,message_id,owner_id,consent_id,request_key,phase,state,error_code,content_kind,source_dependencies)
 ON public.dingtalk_deliveries TO pdos_next_dingtalk_maintenance;
GRANT UPDATE (state,error_code) ON public.dingtalk_deliveries TO pdos_next_dingtalk_maintenance;
GRANT UPDATE (state) ON public.dingtalk_messages TO pdos_next_dingtalk_maintenance;
GRANT SELECT (id,tenant_id,requester_id,writer_id,category_id,state,cancel_epoch,reverted_at)
 ON public.agent_runs TO pdos_next_dingtalk_maintenance;
GRANT UPDATE (state,error_code,cancel_epoch) ON public.agent_runs TO pdos_next_dingtalk_maintenance;
GRANT SELECT (id,tenant_id,run_id,state) ON public.agent_tool_calls TO pdos_next_dingtalk_maintenance;
GRANT SELECT (tenant_id,run_id,sequence) ON public.agent_run_events TO pdos_next_dingtalk_maintenance;
GRANT INSERT ON public.agent_run_events TO pdos_next_dingtalk_maintenance;
GRANT SELECT (id,tenant_id,active,kind) ON public.principals TO pdos_next_dingtalk_maintenance;
GRANT SELECT (tenant_id,principal_id,active) ON public.tenant_administrators TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.kernel_release_call(uuid,uuid,text,boolean,integer,text)
 TO pdos_next_dingtalk_maintenance;
CREATE POLICY dingtalk_cancel_metadata ON public.agent_runs
 TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
CREATE POLICY dingtalk_cancel_event_metadata ON public.agent_run_events
 TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)
 WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
CREATE POLICY dingtalk_cancel_call_metadata ON public.agent_tool_calls
 FOR SELECT TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
CREATE POLICY dingtalk_principal_metadata ON public.principals
 FOR SELECT TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
CREATE POLICY dingtalk_administrator_metadata ON public.tenant_administrators
 FOR SELECT TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE FUNCTION public.dingtalk_admin(t uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p JOIN public.tenant_administrators a
 ON a.tenant_id=p.tenant_id AND a.principal_id=p.id
 WHERE p.tenant_id=t AND p.id=public.scope_actor() AND p.active AND p.kind='human' AND a.active)
$$;
CREATE FUNCTION public.dingtalk_service(t uuid,app uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.dingtalk_applications a JOIN public.principals p
 ON p.tenant_id=a.tenant_id AND p.id=a.service_principal_id
 WHERE a.tenant_id=t AND a.id=app AND p.id=public.scope_actor() AND p.active AND p.kind='agent')
$$;


CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_applications TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_applications FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (true));

CREATE POLICY dingtalk_insert ON public.dingtalk_applications FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (dingtalk_admin(tenant_id)));

CREATE POLICY dingtalk_update ON public.dingtalk_applications FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (dingtalk_admin(tenant_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (dingtalk_admin(tenant_id)));

CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_binding_nonces TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_binding_nonces FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() AND scope_actor()=scope_requester()));

CREATE POLICY dingtalk_insert ON public.dingtalk_binding_nonces FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() AND scope_actor()=scope_requester()));

CREATE POLICY dingtalk_update ON public.dingtalk_binding_nonces FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() AND scope_actor()=scope_requester())) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() AND scope_actor()=scope_requester()));

CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_account_bindings TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_account_bindings FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR dingtalk_admin(tenant_id) OR dingtalk_service(tenant_id,application_id)));

CREATE POLICY dingtalk_insert ON public.dingtalk_account_bindings FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_admin(tenant_id)));

CREATE POLICY dingtalk_update ON public.dingtalk_account_bindings FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_admin(tenant_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_admin(tenant_id)));

CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_messages TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_messages FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR dingtalk_admin(tenant_id) OR dingtalk_service(tenant_id,application_id)));

CREATE POLICY dingtalk_insert ON public.dingtalk_messages FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_service(tenant_id,application_id)));

CREATE POLICY dingtalk_update ON public.dingtalk_messages FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_service(tenant_id,application_id))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND ((owner_id=scope_requester() AND scope_actor()=scope_requester()) OR dingtalk_service(tenant_id,application_id)));

CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_share_consents TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_share_consents FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id AND dingtalk_service(m.tenant_id,m.application_id))));

CREATE POLICY dingtalk_insert ON public.dingtalk_share_consents FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id AND dingtalk_service(m.tenant_id,m.application_id))));

CREATE POLICY dingtalk_update ON public.dingtalk_share_consents FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id AND dingtalk_service(m.tenant_id,m.application_id)))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_share_consents.tenant_id AND m.id=dingtalk_share_consents.message_id AND dingtalk_service(m.tenant_id,m.application_id))));

CREATE POLICY dingtalk_maintenance_tenant ON public.dingtalk_deliveries TO pdos_next_dingtalk_maintenance USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);

CREATE POLICY dingtalk_read ON public.dingtalk_deliveries FOR SELECT TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk_service(m.tenant_id,m.application_id))));

CREATE POLICY dingtalk_insert ON public.dingtalk_deliveries FOR INSERT TO pdos_next_app WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk_service(m.tenant_id,m.application_id))));

CREATE POLICY dingtalk_update ON public.dingtalk_deliveries FOR UPDATE TO pdos_next_app USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk_service(m.tenant_id,m.application_id)))) WITH CHECK (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND (owner_id=scope_requester() OR EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=dingtalk_deliveries.tenant_id AND m.id=dingtalk_deliveries.message_id AND dingtalk_service(m.tenant_id,m.application_id))));


CREATE FUNCTION public.dingtalk_callback_application(app uuid)
 RETURNS TABLE(tenant_id uuid, service_principal_id uuid)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE app_tenant uuid; service_id uuid; previous_tenant text; previous_app text;
BEGIN
 previous_tenant=current_setting('pdos.tenant_id',true);
 previous_app=current_setting('pdos.dingtalk_application',true);
 PERFORM set_config('pdos.dingtalk_application',app::text,true);
 SELECT a.tenant_id,a.service_principal_id INTO app_tenant,service_id
 FROM public.dingtalk_applications a WHERE a.id=app AND a.active;
 PERFORM set_config('pdos.tenant_id',COALESCE(app_tenant::text,''),true);
 IF EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=app_tenant
 AND p.id=service_id AND p.active AND p.kind='agent') THEN
  RETURN QUERY SELECT app_tenant,service_id;
 END IF;
 PERFORM set_config('pdos.tenant_id',COALESCE(previous_tenant,''),true);
 PERFORM set_config('pdos.dingtalk_application',COALESCE(previous_app,''),true);
END $$;
-- Auth has no tenant scope before signature verification. Only this exact
-- UUID locator uses a separate role-specific policy; no app KMS ref is returned.
CREATE POLICY dingtalk_callback_locator ON public.dingtalk_applications FOR SELECT
 TO pdos_next_dingtalk_maintenance USING (id=NULLIF(current_setting('pdos.dingtalk_application',true),'')::uuid);



CREATE FUNCTION public.dingtalk_message_service(t uuid,mid uuid) RETURNS uuid
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT a.service_principal_id FROM public.dingtalk_messages m
 JOIN public.dingtalk_applications a ON a.tenant_id=m.tenant_id AND a.id=m.application_id
 WHERE t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND m.id=mid
$$;
CREATE FUNCTION public.dingtalk_pending_references(t uuid, maximum integer)
 RETURNS TABLE(message_id uuid,run_id uuid,owner_id uuid,consent_id uuid)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m.id,m.run_id,m.owner_id,NULL::uuid FROM public.dingtalk_messages m
 WHERE t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND m.state='pending'
 UNION ALL
 SELECT m.id,m.run_id,m.owner_id,c.id FROM public.dingtalk_share_consents c
 JOIN public.dingtalk_messages m ON m.tenant_id=c.tenant_id AND m.id=c.message_id
 WHERE t=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid AND m.tenant_id=t AND c.state='confirmed' AND NOT EXISTS(
  SELECT 1 FROM public.dingtalk_deliveries d WHERE d.tenant_id=t AND d.consent_id=c.id)
 LIMIT GREATEST(0,LEAST(maximum,100))
$$;
CREATE FUNCTION public.dingtalk_cancel_lost_run(t uuid,mid uuid) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m record; b record; a record; r record; call_id uuid; old_actor text; old_requester text;
BEGIN
 IF t IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::uuid THEN RETURN NULL; END IF;
 SELECT id,tenant_id,application_id,binding_id,binding_epoch,owner_id,run_id INTO m
 FROM public.dingtalk_messages WHERE tenant_id=t AND id=mid FOR UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT active,epoch,owner_id,application_id INTO b FROM public.dingtalk_account_bindings
 WHERE tenant_id=t AND id=m.binding_id;
 SELECT active,service_principal_id INTO a FROM public.dingtalk_applications WHERE tenant_id=t AND id=m.application_id;
 IF a.active AND b.active AND b.epoch=m.binding_epoch AND b.owner_id=m.owner_id
 AND b.application_id=m.application_id AND EXISTS(SELECT 1 FROM public.principals writer
 WHERE writer.tenant_id=t AND writer.id=a.service_principal_id AND writer.active AND writer.kind='agent')
 AND EXISTS(SELECT 1 FROM public.principals p
 WHERE p.tenant_id=t AND p.id=m.owner_id AND p.active AND p.kind='human') THEN RETURN NULL; END IF;
 SELECT id,tenant_id,requester_id,writer_id,category_id,state,cancel_epoch,reverted_at INTO r
 FROM public.agent_runs WHERE tenant_id=t AND id=m.run_id FOR UPDATE;
 IF NOT FOUND OR r.requester_id IS DISTINCT FROM m.owner_id OR r.category_id IS NOT NULL THEN
  RAISE EXCEPTION 'channel run binding mismatch' USING ERRCODE='23514'; END IF;
 UPDATE public.dingtalk_messages SET state='cancelled' WHERE tenant_id=t AND id=mid;
 UPDATE public.dingtalk_deliveries SET state='cancelled',error_code='CANCELLED_RUN'
 WHERE tenant_id=t AND message_id=mid AND state='planned';
 IF r.reverted_at IS NOT NULL OR r.state IN ('completed','partial','failed','cancelled') THEN RETURN r.id; END IF;
 old_actor=current_setting('pdos.actor_id',true); old_requester=current_setting('pdos.requester_id',true);
 -- Native technical release checks this exact persisted writer/requester and
 -- charges any unknown reservation; no Human command or business source READ.
 PERFORM set_config('pdos.actor_id',r.writer_id::text,true);
 PERFORM set_config('pdos.requester_id',r.requester_id::text,true);
 FOR call_id IN SELECT id FROM public.agent_tool_calls WHERE tenant_id=t AND run_id=r.id AND state='started' LOOP
  PERFORM public.kernel_release_call(r.id,call_id,'CANCELLED_RUN',true,0,NULL);
 END LOOP;
 PERFORM set_config('pdos.actor_id',COALESCE(old_actor,''),true);
 PERFORM set_config('pdos.requester_id',COALESCE(old_requester,''),true);
 UPDATE public.agent_runs SET state='cancelled',error_code='CANCELLED_RUN',cancel_epoch=cancel_epoch+1
 WHERE tenant_id=t AND id=r.id;
 INSERT INTO public.agent_run_events(id,tenant_id,created_at,run_id,sequence,body)
 SELECT gen_random_uuid(),t,clock_timestamp(),r.id,COALESCE(max(sequence),0)+1,
  '{"type":"run_state","status":"cancelled","error_code":"CANCELLED_RUN"}'::jsonb
 FROM public.agent_run_events WHERE tenant_id=t AND run_id=r.id;
 RETURN r.id;
END $$;


ALTER FUNCTION public.dingtalk_admin(uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_admin(uuid) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_admin(uuid) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_admin(uuid) TO pdos_next_app;

ALTER FUNCTION public.dingtalk_service(uuid,uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_service(uuid,uuid) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_service(uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_service(uuid,uuid) TO pdos_next_app;

ALTER FUNCTION public.dingtalk_callback_application(uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_callback_application(uuid) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_callback_application(uuid) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_callback_application(uuid) TO pdos_next_auth;

ALTER FUNCTION public.dingtalk_message_service(uuid,uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_message_service(uuid,uuid) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_message_service(uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_message_service(uuid,uuid) TO pdos_next_auth,pdos_next_dispatch;

ALTER FUNCTION public.dingtalk_pending_references(uuid,integer) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_pending_references(uuid,integer) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_pending_references(uuid,integer) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_pending_references(uuid,integer) TO pdos_next_dispatch;

ALTER FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_cancel_lost_run(uuid,uuid) TO pdos_next_dispatch;



-- Immutable verified binding/Run edges. These controls never inspect source text.
CREATE FUNCTION public.dingtalk_control_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a record; n record; b record; m record; r record;
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 THEN RAISE EXCEPTION 'channel tenant mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='dingtalk_applications' THEN
  IF NOT public.dingtalk_admin(NEW.tenant_id) OR NOT EXISTS(SELECT 1 FROM public.principals p
   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.service_principal_id AND p.kind='agent' AND p.active)
  THEN RAISE EXCEPTION 'named administrator and existing agent required' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND (NEW.id<>OLD.id OR NEW.tenant_id<>OLD.tenant_id OR NEW.created_at<>OLD.created_at
   OR NEW.service_principal_id<>OLD.service_principal_id OR NEW.revision<>OLD.revision+1)
  THEN RAISE EXCEPTION 'application identity immutable' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='dingtalk_binding_nonces' THEN
  IF NEW.owner_id IS DISTINCT FROM public.scope_actor() OR public.scope_actor()<>public.scope_requester()
   OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.owner_id AND p.kind='human' AND p.active)
  THEN RAISE EXCEPTION 'nonce must belong to actual human' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' THEN
   SELECT revision,active INTO a FROM public.dingtalk_applications WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;
   IF a.active IS DISTINCT FROM true OR a.revision IS DISTINCT FROM NEW.app_revision
    OR NEW.consumed_at IS NOT NULL OR NEW.expires_at>NEW.created_at+interval '5 minutes'
    OR NEW.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'nonce must use current app and short expiry' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'consumed_at'<>to_jsonb(OLD)-'consumed_at'
   OR OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL OR NEW.expires_at<=NEW.consumed_at)
  THEN RAISE EXCEPTION 'nonce may only be consumed once' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='dingtalk_account_bindings' THEN
  IF TG_OP='INSERT' THEN
   SELECT application_id,owner_id,app_revision,state_sha256,expires_at,consumed_at INTO n
    FROM public.dingtalk_binding_nonces WHERE tenant_id=NEW.tenant_id AND id=NEW.verified_nonce_id;
   SELECT id,revision,active INTO a FROM public.dingtalk_applications WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;
   IF n.application_id IS DISTINCT FROM NEW.application_id OR n.owner_id IS DISTINCT FROM NEW.owner_id
    OR n.consumed_at IS NULL OR n.expires_at<=clock_timestamp() OR n.app_revision IS DISTINCT FROM a.revision
    OR a.active IS DISTINCT FROM true OR NEW.owner_id IS DISTINCT FROM public.scope_actor()
    OR public.scope_actor()<>public.scope_requester() OR NOT NEW.active OR NEW.epoch<>1
   THEN RAISE EXCEPTION 'verified self nonce required' USING ERRCODE='23514'; END IF;
  ELSIF to_jsonb(NEW)-ARRAY['active','epoch','revoked_by','revoke_key','revoke_reason']
   <>to_jsonb(OLD)-ARRAY['active','epoch','revoked_by','revoke_key','revoke_reason']
   OR NOT OLD.active OR NEW.active OR NEW.epoch<>OLD.epoch+1
   OR NEW.revoked_by IS DISTINCT FROM public.scope_actor()
   OR NOT(NEW.owner_id=public.scope_actor() OR public.dingtalk_admin(NEW.tenant_id)) THEN
   RAISE EXCEPTION 'binding only supports named revoke' USING ERRCODE='23514';
  END IF;
 ELSIF TG_TABLE_NAME='dingtalk_messages' THEN
  IF TG_OP='INSERT' THEN
   SELECT active,epoch,owner_id,application_id INTO b FROM public.dingtalk_account_bindings
    WHERE tenant_id=NEW.tenant_id AND id=NEW.binding_id;
   SELECT service_principal_id,active INTO a FROM public.dingtalk_applications
    WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;
   SELECT requester_id,writer_id,category_id,state INTO r FROM public.agent_runs
    WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
   IF b.active IS DISTINCT FROM true OR a.active IS DISTINCT FROM true
    OR b.epoch IS DISTINCT FROM NEW.binding_epoch OR b.owner_id IS DISTINCT FROM NEW.owner_id
    OR b.application_id IS DISTINCT FROM NEW.application_id OR r.requester_id IS DISTINCT FROM NEW.owner_id
    OR r.writer_id IS DISTINCT FROM a.service_principal_id OR r.category_id IS NOT NULL OR r.state<>'queued'
    OR EXISTS(SELECT 1 FROM public.agent_tool_calls c WHERE c.tenant_id=NEW.tenant_id AND c.run_id=NEW.run_id)
    OR NEW.owner_id IS DISTINCT FROM public.scope_actor() OR public.scope_actor()<>public.scope_requester()
   THEN RAISE EXCEPTION 'message requires fresh actual bound personal run' USING ERRCODE='23514'; END IF;
  ELSIF session_user<>'pdos_next_dispatch' AND NOT public.dingtalk_service(NEW.tenant_id,NEW.application_id) THEN
   RAISE EXCEPTION 'actual channel dispatcher required' USING ERRCODE='23514';
  ELSIF to_jsonb(NEW)-ARRAY['state','error_code','lease_id','lease_until','workflow_id']
   <>to_jsonb(OLD)-ARRAY['state','error_code','lease_id','lease_until','workflow_id'] THEN
   RAISE EXCEPTION 'channel run identity immutable' USING ERRCODE='23514';
  END IF;
 ELSIF TG_TABLE_NAME='dingtalk_share_consents' THEN
  SELECT owner_id,conversation_kind,application_id INTO m FROM public.dingtalk_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.message_id;
  IF TG_OP='UPDATE' THEN
   IF session_user<>'pdos_next_dispatch' AND NOT public.dingtalk_service(NEW.tenant_id,m.application_id) THEN
    RAISE EXCEPTION 'only actual channel dispatcher may update delivery state' USING ERRCODE='23514'; END IF;
   IF to_jsonb(NEW)-ARRAY['state','error_code']<>to_jsonb(OLD)-ARRAY['state','error_code'] THEN
    RAISE EXCEPTION 'share consent identity immutable' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
  IF m.owner_id IS DISTINCT FROM NEW.owner_id OR m.conversation_kind<>'group'
   OR NEW.owner_id IS DISTINCT FROM public.scope_actor() OR public.scope_actor()<>public.scope_requester()
  THEN RAISE EXCEPTION 'explicit own group confirmation required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='dingtalk_deliveries' THEN
  SELECT owner_id,application_id INTO m FROM public.dingtalk_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.message_id;
  IF session_user<>'pdos_next_dispatch' AND NOT public.dingtalk_service(NEW.tenant_id,m.application_id)
   THEN RAISE EXCEPTION 'actual service delivery required' USING ERRCODE='23514'; END IF;
  IF NEW.owner_id IS DISTINCT FROM m.owner_id THEN RAISE EXCEPTION 'delivery owner mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.content_kind NOT IN ('control','answer','local_link') OR jsonb_typeof(NEW.source_dependencies) IS DISTINCT FROM 'array'
   OR ((NEW.content_kind='answer') IS DISTINCT FROM (jsonb_array_length(NEW.source_dependencies)>0))
  THEN RAISE EXCEPTION 'outbound copy requires fixed source identities' USING ERRCODE='23514'; END IF;
  -- source_dependencies/content_kind join payload in the immutable comparison below.
  -- Full typed Artifact closure is the shared F/root retention guard, never a permission grant.

  IF TG_OP='UPDATE' AND to_jsonb(NEW)-ARRAY['state','p26','provider_receipt','error_code','attempts','attempt_id','send_started_at']
   <>to_jsonb(OLD)-ARRAY['state','p26','provider_receipt','error_code','attempts','attempt_id','send_started_at']
   THEN RAISE EXCEPTION 'delivery payload and consent immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
ALTER FUNCTION public.dingtalk_control_guard() OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_control_guard() TO pdos_next_owner;
REVOKE ALL ON FUNCTION public.dingtalk_control_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_applications FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_binding_nonces FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_account_bindings FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_messages FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_share_consents FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();
CREATE TRIGGER dingtalk_control BEFORE INSERT OR UPDATE ON public.dingtalk_deliveries FOR EACH ROW EXECUTE FUNCTION public.dingtalk_control_guard();

GRANT UPDATE (state,error_code) ON public.dingtalk_share_consents TO pdos_next_dingtalk_maintenance;
CREATE FUNCTION public.dingtalk_mark_dispatched(t uuid,mid uuid,cid uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF t IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 THEN RAISE EXCEPTION 'channel dispatch tenant mismatch' USING ERRCODE='23514'; END IF;
 IF cid IS NULL THEN
  UPDATE public.dingtalk_messages SET state='admitted' WHERE tenant_id=t AND id=mid AND state='pending';
 ELSE
  UPDATE public.dingtalk_share_consents SET state='dispatched'
   WHERE tenant_id=t AND id=cid AND message_id=mid AND state='confirmed';
 END IF;
END $$;
ALTER FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) TO pdos_next_owner;
REVOKE ALL ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid)
 FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;
GRANT EXECUTE ON FUNCTION public.dingtalk_mark_dispatched(uuid,uuid,uuid) TO pdos_next_dispatch;

CREATE FUNCTION public.dingtalk_run_identity_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.dingtalk_messages m WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.id)
 AND (NEW.versions->'dingtalk' IS DISTINCT FROM '{"version":1}'::jsonb OR NEW.category_id IS NOT NULL)
 THEN RAISE EXCEPTION 'channel run marker immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
ALTER FUNCTION public.dingtalk_run_identity_guard() OWNER TO pdos_next_dingtalk_maintenance;
GRANT EXECUTE ON FUNCTION public.dingtalk_run_identity_guard() TO pdos_next_owner;
REVOKE ALL ON FUNCTION public.dingtalk_run_identity_guard()
 FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch;
CREATE TRIGGER dingtalk_run_identity BEFORE UPDATE ON public.agent_runs FOR EACH ROW
 WHEN (OLD.versions ? 'dingtalk' OR NEW.versions ? 'dingtalk')
 EXECUTE FUNCTION public.dingtalk_run_identity_guard();
REVOKE CREATE ON SCHEMA public FROM pdos_next_dingtalk_maintenance;
