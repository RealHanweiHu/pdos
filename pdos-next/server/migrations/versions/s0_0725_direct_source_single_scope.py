"""Check a direct source array's stable category root once within one statement.

The former source_object_audience calls repeat the identical stable root for
Product, Artifact and Original. Keep the outer root, exact full audience tuples,
nullable product joins, all references and the original JSON/UUID expressions.
Only this SQL definition changes; independently callable helpers, ordinary owner,
search_path, ACL, function flags, policies and business data stay identical.
"""

# ruff: noqa: E501 -- freeze exact actual PostgreSQL definitions and metadata

from alembic import op
from sqlalchemy import text

revision = "s0_0725"
down_revision = "s0_0724"
branch_labels = None
depends_on = None

EXPECTED_FUNCTIONS = [
    {
        "identity": "category_access(uuid,uuid,boolean)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_app=X/pdos_next_owner", "pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.category_access(tid uuid, cid uuid, writing "
        "boolean DEFAULT false)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        "      SELECT tid=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
        "       AND (nullif(current_setting('pdos.category_id',true),'') IS NULL\n"
        "         OR cid=nullif(current_setting('pdos.category_id',true),'')::uuid)\n"
        "       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g\n"
        "         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id\n"
        "         WHERE p.tenant_id=tid AND p.id=public.scope_actor() AND p.active\n"
        "          AND g.category_id=cid AND (g.expires_at IS NULL OR "
        "g.expires_at>statement_timestamp())\n"
        "          AND (NOT writing OR g.can_write))\n"
        "       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g\n"
        "         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id\n"
        "         WHERE p.tenant_id=tid AND p.id=public.scope_requester() AND p.active\n"
        "          AND g.category_id=cid AND (g.expires_at IS NULL OR "
        "g.expires_at>statement_timestamp())\n"
        "          AND (NOT writing OR g.can_write)) $function$\n",
    },
    {
        "identity": "direct_source_set_visible(uuid,uuid,uuid,jsonb)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_app=X/pdos_next_owner", "pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p "
        "uuid, refs jsonb)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        " SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT "
        "EXISTS (\n"
        "   SELECT 1 FROM jsonb_array_elements(refs) r\n"
        "   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid\n"
        "     AND a.tenant_id=t AND a.category_id=c AND a.product_id IS NOT DISTINCT "
        "FROM p\n"
        "   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND "
        "m.category_id=c\n"
        "   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND "
        "o.category_id=c AND o.product_id IS NOT DISTINCT FROM a.product_id\n"
        "   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL\n"
        "     OR NOT "
        "source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)))\n"
        "     OR NOT "
        "source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)\n"
        "     OR (a.original_id IS NOT NULL AND (o.id IS NULL\n"
        "       OR NOT "
        "source_object_audience(t,c,'uploaded_originals',o.id,o.owner_id,o.visibility)))\n"
        " )\n"
        "$function$\n",
    },
    {
        "identity": "source_object_audience(uuid,uuid,text,uuid,uuid,text)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.source_object_audience(t uuid, c uuid, typ "
        "text, sid uuid, own uuid, vis text)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        " SELECT category_access(t,c,false) AND (\n"
        "   vis='category' OR own=scope_requester() OR EXISTS (\n"
        "     SELECT 1 FROM object_audiences a\n"
        "     WHERE a.tenant_id=t AND a.category_id=c AND a.object_type=typ\n"
        "       AND a.subject_id=sid AND a.owner_id=own AND "
        "a.principal_id=scope_requester()\n"
        "   )\n"
        " )\n"
        "$function$\n",
    },
]

AFTER_FUNCTIONS = [
    {
        "identity": "category_access(uuid,uuid,boolean)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_app=X/pdos_next_owner", "pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.category_access(tid uuid, cid uuid, writing "
        "boolean DEFAULT false)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        "      SELECT tid=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
        "       AND (nullif(current_setting('pdos.category_id',true),'') IS NULL\n"
        "         OR cid=nullif(current_setting('pdos.category_id',true),'')::uuid)\n"
        "       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g\n"
        "         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id\n"
        "         WHERE p.tenant_id=tid AND p.id=public.scope_actor() AND p.active\n"
        "          AND g.category_id=cid AND (g.expires_at IS NULL OR "
        "g.expires_at>statement_timestamp())\n"
        "          AND (NOT writing OR g.can_write))\n"
        "       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g\n"
        "         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id\n"
        "         WHERE p.tenant_id=tid AND p.id=public.scope_requester() AND p.active\n"
        "          AND g.category_id=cid AND (g.expires_at IS NULL OR "
        "g.expires_at>statement_timestamp())\n"
        "          AND (NOT writing OR g.can_write)) $function$\n",
    },
    {
        "identity": "direct_source_set_visible(uuid,uuid,uuid,jsonb)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_app=X/pdos_next_owner", "pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p "
        "uuid, refs jsonb)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        " SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT "
        "EXISTS (\n"
        "   SELECT 1 FROM jsonb_array_elements(refs) r\n"
        "   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid\n"
        "     AND a.tenant_id=t AND a.category_id=c AND a.product_id IS NOT DISTINCT "
        "FROM p\n"
        "   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND "
        "m.category_id=c\n"
        "   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND "
        "o.category_id=c AND o.product_id IS NOT DISTINCT FROM a.product_id\n"
        "   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL\n"
        "     OR NOT (m.visibility='category' OR m.owner_id=scope_requester() OR EXISTS "
        "(\n"
        "       SELECT 1 FROM object_audiences aud\n"
        "       WHERE aud.tenant_id=t AND aud.category_id=c AND "
        "aud.object_type='products'\n"
        "         AND aud.subject_id=m.id AND aud.owner_id=m.owner_id AND "
        "aud.principal_id=scope_requester()\n"
        "     ))))\n"
        "     OR NOT (a.visibility='category' OR a.owner_id=scope_requester() OR EXISTS "
        "(\n"
        "       SELECT 1 FROM object_audiences aud\n"
        "       WHERE aud.tenant_id=t AND aud.category_id=c AND "
        "aud.object_type='artifact_versions'\n"
        "         AND aud.subject_id=a.id AND aud.owner_id=a.owner_id AND "
        "aud.principal_id=scope_requester()\n"
        "     ))\n"
        "     OR (a.original_id IS NOT NULL AND (o.id IS NULL\n"
        "       OR NOT (o.visibility='category' OR o.owner_id=scope_requester() OR "
        "EXISTS (\n"
        "         SELECT 1 FROM object_audiences aud\n"
        "         WHERE aud.tenant_id=t AND aud.category_id=c AND "
        "aud.object_type='uploaded_originals'\n"
        "           AND aud.subject_id=o.id AND aud.owner_id=o.owner_id AND "
        "aud.principal_id=scope_requester()\n"
        "       ))))\n"
        " )\n"
        "$function$\n",
    },
    {
        "identity": "source_object_audience(uuid,uuid,text,uuid,uuid,text)",
        "owner": "pdos_next_owner",
        "language": "sql",
        "prokind": "f",
        "prosecdef": True,
        "proleakproof": False,
        "proisstrict": False,
        "provolatile": "s",
        "proparallel": "u",
        "procost": 100.0,
        "prorows": 0.0,
        "proconfig": ["search_path=pg_catalog, public, pg_temp"],
        "acl": ["pdos_next_owner=X/pdos_next_owner"],
        "definition": "CREATE OR REPLACE FUNCTION public.source_object_audience(t uuid, c uuid, typ "
        "text, sid uuid, own uuid, vis text)\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE SECURITY DEFINER\n"
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        "AS $function$\n"
        " SELECT category_access(t,c,false) AND (\n"
        "   vis='category' OR own=scope_requester() OR EXISTS (\n"
        "     SELECT 1 FROM object_audiences a\n"
        "     WHERE a.tenant_id=t AND a.category_id=c AND a.object_type=typ\n"
        "       AND a.subject_id=sid AND a.owner_id=own AND "
        "a.principal_id=scope_requester()\n"
        "   )\n"
        " )\n"
        "$function$\n",
    },
]

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

PREVIOUS = (
    "CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p uuid, refs "
    "jsonb)\n"
    " RETURNS boolean\n"
    " LANGUAGE sql\n"
    " STABLE SECURITY DEFINER\n"
    " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
    "AS $function$\n"
    " SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (\n"
    "   SELECT 1 FROM jsonb_array_elements(refs) r\n"
    "   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid\n"
    "     AND a.tenant_id=t AND a.category_id=c AND a.product_id IS NOT DISTINCT FROM p\n"
    "   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c\n"
    "   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c "
    "AND o.product_id IS NOT DISTINCT FROM a.product_id\n"
    "   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL\n"
    "     OR NOT source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)))\n"
    "     OR NOT source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)\n"
    "     OR (a.original_id IS NOT NULL AND (o.id IS NULL\n"
    "       OR NOT source_object_audience(t,c,'uploaded_originals',o.id,o.owner_id,o.visibility)))\n"
    " )\n"
    "$function$\n"
)

FUNCTION = (
    "CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p uuid, refs "
    "jsonb)\n"
    " RETURNS boolean\n"
    " LANGUAGE sql\n"
    " STABLE SECURITY DEFINER\n"
    " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
    "AS $function$\n"
    " SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (\n"
    "   SELECT 1 FROM jsonb_array_elements(refs) r\n"
    "   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid\n"
    "     AND a.tenant_id=t AND a.category_id=c AND a.product_id IS NOT DISTINCT FROM p\n"
    "   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c\n"
    "   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c "
    "AND o.product_id IS NOT DISTINCT FROM a.product_id\n"
    "   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL\n"
    "     OR NOT (m.visibility='category' OR m.owner_id=scope_requester() OR EXISTS (\n"
    "       SELECT 1 FROM object_audiences aud\n"
    "       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='products'\n"
    "         AND aud.subject_id=m.id AND aud.owner_id=m.owner_id AND "
    "aud.principal_id=scope_requester()\n"
    "     ))))\n"
    "     OR NOT (a.visibility='category' OR a.owner_id=scope_requester() OR EXISTS (\n"
    "       SELECT 1 FROM object_audiences aud\n"
    "       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='artifact_versions'\n"
    "         AND aud.subject_id=a.id AND aud.owner_id=a.owner_id AND "
    "aud.principal_id=scope_requester()\n"
    "     ))\n"
    "     OR (a.original_id IS NOT NULL AND (o.id IS NULL\n"
    "       OR NOT (o.visibility='category' OR o.owner_id=scope_requester() OR EXISTS (\n"
    "         SELECT 1 FROM object_audiences aud\n"
    "         WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='uploaded_originals'\n"
    "           AND aud.subject_id=o.id AND aud.owner_id=o.owner_id AND "
    "aud.principal_id=scope_requester()\n"
    "       ))))\n"
    " )\n"
    "$function$\n"
)


def _require_reviewed_scope(connection, expected):
    identities = tuple(row["identity"] for row in expected)
    actual = (
        connection.execute(
            text(
                "SELECT p.oid::regprocedure::text identity,pg_get_userbyid(p.proowner) owner,"
                "l.lanname language,p.prokind,p.prosecdef,p.proleakproof,p.proisstrict,p.provolatile,"
                "p.proparallel,p.procost,p.prorows,p.proconfig,"
                "ARRAY(SELECT unnest(p.proacl)::text ORDER BY 1) acl,"
                "pg_get_functiondef(p.oid) definition "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='public' "
                "AND p.oid::regprocedure::text = ANY(CAST(:identities AS text[])) "
                "ORDER BY p.oid::regprocedure::text"
            ),
            {"identities": list(identities)},
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in actual] != expected:
        raise RuntimeError("Unreviewed direct-source helper definition or metadata drift")
    roles = (
        connection.execute(
            text(
                "SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,"
                "pg_has_role(rolname,'pdos_next_owner','MEMBER') AS owner_member "
                "FROM pg_roles WHERE rolname IN "
                "('pdos_agent','pdos_next_app','pdos_next_auth',"
                "'pdos_next_dispatch','pdos_next_owner') ORDER BY rolname"
            )
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in roles] != EXPECTED_ROLES:
        raise RuntimeError("Ordinary owner and isolated runtime roles must remain unchanged")


def upgrade():
    connection = op.get_bind()
    _require_reviewed_scope(connection, EXPECTED_FUNCTIONS)
    op.execute(FUNCTION)
    _require_reviewed_scope(connection, AFTER_FUNCTIONS)


def downgrade():
    connection = op.get_bind()
    _require_reviewed_scope(connection, AFTER_FUNCTIONS)
    op.execute(PREVIOUS)
    _require_reviewed_scope(connection, EXPECTED_FUNCTIONS)
