"""Project team (P34-1, P55, P60-4): tenant role catalog, members, one lead per role.

Membership is never a permission root: every read and write goes through the
project row's own policy, writes need the project owner (or the in-flight G0
decision that creates the project), and the agent role has no privilege at all.
"""
# ruff: noqa: E501
from migrations.schema_s0_0817 import HUMAN

TABLES = (
    "project_member_audiences",
    "project_member_roles",
    "project_members",
    "project_team_changes",
    "project_role_catalog_versions",
)

TABLE_SQL = [
    "\nCREATE TABLE project_role_catalog_versions (\n\trevision INTEGER NOT NULL, \n\troles JSONB NOT NULL, \n\tauthor_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, revision), \n\tUNIQUE (tenant_id, author_id, request_key), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT project_role_catalog_shape CHECK (revision>0 AND jsonb_typeof(roles)='array' AND request_sha256 ~ '^[a-f0-9]{64}$')\n)\n\n",
    "CREATE INDEX ix_project_role_catalog_versions_tenant_id ON project_role_catalog_versions (tenant_id)",
    "\nCREATE TABLE project_team_changes (\n\tproject_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tsource VARCHAR(16) NOT NULL, \n\tauthor_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tchanges JSONB NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, project_id, id), \n\tUNIQUE (tenant_id, project_id, revision), \n\tUNIQUE (tenant_id, author_id, request_key), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT project_team_change_shape CHECK (revision>0 AND source IN ('owner','g0','backfill') AND jsonb_typeof(changes)='array' AND request_sha256 ~ '^[a-f0-9]{64}$')\n)\n\n",
    "CREATE INDEX ix_project_team_changes_tenant_id ON project_team_changes (tenant_id)",
    "\nCREATE TABLE project_members (\n\tproject_id UUID NOT NULL, \n\tprincipal_id UUID NOT NULL, \n\tjoined_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tadded_by UUID NOT NULL, \n\tjoined_change_id UUID NOT NULL, \n\tleft_at TIMESTAMP WITH TIME ZONE, \n\tremoved_by UUID, \n\tleft_change_id UUID, \n\tdeparted_roles JSONB, \n\thandover_pending BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, project_id, id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, added_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, removed_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT project_member_joined_change_fk FOREIGN KEY(tenant_id, project_id, joined_change_id) REFERENCES project_team_changes (tenant_id, project_id, id), \n\tCONSTRAINT project_member_left_change_fk FOREIGN KEY(tenant_id, project_id, left_change_id) REFERENCES project_team_changes (tenant_id, project_id, id), \n\tCONSTRAINT project_member_stint CHECK (((left_at IS NULL) = (removed_by IS NULL)) AND ((left_at IS NULL) = (left_change_id IS NULL)) AND ((left_at IS NULL) = (departed_roles IS NULL)) AND (departed_roles IS NULL OR jsonb_typeof(departed_roles)='array') AND (left_at IS NULL OR left_at >= joined_at) AND (NOT handover_pending OR left_at IS NOT NULL))\n)\n\n",
    "CREATE UNIQUE INDEX uq_project_member_active ON project_members (tenant_id, project_id, principal_id) WHERE left_at IS NULL",
    "CREATE INDEX ix_project_members_tenant_id ON project_members (tenant_id)",
    "\nCREATE TABLE project_member_roles (\n\tproject_id UUID NOT NULL, \n\tmember_id UUID NOT NULL, \n\trole_key VARCHAR(64) NOT NULL, \n\tis_lead BOOLEAN NOT NULL, \n\tchange_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, member_id, role_key), \n\tCONSTRAINT project_member_role_member_fk FOREIGN KEY(tenant_id, project_id, member_id) REFERENCES project_members (tenant_id, project_id, id), \n\tCONSTRAINT project_member_role_change_fk FOREIGN KEY(tenant_id, project_id, change_id) REFERENCES project_team_changes (tenant_id, project_id, id), \n\tCONSTRAINT project_member_role_key CHECK (role_key ~ '^[a-z][a-z0-9_]{1,63}$')\n)\n\n",
    "CREATE UNIQUE INDEX uq_project_role_lead ON project_member_roles (tenant_id, project_id, role_key) WHERE is_lead",
    "CREATE INDEX ix_project_member_roles_tenant_id ON project_member_roles (tenant_id)",
    "\nCREATE TABLE project_member_audiences (\n\tproject_id UUID NOT NULL, \n\tmember_id UUID NOT NULL, \n\tobject_type VARCHAR(64) NOT NULL, \n\tsubject_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tprincipal_id UUID NOT NULL, \n\tinserted BOOLEAN NOT NULL, \n\treleased_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, member_id, object_type, subject_id), \n\tCONSTRAINT project_member_audience_member_fk FOREIGN KEY(tenant_id, project_id, member_id) REFERENCES project_members (tenant_id, project_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT project_member_audience_type CHECK (object_type IN ('products','definition_revisions','product_variants','variant_revisions'))\n)\n\n",
    "CREATE INDEX ix_project_member_audiences_tenant_id ON project_member_audiences (tenant_id)",
]


