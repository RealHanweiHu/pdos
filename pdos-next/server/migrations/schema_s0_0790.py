"""Exact project audience and key attestation for native work receipts."""

PREVIOUS_FUNCTIONS = {}

WORK_FUNCTIONS = {}

SCHEMA_SQL = ('CREATE FUNCTION public.work_receipt_project_visible(t uuid,c uuid,p uuid,kind text,target '
 'uuid,rev integer,receipt uuid,actor uuid)\n'
 'RETURNS boolean LANGUAGE plpgsql STABLE STRICT SECURITY DEFINER\n'
 'SET search_path=pg_catalog,public,pg_temp AS $work_receipt$\n'
 'DECLARE project_id uuid; project_owner uuid; project_visibility text; actual_project '
 'public.projects;\n'
 'BEGIN\n'
 ' IF NOT public.category_access(t,c) THEN RETURN false; END IF;\n'
 " IF kind='work_task' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_task_versions x WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p '
 'AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND x.actor_id=actor;\n'
 " ELSIF kind='work_commitment' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_versions x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='project_status_update' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.project_status_updates x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='work_commitment_review' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_reviews x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 ' ELSE RETURN false; END IF;\n'
 ' IF project_id IS NULL THEN RETURN false; END IF;\n'
 ' SELECT * INTO actual_project FROM public.projects x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=project_id AND x.owner_id=project_owner AND '
 'x.visibility=project_visibility;\n'
 " RETURN actual_project.id IS NOT NULL AND (actual_project.visibility='category' OR "
 'actual_project.owner_id=public.scope_requester() OR EXISTS(\n'
 '  SELECT 1 FROM public.object_audiences a WHERE a.tenant_id=t AND a.category_id=c AND '
 "a.object_type='projects'\n"
 '   AND a.subject_id=actual_project.id AND a.owner_id=actual_project.owner_id AND '
 'a.principal_id=public.scope_requester()));\n'
 'END;\n'
 '$work_receipt$',
 'REVOKE ALL ON FUNCTION '
 'public.work_receipt_project_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION '
 'public.work_receipt_project_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) TO pdos_next_app',
 'CREATE POLICY work_receipt_project_read ON public.action_receipts FOR SELECT TO pdos_next_app '
 'USING(public.work_receipt_project_visible(tenant_id,category_id,product_id,subject_type::text,subject_id,subject_revision,id,actor_id))',
 'CREATE FUNCTION public.work_receipt_key_bound(t uuid,p uuid,receipt uuid)\n'
 'RETURNS boolean LANGUAGE sql STABLE STRICT SECURITY DEFINER SET '
 'search_path=pg_catalog,public,pg_temp\n'
 'AS $work_key$\n'
 ' SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.product_id=p AND '
 'r.id=receipt\n'
 '  AND '
 'public.work_receipt_project_visible(r.tenant_id,r.category_id,r.product_id,r.subject_type::text,r.subject_id,r.subject_revision,r.id,r.actor_id)\n'
 '  AND EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=r.tenant_id AND '
 'k.category_id=r.category_id\n'
 '   AND k.actor_id=r.actor_id AND k.receipt_id=r.id AND k.digest=r.request_digest))\n'
 '$work_key$',
 'REVOKE ALL ON FUNCTION public.work_receipt_key_bound(uuid,uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION public.work_receipt_key_bound(uuid,uuid,uuid) TO pdos_next_app')

DOWNGRADE_SQL = ('DO $retain$ BEGIN IF EXISTS(SELECT 1 FROM public.work_commitment_reviews) THEN RAISE EXCEPTION '
 "'Commitment fulfillment history retained; audience proof downgrade refused' USING "
 "ERRCODE='23514'; END IF; END; $retain$",
 'DROP POLICY work_receipt_project_read ON public.action_receipts',
 'DROP FUNCTION public.work_receipt_key_bound(uuid,uuid,uuid)',
 'DROP FUNCTION public.work_receipt_project_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)')

