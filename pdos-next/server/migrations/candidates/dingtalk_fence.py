"""Unnumbered G metadata row-lock repair; no new runtime UPDATE policy."""

SCHEMA_SQL = (
    (
        'GRANT UPDATE(id) ON public.dingtalk_applications TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'GRANT UPDATE(id) ON public.dingtalk_account_bindings TO pdos_next_dingtalk_maintenance'
        ';'
    ),
    (
        'GRANT CREATE ON SCHEMA public TO pdos_next_dingtalk_maintenance;'
    ),
    (
        'CREATE FUNCTION public.dingtalk_lock_message_binding(t uuid, mid uuid) RETURNS void\nL'
        'ANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$\nDECL'
        'ARE app_id uuid; account_id uuid; bound_owner_id uuid;\nBEGIN\n IF t IS NULL OR mid IS'
        " NULL OR t IS DISTINCT FROM\n  NULLIF(current_setting('pdos.tenant_id',true),'')::uuid"
        '\n  OR public.scope_actor() IS DISTINCT FROM public.scope_requester() THEN\n  RAISE EX'
        "CEPTION 'DingTalk service binding required' USING ERRCODE='42501';\n END IF;\n SELECT "
        'm.application_id,m.binding_id,m.owner_id INTO app_id,account_id,bound_owner_id\n FROM '
        'public.dingtalk_messages m WHERE m.tenant_id=t AND m.id=mid;\n IF app_id IS NULL OR pu'
        "blic.dingtalk_service(t,app_id) IS NOT TRUE THEN\n  RAISE EXCEPTION 'DingTalk service "
        "binding required' USING ERRCODE='42501';\n END IF;\n -- Existing config UPDATE locks t"
        'his actual application row. Acquiring this\n -- first gives every channel send one fix'
        'ed app -> account lock order.\n PERFORM a.id FROM public.dingtalk_applications a\n WHE'
        "RE a.tenant_id=t AND a.id=app_id FOR UPDATE;\n IF NOT FOUND THEN\n  RAISE EXCEPTION 'D"
        "ingTalk service binding required' USING ERRCODE='42501';\n END IF;\n -- Check the call"
        'er again after waiting: the actual service may have changed.\n IF public.dingtalk_serv'
        "ice(t,app_id) IS NOT TRUE THEN\n  RAISE EXCEPTION 'DingTalk service binding required' "
        "USING ERRCODE='42501';\n END IF;\n -- Native self/admin revoke holds the same account "
        'row until commit.\n PERFORM b.id FROM public.dingtalk_account_bindings b\n WHERE b.ten'
        'ant_id=t AND b.id=account_id AND b.application_id=app_id\n  AND b.owner_id=bound_owner'
        "_id FOR UPDATE;\n IF NOT FOUND THEN\n  RAISE EXCEPTION 'DingTalk service binding requi"
        "red' USING ERRCODE='42501';\n END IF;\nEND $$;"
    ),
    (
        'ALTER FUNCTION public.dingtalk_lock_message_binding(uuid,uuid) OWNER TO pdos_next_ding'
        'talk_maintenance;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_lock_message_binding(uuid,uuid) TO pdos_next'
        '_owner;'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_lock_message_binding(uuid,uuid) FROM PUBLIC,pdo'
        's_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtalk_lock_message_binding(uuid,uuid) TO pdos_next'
        '_app;'
    ),
    (
        'REVOKE CREATE ON SCHEMA public FROM pdos_next_dingtalk_maintenance;'
    ),
)

DOWNGRADE_SQL = (
    (
        'DROP FUNCTION public.dingtalk_lock_message_binding(uuid,uuid);'
    ),
    (
        'REVOKE UPDATE(id) ON public.dingtalk_account_bindings FROM pdos_next_dingtalk_maintena'
        'nce;'
    ),
    (
        'REVOKE UPDATE(id) ON public.dingtalk_applications FROM pdos_next_dingtalk_maintenance;'
    ),
)
