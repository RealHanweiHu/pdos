"""Tenant working calendars (D221): factory and supplier calendars, append-only versions.

- Every active principal of the tenant reads them (schedules and 小Pai explain dates
  with them); nothing outside the tenant does.
- Only an active human tenant administrator acting for themself writes
  (``account_administrator()``, s0_0856): the AI identity, acting for a person,
  never satisfies it. ``pdos_agent``, auth and dispatch roles get nothing.
- Versions are complete and never updated or deleted; a new revision must follow
  the current one directly, so two concurrent saves cannot both win.
- ``work_calendar_add`` is the SQL twin of ``domain/work_calendar/rules.add_working_days``
  over the tenant's current factory calendar, falling back to Monday to Friday in
  Asia/Shanghai like ``work_weekday_add`` on the follow-up branch (P41 第 10 项).

Placeholder s0_0910 (assigned range s0_0910–s0_0914); renumbered at integration.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.domain.work_calendar.models).
TABLE_SQL = (
    "\nCREATE TABLE work_calendars (\n\tkind VARCHAR(16) NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, name), \n\tFOREIGN KEY(tenant_id, created_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT work_calendar_kind CHECK (kind IN ('factory','supplier')), \n\tCONSTRAINT work_calendar_name CHECK ((kind='factory') = (name='factory') AND char_length(name) BETWEEN 1 AND 80)\n)\n\n",
    'CREATE INDEX ix_work_calendars_tenant_id ON work_calendars (tenant_id)',
    "\nCREATE TABLE work_calendar_versions (\n\tcalendar_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\ttimezone VARCHAR(64) NOT NULL, \n\tworking_weekdays SMALLINT[] NOT NULL, \n\tentries JSONB NOT NULL, \n\treason VARCHAR(200) NOT NULL, \n\tauthor_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, calendar_id, revision), \n\tUNIQUE (tenant_id, calendar_id, request_key), \n\tFOREIGN KEY(tenant_id, calendar_id) REFERENCES work_calendars (tenant_id, id), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT work_calendar_revision CHECK (revision > 0), \n\tCONSTRAINT work_calendar_weekdays CHECK (cardinality(working_weekdays) BETWEEN 1 AND 7 AND working_weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[]), \n\tCONSTRAINT work_calendar_entries CHECK (jsonb_typeof(entries)='array' AND jsonb_array_length(entries) <= 500), \n\tCONSTRAINT work_calendar_reason CHECK (char_length(reason) BETWEEN 1 AND 200), \n\tCONSTRAINT work_calendar_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_work_calendar_versions_tenant_id ON work_calendar_versions (tenant_id)',
)

TABLES = ("work_calendars", "work_calendar_versions")
_TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
_ADMIN = "public.account_administrator()"
_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"


def _member(table):
    return f"""{_TENANT}
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_actor() AND p.active)"""


# A policy cannot read its own table, so the next revision comes from a definer
# function that answers only for the session's own tenant.
REVISION_FUNCTION = """CREATE FUNCTION public.work_calendar_next_revision(p_tenant uuid, p_calendar uuid) RETURNS integer
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT 1 + coalesce(max(v.revision), 0) FROM public.work_calendar_versions v
 WHERE p_tenant = nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND v.tenant_id=p_tenant AND v.calendar_id=p_calendar
$$"""

_NEXT_REVISION = " AND revision = public.work_calendar_next_revision(tenant_id, calendar_id)"

OPEN_FUNCTION = """CREATE FUNCTION public.work_calendar_open(p_day date, p_weekdays smallint[], p_entries jsonb) RETURNS boolean
 LANGUAGE sql STABLE STRICT SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT CASE
  WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p_entries) e WHERE e->>'kind' IN ('holiday','shutdown')
   AND p_day BETWEEN (e->>'start')::date AND (e->>'end')::date) THEN false
  WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p_entries) e WHERE e->>'kind'='makeup_workday'
   AND p_day BETWEEN (e->>'start')::date AND (e->>'end')::date) THEN true
  ELSE extract(isodow FROM p_day)::smallint = ANY(p_weekdays) END
