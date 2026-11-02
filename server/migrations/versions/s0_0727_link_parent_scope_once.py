"""Check each exact Link parent scope once while retaining every live audience guard.

The complete Projection and Measurement EXISTS already require the same visible
parent id/tenant/product plus project/request/run and exact revision. Their two
wider id/tenant/product EXISTS are therefore redundant for that same statement.
Only those two conjuncts change in USING and WITH CHECK. The other four Link
policies, all functions, ordinary owner/forced RLS/ACL, triggers, constraints,
columns and parent/source/Current guards remain intact. Downgrade restores the
exact reviewed policy. This migration does not assert performance acceptance.
"""

import json
from hashlib import sha256

from alembic import op
from sqlalchemy import text

revision = "s0_0727"
down_revision = "s0_0726"
branch_labels = None
depends_on = None

TABLE = "quality_event_failure_links"
POLICY = "category_scope"
EXPECTED_DEFINERS = 43

# Frozen actual pg_policies rows; no runtime dependency on private evidence.
OLD_POLICY = {
    "schemaname": "public",
    "tablename": "quality_event_failure_links",
    "policyname": "category_scope",
    "permissive": "PERMISSIVE",
    "roles": ["public"],
    "cmd": "ALL",
    "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.id = "
    "quality_event_failure_links.projection_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM quality_issue_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.issue_id = "
    "quality_event_failure_links.issue_id) AND (p.id = "
    "quality_event_failure_links.issue_version_id) AND (p.revision = "
    "quality_event_failure_links.issue_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.projection_id) AND (p.revision = "
    "quality_event_failure_links.projection_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.measurement_id) AND (p.revision = "
    "quality_event_failure_links.measurement_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.run_version_id) AND (p.revision = "
    "quality_event_failure_links.run_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.id = "
    "quality_event_failure_links.measurement_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM products p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.category_id = "
    "quality_event_failure_links.category_id) AND (p.id = "
    "quality_event_failure_links.product_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_identities p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.build_id = "
    "quality_event_failure_links.build_id) AND (p.id = "
    "quality_event_failure_links.run_id)))))",
    "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.id = "
    "quality_event_failure_links.projection_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM quality_issue_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.issue_id = "
    "quality_event_failure_links.issue_id) AND (p.id = "
    "quality_event_failure_links.issue_version_id) AND (p.revision = "
    "quality_event_failure_links.issue_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.projection_id) AND (p.revision = "
    "quality_event_failure_links.projection_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.measurement_id) AND (p.revision = "
    "quality_event_failure_links.measurement_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.run_version_id) AND (p.revision = "
    "quality_event_failure_links.run_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.id = "
    "quality_event_failure_links.measurement_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM products p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.category_id = quality_event_failure_links.category_id) AND (p.id = "
    "quality_event_failure_links.product_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_identities p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.build_id = "
    "quality_event_failure_links.build_id) AND (p.id = "
    "quality_event_failure_links.run_id)))))",
}

NEW_POLICY = {
    "schemaname": "public",
    "tablename": "quality_event_failure_links",
    "policyname": "category_scope",
    "permissive": "PERMISSIVE",
    "roles": ["public"],
    "cmd": "ALL",
    "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
    "   FROM quality_issue_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.issue_id = "
    "quality_event_failure_links.issue_id) AND (p.id = "
    "quality_event_failure_links.issue_version_id) AND (p.revision = "
    "quality_event_failure_links.issue_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.projection_id) AND (p.revision = "
    "quality_event_failure_links.projection_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.measurement_id) AND (p.revision = "
    "quality_event_failure_links.measurement_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.run_version_id) AND (p.revision = "
    "quality_event_failure_links.run_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM products p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.category_id = "
    "quality_event_failure_links.category_id) AND (p.id = "
    "quality_event_failure_links.product_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_identities p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.product_id = "
    "quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.build_id = "
    "quality_event_failure_links.build_id) AND (p.id = "
    "quality_event_failure_links.run_id)))))",
    "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
    "   FROM quality_issue_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.issue_id = "
    "quality_event_failure_links.issue_id) AND (p.id = "
    "quality_event_failure_links.issue_version_id) AND (p.revision = "
    "quality_event_failure_links.issue_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_result_projections p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.projection_id) AND (p.revision = "
    "quality_event_failure_links.projection_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM test_measurements p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.measurement_id) AND (p.revision = "
    "quality_event_failure_links.measurement_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_versions p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.request_id = "
    "quality_event_failure_links.request_id) AND (p.run_id = "
    "quality_event_failure_links.run_id) AND (p.id = "
    "quality_event_failure_links.run_version_id) AND (p.revision = "
    "quality_event_failure_links.run_revision)))) AND (EXISTS ( SELECT 1\n"
    "   FROM products p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.category_id = quality_event_failure_links.category_id) AND (p.id = "
    "quality_event_failure_links.product_id)))) AND (EXISTS ( SELECT 1\n"
    "   FROM verification_run_identities p\n"
    "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
    "(p.product_id = quality_event_failure_links.product_id) AND (p.project_id = "
    "quality_event_failure_links.project_id) AND (p.build_id = "
    "quality_event_failure_links.build_id) AND (p.id = "
    "quality_event_failure_links.run_id)))))",
}