def _visible(table):
    return f"EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={table}.tenant_id AND p.id={table}.project_id)"


def _owned(table):
    return (
        f"EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={table}.tenant_id AND p.id={table}.project_id "
        "AND p.owner_id=public.scope_actor() AND public.category_access(p.tenant_id,p.category_id,true))"
    )


def _g0(table):
    return (
        f"EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={table}.tenant_id AND p.id={table}.project_id "
        "AND public.m3_result_access(p.tenant_id,p.category_id,'projects',p.id))"
    )


ADMIN = (
    "EXISTS(SELECT 1 FROM public.tenant_administrators ta WHERE ta.tenant_id=project_role_catalog_versions.tenant_id "
    "AND ta.principal_id=public.scope_actor() AND ta.active)"
)
RUNTIME = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"


def _base(table, privileges):
    return [
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {RUNTIME}",
        f"GRANT {privileges} ON public.{table} TO pdos_next_app",
    ]


POLICY_SQL = [
    *_base("project_role_catalog_versions", "SELECT,INSERT"),
    f"CREATE POLICY catalog_read ON public.project_role_catalog_versions FOR SELECT TO pdos_next_app USING({HUMAN})",
    f"CREATE POLICY catalog_publish ON public.project_role_catalog_versions FOR INSERT TO pdos_next_app WITH CHECK({HUMAN} AND author_id=public.scope_actor() AND {ADMIN})",
    *_base("project_team_changes", "SELECT,INSERT"),
    f"CREATE POLICY team_read ON public.project_team_changes FOR SELECT TO pdos_next_app USING({HUMAN} AND {_visible('project_team_changes')})",
    f"CREATE POLICY team_change ON public.project_team_changes FOR INSERT TO pdos_next_app WITH CHECK({HUMAN} AND author_id=public.scope_actor() AND ((source='owner' AND {_owned('project_team_changes')}) OR (source='g0' AND {_g0('project_team_changes')})))",
    *_base("project_members", "SELECT,INSERT,UPDATE"),
    f"CREATE POLICY member_read ON public.project_members FOR SELECT TO pdos_next_app USING({HUMAN} AND {_visible('project_members')})",
    f"CREATE POLICY member_join ON public.project_members FOR INSERT TO pdos_next_app WITH CHECK({HUMAN} AND added_by=public.scope_actor() AND ({_owned('project_members')} OR {_g0('project_members')}))",
    f"CREATE POLICY member_leave ON public.project_members FOR UPDATE TO pdos_next_app USING({HUMAN} AND {_owned('project_members')}) WITH CHECK({HUMAN} AND {_owned('project_members')})",
    *_base("project_member_roles", "SELECT,INSERT,DELETE"),
    f"CREATE POLICY role_read ON public.project_member_roles FOR SELECT TO pdos_next_app USING({HUMAN} AND {_visible('project_member_roles')})",
    f"CREATE POLICY role_set ON public.project_member_roles FOR INSERT TO pdos_next_app WITH CHECK({HUMAN} AND {_owned('project_member_roles')})",
    f"CREATE POLICY role_unset ON public.project_member_roles FOR DELETE TO pdos_next_app USING({HUMAN} AND {_owned('project_member_roles')})",
    *_base("project_member_audiences", "SELECT,INSERT"),
    f"CREATE POLICY upstream_read ON public.project_member_audiences FOR SELECT TO pdos_next_app USING({HUMAN} AND {_visible('project_member_audiences')})",
    f"CREATE POLICY upstream_claim ON public.project_member_audiences FOR INSERT TO pdos_next_app WITH CHECK({HUMAN} AND {_owned('project_member_audiences')})",
]

