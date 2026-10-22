"""Read professional Current through its exact Fact's complete live audience once.

The unchanged category_scope already selects the exact immutable Fact under its
full RLS. The two SELECT-only predicates repeat that same audience and source
work. No standalone helper, write policy, owner or runtime privilege changes.
"""

from alembic import op
from sqlalchemy import text

revision = "s0_0723"
down_revision = "s0_0722"
branch_labels = None
depends_on = None

# Reviewed actual s0_0722 material. Ignore whitespace only, never SQL predicates.
EXPECTED_POLICIES = [
    {
        "tablename": "professional_authority_current",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM professional_authority_facts p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND (p.product_id "
        "= professional_authority_current.product_id) AND (p.project_id = "
        "professional_authority_current.project_id) AND (p.subject_id = "
        "professional_authority_current.subject_id) AND ((p.kind)::text = "
        "(professional_authority_current.kind)::text) AND (p.series_id = "
        "professional_authority_current.series_id) AND (p.id = "
        "professional_authority_current.fact_id) AND (p.revision = "
        "professional_authority_current.fact_revision)))) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND (p.category_id "
        "= professional_authority_current.category_id) AND (p.id = "
        "professional_authority_current.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM professional_authority_facts p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND "
        "(p.product_id = professional_authority_current.product_id) AND (p.project_id = "
        "professional_authority_current.project_id) AND (p.subject_id = "
        "professional_authority_current.subject_id) AND ((p.kind)::text = "
        "(professional_authority_current.kind)::text) AND (p.series_id = "
        "professional_authority_current.series_id) AND (p.id = "
        "professional_authority_current.fact_id) AND (p.revision = "
        "professional_authority_current.fact_revision)))) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND "
        "(p.category_id = professional_authority_current.category_id) AND (p.id = "
        "professional_authority_current.product_id)))))",
    },
    {
        "tablename": "professional_authority_current",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND (p.category_id "
        "= professional_authority_current.category_id) AND (p.id = "
        "professional_authority_current.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_current.tenant_id) AND "
        "(p.category_id = professional_authority_current.category_id) AND (p.id = "
        "professional_authority_current.product_id)))))",
    },
    {
        "tablename": "professional_authority_current",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "tablename": "professional_authority_current",
        "policyname": "professional_summary_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "professional_summary_visible(tenant_id, category_id, product_id, summary)",
        "with_check": None,
    },
    {
        "tablename": "professional_authority_current",
        "policyname": "upstream_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "business_upstream_visible(tenant_id, category_id, product_id, "
        "'professional_authority_facts'::text, fact_id)",
        "with_check": None,
    },
    {
        "tablename": "professional_authority_facts",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (((visibility)::text = "
        "'category'::text) OR (owner_id = scope_requester()) OR (EXISTS ( SELECT 1\n"
        "   FROM object_audiences a\n"
        "  WHERE ((a.tenant_id = professional_authority_facts.tenant_id) AND (a.category_id = "
        "professional_authority_facts.category_id) AND ((a.object_type)::text = "
        "'professional_authority_facts'::text) AND (a.subject_id = "
        "professional_authority_facts.id) AND (a.owner_id = "
        "professional_authority_facts.owner_id) AND (a.principal_id = scope_requester()))))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (((visibility)::text = "
        "'category'::text) OR (owner_id = scope_requester()) OR (EXISTS ( SELECT 1\n"
        "   FROM object_audiences a\n"
        "  WHERE ((a.tenant_id = professional_authority_facts.tenant_id) AND "
        "(a.category_id = professional_authority_facts.category_id) AND "
        "((a.object_type)::text = 'professional_authority_facts'::text) AND "
        "(a.subject_id = professional_authority_facts.id) AND (a.owner_id = "
        "professional_authority_facts.owner_id) AND (a.principal_id = "
        "scope_requester()))))))",
    },
    {
        "tablename": "professional_authority_facts",
        "policyname": "direct_source_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "direct_source_set_visible(tenant_id, category_id, product_id, "
        "required_source_read_set)",
        "with_check": None,
    },
    {
        "tablename": "professional_authority_facts",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_facts.tenant_id) AND (p.category_id = "
        "professional_authority_facts.category_id) AND (p.id = "
        "professional_authority_facts.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = professional_authority_facts.tenant_id) AND "
        "(p.category_id = professional_authority_facts.category_id) AND (p.id = "
        "professional_authority_facts.product_id)))))",
    },
    {
        "tablename": "professional_authority_facts",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "tablename": "professional_authority_facts",
        "policyname": "upstream_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_next_app"],
        "cmd": "SELECT",
        "qual": "business_audience_summary_visible(tenant_id, category_id, product_id, "
        "audience_dependencies)",
        "with_check": None,
    },
]


def _canonical(row):
    value = dict(row)
    value["roles"] = tuple(sorted(value["roles"]))
    for key in ("qual", "with_check"):
        if value[key] is not None:
            value[key] = " ".join(value[key].split())
    return value


def _require_reviewed_scope(connection):
    actual = (
        connection.execute(
            text(
                "SELECT tablename,policyname,permissive,roles,cmd,qual,with_check "
                "FROM pg_policies WHERE schemaname='public' AND tablename IN "
                "('professional_authority_current','professional_authority_facts') "
                "ORDER BY tablename,policyname"
            )
        )
        .mappings()
        .all()
    )
    expected = sorted(EXPECTED_POLICIES, key=lambda row: (row["tablename"], row["policyname"]))
    if [_canonical(row) for row in actual] != [_canonical(row) for row in expected]:
        raise RuntimeError("Unreviewed professional Current/Fact audience policies")
    roles = (
        connection.execute(
            text(
                "SELECT rolname,rolsuper,rolbypassrls,"
                "pg_has_role(rolname,'pdos_next_owner','MEMBER') AS owner_member "
                "FROM pg_roles WHERE rolname IN ('pdos_next_app','pdos_next_owner') "
                "ORDER BY rolname"
            )
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in roles] != [
        {
            "rolname": "pdos_next_app",
            "rolsuper": False,
            "rolbypassrls": False,
            "owner_member": False,
        },
        {
            "rolname": "pdos_next_owner",
            "rolsuper": False,
            "rolbypassrls": False,
            "owner_member": True,
        },
    ]:
        raise RuntimeError("Ordinary professional owner and isolated app role are required")
    tables = (
        connection.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity,"
                "pg_get_userbyid(relowner) AS owner FROM pg_class "
                "WHERE relnamespace='public'::regnamespace AND relname IN "
                "('professional_authority_current','professional_authority_facts') "
                "ORDER BY relname"
            )
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in tables] != [
        {
            "relname": name,
            "relrowsecurity": True,
            "relforcerowsecurity": True,
            "owner": "pdos_next_owner",
        }
        for name in ("professional_authority_current", "professional_authority_facts")
    ]:
        raise RuntimeError("Professional tables must retain forced RLS and ordinary ownership")


def upgrade():
    connection = op.get_bind()
    # Keep the verified policy set stable until this migration's DDL commits.
    connection.execute(
        text(
            "LOCK TABLE public.professional_authority_current, "
            "public.professional_authority_facts IN ACCESS EXCLUSIVE MODE"
        )
    )
    _require_reviewed_scope(connection)
    op.execute("DROP POLICY professional_summary_audience ON professional_authority_current")
    op.execute("DROP POLICY upstream_audience ON professional_authority_current")


def downgrade():
    # Exact s0_0400 and s0_0401 definitions; independent functions and ACL survive.
    op.execute("""
CREATE POLICY professional_summary_audience ON professional_authority_current AS RESTRICTIVE
 FOR SELECT TO pdos_next_app USING
 (professional_summary_visible(tenant_id,category_id,product_id,summary));
""")
    op.execute(
        "CREATE POLICY upstream_audience ON professional_authority_current AS RESTRICTIVE "
        "FOR SELECT TO pdos_next_app USING (business_upstream_visible("
        "tenant_id,category_id,product_id,'professional_authority_facts',fact_id))"
    )