OTHER_POLICIES = [
    {
        "schemaname": "public",
        "tablename": "quality_event_failure_links",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND (p.category_id = "
        "quality_event_failure_links.category_id) AND (p.id = "
        "quality_event_failure_links.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_event_failure_links.tenant_id) AND "
        "(p.category_id = quality_event_failure_links.category_id) AND (p.id = "
        "quality_event_failure_links.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "quality_event_failure_links",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "quality_event_failure_links",
        "policyname": "source_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "direct_source_set_visible(tenant_id, category_id, product_id, "
        "required_source_read_set)",
        "with_check": None,
    },
    {
        "schemaname": "public",
        "tablename": "quality_event_failure_links",
        "policyname": "upstream_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "business_audience_summary_visible(tenant_id, category_id, product_id, "
        "audience_dependencies)",
        "with_check": None,
    },
]

EXPECTED_RELATION = {
    "relname": "quality_event_failure_links",
    "relkind": "r",
    "owner": "pdos_next_owner",
    "relpersistence": "p",
    "relrowsecurity": True,
    "relforcerowsecurity": True,
    "relreplident": "d",
    "relispartition": False,
    "reloptions": None,
    "acl": ["pdos_next_app=ar/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    "view_definition": None,
    "partition_bound": None,
    "partition_key": None,
    "tablespace": None,
}

EXPECTED_ROLES = [
    {
        "rolname": "pdos_agent",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_app",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_auth",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_dispatch",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_owner",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": True,
    },
]

RELATION_QUERY = (
    "SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner) owner,\n"
    "      "
    "c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.relreplident,c.relispartition,\n"
    "      c.reloptions,ARRAY(SELECT unnest(c.relacl)::text ORDER BY 1) acl,\n"
    "      CASE WHEN c.relkind IN ('v','m') THEN pg_get_viewdef(c.oid,true) END view_definition,\n"
    "      CASE WHEN c.relispartition THEN pg_get_expr(c.relpartbound,c.oid) END "
    "partition_bound,\n"
    "      CASE WHEN c.relkind='p' THEN pg_get_partkeydef(c.oid) END partition_key,\n"
    "      (SELECT spcname FROM pg_tablespace WHERE oid=c.reltablespace) tablespace\n"
    "      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n"
    "      WHERE n.nspname='public' AND c.relname=:table ORDER BY c.relname,c.relkind"
)

SCHEMA_GUARDS = {
    "columns": {
        "query": "SELECT c.relname,a.attname,a.attnum,format_type(a.atttypid,a.atttypmod) "
        "type,\n"
        "      "
        "a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,a.attstorage,a.attcompression,\n"
        "      a.attstattarget,co.collname "
        "collation,pg_get_expr(d.adbin,d.adrelid) default_expression,\n"
        "      ARRAY(SELECT unnest(a.attacl)::text ORDER BY 1) "
        "acl,a.attoptions,a.attfdwoptions\n"
        "      FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid\n"
        "      JOIN pg_namespace n ON n.oid=c.relnamespace\n"
        "      LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum\n"
        "      LEFT JOIN pg_collation co ON co.oid=a.attcollation\n"
        "      WHERE n.nspname='public' AND c.relname=:table AND a.attnum>0 "
        "ORDER BY c.relname,a.attnum",
        "rows": 26,
        "sha256": "a02156cc4d04e41dd1b0a28ec89b1a0a9d8bcdea0b042eb9cebcd0b9d8cc3f17",
    },
    "constraints": {
        "query": "SELECT "
        "c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,\n"
        "      k.convalidated,k.conislocal,k.coninhcount,k.connoinherit,\n"
        "      pg_get_constraintdef(k.oid,false) definition\n"
        "      FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid\n"
        "      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "
        "n.nspname='public' AND c.relname=:table\n"
        "      ORDER BY c.relname,k.conname",
        "rows": 17,
        "sha256": "20063f771214627eebf2ed37c240e56ebb8fb40f41d1818ecf32367b4a05dca2",
    },
    "indexes": {
        "query": "SELECT t.relname table_name,i.relname index_name,\n"
        "      pg_get_indexdef(x.indexrelid) "
        "definition,x.indisunique,x.indisprimary,\n"
        "      "
        "x.indisexclusion,x.indimmediate,x.indisclustered,x.indisvalid,x.indisready,\n"
        "      x.indislive,x.indisreplident,x.indnullsnotdistinct,i.reloptions,\n"
        "      pg_get_userbyid(i.relowner) owner,ARRAY(SELECT "
        "unnest(i.relacl)::text ORDER BY 1) acl\n"
        "      FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid\n"
        "      JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON "
        "n.oid=t.relnamespace\n"
        "      WHERE n.nspname='public' AND t.relname=:table ORDER BY "
        "t.relname,i.relname",
        "rows": 4,
        "sha256": "2d1298b7aa21ef142411e439f90bb2fd2466362d48e91407ae110c632e56b598",
    },
    "triggers": {
        "query": "SELECT c.relname,\n"
        "      CASE WHEN t.tgisinternal THEN NULL ELSE t.tgname END "
        "trigger_name,\n"
        "      t.tgisinternal,k.conname "
        "constraint_name,t.tgtype,t.tgenabled,t.tgdeferrable,\n"
        "      t.tginitdeferred,t.tgattr::text "
        "attributes,encode(t.tgargs,'hex') arguments,\n"
        "      t.tgfoid::regprocedure::text "
        "function,pg_get_expr(t.tgqual,t.tgrelid) condition,\n"
        "      t.tgoldtable,t.tgnewtable,\n"
        "      CASE WHEN NOT t.tgisinternal THEN pg_get_triggerdef(t.oid,false) "
        "END definition\n"
        "      FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid\n"
        "      JOIN pg_namespace n ON n.oid=c.relnamespace\n"
        "      LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint\n"
        "      WHERE n.nspname='public' AND c.relname=:table\n"
        "      ORDER BY "
        "c.relname,t.tgisinternal,k.conname,t.tgtype,t.tgfoid::regprocedure::text,t.tgname",
        "rows": 28,
        "sha256": "5d52722b571add5e59fa04a9467750f59ba3e4f68d32b243499d41604aaac9f9",
    },
    "rules": {
        "query": "SELECT c.relname,r.rulename,pg_get_ruledef(r.oid,false) definition\n"
        "      FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class\n"
        "      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "
        "n.nspname='public' AND c.relname=:table\n"
        "      ORDER BY c.relname,r.rulename",
        "rows": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
    "functions": {
        "query": "SELECT p.oid::regprocedure::text identity,pg_get_userbyid(p.proowner) "
        "owner,\n"
        "      l.lanname "
        "language,p.prokind,p.prosecdef,p.proleakproof,p.proisstrict,p.provolatile,\n"
        "      p.proparallel,p.procost,p.prorows,p.proconfig,\n"
        "      ARRAY(SELECT unnest(p.proacl)::text ORDER BY 1) acl,\n"
        "      CASE WHEN p.prokind<>'a' THEN pg_get_functiondef(p.oid) END "
        "definition\n"
        "      FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n"
        "      JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='public'\n"
        "      ORDER BY p.oid::regprocedure::text",
        "rows": 160,
        "sha256": "3ef8d45119decb445eebaff0c835de65259fed352e896e00a5e1f17223ea2137",
        # The main test chain has two reviewed formatting-only definitions;
        # the rebuilt B8/empty chain has the second exact complete catalog.
        # Keep both frozen fingerprints rather than normalizing SQL literals.
        "accepted_sha256": [
            "70c739e27ffabc2243e8ac1de4592bf85f1aff8a8e1a9daf33cae7f2ce92ee73",
            "3ef8d45119decb445eebaff0c835de65259fed352e896e00a5e1f17223ea2137",
        ],
    },
    "runtime_memberships": {
        "query": "SELECT r.rolname role,m.rolname member,g.rolname grantor,\n"
        "      a.admin_option,a.inherit_option,a.set_option FROM "
        "pg_auth_members a\n"
        "      JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON "
        "m.oid=a.member\n"
        "      JOIN pg_roles g ON g.oid=a.grantor WHERE r.rolname IN "
        "('pdos_agent','pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_next_owner') "
        "OR m.rolname IN "
        "('pdos_agent','pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_next_owner') "
        "ORDER BY r.rolname,m.rolname,g.rolname",
        "rows": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
}

EXPECTED_POLICIES = sorted([OLD_POLICY, *OTHER_POLICIES], key=lambda row: row["policyname"])
AFTER_POLICIES = sorted([NEW_POLICY, *OTHER_POLICIES], key=lambda row: row["policyname"])


def _rows(connection, query):
    return [dict(row) for row in connection.execute(text(query), {"table": TABLE}).mappings()]


def _fingerprint(rows):
    def encoded(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)

    return sha256(encoded(sorted(rows, key=encoded)).encode()).hexdigest()


def _require_reviewed_scope(connection, expected):
    policies = _rows(
        connection,
        "SELECT schemaname,tablename,policyname,permissive,"
        "ARRAY(SELECT unnest(roles)::text ORDER BY 1) roles,cmd,qual,with_check "
        "FROM pg_policies WHERE schemaname='public' AND tablename=:table ORDER BY policyname",
    )
    if policies != expected:
        raise RuntimeError("Unreviewed exact Link policy metadata or expression drift")
    if _rows(connection, RELATION_QUERY) != [EXPECTED_RELATION]:
        raise RuntimeError("Link ordinary owner, forced RLS, relation or table ACL drift")
    roles = _rows(
        connection,
        "SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,"
        "pg_has_role(rolname,'pdos_next_owner','MEMBER') AS owner_member FROM pg_roles "
        "WHERE rolname IN ('pdos_agent','pdos_next_app','pdos_next_auth',"
        "'pdos_next_dispatch','pdos_next_owner') ORDER BY rolname",
    )
    if roles != EXPECTED_ROLES:
        raise RuntimeError("Ordinary owner and isolated runtime roles must remain unchanged")
    fingerprints = {}
    for name, guard in SCHEMA_GUARDS.items():
        rows = _rows(connection, guard["query"])
        fingerprints[name] = _fingerprint(rows)
        accepted = guard.get("accepted_sha256", [guard["sha256"]])
        if len(rows) != guard["rows"] or fingerprints[name] not in accepted:
            raise RuntimeError("Unreviewed Link schema/function/membership drift: " + name)
        if (
            name == "functions"
            and sum(row["prosecdef"] is True for row in rows) != EXPECTED_DEFINERS
        ):
            raise RuntimeError("The complete ordinary-owner definer set must remain unchanged")
    return fingerprints


def _replace(expected, replacement):
    connection = op.get_bind()
    connection.execute(
        text('LOCK TABLE public."quality_event_failure_links" IN ACCESS EXCLUSIVE MODE')
    )
    before = _require_reviewed_scope(connection, expected)
    op.execute(
        f'ALTER POLICY "category_scope" ON public."quality_event_failure_links" '
        f"USING ({replacement['qual']}) WITH CHECK ({replacement['with_check']})"
    )
    after = _require_reviewed_scope(
        connection, AFTER_POLICIES if replacement == NEW_POLICY else EXPECTED_POLICIES
    )
    if after != before:
        raise RuntimeError("Link schema/function/membership changed during policy replacement")


def upgrade():
    _replace(EXPECTED_POLICIES, NEW_POLICY)


def downgrade():
    _replace(AFTER_POLICIES, OLD_POLICY)