GUARD_SQL = [
    """CREATE FUNCTION public.reject_project_team_history() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Project team history is append only' USING ERRCODE='23514'; END $$""",
    # P60-4: a role still held by any current member may be deactivated, never deleted.
    # Runs as the schema owner so references in projects the admin cannot see still count.
    """CREATE FUNCTION public.guard_project_role_catalog() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE latest integer; item jsonb; missing text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('project-role-catalog:'||NEW.tenant_id::text,0));
 SELECT coalesce(max(revision),0) INTO latest FROM project_role_catalog_versions WHERE tenant_id=NEW.tenant_id;
 IF NEW.revision<>latest+1 OR NEW.author_id IS DISTINCT FROM scope_actor() THEN
  RAISE EXCEPTION 'Invalid role catalog transition' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(NEW.roles) NOT BETWEEN 1 AND 100 THEN
  RAISE EXCEPTION 'Role catalog size out of range' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.roles) LOOP
  IF jsonb_typeof(item)<>'object' OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(item) k)<>ARRAY['active','key','name']
   OR jsonb_typeof(item->'key')<>'string' OR item->>'key' !~ '^[a-z][a-z0-9_]{1,63}$'
   OR jsonb_typeof(item->'name')<>'string' OR char_length(btrim(item->>'name')) NOT BETWEEN 1 AND 40
   OR jsonb_typeof(item->'active')<>'boolean' THEN
   RAISE EXCEPTION 'Invalid role catalog entry' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT value->>'key') FROM jsonb_array_elements(NEW.roles))<>jsonb_array_length(NEW.roles) THEN
  RAISE EXCEPTION 'Duplicate role key' USING ERRCODE='23514'; END IF;
 SELECT r.role_key INTO missing FROM project_member_roles r WHERE r.tenant_id=NEW.tenant_id
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.roles) e WHERE e.value->>'key'=r.role_key) LIMIT 1;
 IF missing IS NOT NULL THEN
  RAISE EXCEPTION 'Referenced role cannot be deleted' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",
    """CREATE FUNCTION public.project_role_references(t uuid, keys text[]) RETURNS text[] LANGUAGE sql
 STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce(array_agg(DISTINCT r.role_key ORDER BY r.role_key),ARRAY[]::text[]) FROM project_member_roles r
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND r.tenant_id=t AND r.role_key=ANY(keys)
  AND scope_actor()=scope_requester()
  AND EXISTS(SELECT 1 FROM tenant_administrators ta JOIN principals p ON p.tenant_id=ta.tenant_id AND p.id=ta.principal_id
   WHERE ta.tenant_id=t AND ta.principal_id=scope_actor() AND ta.active AND p.active AND p.kind='human')
$$""",
    """CREATE FUNCTION public.guard_project_team_change() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE latest integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('project-team:'||NEW.project_id::text,0));
 IF NOT EXISTS(SELECT 1 FROM projects p WHERE p.id=NEW.project_id AND p.tenant_id=NEW.tenant_id) THEN
  RAISE EXCEPTION 'Project team change outside its project' USING ERRCODE='23514'; END IF;
 SELECT coalesce(max(revision),0) INTO latest FROM project_team_changes WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
 IF NEW.revision<>latest+1 THEN RAISE EXCEPTION 'Project team revision conflict' USING ERRCODE='23514'; END IF;
 IF NEW.source='backfill' THEN
  IF current_user<>'pdos_next_owner' THEN RAISE EXCEPTION 'Backfill is migration only' USING ERRCODE='23514'; END IF;
 ELSIF NEW.author_id IS DISTINCT FROM scope_actor() OR (NEW.source='g0' AND NEW.revision<>1) THEN
  RAISE EXCEPTION 'Invalid project team change' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$""",
    # Only an active named person with a current grant in the project's category can
    # join (小Pai is never a member); the owner never leaves; leaving drops roles first.
    """CREATE FUNCTION public.guard_project_member() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE change project_team_changes; project projects;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Project member history is append only' USING ERRCODE='23514'; END IF;
 SELECT * INTO project FROM projects WHERE id=NEW.project_id AND tenant_id=NEW.tenant_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Project member outside its project' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO STRICT change FROM project_team_changes WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.joined_change_id;
  IF NEW.added_by IS DISTINCT FROM change.author_id OR NEW.left_at IS NOT NULL OR NEW.handover_pending THEN
   RAISE EXCEPTION 'Invalid project member join' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.principal_id AND p.active AND p.kind='human') THEN
   RAISE EXCEPTION 'Project member must be an active named person' USING ERRCODE='23514'; END IF;
  IF change.source<>'backfill' THEN
   IF NOT EXISTS(SELECT 1 FROM grants g WHERE g.tenant_id=NEW.tenant_id AND g.category_id=project.category_id
     AND g.principal_id=NEW.principal_id AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp())) THEN
    RAISE EXCEPTION 'Project member needs a category grant' USING ERRCODE='23514'; END IF;
   NEW.joined_at=statement_timestamp();
  END IF;
  RETURN NEW;
 END IF;
 IF OLD.left_at IS NOT NULL THEN
  -- Completing a removal kept open for handover: only the flag clears, by the owner.
  IF NOT OLD.handover_pending OR NEW.handover_pending OR project.owner_id IS DISTINCT FROM scope_actor()
   OR ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.project_id,NEW.principal_id,NEW.joined_at,NEW.added_by,NEW.joined_change_id,NEW.left_at,NEW.removed_by,NEW.left_change_id,NEW.departed_roles)
    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.project_id,OLD.principal_id,OLD.joined_at,OLD.added_by,OLD.joined_change_id,OLD.left_at,OLD.removed_by,OLD.left_change_id,OLD.departed_roles) THEN
   RAISE EXCEPTION 'Invalid project member handover completion' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.left_at IS NULL OR (NEW.handover_pending AND project.visibility='category')
  OR ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.project_id,NEW.principal_id,NEW.joined_at,NEW.added_by,NEW.joined_change_id)
   IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.project_id,OLD.principal_id,OLD.joined_at,OLD.added_by,OLD.joined_change_id)
  OR NEW.removed_by IS DISTINCT FROM scope_actor() THEN
  RAISE EXCEPTION 'Invalid project member leave' USING ERRCODE='23514'; END IF;
 IF NEW.principal_id=project.owner_id THEN
  RAISE EXCEPTION 'Project owner stays on the team' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM project_team_changes c WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id
   AND c.id=NEW.left_change_id AND c.author_id=scope_actor() AND c.source='owner') THEN
  RAISE EXCEPTION 'Invalid project member leave' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM project_member_roles r WHERE r.tenant_id=NEW.tenant_id AND r.member_id=NEW.id) THEN
  RAISE EXCEPTION 'Leaving member still holds roles' USING ERRCODE='23514'; END IF;
 NEW.left_at=greatest(statement_timestamp(),OLD.joined_at);
 RETURN NEW;
