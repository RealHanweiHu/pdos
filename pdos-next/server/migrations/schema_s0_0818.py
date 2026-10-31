"""Shared grouping with append-only revisions; personal project following."""
# ruff: noqa: E501
from migrations.schema_s0_0817 import HUMAN, STATE, GUARD

TABLE_SQL = ['\nCREATE TABLE project_set_versions (\n\tset_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\tdescription VARCHAR(500) NOT NULL, \n\tauthor_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, set_id, revision), \n\tUNIQUE (tenant_id, author_id, request_key), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCHECK (revision>0 AND char_length(btrim(name)) BETWEEN 1 AND 80)\n)\n\n', 'CREATE INDEX ix_project_set_versions_tenant_id ON project_set_versions (tenant_id)', '\nCREATE TABLE project_set_links (\n\tproject_id UUID NOT NULL, \n\tset_id UUID, \n\trevision INTEGER NOT NULL, \n\tauthor_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, project_id, revision), \n\tUNIQUE (tenant_id, author_id, request_key, project_id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(tenant_id, set_id) REFERENCES project_set_versions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCHECK (revision>0)\n)\n\n', 'CREATE INDEX ix_project_set_links_tenant_id ON project_set_links (tenant_id)']
PROJECT = "EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=project_set_links.tenant_id AND p.id=project_set_links.project_id)"
SECURITY_SQL = []
for table, predicate in (("project_set_versions", HUMAN), ("project_set_links", HUMAN+" AND "+PROJECT)):
    SECURITY_SQL.extend([
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"CREATE POLICY human_read ON public.{table} FOR SELECT TO pdos_next_app USING({predicate})",
        f"CREATE POLICY human_append ON public.{table} FOR INSERT TO pdos_next_app WITH CHECK({predicate} AND author_id=scope_actor())",
        f"REVOKE ALL ON public.{table} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        f"GRANT SELECT,INSERT ON public.{table} TO pdos_next_app",
        f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_inbox_mutation()",
    ])
SECURITY_SQL += ["""CREATE FUNCTION public.guard_project_set_append() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE latest integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('project-sets:'||NEW.tenant_id::text,0));
 IF TG_TABLE_NAME='project_set_versions' THEN
  SELECT coalesce(max(revision),0) INTO latest FROM project_set_versions WHERE tenant_id=NEW.tenant_id AND set_id=NEW.set_id;
  IF latest=0 AND NEW.set_id<>NEW.id THEN RAISE EXCEPTION 'First version must establish set identity' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT coalesce(max(revision),0) INTO latest FROM project_set_links WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
  IF NEW.set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM project_set_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.set_id AND revision=1) THEN RAISE EXCEPTION 'Set identity required' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.revision<>latest+1 OR NEW.author_id<>scope_actor() THEN RAISE EXCEPTION 'Invalid project set transition' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$"""]
for table in ("project_set_versions", "project_set_links"):
    SECURITY_SQL.append(f"CREATE TRIGGER append_guard BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.guard_project_set_append()")
PROJECT_STATE = "(kind='project' AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=inbox_states.tenant_id AND p.id=inbox_states.target_id))"
NEW_STATE = f"({STATE}) OR ({HUMAN} AND owner_id=scope_requester() AND {PROJECT_STATE})"
NEW_GUARD = GUARD.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1).replace("   ELSE\n    SELECT state", """   ELSIF NEW.kind='project' THEN
    SELECT id::text INTO current_token FROM project_status_updates WHERE tenant_id=NEW.tenant_id AND project_id=NEW.target_id ORDER BY created_at DESC,id DESC LIMIT 1;
    IF NEW.read_through IS DISTINCT FROM coalesce(current_token,'none') THEN RAISE EXCEPTION 'Project update changed' USING ERRCODE='23514'; END IF;
   ELSE
    SELECT state""")
SCHEMA_SQL = TABLE_SQL + SECURITY_SQL + [
 "ALTER TABLE inbox_states DROP CONSTRAINT inbox_state_kind",
 "ALTER TABLE inbox_states ADD CONSTRAINT inbox_state_kind CHECK(kind IN ('conversation','run','project'))",
 "DROP POLICY inbox_read ON inbox_states", "DROP POLICY inbox_insert ON inbox_states",
 f"CREATE POLICY inbox_read ON inbox_states FOR SELECT TO pdos_next_app USING({NEW_STATE})",
 f"CREATE POLICY inbox_insert ON inbox_states FOR INSERT TO pdos_next_app WITH CHECK({NEW_STATE})", NEW_GUARD,
]
DOWNGRADE_SQL = [
 "DROP TABLE project_set_links", "DROP TABLE project_set_versions", "DROP FUNCTION public.guard_project_set_append()",
 "ALTER TABLE inbox_states DROP CONSTRAINT inbox_state_kind",
 "ALTER TABLE inbox_states ADD CONSTRAINT inbox_state_kind CHECK(kind IN ('conversation','run'))",
 "DROP POLICY inbox_read ON inbox_states", "DROP POLICY inbox_insert ON inbox_states",
 f"CREATE POLICY inbox_read ON inbox_states FOR SELECT TO pdos_next_app USING({STATE})",
 f"CREATE POLICY inbox_insert ON inbox_states FOR INSERT TO pdos_next_app WITH CHECK({STATE})", GUARD.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1),
]
