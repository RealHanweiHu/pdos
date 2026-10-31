"""Sanitized resource capacity across project visibility boundaries."""
# ruff: noqa: E501
SCHEMA_SQL = ["""CREATE FUNCTION planning_resource_windows(t uuid, p uuid, rid uuid, resource_kind text)
RETURNS TABLE(window_start timestamptz,window_finish timestamptz,units numeric,source_kind text,visible_project_id uuid,visible_project_name text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE target projects;
BEGIN
 SELECT * INTO target FROM projects WHERE tenant_id=t AND id=p;
 IF NOT FOUND OR NOT category_access(t,target.category_id) OR NOT m3_result_access(t,target.category_id,'projects',p) THEN
  RAISE EXCEPTION 'Planning scope unavailable' USING ERRCODE='42501';
 END IF;
 IF resource_kind='person' THEN
  IF NOT EXISTS(SELECT 1 FROM principals h JOIN grants g ON g.tenant_id=h.tenant_id AND g.principal_id=h.id
   WHERE h.tenant_id=t AND h.id=rid AND h.kind='human' AND g.category_id=target.category_id AND (g.expires_at IS NULL OR g.expires_at>now())) THEN
   RAISE EXCEPTION 'Planning person unavailable' USING ERRCODE='42501';
  END IF;
 ELSIF resource_kind='resource' THEN
  IF NOT EXISTS(SELECT 1 FROM build_operational_facts f JOIN build_operational_current c ON c.tenant_id=f.tenant_id AND c.fact_id=f.id
    WHERE f.tenant_id=t AND f.project_id=p AND f.state='active' AND f.valid_from<=now() AND (f.valid_until IS NULL OR f.valid_until>now())
    AND EXISTS(SELECT 1 FROM jsonb_array_elements(f.data->'resources') r WHERE r->'resource'->>'id'=rid::text)) THEN
   RAISE EXCEPTION 'Planning physical resource unavailable' USING ERRCODE='42501';
  END IF;
 ELSE RAISE EXCEPTION 'Unsupported resource kind' USING ERRCODE='23514'; END IF;
 RETURN QUERY
 SELECT (task->>'earliest_start')::timestamptz,(task->>'latest_finish')::timestamptz,(d->>'units')::numeric,'plan'::text,
  CASE WHEN category_access(t,other.category_id) AND m3_result_access(t,other.category_id,'projects',other.id) THEN other.id ELSE NULL::uuid END,
  CASE WHEN category_access(t,other.category_id) AND m3_result_access(t,other.category_id,'projects',other.id) THEN other.name ELSE '受限项目的计划需求'::text END
 FROM projects other JOIN plan_revisions pr ON pr.tenant_id=other.tenant_id AND pr.id=other.current_plan_id
 JOIN plan_proposals pp ON pp.tenant_id=pr.tenant_id AND pp.id=pr.proposal_id
 CROSS JOIN LATERAL jsonb_array_elements(pp.resource_demands) d
 CROSS JOIN LATERAL jsonb_array_elements(pr.forecast->'tasks') task
 WHERE other.tenant_id=t AND other.id<>p AND d->>'kind'=resource_kind AND d->>'resource_id'=rid::text AND task->>'key'=d->>'task_key';
 RETURN QUERY SELECT o.window_start,o.window_finish,o.units,'reservation'::text,NULL::uuid,'已确认的实际占用'::text
 FROM operational_resource_occupancies o WHERE o.tenant_id=t AND o.resource_id=rid;
END $$""",
 "REVOKE ALL ON FUNCTION planning_resource_windows(uuid,uuid,uuid,text) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
 "GRANT EXECUTE ON FUNCTION planning_resource_windows(uuid,uuid,uuid,text) TO pdos_next_app",
]
DOWNGRADE_SQL = ["DROP FUNCTION planning_resource_windows(uuid,uuid,uuid,text)"]