END $$""",
    """CREATE FUNCTION public.guard_project_member_role() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Project roles are replaced, not edited' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NOT EXISTS(SELECT 1 FROM project_members m WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id
   AND m.id=NEW.member_id AND m.left_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM project_team_changes c WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id
   AND c.id=NEW.change_id AND c.author_id=scope_actor() AND c.source='owner') THEN
  RAISE EXCEPTION 'Invalid project role assignment' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",
    # A claim is made by a current member; the project owner adds only rows for
    # objects the owner owns. Afterwards it may only be released once, or take over
    # the origin of a row another current membership still relies on.
    """CREATE FUNCTION public.guard_project_member_audience() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Project member audience history is append only' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.released_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM project_members m WHERE m.tenant_id=NEW.tenant_id
    AND m.project_id=NEW.project_id AND m.id=NEW.member_id AND m.principal_id=NEW.principal_id AND m.left_at IS NULL)
   OR (NEW.inserted AND NOT EXISTS(SELECT 1 FROM projects p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.project_id
    AND p.owner_id=NEW.owner_id AND p.owner_id=scope_actor())) THEN
   RAISE EXCEPTION 'Invalid project member audience claim' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.project_id,NEW.member_id,NEW.object_type,NEW.subject_id,NEW.owner_id,NEW.principal_id)
   IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.project_id,OLD.member_id,OLD.object_type,OLD.subject_id,OLD.owner_id,OLD.principal_id)
  OR (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at)
  OR (OLD.inserted AND NOT NEW.inserted) THEN
  RAISE EXCEPTION 'Invalid project member audience change' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",
]

# P34/P55: the project's audience is exactly its current members (plus removals kept
# open for handover, P56 as decided 2026-11-07), checked at commit.
CONSISTENCY_SQL = """CREATE FUNCTION public.require_project_team_audience() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE row_value jsonb; t uuid; pid uuid; owner uuid;
BEGIN
 IF TG_OP='DELETE' THEN row_value=to_jsonb(OLD); ELSE row_value=to_jsonb(NEW); END IF;
 IF TG_TABLE_NAME='object_audiences' THEN
  IF row_value->>'object_type'<>'projects' THEN RETURN NULL; END IF;
  pid=(row_value->>'subject_id')::uuid;
 ELSE
  pid=(row_value->>'project_id')::uuid;
 END IF;
 t=(row_value->>'tenant_id')::uuid;
 SELECT p.owner_id INTO owner FROM projects p WHERE p.tenant_id=t AND p.id=pid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF EXISTS(
   (SELECT a.principal_id FROM object_audiences a WHERE a.tenant_id=t AND a.object_type='projects'
     AND a.subject_id=pid AND a.owner_id=owner
    EXCEPT SELECT m.principal_id FROM project_members m WHERE m.tenant_id=t AND m.project_id=pid AND (m.left_at IS NULL OR m.handover_pending))
   UNION ALL
   (SELECT m.principal_id FROM project_members m WHERE m.tenant_id=t AND m.project_id=pid AND (m.left_at IS NULL OR m.handover_pending)
    EXCEPT SELECT a.principal_id FROM object_audiences a WHERE a.tenant_id=t AND a.object_type='projects'
     AND a.subject_id=pid AND a.owner_id=owner)) THEN
  RAISE EXCEPTION 'Project audience differs from its current members' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$"""

# The owner may withdraw a project audience row only once that membership has ended.
RELEASE_SQL = """CREATE FUNCTION public.project_audience_releasable(t uuid, project uuid, person uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM projects p WHERE p.tenant_id=t AND p.id=project AND p.owner_id=scope_actor()
   AND p.owner_id<>person AND scope_actor()=scope_requester())
  AND EXISTS(SELECT 1 FROM project_members m WHERE m.tenant_id=t AND m.project_id=project AND m.principal_id=person)
  AND NOT EXISTS(SELECT 1 FROM project_members m WHERE m.tenant_id=t AND m.project_id=project AND m.principal_id=person
   AND (m.left_at IS NULL OR m.handover_pending))