$$"""

NEXT_FUNCTION = """CREATE FUNCTION public.work_calendar_next(p_day date, p_weekdays smallint[], p_entries jsonb) RETURNS date
 LANGUAGE plpgsql STABLE STRICT SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d date := p_day;
BEGIN
 FOR i IN 1..3660 LOOP
  d := d + 1;
  IF public.work_calendar_open(d, p_weekdays, p_entries) THEN RETURN d; END IF;
 END LOOP;
 RAISE EXCEPTION 'Calendar has no working day ahead' USING ERRCODE='22023';
END $$"""

ADD_FUNCTION = """CREATE FUNCTION public.work_calendar_add(p_at timestamptz, p_days integer) RETURNS timestamptz
 LANGUAGE plpgsql STABLE STRICT SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tz text; weekdays smallint[]; items jsonb; local_at timestamp; d date;
BEGIN
 IF p_days < 0 OR p_days > 366 THEN
  RAISE EXCEPTION 'Working days must be from 0 to 366' USING ERRCODE='22023'; END IF;
 SELECT v.timezone, v.working_weekdays, v.entries INTO tz, weekdays, items
  FROM public.work_calendar_versions v JOIN public.work_calendars c
   ON c.tenant_id=v.tenant_id AND c.id=v.calendar_id
  WHERE c.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND c.kind='factory'
  ORDER BY v.revision DESC LIMIT 1;
 IF NOT FOUND THEN
  -- No calendar yet: Monday to Friday, holidays and line stops not deducted (P41-10).
  tz := 'Asia/Shanghai'; weekdays := ARRAY[1,2,3,4,5]::smallint[]; items := '[]'::jsonb;
 END IF;
 local_at := p_at AT TIME ZONE tz;
 d := local_at::date;
 -- A start on a day off begins at 00:00 of the next working day.
 IF NOT public.work_calendar_open(d, weekdays, items) THEN
  d := public.work_calendar_next(d, weekdays, items);
  local_at := d::timestamp;
 END IF;
 FOR i IN 1..p_days LOOP
  d := public.work_calendar_next(d, weekdays, items);
 END LOOP;
 RETURN (d + local_at::time) AT TIME ZONE tz;
END $$"""

SECURITY_SQL = (
    REVISION_FUNCTION,
    f"REVOKE ALL ON FUNCTION public.work_calendar_next_revision(uuid,uuid) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.work_calendar_next_revision(uuid,uuid) TO pdos_next_app",
    *(statement for table in TABLES for statement in (
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {_REVOKED}",
        f"CREATE POLICY {table}_read ON public.{table} FOR SELECT TO pdos_next_app USING({_member(table)})",
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
        f"GRANT SELECT,INSERT ON public.{table} TO pdos_next_app",
    )),
    f"CREATE POLICY work_calendars_create ON public.work_calendars FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_TENANT} AND {_ADMIN} AND created_by=public.scope_actor())",
    f"CREATE POLICY work_calendar_versions_save ON public.work_calendar_versions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_TENANT} AND {_ADMIN} AND author_id=public.scope_actor(){_NEXT_REVISION})",
    OPEN_FUNCTION,
    NEXT_FUNCTION,
    ADD_FUNCTION,
    *(statement for signature in (
        "work_calendar_open(date,smallint[],jsonb)",
        "work_calendar_next(date,smallint[],jsonb)",
        "work_calendar_add(timestamp with time zone,integer)",
    ) for statement in (
        f"REVOKE ALL ON FUNCTION public.{signature} FROM {_REVOKED}",
        f"GRANT EXECUTE ON FUNCTION public.{signature} TO pdos_next_app",
    )),
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.work_calendars) THEN
     RAISE EXCEPTION 'Tenant working calendars require s0_0910'; END IF; END $$""",
    "DROP FUNCTION public.work_calendar_add(timestamp with time zone,integer)",
    "DROP FUNCTION public.work_calendar_next(date,smallint[],jsonb)",
    "DROP FUNCTION public.work_calendar_open(date,smallint[],jsonb)",
    "DROP TABLE public.work_calendar_versions",
    "DROP FUNCTION public.work_calendar_next_revision(uuid,uuid)",
    "DROP TABLE public.work_calendars",
)
