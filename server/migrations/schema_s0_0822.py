"""Use actual project and model audiences for capacity label projection."""
# ruff: noqa: E501
from migrations.schema_s0_0821 import SCHEMA_SQL as PREVIOUS
VISIBLE = """CREATE FUNCTION planning_project_visible(t uuid,p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM projects pr JOIN products model ON model.tenant_id=pr.tenant_id AND model.id=pr.product_id
 WHERE pr.tenant_id=t AND pr.id=p AND category_access(t,pr.category_id)
 AND (pr.owner_id=scope_requester() OR pr.visibility='category' OR (pr.visibility='audience' AND EXISTS(SELECT 1 FROM object_audiences a WHERE a.tenant_id=t AND a.category_id=pr.category_id AND a.object_type='projects' AND a.subject_id=pr.id AND a.owner_id=pr.owner_id AND a.principal_id=scope_requester())))
 AND (model.owner_id=scope_requester() OR model.visibility='category' OR (model.visibility='audience' AND EXISTS(SELECT 1 FROM object_audiences a WHERE a.tenant_id=t AND a.category_id=model.category_id AND a.object_type='products' AND a.subject_id=model.id AND a.owner_id=model.owner_id AND a.principal_id=scope_requester())))
 AND (m3_result_access(t,pr.category_id,'projects',pr.id) OR project_definition_visible(t,pr.category_id,pr.product_id,pr.id) OR m3_g0_result_reader(t,pr.category_id,'projects',pr.id)))
$$"""
WINDOWS = PREVIOUS[0].replace('CREATE FUNCTION planning_resource_windows','CREATE OR REPLACE FUNCTION planning_resource_windows',1).replace("NOT m3_result_access(t,target.category_id,'projects',p)","NOT planning_project_visible(t,p)").replace("m3_result_access(t,other.category_id,'projects',other.id)","planning_project_visible(t,other.id)")
SCHEMA_SQL = [VISIBLE,"REVOKE ALL ON FUNCTION planning_project_visible(uuid,uuid) FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",WINDOWS]
DOWNGRADE_SQL = [PREVIOUS[0].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1),"DROP FUNCTION planning_project_visible(uuid,uuid)"]