$$"""
# A private project is usable only with its model and G0 definition (and variant).
# Lists them for one person: open (category or own), audience (already granted),
# addable (owned by the project owner) or blocked (owned by someone else).
UPSTREAM_SQL = """CREATE FUNCTION public.project_upstream(t uuid, project uuid, person uuid)
 RETURNS TABLE(object_type text, subject_id uuid, owner_id uuid, state text)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH scope AS (
  SELECT p.tenant_id, p.category_id, p.owner_id AS project_owner, l.product_id, l.variant_id, l.definition_id
  FROM projects p JOIN project_product_links l ON l.tenant_id=p.tenant_id AND l.project_id=p.id
  WHERE p.tenant_id=t AND p.id=project AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
   AND scope_actor()=scope_requester()
   AND (p.owner_id=scope_actor() OR EXISTS(SELECT 1 FROM project_members m WHERE m.tenant_id=t
    AND m.project_id=project AND m.principal_id=scope_actor() AND m.left_at IS NULL))
 ), objects AS (
  SELECT 'products'::text AS typ, x.id AS sid, x.owner_id AS own, x.visibility::text AS vis, s.tenant_id, s.category_id, s.project_owner
   FROM scope s JOIN products x ON x.tenant_id=s.tenant_id AND x.id=s.product_id
  UNION ALL SELECT 'definition_revisions', x.id, x.owner_id, x.visibility::text, s.tenant_id, s.category_id, s.project_owner
   FROM scope s JOIN definition_revisions x ON x.tenant_id=s.tenant_id AND x.id=s.definition_id
  UNION ALL SELECT 'product_variants', x.id, x.owner_id, x.visibility::text, s.tenant_id, s.category_id, s.project_owner
   FROM scope s JOIN product_variants x ON x.tenant_id=s.tenant_id AND x.id=s.variant_id
  UNION ALL SELECT 'variant_revisions', x.id, x.owner_id, x.visibility::text, s.tenant_id, s.category_id, s.project_owner
   FROM scope s JOIN variant_revisions x ON x.tenant_id=s.tenant_id AND x.variant_id=s.variant_id AND x.definition_id=s.definition_id
 )
 SELECT o.typ, o.sid, o.own, CASE
  WHEN o.vis='category' OR o.own=person THEN 'open'
  WHEN EXISTS(SELECT 1 FROM object_audiences a WHERE a.tenant_id=o.tenant_id AND a.category_id=o.category_id
   AND a.object_type=o.typ AND a.subject_id=o.sid AND a.owner_id=o.own AND a.principal_id=person) THEN 'audience'
  WHEN o.own=o.project_owner THEN 'addable'
  ELSE 'blocked' END
 FROM objects o
