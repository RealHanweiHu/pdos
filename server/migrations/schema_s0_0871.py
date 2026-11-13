"""Working-day estimate and the readable status-update cadence (D71/D190, D75, P34-6, P65).

- `work_weekday_add` is the SQL twin of `projects/work/business_days.add_weekdays`:
  Monday to Friday in the given zone, holidays and line stops not deducted (P41-10),
  until the tenant calendar (D221) replaces both.
- `project_status_cadence` returns only the timing of a project's active status-update
  cadence rule (template `status_update_draft`) to anyone who can see the project now,
  so members and the cockpit can show "状态更新缺失" (P34-6). The rule itself, its goal,
  skills and budget stay readable only by its owner (automation RLS). Only a rule whose
  owner is the current project owner counts (P57-2, P65).

Assigned s0_0871 at the 11-10 integration (placeholder s0_0905, range s0_0905–s0_0909).
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

FUNCTIONS = (
    (
        "work_weekday_add(timestamp with time zone,integer,text)",
        """CREATE FUNCTION public.work_weekday_add(p_at timestamptz, p_days integer, p_tz text) RETURNS timestamptz
 LANGUAGE plpgsql STABLE STRICT SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE local_at timestamp; n integer := 0;
BEGIN
 IF p_days < 0 OR p_days > 366 THEN
  RAISE EXCEPTION 'Working days must be from 0 to 366' USING ERRCODE='22023'; END IF;
 -- Counted on weekdays only: a weekend start begins on Monday 00:00 local (P41-10).
 local_at := p_at AT TIME ZONE p_tz;
 IF extract(isodow FROM local_at) >= 6 THEN
  local_at := date_trunc('day', local_at) + make_interval(days => 8 - extract(isodow FROM local_at)::integer);
 END IF;
 WHILE n < p_days LOOP
  local_at := local_at + interval '1 day';
  IF extract(isodow FROM local_at) = 6 THEN local_at := local_at + interval '2 days'; END IF;
  n := n + 1;
 END LOOP;
 RETURN local_at AT TIME ZONE p_tz;
END $$""",
        ("pdos_next_app",),
    ),
    (
        "project_status_cadence(uuid,uuid)",
        """CREATE FUNCTION public.project_status_cadence(t uuid, project uuid)
 RETURNS TABLE(rule_id uuid, version_id uuid, owner_id uuid, schedule jsonb, activated_at timestamptz)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT cur.rule_id, v.id, v.owner_id, v.spec->'trigger_config', v.created_at
 FROM public.projects p
 JOIN public.automation_rule_currents cur ON cur.tenant_id=p.tenant_id AND cur.category_id=p.category_id
  AND cur.owner_id=p.owner_id AND cur.state='active'
 JOIN public.automation_rule_versions v ON v.tenant_id=cur.tenant_id AND v.id=cur.published_version_id
  AND v.rule_id=cur.rule_id AND v.owner_id=cur.owner_id AND v.action='activate' AND v.state='active'
 WHERE t IS NOT DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND p.tenant_id=t AND p.id=project
  AND v.spec->>'template'='status_update_draft' AND v.spec->>'trigger_kind'='schedule'
  AND v.spec->'trigger_config'->>'project_id'=p.id::text
  AND public.notification_subject_open(t, public.scope_requester(), 'project', p.id, p.id)
 ORDER BY v.created_at DESC, v.id
 LIMIT 1
$$""",
        ("pdos_next_app",),
    ),
)

SCHEMA_SQL = (
    *(body for _, body, _ in FUNCTIONS),
    *(
        f"REVOKE ALL ON FUNCTION public.{sig} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch"
        for sig, _, _ in FUNCTIONS
    ),
    *(f"GRANT EXECUTE ON FUNCTION public.{sig} TO {role}" for sig, _, roles in FUNCTIONS for role in roles),
)

DOWNGRADE_SQL = tuple(f"DROP FUNCTION public.{sig}" for sig, _, _ in reversed(FUNCTIONS))