$$"""

# Full removal withdraws the upstream rows this membership added, unless another
# current membership still relies on them (that claim then owns the row); rows the
# person had before, or got elsewhere, are kept.
RELEASE_UPSTREAM_SQL = """CREATE FUNCTION public.release_project_member_upstream(t uuid, member uuid) RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m project_members; p projects; c project_member_audiences; heir uuid; removed integer := 0;
BEGIN
 SELECT * INTO m FROM project_members WHERE tenant_id=t AND id=member;
 SELECT * INTO p FROM projects WHERE tenant_id=t AND id=m.project_id;
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid OR m.id IS NULL
  OR p.owner_id IS DISTINCT FROM scope_actor() OR scope_actor() IS DISTINCT FROM scope_requester()
  OR m.left_at IS NULL OR m.handover_pending THEN
  RAISE EXCEPTION 'Project member is not fully removed' USING ERRCODE='23514'; END IF;
 FOR c IN SELECT * FROM project_member_audiences WHERE tenant_id=t AND member_id=member AND released_at IS NULL ORDER BY id FOR UPDATE LOOP
  UPDATE project_member_audiences SET released_at=statement_timestamp() WHERE id=c.id;
  IF c.inserted THEN
   SELECT o.id INTO heir FROM project_member_audiences o JOIN project_members x ON x.tenant_id=o.tenant_id AND x.id=o.member_id
    WHERE o.tenant_id=t AND o.object_type=c.object_type AND o.subject_id=c.subject_id AND o.principal_id=c.principal_id
     AND o.released_at IS NULL AND (x.left_at IS NULL OR x.handover_pending)
    ORDER BY o.created_at, o.id LIMIT 1;
   IF heir IS NOT NULL THEN
    UPDATE project_member_audiences SET inserted=true WHERE id=heir;
   ELSE
    DELETE FROM object_audiences a WHERE a.tenant_id=t AND a.category_id=p.category_id AND a.object_type=c.object_type
     AND a.subject_id=c.subject_id AND a.owner_id=c.owner_id AND a.principal_id=c.principal_id;
    removed := removed + 1;
   END IF;
  END IF;
 END LOOP;
 RETURN removed;
END $$"""

PROPOSAL_DELETE = "(object_type::text='proposals' AND owner_id=scope_actor() AND m3_evidence_share_pending(tenant_id,category_id,subject_id,NULL::integer))"
PROJECT_DELETE = "(object_type::text='projects' AND owner_id=scope_actor() AND public.project_audience_releasable(tenant_id,subject_id,principal_id))"

TRIGGER_SQL = [
    "CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON public.project_role_catalog_versions FOR EACH ROW EXECUTE FUNCTION public.reject_project_team_history()",
    "CREATE TRIGGER append_guard BEFORE INSERT ON public.project_role_catalog_versions FOR EACH ROW EXECUTE FUNCTION public.guard_project_role_catalog()",
    "CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON public.project_team_changes FOR EACH ROW EXECUTE FUNCTION public.reject_project_team_history()",
    "CREATE TRIGGER append_guard BEFORE INSERT ON public.project_team_changes FOR EACH ROW EXECUTE FUNCTION public.guard_project_team_change()",
    "CREATE TRIGGER member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.project_members FOR EACH ROW EXECUTE FUNCTION public.guard_project_member()",
    "CREATE TRIGGER role_guard BEFORE INSERT OR UPDATE OR DELETE ON public.project_member_roles FOR EACH ROW EXECUTE FUNCTION public.guard_project_member_role()",
    CONSISTENCY_SQL,
    "CREATE CONSTRAINT TRIGGER team_audience AFTER INSERT OR UPDATE ON public.project_members DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_project_team_audience()",
    "CREATE CONSTRAINT TRIGGER project_team_audience AFTER INSERT OR UPDATE OR DELETE ON public.object_audiences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_project_team_audience()",
    RELEASE_SQL,
    "CREATE TRIGGER audience_guard BEFORE INSERT OR UPDATE OR DELETE ON public.project_member_audiences FOR EACH ROW EXECUTE FUNCTION public.guard_project_member_audience()",
    UPSTREAM_SQL,
    RELEASE_UPSTREAM_SQL,
    "DROP POLICY m3_share_delete_only ON public.object_audiences",
    f"CREATE POLICY m3_share_delete_only ON public.object_audiences AS RESTRICTIVE FOR DELETE TO pdos_next_app USING({PROPOSAL_DELETE} OR {PROJECT_DELETE})",
]

FUNCTION_GRANTS = [
    *(
        f"REVOKE ALL ON FUNCTION public.{name} FROM PUBLIC,pdos_agent"
        for name in (
            "reject_project_team_history()",
            "guard_project_role_catalog()",
            "guard_project_team_change()",
            "guard_project_member()",
            "guard_project_member_role()",
            "require_project_team_audience()",
            "project_audience_releasable(uuid,uuid,uuid)",
            "project_role_references(uuid,text[])",
            "guard_project_member_audience()",
            "project_upstream(uuid,uuid,uuid)",
            "release_project_member_upstream(uuid,uuid)",
        )
    ),
    "GRANT EXECUTE ON FUNCTION public.project_upstream(uuid,uuid,uuid) TO pdos_next_app",
    "GRANT EXECUTE ON FUNCTION public.release_project_member_upstream(uuid,uuid) TO pdos_next_app",
    "GRANT EXECUTE ON FUNCTION public.project_audience_releasable(uuid,uuid,uuid) TO pdos_next_app",
    "GRANT EXECUTE ON FUNCTION public.project_role_references(uuid,text[]) TO pdos_next_app",
]

# P55 for history: every project's current audience becomes its team, roles empty.
# Projects only exist through G0, whose decision names who added them.
BACKFILL_SQL = [
    """INSERT INTO public.object_audiences (id,tenant_id,created_at,category_id,object_type,subject_id,owner_id,principal_id)
 SELECT gen_random_uuid(),p.tenant_id,p.created_at,p.category_id,'projects',p.id,p.owner_id,p.owner_id FROM public.projects p
 WHERE NOT EXISTS(SELECT 1 FROM public.object_audiences a WHERE a.tenant_id=p.tenant_id AND a.category_id=p.category_id
  AND a.object_type='projects' AND a.subject_id=p.id AND a.principal_id=p.owner_id)""",
    """INSERT INTO public.project_team_changes (id,tenant_id,created_at,project_id,revision,source,author_id,request_key,request_sha256,changes)
 SELECT gen_random_uuid(),p.tenant_id,statement_timestamp(),p.id,1,'backfill',d.decided_by,p.id,
  encode(sha256(convert_to('backfill:'||p.id::text,'UTF8')),'hex'),
  coalesce((SELECT jsonb_agg(jsonb_build_object('action','add','principal_id',a.principal_id) ORDER BY a.created_at,a.principal_id)
   FROM public.object_audiences a WHERE a.tenant_id=p.tenant_id AND a.category_id=p.category_id AND a.object_type='projects'
    AND a.subject_id=p.id AND a.owner_id=p.owner_id),'[]'::jsonb)
 FROM public.projects p JOIN public.proposal_decisions d ON d.tenant_id=p.tenant_id AND d.category_id=p.category_id AND d.id=p.g0_decision_id""",
    """INSERT INTO public.project_members (id,tenant_id,created_at,project_id,principal_id,joined_at,added_by,joined_change_id,handover_pending)
 SELECT gen_random_uuid(),a.tenant_id,statement_timestamp(),p.id,a.principal_id,a.created_at,c.author_id,c.id,false
 FROM public.projects p JOIN public.project_team_changes c ON c.tenant_id=p.tenant_id AND c.project_id=p.id AND c.revision=1
 JOIN public.object_audiences a ON a.tenant_id=p.tenant_id AND a.category_id=p.category_id AND a.object_type='projects'
  AND a.subject_id=p.id AND a.owner_id=p.owner_id""",
]

SCHEMA_SQL = TABLE_SQL + POLICY_SQL + GUARD_SQL + TRIGGER_SQL + FUNCTION_GRANTS + BACKFILL_SQL

DOWNGRADE_SQL = [
    "DROP POLICY m3_share_delete_only ON public.object_audiences",
    f"CREATE POLICY m3_share_delete_only ON public.object_audiences AS RESTRICTIVE FOR DELETE TO pdos_next_app USING({PROPOSAL_DELETE})",
    "DROP TRIGGER project_team_audience ON public.object_audiences",
    *(f"DROP TABLE public.{name}" for name in TABLES),
    "DROP FUNCTION public.release_project_member_upstream(uuid,uuid)",
    "DROP FUNCTION public.project_upstream(uuid,uuid,uuid)",
    "DROP FUNCTION public.guard_project_member_audience()",
    "DROP FUNCTION public.project_audience_releasable(uuid,uuid,uuid)",
    "DROP FUNCTION public.project_role_references(uuid,text[])",
    "DROP FUNCTION public.require_project_team_audience()",
    "DROP FUNCTION public.guard_project_member_role()",
    "DROP FUNCTION public.guard_project_member()",
    "DROP FUNCTION public.guard_project_team_change()",
    "DROP FUNCTION public.guard_project_role_catalog()",
    "DROP FUNCTION public.reject_project_team_history()",
]
